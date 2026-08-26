"""The capability projection and the gate that enforces it are one thing.

A capability that answers "yes" while the endpoint answers 403 is worse than
no capability at all: a UI trusts the published answer and renders a control
that leads to a refusal. The module prevents that structurally —
``views.gated(...)`` is the only place an action is named, ``_access_error``
authorizes off that declaration and ``CapabilityAwareAutoSchema`` publishes
off the same one — but "structurally" is a claim, and this file is what makes
it a checked one.

Four things are asserted here, in the order of what would hurt most:

1. **every** admin route+method declares an action (the "a gate that cannot
   see the thing it checks" class — an undeclared handler is not a silently
   open door here, it is a hard boot-level refusal, but it must also never
   ship);
2. the published capability is the capability the endpoint honours, proved by
   driving each route twice: granted only that string it must not refuse, and
   granted every other string it must;
3. ``docs/capabilities.json`` and ``docs/schema.json`` project exactly the
   capability set ``authz`` enforces, with matching operations;
4. the derivations that hold the whole thing together (``CAPABILITIES`` from
   ``ACTION_CAPABILITIES``, the refusal of an undeclared handler).

No sibling service is needed for any of it: ``conftest.py`` registers an
in-process ``workspaces.check_capability`` provider over an explicit grant
table, so deny-by-default is exercised honestly and a clean CI runner with
nothing but this package installed runs the whole file.
"""
import json
from pathlib import Path

import pytest

from stapel_forms import views
from stapel_forms.authz import ACTION_CAPABILITIES, CAPABILITIES, capability_for
from stapel_forms.models import Submission

pytestmark = pytest.mark.django_db

BASE = "/forms/api/v1"
DOCS = Path(__file__).resolve().parent.parent / "docs"

#: Routes the module serves anonymously on purpose (MODULE.md §3). They carry
#: no capability, and this test file must not "fix" that by expecting one.
PUBLIC_VIEWS = {"PublicFormView", "PublicSubmitView", "FormsErrorKeysView"}


def _admin_handlers():
    """(view class, http method, declared action) for every admin handler.

    Walked off the real URLconf rather than a hand-kept list — a route added
    to ``urls_v1.py`` and forgotten here is what this is guarding against.
    """
    from stapel_forms import urls_v1

    found = []
    for pattern in urls_v1.urlpatterns:
        cls = getattr(pattern.callback, "cls", None) or getattr(
            pattern.callback, "view_class", None
        )
        if cls is None or cls.__name__ in PUBLIC_VIEWS:
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            handler = getattr(cls, method, None)
            if handler is None:
                continue
            found.append((cls, method, getattr(handler, views.GATE_ATTR, None)))
    return found


# ── 1. Nothing is gated by accident ──────────────────────────────────


def test_every_admin_handler_declares_an_action():
    undeclared = [
        f"{cls.__name__}.{method}" for cls, method, action in _admin_handlers() if action is None
    ]
    assert not undeclared, (
        f"admin handlers with no @gated(...) declaration: {undeclared}. They "
        "authorize nothing a client can see, so a UI cannot tell whether to "
        "offer the control."
    )


def test_declared_actions_are_all_known():
    for cls, method, action in _admin_handlers():
        assert action in ACTION_CAPABILITIES, f"{cls.__name__}.{method} -> {action!r}"


def test_capabilities_are_derived_from_the_action_map():
    # Not a tautology check: it pins that nobody re-hand-writes the tuple,
    # which is how a capability ends up published but unenforced.
    assert CAPABILITIES == tuple(ACTION_CAPABILITIES.values())
    assert "forms.responses.manage" in CAPABILITIES


def test_capability_for_refuses_an_unknown_action():
    with pytest.raises(ValueError):
        capability_for("responses.export")


def test_gated_refuses_an_unknown_action_at_decoration_time():
    with pytest.raises(ValueError):
        views.gated("responses.purge")


