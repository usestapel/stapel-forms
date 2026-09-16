"""Every response body the contract declares is a body the views actually send.

``docs/schema.json`` is emitted from the views' ``@extend_schema``
annotations, and an annotation is a CLAIM: it says what the view returns, and
the generator has no way to check it against the method body.
``tests/test_contract.py`` compares the committed document against a FRESH
EMISSION of the same annotations — it proves the file is not stale, and
nothing else, because both sides come from the claim. stapel-alerts 0.2.0
shipped ``GET /issues`` declared as ``Issue[]`` while the wire carried
``{count, offset, limit, results}``: the drift gate was green and the
frontend pair rendered ``undefined``.

This is the gate the generator cannot be: it performs every operation the
committed schema declares with a JSON response body, and validates the body
it gets against the schema it was promised.

Rules this file holds itself to:

* an operation with a declared JSON response and no entry in ``RECIPES``
  FAILS LOUDLY — a gate that quietly covers fourteen of fifteen rows is the
  family of green that proves nothing;
* a path parameter the gate cannot fill fails at the point of substitution,
  naming the operation;
* the operations that genuinely cannot be driven in-process are listed by
  name in ``UNDRIVABLE`` with a one-line reason each. That list is asserted
  to be exactly current: a stale entry, or a missing reason, fails;
* a collection that comes back empty fails in the populated pass — an empty
  array validates against any item schema, so an empty answer is a check that
  looked at nothing. That holds for the arrays NESTED in an envelope too
  (``FieldKindsDTO.kinds``, ``PublicFormDTO.fields``), which
  ``COLLECTION_KEYS`` names;
* a body is checked in BOTH directions. ``jsonschema`` answers "is every
  declared property satisfied"; an OpenAPI object schema without
  ``additionalProperties`` also claims to ENUMERATE the body, and a key the
  document never mentions is a key no generated client has a field for. That
  half is :func:`_undeclared_keys`;
* every read is driven a SECOND time in its emptiest legal state
  (``EMPTY_STATE``). Every null finding in the first wave of this gate was
  there: an ``exp`` null for every active token, a ``created_at`` null for
  every account that had just signed up.

Runs on every interpreter: it reads the committed schema and never emits.

THE MOUNT. ``codegen_urls.py`` mounts ``forms/`` and the module's own
``urls.py`` contributes ``api/v1/``, so the document is written against
``/forms/api/v1/…``. ``tests/urls.py`` mounts the same thing (plus the admin
peephole, which the contract does not describe and this file does not need),
so forms is one of the libraries whose suite was already looking where its
document describes — five of the first eight in this wave were not. The
emission mount is declared here anyway, because
``test_every_declared_path_resolves_under_this_urlconf`` can only hold if the
urlconf under test is this file's own.

What it found on its first run: 15 of 15 operations driven, both states, 0
red. Every declared body — including all eight ``nullable`` fields across
``FormPresenterDTO``, ``FormVersionPresenterDTO`` and
``SubmissionPresenterDTO`` — is a body the views send.

The presenters are why. Every nullable field here is spelled out in
``custom_fields`` with an explicit ``Optional[...]`` and a ``default=None``
(the ``custom_fields`` blocks of ``FormPresenter``,
``FormVersionPresenter`` and ``SubmissionPresenter`` in ``presenters.py``),
rather than left to the model-field inference that publishes ``float`` for a
``FloatField(null=True)``
— which is exactly the defect this same sweep found one library over.

No operation answers a key the contract fails to mention either — the check
that caught stapel-video's ``lobby/deny`` runs on all fifteen of these bodies
and finds nothing.

``test_the_gate_is_not_blind`` proves the green is a finding rather than a
gate that never looked: it re-drives every operation with its declared schema
swapped for ``{"type": "string"}`` and requires all fifteen to fail.
"""
import copy
import json
import re
import uuid
from pathlib import Path

import jsonschema
import pytest
from django.test import override_settings
from django.urls import include, path as url_path
from rest_framework.test import APIClient

REPO = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO / "docs" / "schema.json").read_text())

#: The mount the contract is emitted at (``codegen_urls.py``), reproduced for
#: the test client rather than borrowed from ``tests/urls.py``: a gate that
#: inherits the suite's mount cannot notice when the suite's mount is wrong.
urlpatterns = [
    url_path("forms/", include("stapel_forms.urls")),
]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]

V1 = "/forms/api/v1"


