"""``GET /forms/api/v1/field-kinds`` — the builder's dictionary.

The React pair builds its field-config forms off stapel-attributes'
``config_form()`` declarations (spec §8). Until this route existed it read a
hand-written TypeScript mirror of ``BUILTIN_FORMS`` (§11c delta 1), which is
a table that drifts silently. These tests pin the properties the mirror
cannot have: the live registry, EXTRA_TYPES included, and the upstream quirks
the pair had pinned client-side now pinned on the side that owns them.
"""
import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

BASE = "/forms/api/v1"
URL = f"{BASE}/field-kinds"


@pytest.fixture
def authed(api_client, user, workspace_id, grant_capabilities):
    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk)
    return api_client


@pytest.fixture
def extra_type():
    """Register a host type the way a deployment does — via EXTRA_TYPES.

    Torn down explicitly: the attributes registry is process-global, and a
    leaked slug would make some later test's ``registered_types()`` depend
    on execution order.
    """
    from stapel_attributes import registry

    from .extra_type import EXTRA_TYPE_PATH, EXTRA_TYPE_SLUG

    with override_settings(STAPEL_ATTRIBUTES={"EXTRA_TYPES": [EXTRA_TYPE_PATH]}):
        registry.registered_types()  # forces the lazy EXTRA_TYPES load
        yield EXTRA_TYPE_SLUG
    registry._FEATURE_TYPES.pop(EXTRA_TYPE_SLUG, None)
    registry._loaded_extra_paths.discard(EXTRA_TYPE_PATH)


def _kinds(payload):
    return {entry["kind"]: entry for entry in payload["kinds"]}


def _fields(entry):
    return {declaration["name"]: declaration for declaration in entry["fields"]}


# ── Shape ────────────────────────────────────────────────────────────


def test_returns_the_catalogue(authed, workspace_id):
    resp = authed.get(URL, {"workspace_id": str(workspace_id)})
    assert resp.status_code == 200
    payload = resp.json()
    assert set(payload) == {"kinds", "config_widgets"}

    kinds = _kinds(payload)
    # Every built-in the engine registers, whether or not forms allowlists it.
    assert {"string", "int", "float", "bool", "select", "date", "header"} <= set(kinds)
    for entry in payload["kinds"]:
        assert set(entry) == {"kind", "label_key", "allowed", "registered", "fields"}
        assert entry["label_key"] == f"admin.attributes.type.{entry['kind']}"
    # Deterministic order — the builder renders the palette straight from it.
    assert [entry["kind"] for entry in payload["kinds"]] == sorted(kinds)


def test_declarations_keep_upstream_shape(authed, workspace_id):
    """The declaration is passed through, not re-shaped by this module."""
    payload = authed.get(URL, {"workspace_id": str(workspace_id)}).json()
    allowed_keys = {"name", "kind", "label_key", "required", "default", "params"}
    widgets = set(payload["config_widgets"])
    for entry in payload["kinds"]:
        for declaration in entry["fields"]:
            assert set(declaration) <= allowed_keys
            assert {"name", "kind", "label_key"} <= set(declaration)
            assert declaration["kind"] in widgets


def test_config_widget_dictionary_is_served(authed, workspace_id):
    payload = authed.get(URL, {"workspace_id": str(workspace_id)}).json()
    assert payload["config_widgets"]["number"] == ["step"]
    assert payload["config_widgets"]["checkbox"] == []
    assert payload["config_widgets"]["select"] == ["options"]


def test_pins_the_quirks_the_pair_had_to_mirror(authed, workspace_id):
    """§11c delta 1: each of these is a default the client had pinned blind."""
    kinds = _kinds(authed.get(URL, {"workspace_id": str(workspace_id)}).json())

    # LN-B15: hex_color.allowCustom defaults FALSE where int/float/string are TRUE.
    assert _fields(kinds["hex_color"])["allowCustom"]["default"] is False
    assert _fields(kinds["int"])["allowCustom"]["default"] is True
    assert _fields(kinds["string"])["allowCustom"]["default"] is True

    # LN-B01: header.style defaults to "h2", which matches NEITHER option.
    style = _fields(kinds["header"])["style"]
    assert style["default"] == "h2"
    assert [option["value"] for option in style["params"]["options"]] == ["l", "m"]

    # The engine's own select defaults: dropdown, and no maxSelected default
    # at all (absent means unlimited).
    select = _fields(kinds["select"])
    assert select["uiStyle"]["default"] == "dropdown"
    assert "default" not in select["maxSelected"]


