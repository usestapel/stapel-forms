"""The capability-gated admin surface — including the resend endpoint."""
import pytest

from stapel_forms.models import Submission

pytestmark = pytest.mark.django_db

BASE = "/forms/api/v1"


@pytest.fixture
def authed(api_client, user, workspace_id, grant_capabilities):
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk)
    return api_client


def _ws(workspace_id, **extra):
    return {"workspace_id": str(workspace_id), **extra}


def test_deny_by_default(api_client, user, workspace_id):
    api_client.force_authenticate(user=user)
    resp = api_client.get(f"{BASE}/forms", _ws(workspace_id))
    assert resp.status_code == 403
    assert resp.json()["localizable_error"] == "error.403.forms_forbidden"


def test_anonymous_cannot_reach_the_admin_surface(api_client, workspace_id):
    assert api_client.get(f"{BASE}/forms", _ws(workspace_id)).status_code in (401, 403)


def test_view_capability_does_not_grant_manage(api_client, user, workspace_id, grant_capabilities):
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.view")
    assert api_client.get(f"{BASE}/forms", _ws(workspace_id)).status_code == 200
    created = api_client.post(
        f"{BASE}/forms", {"workspace_id": str(workspace_id), "title": "T"}, format="json"
    )
    assert created.status_code == 403


def test_responses_view_does_not_grant_responses_manage(
    api_client, user, workspace_id, grant_capabilities, published_form
):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    row = Submission.objects.get()
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.responses.view")
    assert api_client.get(
        f"{BASE}/submissions/{row.id}", _ws(workspace_id)
    ).status_code == 200
    assert api_client.delete(
        f"{BASE}/submissions/{row.id}?workspace_id={workspace_id}"
    ).status_code == 403


def test_full_authoring_flow(authed, workspace_id, simple_schema):
    created = authed.post(
        f"{BASE}/forms",
        {"workspace_id": str(workspace_id), "title": "Contact us",
         "settings": {"notify_emails": ["sales@example.com"]}},
        format="json",
    )
    assert created.status_code == 201
    form_id = created.json()["id"]
    assert created.json()["state"] == "draft"

    draft = authed.put(
        f"{BASE}/forms/{form_id}/draft?workspace_id={workspace_id}",
        {"schema": simple_schema},
        format="json",
    )
    assert draft.status_code == 200
    assert draft.json()["draft_schema"]["meta"]["title"] == "Sign up"

    published = authed.post(
        f"{BASE}/forms/{form_id}/publish?workspace_id={workspace_id}", format="json"
    )
    assert published.status_code == 201
    assert published.json()["version"] == 1

    opened = authed.post(
        f"{BASE}/forms/{form_id}/state?workspace_id={workspace_id}",
        {"state": "open"},
        format="json",
    )
    assert opened.json()["state"] == "open"
    assert opened.json()["active_version"] == 1

    versions = authed.get(f"{BASE}/forms/{form_id}/versions", _ws(workspace_id))
    assert [v["version"] for v in versions.json()] == [1]


def test_publishing_a_bad_draft_reports_the_offending_field(authed, workspace_id):
    created = authed.post(
        f"{BASE}/forms", {"workspace_id": str(workspace_id), "title": "T"}, format="json"
    )
    form_id = created.json()["id"]
    authed.put(
        f"{BASE}/forms/{form_id}/draft?workspace_id={workspace_id}",
        {"schema": {"fields": [{"slug": "a", "name": "A", "config": {"type": "nope"}}]}},
        format="json",
    )
    resp = authed.post(f"{BASE}/forms/{form_id}/publish?workspace_id={workspace_id}", format="json")
    assert resp.status_code == 400
    assert resp.json()["localizable_error"] == "error.400.forms_kind_not_allowed"


def test_rotate_link_over_http(authed, workspace_id, published_form):
    old = published_form.public_id
    resp = authed.post(
        f"{BASE}/forms/{published_form.id}/rotate-link?workspace_id={workspace_id}", format="json"
    )
    assert resp.status_code == 200 and resp.json()["public_id"] != old