@pytest.fixture(autouse=True)
def _media_root(tmp_path):
    """Nothing here writes files today; pin the root so nothing ever does.

    ``MEDIA_ROOT`` is unset in this module's harness settings, so it defaults
    to the working directory — in stapel-auth that put a data export into the
    checkout, where a stray directory then shadowed a real module. The CSV
    export streams rather than writing, but a future attachment would land
    the ordinary way.
    """
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        yield


@pytest.fixture(autouse=True)
def _no_throttles_no_cooldown():
    """Three rate limiters stood down; none of them is a response shape.

    ``SUBMIT_THROTTLE`` and ``PUBLIC_SCHEMA_THROTTLE`` share one anonymous
    per-IP bucket in the process-wide locmem cache with every other module in
    the run, so the public endpoints answer 429 depending on what ran before
    them. The notify cooldown is a clock. All three are behaviour this
    module's own suites already pin.
    """
    with override_settings(
        STAPEL_FORMS={
            "SUBMIT_THROTTLE": None,
            "PUBLIC_SCHEMA_THROTTLE": None,
            "NOTIFY_COOLDOWN_SECONDS": 0,
        }
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_cache():
    """The capability verdict is cached for 30 s and the notify cooldown lives
    in the same cache; either would let one recipe answer the next."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


# ─────────────────────────────────────────────────────────────────────────────
# The contract side: what the document declares
# ─────────────────────────────────────────────────────────────────────────────


def _json_schema(node):
    """OpenAPI 3.0 → JSON Schema, for the divergences that matter here.

    OAS 3.0 spells "may be null" as ``nullable: true`` beside a ``type``;
    JSON Schema has no such keyword and would refuse the null — which is
    exactly what ``active_version``, ``draft_schema``, ``submitted_by``,
    ``client_meta`` and ``erased_at`` answer in their empty state, the state
    the second pass exists for. Everything else drf-spectacular emits here
    (``$ref``, ``allOf``, ``enum``, ``required``, ``additionalProperties``)
    is JSON Schema as written.
    """
    if isinstance(node, list):
        return [_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    rebuilt = {k: _json_schema(v) for k, v in node.items() if k != "nullable"}
    if node.get("nullable"):
        return {"anyOf": [rebuilt, {"type": "null"}]}
    return rebuilt


def _validator(response_schema):
    root = copy.deepcopy(response_schema)
    root["components"] = copy.deepcopy(SCHEMA["components"])
    return jsonschema.Draft202012Validator(_json_schema(root))


def _operations():
    """Every ``(method, path, 2xx code, JSON body schema)`` the contract declares."""
    ops = []
    for path, methods in SCHEMA["paths"].items():
        for method, op in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for code, response in op.get("responses", {}).items():
                body = (
                    response.get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                if body is not None and code.startswith("2"):
                    ops.append((method.upper(), path, int(code), body))
    return sorted(ops, key=lambda o: (o[1], o[0], o[2]))


OPERATIONS = _operations()


# ─────────────────────────────────────────────────────────────────────────────
# The second half of the check: keys the document never mentions
# ─────────────────────────────────────────────────────────────────────────────


def _deref(node):
    """Follow one ``$ref`` into ``components.schemas``."""
    ref = node.get("$ref") if isinstance(node, dict) else None
    if not ref:
        return node
    name = ref.rsplit("/", 1)[-1]
    return SCHEMA["components"]["schemas"].get(name, {})


def _properties_of(node):
    """``(properties, enumerates)`` for one object schema.

    ``enumerates`` is False when the schema declines to be a closed list —
    it has an ``additionalProperties`` of its own (a free-form map: this
    module uses several for settings, payload and answer blobs) or it is a
    ``oneOf``/``anyOf`` this walk will not try to choose between. Those are
    skipped rather than guessed at: a false positive here would be worse than
    the miss, because it would teach the next reader to distrust the check.
    """
    node = _deref(node)
    if not isinstance(node, dict):
        return {}, False
    if "oneOf" in node or "anyOf" in node:
        return {}, False
    if "additionalProperties" in node:
        return dict(node.get("properties") or {}), False
    properties = dict(node.get("properties") or {})
    for branch in node.get("allOf") or ():
        branch_properties, branch_enumerates = _properties_of(branch)
        properties.update(branch_properties)
        if not branch_enumerates:
            return properties, False
    if not properties:
        return {}, False
    return properties, True


def _undeclared_keys(body, schema, path=()):
    """Keys the received body carries that the declared schema never names.

    ``jsonschema`` answers one half of "does this body match the contract":
    every declared property is there and well typed. The other half is that
    the contract ENUMERATES the body — a client is generated from the
    document, so a key the document does not mention is a key no generated
    type has a field for, and reading it is ``undefined`` at runtime and a
    compile error in a typed client. An OpenAPI schema with ``properties``
    and no ``additionalProperties`` is exactly that claim, and this is what
    checks it. It is what caught ``POST /rooms/{join_code}/lobby/deny`` in
    stapel-video: a body carrying a ``status`` key the document never
    mentions, which plain validation passes without a word.
    """
    found = []
    if isinstance(body, list):
        items = _deref(schema).get("items") if isinstance(_deref(schema), dict) else None
        if items is not None:
            for index, item in enumerate(body):
                found.extend(_undeclared_keys(item, items, path + (index,)))
        return found
    if not isinstance(body, dict):
        return found
    properties, enumerates = _properties_of(schema)
    if enumerates:
        for key in body:
            if key not in properties:
                found.append(".".join(str(part) for part in path + (key,)))
    for key, value in body.items():
        if key in properties:
            found.extend(_undeclared_keys(value, properties[key], path + (key,)))
    return found


# ─────────────────────────────────────────────────────────────────────────────
# The wire side: harness
# ─────────────────────────────────────────────────────────────────────────────


def _unique(prefix):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def anonymous():
    return APIClient()


def make_user(**kwargs):
    from django.contrib.auth import get_user_model

    defaults = dict(
        username=_unique("wire-"),
        email=f"{_unique('wire-')}@example.com",
    )
    defaults.update(kwargs)
    return get_user_model().objects.create(**defaults)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class capability_seam:
    """Stand in for ``workspaces.check_capability`` — the seam a host wires.

    ``stapel-forms`` never imports stapel-workspaces; ``authz.authorize``
    asks a comm Function by name and fails CLOSED when nobody answers. That
    name is the whole authorization decision for the admin surface, so the
    gate registers a provider exactly the way a deployment does, and
    everything on this side of the seam — the ``@gated`` action, the
    capability lookup, the 403/503 split — runs for real.

    Registered per call and restored on exit, displacing the suite-wide
    stand-in the repo's ``conftest.py`` installs at session start: a function
    name has exactly one provider, and ``FunctionRegistry.register`` refuses
    a second one.
    """

    NAME = "workspaces.check_capability"

    def __init__(self, allowed=True, role="owner"):
        self.allowed = allowed
        self.role = role

    def __enter__(self):
        from stapel_core.comm.registry import function_registry

        self._previous = function_registry._providers.pop(self.NAME, None)
        self._previous_schema = function_registry._schemas.pop(self.NAME, None)
        allowed, role = self.allowed, self.role
        function_registry.register(
            self.NAME,
            lambda payload: {"allowed": allowed, "role": role if allowed else None},
        )
        return self

    def __exit__(self, *exc):
        from stapel_core.comm.registry import function_registry

        function_registry._providers.pop(self.NAME, None)
        function_registry._schemas.pop(self.NAME, None)
        if self._previous is not None:
            function_registry._providers[self.NAME] = self._previous
        if self._previous_schema is not None:
            function_registry._schemas[self.NAME] = self._previous_schema
        return False


SIMPLE_SCHEMA = {
    "fields": [
        {"slug": "sec", "name": "About you", "config": {"type": "header"}},
        {
            "slug": "full_name",
            "name": "Full name",
            "mandatory": True,
            "config": {"type": "string", "maxLength": 40},
        },
        {"slug": "age", "name": "Age", "config": {"type": "int", "min": 0, "max": 130}},
        {
            "slug": "plan",
            "name": "Plan",
            "mandatory": True,
            "config": {
                "type": "select",
                "options": [
                    {"value": "basic", "label": "Basic"},
                    {"value": "pro", "label": "Pro"},
                ],
            },
        },
    ],
    "meta": {
        "title": "Sign up",
        "confirmation_text": "Thanks — we will be in touch.",
        "submit_label": "Send",
    },
}

#: The emptiest form this module will actually PUBLISH: one question, and no
#: ``meta`` at all — no title, no submit label, no confirmation text. A
#: schema with no fields is refused outright (``schema.validate_schema`` ->
#: ``error.400.forms_empty_schema``), which is itself the answer to "what is
#: the emptiest legal state": not nothing.
BARE_SCHEMA: dict = {
    "fields": [{"slug": "q", "name": "Q", "config": {"type": "string"}}]
}


class Workspace:
    """One workspace id plus the account that may act in it."""

    def __init__(self):
        self.id = uuid.uuid4()
        self.user = make_user()

    @property
    def query(self):
        return f"?workspace_id={self.id}"

    def client(self):
        return client_for(self.user)


def make_form(workspace, *, schema=SIMPLE_SCHEMA, publish=False, state=None,
              settings=None):
    from stapel_forms import services

    form = services.create_form(
        workspace_id=workspace.id,
        title="Sign up",
        user=workspace.user,
        settings=settings if settings is not None else {
            "notify_emails": ["sales@example.test"]
        },
        draft_schema=schema,
    )
    if publish:
        services.publish(form, user=workspace.user)
        services.set_state(form, state or "open")
        form.refresh_from_db()
    return form


def make_submission(form, answers=None, user_id=None):
    from stapel_forms import services

    return services.submit(
        form,
        answers=answers if answers is not None else {"full_name": "Ann", "plan": "pro"},
        user_id=user_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# The recipe table
# ─────────────────────────────────────────────────────────────────────────────


class Call:
    """Performs one declared operation, and refuses to guess a path parameter."""

    def __init__(self, method, path):
        self.method = method
        self.path = path

    def __call__(self, client, params=None, data=None, query="", **extra):
        url = self.path
        for name, value in (params or {}).items():
            url = url.replace("{%s}" % name, str(value))
        assert "{" not in url, (
            f"{self.method} {self.path}: a path parameter this gate does not "
            "know how to fill — teach its recipe, or the operation goes unchecked"
        )
        send = getattr(client, self.method.lower())
        if self.method in ("GET", "DELETE"):
            return send(url + query, **extra)
        return send(url + query, data if data is not None else {}, format="json", **extra)


#: How to perform each operation the contract declares with a JSON response
#: body, keyed by ``(METHOD, path template, status code)``. ``code`` is
#: ``None`` for the usual case of one 2xx per operation.
RECIPES = {}

#: The same operations again, in the emptiest state the contract still has to
#: describe: no rows, or the one row the operation addresses carrying none of
#: its optional values. A populated answer cannot say what a field holds when
#: there is nothing to hold, and that is where every null finding in the first
#: wave of this gate was.
EMPTY_STATE = {}


def recipe(method, path, code=None, table=None):
    def register(fn):
        target = RECIPES if table is None else table
        key = (method, V1 + path, code)
        assert key not in target, f"duplicate recipe for {method} {path} {code}"
        target[key] = fn
        return fn

    return register


def empty_state(method, path, code=None):
    return recipe(method, path, code, table=EMPTY_STATE)


#: Operations that cannot be driven in-process, by name and with the reason.
#:
#: EMPTY. Every operation this module declares is reachable from a test
#: client, including the whole admin surface — that is gated on a comm
#: Function stapel-workspaces owns, which is a SEAM a deployment wires, so
#: the gate wires it too. The CSV export declares no JSON body and is
#: therefore not an operation here at all.
UNDRIVABLE: dict = {}

#: Where the rows live, for operations whose collection is NESTED in an
#: object. An empty array validates against any item schema, so the populated
#: pass has to insist the array actually carried something; the top-level
#: arrays are checked by shape without an entry here.
COLLECTION_KEYS = {
    ("GET", V1 + "/field-kinds"): ("kinds",),
    ("GET", V1 + "/public/{public_id}/"): ("fields",),
}


# ── the public surface ───────────────────────────────────────────────────────


@recipe("GET", "/public/{public_id}/")
def _public_form(call):
    form = make_form(Workspace(), publish=True)
    return call(anonymous(), params={"public_id": form.public_id})


@empty_state("GET", "/public/{public_id}/")
def _public_form_empty(call):
    """The emptiest publishable form: one question and no ``meta`` at all.

    ``meta`` is ``{}`` here and nowhere else — no title, no submit label, no
    confirmation text — which is the state a renderer's fallbacks exist for.
    A schema with NO fields is refused by ``services.publish``, so this is
    the floor rather than a contrivance.
    """
    form = make_form(Workspace(), schema=BARE_SCHEMA, publish=True)
    return call(anonymous(), params={"public_id": form.public_id})


@recipe("POST", "/public/{public_id}/submissions/")
def _public_submit(call):
    form = make_form(Workspace(), publish=True)
    return call(
        anonymous(),
        params={"public_id": form.public_id},
        data={
            "answers": {"full_name": "Ann", "plan": "pro", "age": 33},
            "version_id": str(form.active_version_id),
        },
    )


# ── the builder's dictionary ─────────────────────────────────────────────────


@recipe("GET", "/field-kinds")
def _field_kinds(call):
    """A deployment that allow-lists the module's own default kinds."""
    workspace = Workspace()
    with capability_seam():
        return call(workspace.client(), query=workspace.query)


@empty_state("GET", "/field-kinds")
def _field_kinds_empty(call):
    """A deployment that allow-lists NOTHING.

    Every registered kind still appears — a schema published before a kind
    left the allowlist still has to render — but ``allowed`` is false on all
    of them and the answer carries no ``config_widgets`` a builder could use.
    """
    workspace = Workspace()
    with capability_seam(), override_settings(STAPEL_FORMS={"FIELD_KINDS": []}):
        return call(workspace.client(), query=workspace.query)


# ── forms ────────────────────────────────────────────────────────────────────


@recipe("GET", "/forms")
def _form_list(call):
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    make_submission(form)
    with capability_seam():
        return call(workspace.client(), query=workspace.query)


@empty_state("GET", "/forms")
def _form_list_empty(call):
    """A workspace nobody has built a form in."""
    workspace = Workspace()
    with capability_seam():
        return call(workspace.client(), query=workspace.query)


@recipe("POST", "/forms")
def _form_create(call):
    workspace = Workspace()
    with capability_seam():
        return call(
            workspace.client(),
            data={
                "workspace_id": str(workspace.id),
                "title": "Contact us",
                "settings": {"notify_emails": ["sales@example.test"]},
                "draft_schema": SIMPLE_SCHEMA,
            },
        )


@recipe("GET", "/forms/{form_id}")
def _form_detail(call):
    """A form with everything on it: published, open, answered."""
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    make_submission(form)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@empty_state("GET", "/forms/{form_id}")
def _form_detail_empty(call):
    """A form the moment it is created: never published, never answered.

    ``active_version``, ``active_version_id`` and ``deleted_at`` are all null
    here and nowhere else, and ``submission_count`` is zero. This is the
    state stapel-profiles' ``created_at`` lie was found in — a field that is
    only ever inspected on a fully populated row is a field nobody checks.
    """
    workspace = Workspace()
    from stapel_forms import services

    form = services.create_form(
        workspace_id=workspace.id, title="Untitled", user=workspace.user
    )
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@recipe("PATCH", "/forms/{form_id}")
def _form_patch(call):
    workspace = Workspace()
    form = make_form(workspace)
    with capability_seam():
        return call(
            workspace.client(),
            params={"form_id": form.id},
            query=workspace.query,
            data={"title": "Contact us (renamed)"},
        )


@recipe("PUT", "/forms/{form_id}/draft")
def _form_draft(call):
    workspace = Workspace()
    form = make_form(workspace, schema=BARE_SCHEMA)
    with capability_seam():
        return call(
            workspace.client(),
            params={"form_id": form.id},
            query=workspace.query,
            data={"schema": SIMPLE_SCHEMA},
        )


@recipe("POST", "/forms/{form_id}/publish")
def _form_publish(call):
    workspace = Workspace()
    form = make_form(workspace)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@recipe("POST", "/forms/{form_id}/rotate-link")
def _form_rotate_link(call):
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@recipe("POST", "/forms/{form_id}/state")
def _form_state(call):
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    with capability_seam():
        return call(
            workspace.client(),
            params={"form_id": form.id},
            query=workspace.query,
            data={"state": "closed"},
        )


@recipe("GET", "/forms/{form_id}/versions")
def _form_versions(call):
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    make_submission(form)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@empty_state("GET", "/forms/{form_id}/versions")
def _form_versions_empty(call):
    """A form nobody has published — no versions at all."""
    workspace = Workspace()
    form = make_form(workspace)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


# ── responses ────────────────────────────────────────────────────────────────


@recipe("GET", "/forms/{form_id}/submissions")
def _form_submissions(call):
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    with override_settings(STAPEL_FORMS={"STORE_CLIENT_META": True}):
        make_submission(form, user_id=workspace.user.pk)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@empty_state("GET", "/forms/{form_id}/submissions")
def _form_submissions_empty(call):
    """A published, open form nobody has answered."""
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    with capability_seam():
        return call(
            workspace.client(), params={"form_id": form.id}, query=workspace.query
        )


@recipe("GET", "/submissions/{submission_id}")
def _submission_detail(call):
    """A response with everything recorded: a signed-in respondent, and the
    client forensics a host that turned ``STORE_CLIENT_META`` on collects."""
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    with override_settings(STAPEL_FORMS={"STORE_CLIENT_META": True}):
        submission = make_submission(form, user_id=workspace.user.pk)
    with capability_seam():
        return call(
            workspace.client(),
            params={"submission_id": submission.id},
            query=workspace.query,
        )


@empty_state("GET", "/submissions/{submission_id}")
def _submission_detail_empty(call):
    """An anonymous response on a deployment that stores no forensics.

    ``submitted_by`` and ``client_meta`` are both null here — the default
    posture, and the one a host runs in unless it opted into collecting
    respondent metadata — and ``erased_at`` is null because the row is live.
    """
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    submission = make_submission(form, answers={"full_name": "A", "plan": "basic"})
    with capability_seam():
        return call(
            workspace.client(),
            params={"submission_id": submission.id},
            query=workspace.query,
        )


@recipe("POST", "/submissions/{submission_id}/resend")
def _submission_resend(call):
    """Re-delivery to the form's configured targets.

    ``notifications._request`` logs and swallows a transport failure by
    design — the row is already committed — so the count in the body is the
    number of DESTINATIONS addressed, which is what this operation claims.
    """
    workspace = Workspace()
    form = make_form(workspace, publish=True)
    submission = make_submission(form)
    with capability_seam():
        return call(
            workspace.client(),
            params={"submission_id": submission.id},
            query=workspace.query,
            data={"recipients": ["ops@example.test", "legal@example.test"]},
        )


# ─────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────


#: Operations whose declared body the wire does not send.
#:
#: EMPTY, and that is the finding rather than the absence of one: 15 of 15
#: operations were driven and every declared body held, in both the populated
#: and the empty state. The mechanism stays because the next change will need
#: it — an entry must name the defect AND its owner, and ``strict=True`` turns
#: a fixed one into a failure until the entry is deleted, so a finding can be
#: neither forgotten nor quietly kept.
KNOWN_MISMATCHES: dict = {}

#: Which pass each recorded mismatch applies to.
#:
#: A defect that shows in only ONE state must not xfail the other: with
#: ``strict=True`` an honest answer marked xfail is itself a failure, and
#: marking both passes would be a claim this gate has not made. Anything not
#: named here applies to both.
MISMATCH_STATES: dict = {}

_ALL_STATES = frozenset({"populated", "empty"})


def _mismatch_reason(method, path, state):
    """The recorded reason if this operation lies in THIS state, else None."""
    key = (method, path)
    if key not in KNOWN_MISMATCHES:
        return None
    if state not in MISMATCH_STATES.get(key, _ALL_STATES):
        return None
    return KNOWN_MISMATCHES[key]


def _recipe_for(table, method, path, code):
    """The code-specific recipe if there is one, else the operation's."""
    return table.get((method, path, code)) or table.get((method, path, None))


def test_the_contract_declares_something_to_check():
    assert OPERATIONS, "docs/schema.json declares no JSON responses at all"


def test_every_declared_path_resolves_under_this_urlconf():
    """The suite must be looking where the document describes.

    Five of the first eight libraries this gate was written for had a
    committed contract that nothing had ever driven, because the test urlconf
    mounted somewhere the document does not describe: a prefix one segment
    short, the paths bare, less than the emission, both segments skipped, a
    doubled prefix. In every case the operations were "covered" by a file that
    could not have reached a single one of them.

    That is the same family as a gate nobody asks: the recipes can all be
    written, the run can be green, and not one request went where the contract
    says it goes. A missing recipe already fails loudly; this fails when the
    MOUNT is wrong, which no per-operation check can see, because when the
    mount is wrong every operation is equally and silently unreachable.

    Asserted against the urlconf THIS module declares — inheriting the suite's
    mount would be exactly the blindness the check exists to remove.
    """
    from django.urls import Resolver404, resolve

    # Resolution cares about the SHAPE of a segment, and this URL set mixes
    # uuid converters with the free-form public handle. A path counts as
    # reachable if any one shape resolves: the question here is whether the
    # mount exists, not whether a particular id does.
    candidates = (
        "00000000-0000-4000-8000-000000000000",
        "1",
        "a-slug",
    )

    unreachable = []
    for _method, path, _code, _schema in OPERATIONS:
        for value in candidates:
            try:
                resolve(re.sub(r"\{[^}]+\}", value, path))
                break
            except Resolver404:
                continue
        else:
            unreachable.append(path)

    assert not unreachable, (
        "these declared paths do not resolve under this module's urlconf, so "
        "nothing here can be driving them — the mount is wrong, not the "
        "recipes:\n  " + "\n  ".join(sorted(set(unreachable)))
    )


def test_every_declared_operation_is_driven_or_named_undrivable():
    """No operation is covered by silence, and no entry outlives its operation."""
    missing = [
        (method, path, code)
        for method, path, code, _schema in OPERATIONS
        if _recipe_for(RECIPES, method, path, code) is None
        and (method, path) not in UNDRIVABLE
    ]
    assert not missing, (
        "operations with a declared JSON response body and no recipe:\n"
        + "\n".join(f"  {m} {p} -> {c}" for m, p, c in missing)
    )

    declared_codes = {(m, p, c) for m, p, c, _ in OPERATIONS}
    declared_ops = {(m, p) for m, p, _c, _ in OPERATIONS}
    stale = sorted(
        key
        for key in RECIPES
        if (key[0], key[1]) not in declared_ops
        or (key[2] is not None and key not in declared_codes)
    )
    assert not stale, (
        "recipes for operations/status codes the contract no longer declares:\n"
        + "\n".join(f"  {m} {p} -> {c}" for m, p, c in stale)
    )
    stale_exclusions = sorted(set(UNDRIVABLE) - declared_ops)
    assert not stale_exclusions, (
        f"exclusions for operations the contract no longer declares: {stale_exclusions}"
    )
    both = sorted((m, p) for m, p, _c in RECIPES if (m, p) in UNDRIVABLE)
    assert not both, f"driven AND excluded: {both}"
    for key, reason in UNDRIVABLE.items():
        assert reason and reason.strip(), f"{key} is excluded with no reason"

    # RECIPES ∪ UNDRIVABLE is EXACTLY the declared set — asserted as sets, so
    # neither an operation nobody drives nor an entry nobody needs survives.
    covered = {(m, p) for m, p, _c in RECIPES} | set(UNDRIVABLE)
    assert covered == declared_ops, (
        "RECIPES ∪ UNDRIVABLE is not the declared set:\n"
        f"  declared but uncovered: {sorted(declared_ops - covered)}\n"
        f"  covered but undeclared: {sorted(covered - declared_ops)}"
    )

    stale_collections = sorted(set(COLLECTION_KEYS) - declared_ops)
    assert not stale_collections, (
        f"COLLECTION_KEYS names operations the contract no longer declares: "
        f"{stale_collections}"
    )


def test_every_read_is_also_driven_in_its_emptiest_state():
    """A populated answer cannot say what a field holds when there is nothing.

    Every null finding in the first wave of this gate was on the empty state.
    A gate that only ever seeds three rows and asks never sees any of them.
    """
    exempt: set = set()
    reads = {
        (method, path)
        for method, path, _code, _schema in OPERATIONS
        if method == "GET"
    }
    covered = {(m, p) for m, p, _c in EMPTY_STATE}
    missing = sorted(reads - covered - exempt)
    assert not missing, (
        "reads driven only against a populated database — the state where "
        "every null claim in this gate's history was found is unchecked:\n"
        + "\n".join(f"  {m} {p}" for m, p in missing)
    )
    declared_ops = {(m, p) for m, p, _c, _ in OPERATIONS}
    stale = sorted({(m, p) for m, p, _c in EMPTY_STATE} - declared_ops)
    assert not stale, f"empty-state recipes for undeclared operations: {stale}"


def test_every_known_mismatch_is_still_declared_and_explained():
    """A recorded defect must name a live operation and carry its reason.

    Without this, an operation that is renamed or removed leaves an entry that
    silences nothing and reads like a known problem forever.
    """
    declared = {(method, path) for method, path, _code, _schema in OPERATIONS}
    for key, reason in KNOWN_MISMATCHES.items():
        assert key in declared, (
            f"{key} is recorded as a known mismatch but the contract no longer "
            "declares it — delete the entry"
        )
        assert reason and reason.strip(), f"{key} is recorded with no reason"

    stale_states = sorted(set(MISMATCH_STATES) - set(KNOWN_MISMATCHES))
    assert not stale_states, (
        f"MISMATCH_STATES narrows operations that are not recorded as "
        f"mismatches at all: {stale_states}"
    )
    for key, states in MISMATCH_STATES.items():
        assert states and states <= _ALL_STATES, (
            f"{key} is narrowed to {sorted(states)}, which is not a subset of "
            f"{sorted(_ALL_STATES)} — an empty or unknown set silences nothing"
        )


def _drive(table, method, path, code, body_schema, *, expect_rows):
    perform = _recipe_for(table, method, path, code)
    assert perform is not None, (
        f"{method} {path} declares a response body and has no recipe — an "
        "unchecked operation is a schema nobody proves. Teach RECIPES, or "
        "name it in UNDRIVABLE with a reason."
    )

    response = perform(Call(method, path))
    assert response.status_code == code, (
        f"{method} {path}: expected the declared {code}, got "
        f"{response.status_code}: {response.content[:400]}"
    )

    body = response.json()
    errors = sorted(_validator(body_schema).iter_errors(body), key=lambda e: list(e.path))
    assert not errors, (
        f"{method} {path} answers a body the contract does not describe:\n"
        + "\n".join(f"  at {list(e.path) or '<root>'}: {e.message}" for e in errors[:10])
        + f"\n  body: {json.dumps(body)[:600]}"
    )
    # The other direction: a key the document never mentions is a key no
    # generated client has a field for.
    undeclared = _undeclared_keys(body, body_schema)
    assert not undeclared, (
        f"{method} {path} answers keys the contract never mentions, so no "
        f"generated client has a field for them: {sorted(undeclared)}"
        + f"\n  body: {json.dumps(body)[:600]}"
    )
    # An empty list validates against any item schema, so a collection must
    # actually carry a row for the check to have looked at anything — both the
    # top-level arrays and the ones nested in an envelope.
    if expect_rows:
        if isinstance(body, list):
            assert body, f"{method} {path}: the declared collection came back empty"
        if isinstance(body, dict):
            for key in COLLECTION_KEYS.get((method, path), ()):
                assert body.get(key), (
                    f"{method} {path}: the declared {key!r} collection came "
                    "back empty, so its item schema was never looked at"
                )
    return body


@pytest.mark.parametrize(
    "method,path,code,body_schema",
    OPERATIONS,
    ids=[f"{m} {p} {c}" for m, p, c, _ in OPERATIONS],
)
def test_the_wire_matches_the_declared_response(method, path, code, body_schema, request):
    if (method, path) in UNDRIVABLE:
        pytest.skip(f"excluded by name: {UNDRIVABLE[(method, path)]}")

    reason = _mismatch_reason(method, path, "populated")
    if reason is not None:
        request.node.add_marker(
            pytest.mark.xfail(strict=True, reason=f"{method} {path}: {reason}")
        )

    _drive(RECIPES, method, path, code, body_schema, expect_rows=True)


_EMPTY_OPERATIONS = [
    (method, path, code, schema)
    for method, path, code, schema in OPERATIONS
    if _recipe_for(EMPTY_STATE, method, path, code) is not None
]


@pytest.mark.parametrize(
    "method,path,code,body_schema",
    _EMPTY_OPERATIONS,
    ids=[f"{m} {p} {c}" for m, p, c, _ in _EMPTY_OPERATIONS],
)
def test_the_wire_matches_the_declared_response_when_there_is_nothing_there(
    method, path, code, body_schema, request
):
    """The same claim, asked in the state where the nulls live."""
    reason = _mismatch_reason(method, path, "empty")
    if reason is not None:
        request.node.add_marker(
            pytest.mark.xfail(strict=True, reason=f"{method} {path}: {reason}")
        )

    _drive(EMPTY_STATE, method, path, code, body_schema, expect_rows=False)


def test_the_undeclared_key_check_is_not_blind():
    """The enumeration half, canaried the way the validation half is.

    A check that silently returned an empty list for every input would look
    exactly like a clean run. So: give it a real body and a schema that
    enumerates only one of its keys, and require it to name the rest.
    """
    schema = {"type": "object", "properties": {"kept": {"type": "string"}}}
    body = {"kept": "yes", "extra": 1, "another": None}
    assert sorted(_undeclared_keys(body, schema)) == ["another", "extra"]

    # A schema that declines to enumerate (a free-form map) reports nothing,
    # and a nested object is walked rather than skipped.
    assert _undeclared_keys(body, {"type": "object", "additionalProperties": {}}) == []
    nested = {
        "type": "object",
        "properties": {"inner": {"type": "object", "properties": {}}},
    }
    assert _undeclared_keys({"inner": {"surprise": 1}}, nested) == []


def test_the_gate_is_not_blind():
    """A canary: swap a declared schema for one the wire cannot satisfy.

    Everything above can be green for two reasons — the claims are honest, or
    the check never looks at the body. This tells them apart by validating a
    real response against ``{"type": "string"}``: every operation here answers
    an object or an array, so every one of them must fail. If any passes, the
    validation in ``_drive`` is not reaching the received body and this whole
    file proves nothing. With ``KNOWN_MISMATCHES`` empty this covers the
    entire declared surface.
    """
    honest = [
        (method, path, code)
        for method, path, code, _schema in OPERATIONS
        if (method, path) not in KNOWN_MISMATCHES and (method, path) not in UNDRIVABLE
    ]
    assert honest, "nothing left to canary"

    survivors = []
    for method, path, code in honest:
        try:
            _drive(RECIPES, method, path, code, {"type": "string"}, expect_rows=False)
        except AssertionError:
            continue
        survivors.append(f"{method} {path}")
    assert not survivors, (
        "these operations passed validation against {'type': 'string'} — the "
        "gate is not looking at the body it received:\n  " + "\n  ".join(survivors)
    )