def test_access_error_refuses_an_undeclared_handler(rf):
    from django.core.exceptions import ImproperlyConfigured

    request = rf.get("/")
    with pytest.raises(ImproperlyConfigured):
        views._access_error(request, "00000000-0000-0000-0000-000000000000")


# ── 2. Published == enforced, driven over HTTP ───────────────────────


@pytest.fixture
def one_submission(published_form):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    return Submission.objects.get()


def _routes(form, submission, workspace_id):
    """(label, method, url, body, expected capability) for every gated route.

    Bodies are the minimum a handler needs to reach its gate. Two handlers
    validate the request body BEFORE authorizing (form creation and the
    draft PUT), so those carry a valid one — otherwise the route would
    answer 400 and the test would prove nothing about the gate.
    """
    ws = f"workspace_id={workspace_id}"
    return [
        ("forms:list", "get", f"{BASE}/forms?{ws}", None, "forms.view"),
        ("forms:create", "post", f"{BASE}/forms",
         {"workspace_id": str(workspace_id), "title": "T"}, "forms.manage"),
        ("form:read", "get", f"{BASE}/forms/{form.id}?{ws}", None, "forms.view"),
        ("form:patch", "patch", f"{BASE}/forms/{form.id}?{ws}",
         {"title": "Renamed"}, "forms.manage"),
        ("form:delete", "delete", f"{BASE}/forms/{form.id}?{ws}", None, "forms.manage"),
        ("form:draft", "put", f"{BASE}/forms/{form.id}/draft?{ws}",
         {"schema": {"fields": [], "meta": {}}}, "forms.manage"),
        ("form:publish", "post", f"{BASE}/forms/{form.id}/publish?{ws}", None, "forms.manage"),
        ("form:state", "post", f"{BASE}/forms/{form.id}/state?{ws}",
         {"state": "closed"}, "forms.manage"),
        ("form:rotate", "post", f"{BASE}/forms/{form.id}/rotate-link?{ws}", None, "forms.manage"),
        ("field-kinds", "get", f"{BASE}/field-kinds?{ws}", None, "forms.manage"),
        ("form:versions", "get", f"{BASE}/forms/{form.id}/versions?{ws}", None, "forms.view"),
        ("form:responses", "get", f"{BASE}/forms/{form.id}/submissions?{ws}", None,
         "forms.responses.view"),
        ("form:export", "get", f"{BASE}/forms/{form.id}/submissions/export?{ws}", None,
         "forms.responses.view"),
        ("response:read", "get", f"{BASE}/submissions/{submission.id}?{ws}", None,
         "forms.responses.view"),
        ("response:delete", "delete", f"{BASE}/submissions/{submission.id}?{ws}", None,
         "forms.responses.manage"),
        ("response:resend", "post", f"{BASE}/submissions/{submission.id}/resend?{ws}",
         {}, "forms.responses.manage"),
    ]


def _labels():
    return [r[0] for r in _routes(_Stub(), _Stub(), "w")]


class _Stub:
    id = "x"


@pytest.mark.parametrize("label", _labels())
def test_the_projected_capability_is_the_one_that_opens_the_route(
    label, api_client, user, workspace_id, grant_capabilities, published_form, one_submission
):
    """Granted only its published capability, a route must not refuse."""
    route = next(r for r in _routes(published_form, one_submission, workspace_id) if r[0] == label)
    _, method, url, body, capability = route

    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, capability)
    kwargs = {"format": "json"} if body is not None else {}
    resp = getattr(api_client, method)(url, body, **kwargs) if body is not None else getattr(
        api_client, method
    )(url)

    assert resp.status_code != 403, (
        f"{label} publishes {capability!r} in docs/capabilities.json and "
        f"docs/schema.json, but holding exactly that capability is refused — "
        "a UI trusting the contract would render a control that 403s."
    )