def test_forms_of_another_workspace_are_invisible(authed, workspace_id, published_form):
    import uuid

    other = uuid.uuid4()
    # No capability there either, but the point is the 403/404 boundary is
    # never a leak: scoping happens before the row is fetched.
    assert authed.get(f"{BASE}/forms/{published_form.id}", _ws(other)).status_code == 403


def test_response_review_and_keyset_paging(authed, workspace_id, published_form):
    from stapel_forms import services

    for i in range(3):
        services.submit(published_form, answers={"full_name": f"P{i}", "plan": "pro"})

    page = authed.get(
        f"{BASE}/forms/{published_form.id}/submissions", _ws(workspace_id, limit=2)
    )
    assert page.status_code == 200 and len(page.json()) == 2
    cursor = page.json()[-1]["submitted_at"]
    rest = authed.get(
        f"{BASE}/forms/{published_form.id}/submissions", _ws(workspace_id, before=cursor)
    )
    assert len(rest.json()) == 1
    assert rest.json()[0]["answers"]["full_name"] == "P0"


def test_submission_detail_and_delete(authed, workspace_id, published_form):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    row = Submission.objects.get()
    detail = authed.get(f"{BASE}/submissions/{row.id}", _ws(workspace_id))
    # Headers are captions, not answers, and an omitted optional is absent
    # rather than null — the DAO only ever holds what was actually answered.
    assert detail.json()["answers"] == {"full_name": "Ann", "plan": ["pro"]}
    assert authed.delete(
        f"{BASE}/submissions/{row.id}?workspace_id={workspace_id}"
    ).status_code == 204
    assert not Submission.objects.exists()


def test_resend_is_admin_initiated_and_ignores_the_cooldown(
    authed, workspace_id, published_form, monkeypatch
):
    from stapel_forms import notifications, services

    sent = []
    monkeypatch.setattr(
        notifications, "_request", lambda t, r, v: sent.append((t, tuple(r), v))
    )
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    row = Submission.objects.get()
    url = f"{BASE}/submissions/{row.id}/resend?workspace_id={workspace_id}"

    first = authed.post(url, {}, format="json")
    second = authed.post(url, {}, format="json")
    assert first.json() == second.json() == {"sent": 1}

    resends = [s for s in sent if s[0] == "forms.submission_resend"]
    assert len(resends) == 2  # the cooldown never applies to an operator act
    assert resends[0][1] == ("sales@example.com",)
    assert resends[0][2]["answers"]["full_name"] == "Ann"


def test_resend_accepts_a_destination_override(authed, workspace_id, published_form, monkeypatch):
    from stapel_forms import notifications, services

    sent = []
    monkeypatch.setattr(notifications, "_request", lambda t, r, v: sent.append((t, tuple(r))))
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    row = Submission.objects.get()
    resp = authed.post(
        f"{BASE}/submissions/{row.id}/resend?workspace_id={workspace_id}",
        {"recipients": ["ops@example.com", "legal@example.com"]},
        format="json",
    )
    assert resp.json() == {"sent": 2}
    assert [r for t, r in sent if t == "forms.submission_resend"] == [
        ("ops@example.com", "legal@example.com")
    ]


def test_resend_without_any_recipient_refuses(authed, workspace_id, published_form):
    from stapel_forms import services

    services.update_form(published_form, settings={})
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    row = Submission.objects.get()
    resp = authed.post(
        f"{BASE}/submissions/{row.id}/resend?workspace_id={workspace_id}", {}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["localizable_error"] == "error.400.forms_no_recipients"


def test_error_keys_endpoint_is_mounted(api_client, user):
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    api_client.force_authenticate(user=user)
    resp = api_client.get(f"{BASE}/error-keys/")
    assert resp.status_code == 200
    assert "error.404.forms_not_found" in resp.json()