def test_string_declares_multiline(authed, workspace_id):
    """The 0.4.6 floor, visible on the wire: the textarea-vs-input hint."""
    kinds = _kinds(authed.get(URL, {"workspace_id": str(workspace_id)}).json())
    multiline = _fields(kinds["string"])["multiline"]
    assert multiline["kind"] == "checkbox"
    assert multiline["default"] is False  # absent means single-line


# ── Kinds the builder cannot render ──────────────────────────────────


def test_a_kind_without_a_config_form_is_listed_empty(authed, workspace_id):
    """§12 risk 5 / §11c delta 4 — ``convertible_unit`` declares no form.

    Listed with an empty ``fields`` list rather than omitted: the empty list
    is the builder's signal to state what it cannot show, and an omission
    would read as "this kind does not exist".
    """
    kinds = _kinds(authed.get(URL, {"workspace_id": str(workspace_id)}).json())
    assert kinds["convertible_unit"]["registered"] is True
    assert kinds["convertible_unit"]["fields"] == []


@override_settings(STAPEL_FORMS={"FIELD_KINDS": ["string", "not_a_kind"]})
def test_an_allowlisted_unknown_kind_is_listed_as_unregistered(authed, workspace_id):
    """A kind the host allowlisted that the registry does not carry.

    It still appears — a stored schema may already use it, and a builder
    that never hears the name silently drops the field.
    """
    kinds = _kinds(authed.get(URL, {"workspace_id": str(workspace_id)}).json())
    assert kinds["not_a_kind"] == {
        "kind": "not_a_kind",
        "label_key": "admin.attributes.type.not_a_kind",
        "allowed": True,
        "registered": False,
        "fields": [],
    }


@override_settings(STAPEL_FORMS={"FIELD_KINDS": ["string"]})
def test_allowed_tracks_the_host_allowlist(authed, workspace_id):
    kinds = _kinds(authed.get(URL, {"workspace_id": str(workspace_id)}).json())
    assert kinds["string"]["allowed"] is True
    # Registered, renderable, but not offerable for a NEW field.
    assert kinds["int"]["allowed"] is False
    assert kinds["int"]["registered"] is True
    assert kinds["int"]["fields"]


# ── EXTRA_TYPES ──────────────────────────────────────────────────────


def test_extra_types_reach_the_builder(authed, workspace_id, extra_type):
    """The whole point: a host type with no release of this module."""
    kinds = _kinds(authed.get(URL, {"workspace_id": str(workspace_id)}).json())
    entry = kinds[extra_type]
    assert entry["registered"] is True
    assert entry["allowed"] is False  # not in the FIELD_KINDS allowlist
    assert entry["fields"] == [
        {
            "name": "policyUrl",
            "kind": "text",
            "label_key": "admin.attributes.form.consent.policyUrl",
            "required": True,
        }
    ]


# ── Authorization ────────────────────────────────────────────────────


def test_anonymous_is_refused(api_client, workspace_id):
    assert api_client.get(URL, {"workspace_id": str(workspace_id)}).status_code in (401, 403)


def test_no_capability_is_refused(api_client, user, workspace_id):
    api_client.force_authenticate(user=user)
    resp = api_client.get(URL, {"workspace_id": str(workspace_id)})
    assert resp.status_code == 403
    assert resp.json()["localizable_error"] == "error.403.forms_forbidden"


def test_view_capability_does_not_grant_the_builder(
    api_client, user, workspace_id, grant_capabilities
):
    """Same capability as form management — a reader has no use for it."""
    from django.core.cache import cache

    api_client.force_authenticate(user=user)
    grant_capabilities(workspace_id, user.pk, "forms.view")
    assert api_client.get(URL, {"workspace_id": str(workspace_id)}).status_code == 403
    grant_capabilities(workspace_id, user.pk, "forms.manage")
    cache.clear()  # the capability verdict is cached for 30 s
    assert api_client.get(URL, {"workspace_id": str(workspace_id)}).status_code == 200


def test_workspace_id_is_required(authed):
    assert authed.get(URL).status_code == 400