@pytest.mark.parametrize("label", _labels())
def test_every_other_capability_does_not_open_the_route(
    label, api_client, user, workspace_id, grant_capabilities, published_form, one_submission
):
    """Granted everything EXCEPT its published capability, a route must refuse.

    The half that catches an over-broad projection: without it a route gated
    on ``forms.view`` could advertise ``forms.responses.manage`` and still
    pass the test above whenever the holder had both.
    """
    route = next(r for r in _routes(published_form, one_submission, workspace_id) if r[0] == label)
    _, method, url, body, capability = route

    others = [c for c in CAPABILITIES if c != capability]
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, *others)
    kwargs = {"format": "json"} if body is not None else {}
    resp = getattr(api_client, method)(url, body, **kwargs) if body is not None else getattr(
        api_client, method
    )(url)

    assert resp.status_code == 403, (
        f"{label} publishes {capability!r}, but {others} opened it too — the "
        "published capability is narrower than the enforced one, so a "
        "deployment cannot actually express who may drive this route."
    )


def test_the_route_table_covers_every_gated_handler(published_form, one_submission, workspace_id):
    """The table above is hand-written; this is what stops it going stale."""
    from_urlconf = {
        (cls.__name__, method) for cls, method, action in _admin_handlers() if action is not None
    }
    assert len(_routes(published_form, one_submission, workspace_id)) == len(from_urlconf)


# ── 3. The committed artifacts agree with the gate ───────────────────


def test_capabilities_json_projects_the_enforced_set():
    doc = json.loads((DOCS / "capabilities.json").read_text())
    assert [c["key"] for c in doc["capabilities"]] == list(CAPABILITIES)
    for entry in doc["capabilities"]:
        assert entry["gates"]["operations"], f"{entry['key']} gates nothing"
        assert entry["curated"]["summary"]
        assert entry["curated"]["business_label"]


def test_schema_json_carries_the_same_capability_per_operation():
    schema = json.loads((DOCS / "schema.json").read_text())
    doc = json.loads((DOCS / "capabilities.json").read_text())
    projected = {
        op: entry["key"]
        for entry in doc["capabilities"]
        for op in entry["gates"]["operations"]
    }
    from_schema = {}
    for path_item in schema["paths"].values():
        for method, op in path_item.items():
            if method in ("get", "put", "post", "patch", "delete") and "x-stapel-capability" in op:
                from_schema[op["operationId"]] = op["x-stapel-capability"]
    assert from_schema == projected


def test_the_public_surface_carries_no_capability():
    schema = json.loads((DOCS / "schema.json").read_text())
    for path, path_item in schema["paths"].items():
        if "/public/" not in path:
            continue
        for method, op in path_item.items():
            if method in ("get", "put", "post", "patch", "delete"):
                assert "x-stapel-capability" not in op, (
                    f"{method.upper()} {path} is an anonymous respondent route; "
                    "publishing a capability for it invites a UI to gate a form "
                    "strangers are meant to be able to answer."
                )


def test_every_capability_publishes_how_a_refusal_reads():
    """The `behavior` line says what a 403 means — and says it truthfully.

    Until 0.4.0 it carried a caveat: a 403 meant EITHER "not granted" OR
    "no verdict was reached", because core's ``require_capability``
    collapsed an outage into a denial and the ``unavailable`` -> 503 branch
    could not fire. Core 0.47.0 fixed that, so the caveat is not merely
    stale, it is FALSE — a client that still codes around it treats a real
    permission decision as a maybe. This asserts both halves: the line
    still tells a consumer how to read a refusal, and it no longer tells
    them the refusal might be an outage.
    """
    doc = json.loads((DOCS / "capabilities.json").read_text())
    for entry in doc["capabilities"]:
        behavior = entry["gates"].get("behavior", "")
        assert "403" in behavior and "503" in behavior, (
            f"{entry['key']} does not tell a consumer how a refusal from these "
            "routes reads. Both statuses belong here: 403 is the verdict, 503 "
            "is the absence of one."
        )
        for dead in ("EITHER", "0.45.0", "cannot fire", "collapses outage"):
            assert dead not in behavior, (
                f"{entry['key']} still carries the pre-0.4.0 outage caveat "
                f"({dead!r}). stapel-core >= 0.47.0 distinguishes an outage "
                "from a denial, so a contract that says a 403 might mean 'no "
                "verdict' is publishing an untruth — which is worse than the "
                "honest caveat it replaced."
            )


