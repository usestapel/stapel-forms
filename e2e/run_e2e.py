"""End-to-end proof over real HTTP.

Boots the e2e host (SQLite, in-process comm, outbox on), then drives the
whole lifecycle with plain HTTP requests — the admin side with a real
session, and the respondent side with a client that genuinely has none.
That last part is why this script exists: the pytest suite's API client
always has a session available, so "an anonymous stranger can answer this
and cannot see anything else" is a property only a second, session-less
client can actually demonstrate.

    login -> create form -> draft -> publish -> open
    -> anonymous GET schema (and the envelope carries no tenant facts)
    -> anonymous POST (valid)
    -> each refusal class: uniform 404, 410 closed, 413 oversized,
       400 unknown field, 400 missing mandatory, 409 stale version,
       409 submission cap
    -> review list -> CSV export (formula escape verified)
    -> resend -> erase -> retention purge

Run:  .venv/bin/python e2e/run_e2e.py
Exit code 0 + "E2E PASS" is the gate; any assertion failure is a real
defect somewhere on the path.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get("STAPEL_FORMS_E2E_DIR", "/tmp/stapel-forms-e2e"))
PY = sys.executable
BASE = "http://127.0.0.1:8771"
API = f"{BASE}/forms/api/v1"

PASSWORD = "e2e-pass-Str0ng!"

SCHEMA = {
    "fields": [
        {"slug": "sec", "name": "About you", "config": {"type": "header"}},
        {"slug": "full_name", "name": "Full name", "mandatory": True,
         "config": {"type": "string", "maxLength": 40}},
        {"slug": "age", "name": "Age", "config": {"type": "int", "min": 0, "max": 130}},
        {"slug": "plan", "name": "Plan", "mandatory": True,
         "config": {"type": "select",
                    "options": [{"value": "basic", "label": "Basic"},
                                {"value": "pro", "label": "Pro"}]}},
    ],
    "meta": {"title": "Sign up", "confirmation_text": "Thanks!", "submit_label": "Send"},
}


def manage(*args):
    env = {**os.environ, "STAPEL_FORMS_E2E_DIR": str(STATE)}
    return subprocess.run(
        [PY, str(REPO / "e2e" / "manage.py"), *args],
        cwd=REPO, env=env, check=True, capture_output=True, text=True,
    )


def step(name):
    print(f"--- {name}")


def expect(resp, status, name):
    if resp.status_code != status:
        print(f"FAIL {name}: expected {status}, got {resp.status_code}: {resp.text[:500]}")
        raise SystemExit(1)
    return resp


def expect_key(resp, status, key, name):
    expect(resp, status, name)
    got = resp.json().get("localizable_error")
    if got != key:
        print(f"FAIL {name}: expected {key}, got {got}")
        raise SystemExit(1)
    return resp


def check(condition, name):
    if not condition:
        print(f"FAIL {name}")
        raise SystemExit(1)


def main():
    step("reset state dir")
    shutil.rmtree(STATE, ignore_errors=True)
    STATE.mkdir(parents=True)

    step("migrate")
    manage("migrate", "--noinput")

    step("bootstrap user")
    manage(
        "shell", "-c",
        "from django.contrib.auth import get_user_model as g;"
        f"u=g().objects.create_user(username='owner',email='owner@e2e.local',password='{PASSWORD}');"
        "u.is_active=True;u.save()",
    )

    env = {**os.environ, "STAPEL_FORMS_E2E_DIR": str(STATE)}
    server = subprocess.Popen(
        [PY, str(REPO / "e2e" / "manage.py"), "runserver", "127.0.0.1:8771", "--noreload"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        step("wait for server")
        for _ in range(80):
            try:
                requests.get(f"{BASE}/forms/api/v1/forms", timeout=1)
                break
            except requests.RequestException:
                time.sleep(0.25)
        else:
            print("FAIL: server never came up")
            raise SystemExit(1)

        step("login")
        admin = requests.Session()
        # The cookie jar carries the session; the module never sees a token.
        expect(admin.post(f"{BASE}/auth/api/v1/password/login/",
                          json={"login": "owner", "password": PASSWORD}), 200, "login")
        # The respondent. A separate session that carries no credential at
        # all — the whole point of the anonymous half of this run.
        stranger = requests.Session()

        # A workspace id is just a UUID to this module — the host owns the
        # workspace model, and this run owns the capability answer for it
        # (e2e/apps.py). Using a fixed id keeps the run a proof of forms.
        ws_id = "3f8c1a52-0d47-4a1e-9c2b-7e5d6a4b8c10"

        step("create form")
        form = expect(admin.post(f"{API}/forms", json={
            "workspace_id": ws_id, "title": "Sign up",
            "settings": {"notify_emails": ["sales@e2e.local"]},
        }), 201, "create form").json()
        fid = form["id"]
        check(form["state"] == "draft", "new form is a draft")

        step("draft + publish + open")
        expect(admin.put(f"{API}/forms/{fid}/draft?workspace_id={ws_id}",
                         json={"schema": SCHEMA}), 200, "save draft")
        published = expect(admin.post(f"{API}/forms/{fid}/publish?workspace_id={ws_id}"),
                           201, "publish").json()
        check(published["version"] == 1, "first version is 1")
        opened = expect(admin.post(f"{API}/forms/{fid}/state?workspace_id={ws_id}",
                                   json={"state": "open"}), 200, "open").json()
        public_id = opened["public_id"]

        step("anonymous GET schema")
        schema = expect(stranger.get(f"{API}/public/{public_id}/"), 200, "public schema").json()
        check(schema["version"] == 1, "public schema is v1")
        check([f["slug"] for f in schema["fields"]] == ["sec", "full_name", "age", "plan"],
              "public schema carries the fields in order")
        body = json.dumps(schema)
        check(ws_id not in body and fid not in body, "public envelope leaks no tenant facts")
        version_id = schema["version_id"]

        step("anonymous POST — valid")
        ok = expect(stranger.post(f"{API}/public/{public_id}/submissions/", json={
            "answers": {"full_name": "=1+1", "plan": "pro", "age": 33},
            "version_id": version_id,
        }), 201, "submit").json()
        check(ok["confirmation"] == "Thanks!", "confirmation text comes back")
        check("id" not in ok and "submission_id" not in ok, "no submission id is handed out")

        step("refusal: uniform 404 on an unknown handle")
        expect_key(stranger.get(f"{API}/public/aaaaaaaaaaaaaaaaaaaaaa/"),
                   404, "error.404.forms_not_found", "unknown handle")

        step("refusal: 400 unknown field")
        expect_key(stranger.post(f"{API}/public/{public_id}/submissions/", json={
            "answers": {"full_name": "Ann", "plan": "pro", "evil": "x"}}),
            400, "error.400.forms_unknown_field", "unknown field")

        step("refusal: 400 missing mandatory, with params.field")
        missing = expect_key(stranger.post(f"{API}/public/{public_id}/submissions/", json={
            "answers": {"plan": "pro"}}),
            400, "error.400.feature_mandatory_missing", "missing mandatory").json()
        check(missing["params"]["field"] == "full_name", "the error names the control")

        step("refusal: 413 oversized body")
        expect_key(stranger.post(f"{API}/public/{public_id}/submissions/", json={
            "answers": {"full_name": "A" * 200000, "plan": "pro"}}),
            413, "error.413.forms_body_too_large", "oversized body")

        step("refusal: 409 stale version after a republish")
        expect(admin.put(f"{API}/forms/{fid}/draft?workspace_id={ws_id}",
                         json={"schema": SCHEMA}), 200, "save draft again")
        expect(admin.post(f"{API}/forms/{fid}/publish?workspace_id={ws_id}"), 201, "publish v2")
        expect_key(stranger.post(f"{API}/public/{public_id}/submissions/", json={
            "answers": {"full_name": "Ann", "plan": "pro"}, "version_id": version_id}),
            409, "error.409.forms_version_superseded", "stale version")

        step("refusal: 409 submission cap")
        fresh = expect(stranger.get(f"{API}/public/{public_id}/"), 200, "refetch").json()
        for i in range(2):
            expect(stranger.post(f"{API}/public/{public_id}/submissions/", json={
                "answers": {"full_name": f"P{i}", "plan": "basic"},
                "version_id": fresh["version_id"]}), 201, f"fill cap {i}")
        expect_key(stranger.post(f"{API}/public/{public_id}/submissions/", json={
            "answers": {"full_name": "Over", "plan": "basic"},
            "version_id": fresh["version_id"]}),
            409, "error.409.forms_submission_cap", "submission cap")

        step("review list")
        rows = expect(admin.get(f"{API}/forms/{fid}/submissions?workspace_id={ws_id}"),
                      200, "list responses").json()
        check(len(rows) == 3, f"three responses stored, got {len(rows)}")
        check(any(r["answers"].get("full_name") == "=1+1" for r in rows),
              "the hostile answer is stored verbatim")

        step("CSV export escapes the formula")
        csv = expect(admin.get(
            f"{API}/forms/{fid}/submissions/export?workspace_id={ws_id}&version=1"),
            200, "export").text
        check("'=1+1" in csv, "formula lead is escaped in the CSV")
        check("Age" in csv.splitlines()[0], "v1 columns include the field v1 had")

        step("resend")
        target = next(r for r in rows if r["answers"].get("full_name") == "=1+1")
        sent = expect(admin.post(
            f"{API}/submissions/{target['id']}/resend?workspace_id={ws_id}",
            json={"recipients": ["ops@e2e.local"]}), 200, "resend").json()
        check(sent["sent"] == 1, "resend reports one delivery")

        step("close -> 410")
        expect(admin.post(f"{API}/forms/{fid}/state?workspace_id={ws_id}",
                          json={"state": "closed"}), 200, "close")
        expect_key(stranger.get(f"{API}/public/{public_id}/"),
                   410, "error.410.forms_closed", "closed form")

        step("delete one response")
        expect(admin.delete(f"{API}/submissions/{target['id']}?workspace_id={ws_id}"),
               204, "delete response")
        rows = expect(admin.get(f"{API}/forms/{fid}/submissions?workspace_id={ws_id}"),
                      200, "list after delete").json()
        check(len(rows) == 2, "the response is gone")

        step("retention purge destroys aged rows")
        manage("shell", "-c",
               "from django.utils import timezone;from datetime import timedelta;"
               "from stapel_forms.models import Submission;"
               "Submission.objects.update(submitted_at=timezone.now()-timedelta(days=400))")
        out = manage("forms_purge_expired").stdout
        check("purged 2 submission" in out, f"purge reported what it destroyed: {out.strip()}")
        rows = expect(admin.get(f"{API}/forms/{fid}/submissions?workspace_id={ws_id}"),
                      200, "list after purge").json()
        check(rows == [], "retention emptied the table")

        print("E2E PASS")
        return 0
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