# ── 4. Outage and denial, pinned APART ───────────────────────────────
#
# These two are a pair and only mean anything together. Each drives the
# SAME route with the SAME principal and differs in exactly one thing —
# whether the workspaces service answered — and they must produce different
# statuses. Keeping only the 503 half would leave "the gate refuses
# everything with 503" passing; keeping only the 403 half is where this
# module was until 0.4.0. What is under test is the DISTINCTION.


def test_a_workspaces_outage_renders_503_not_403(
    api_client, user, workspace_id, grant_capabilities, published_form,
    one_submission, monkeypatch,
):
    """No verdict is not a denial (stapel-core >= 0.47.0).

    The grant is real, so the ONLY reason this request can be refused is the
    outage — without it the route would refuse for the ordinary reason and
    the test would prove nothing about outages.

    Patched at the comm call, not at ``require_capability``: the behaviour
    under test is core's own except-branch turning a ``FunctionCallError``
    into ``WorkspaceLookupUnavailable``, so stubbing the gate itself would
    assert nothing about the thing that actually decides.

    This replaces ``test_a_workspaces_outage_still_renders_403_not_503``,
    which pinned the defect on purpose so that the caveat in every
    ``capabilities[].gates.behavior`` would die with it rather than outlive
    it. It went red on core 0.47.0, and this is what it turned into.
    """
    from stapel_core.comm.exceptions import FunctionCallError

    def _unreachable(*args, **kwargs):
        raise FunctionCallError("workspaces service unreachable")

    grant_capabilities(workspace_id, user.pk, "forms.responses.manage")
    monkeypatch.setattr("stapel_core.comm.call", _unreachable)

    api_client.force_authenticate(user=user)
    resp = api_client.delete(
        f"{BASE}/submissions/{one_submission.id}?workspace_id={workspace_id}"
    )
    assert resp.status_code == 503, (
        "a workspaces outage rendered as something other than 503. If this is "
        "a 403, the gate is fabricating a verdict out of a non-answer and the "
        "capability projection is publishing an untruth."
    )
    assert resp.json()["localizable_error"] == "error.503.forms_workspaces_unavailable"


def test_a_genuine_denial_renders_403_not_503(
    api_client, user, workspace_id, grant_capabilities, published_form,
    one_submission,
):
    """The other half of the pair: a verdict of "no" is still a 403.

    Same route, same principal, workspaces answering normally — and holding
    every OTHER forms capability, so the refusal is specifically about the
    one this route asks for rather than about having no grants at all.
    """
    grant_capabilities(
        workspace_id, user.pk,
        "forms.view", "forms.manage", "forms.responses.view",
    )

    api_client.force_authenticate(user=user)
    resp = api_client.delete(
        f"{BASE}/submissions/{one_submission.id}?workspace_id={workspace_id}"
    )
    assert resp.status_code == 403, (
        "a rendered denial must stay a 403. A gate that answers 503 to a real "
        "refusal tells a client to retry forever."
    )
    assert resp.json()["localizable_error"] == "error.403.forms_forbidden"


def test_responses_manage_is_projected_on_exactly_its_two_operations():
    """The gap this release closed, pinned by name."""
    doc = json.loads((DOCS / "capabilities.json").read_text())
    entry = next(c for c in doc["capabilities"] if c["key"] == "forms.responses.manage")
    assert entry["gates"]["operations"] == [
        "forms_api_v1_submissions_destroy",
        "forms_api_v1_submissions_resend_create",
    ]
