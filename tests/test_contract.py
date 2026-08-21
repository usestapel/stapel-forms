"""The committed contract artifacts must describe the API that ships.

``make contract-check`` re-emits the quintet and diffs it, but it needs the
pinned Python 3.12 interpreter plus stapel-tools, so it is a dev-loop and
release gate rather than something the 3.11/3.12/3.13 CI matrix can run.
These tests are the part that runs everywhere: they read the COMMITTED
artifacts and assert the two properties a stale artifact silently breaks —
every route this module mounts is described, and every error key it can
return is declared.

The second one is why this file exists. ``docs/errors.json`` shipped 63 keys
in 0.1.0 and not one of the ``error.400.feature_*`` family, even though the
submit path returns those codes at the top level of a per-field refusal
(§11c delta 2): the frontend bundle generated from the artifact could not
cover the errors a respondent is most likely to see.
"""
import json
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parent.parent / "docs"


@pytest.fixture(scope="module")
def errors_artifact():
    return {entry["code"]: entry for entry in json.loads((DOCS / "errors.json").read_text())}


@pytest.fixture(scope="module")
def schema_artifact():
    return json.loads((DOCS / "schema.json").read_text())


# ── errors.json ──────────────────────────────────────────────────────


def test_forms_owned_keys_are_declared(errors_artifact):
    from stapel_forms.errors import STAPEL_FORMS_ERRORS

    for code, text in STAPEL_FORMS_ERRORS.items():
        assert code in errors_artifact, f"{code} missing from docs/errors.json"
        assert errors_artifact[code]["owner"] == "stapel_forms"
        assert errors_artifact[code]["en"] == text


def test_the_attributes_validation_family_is_declared(errors_artifact):
    """§11c delta 2 — the family the submit path returns, in the artifact.

    Owned by (and translated by) stapel-attributes: this module only forces
    the registration so the key lands wherever forms is mounted. Asserting
    the OWNER too is the half that keeps the fix honest — a future release
    that "fixes" this by copying the strings into ``STAPEL_FORMS_ERRORS``
    would take on a catalogue obligation that is upstream's, and this test
    goes red instead of the catalogues going quietly out of sync.
    """
    from stapel_forms.errors import ATTRIBUTE_VALIDATION_ERRORS

    assert ATTRIBUTE_VALIDATION_ERRORS, "the attributes registry came back empty"
    for code in ATTRIBUTE_VALIDATION_ERRORS:
        assert code in errors_artifact, f"{code} missing from docs/errors.json"
        assert errors_artifact[code]["owner"] == "stapel_attributes"


def test_every_code_the_submit_path_can_raise_is_declared(errors_artifact):
    """Walked from the engine's own mapping, not from a hand-kept list.

    ``schema.validate_answers`` returns ``row.localizable_error`` verbatim
    and ``services.submit`` re-raises the first one, so the reachable set is
    exactly the image of ``ERROR_CODE_TO_KEY`` plus the fallback.
    """
    from stapel_attributes.errors import ERROR_CODE_TO_KEY

    reachable = set(ERROR_CODE_TO_KEY.values()) | {"error.400.feature_invalid_type"}
    assert reachable <= set(errors_artifact)


def test_the_error_keys_view_stays_forms_owned():
    """The stapel-translate collector must not be told forms owns upstream.

    ``/error-keys/`` is what drives catalogue regeneration for a service.
    Listing another package's keys there would silently move the translation
    obligation onto this repo.
    """
    from stapel_attributes.errors import ATTRIBUTES_ERRORS
    from stapel_forms.errors import STAPEL_FORMS_ERRORS

    assert not set(STAPEL_FORMS_ERRORS) & set(ATTRIBUTES_ERRORS)
    assert all(code.split(".")[-1].startswith("forms_") for code in STAPEL_FORMS_ERRORS)


# ── schema.json ──────────────────────────────────────────────────────


def test_every_mounted_route_is_described(schema_artifact):
    """A route added without regenerating the quintet fails here.

    The gap this closes is not hypothetical: the pair reads ``schema.json``
    to generate its typed client, so an endpoint missing from the artifact
    is an endpoint the frontend cannot call.
    """
    import re

    from stapel_forms import urls_v1

    described = set(schema_artifact["paths"])
    for pattern in urls_v1.urlpatterns:
        route = str(pattern.pattern)
        if route == "error-keys/":
            continue  # the translate collector's listing, not a product route
        # `<uuid:form_id>` -> `{form_id}`, and drf-spectacular keeps the
        # trailing slash exactly as mounted.
        route = re.sub(r"<(?:[a-z_]+:)?([^>]+)>", r"{\1}", route)
        assert f"/forms/api/v1/{route}" in described, (
            f"{route} is mounted but absent from docs/schema.json — "
            "run 'make contract' and commit the artifacts"
        )


def test_the_field_kinds_route_is_described(schema_artifact):
    """§11c delta 1 — the endpoint that deletes the pair's TypeScript mirror."""
    operation = schema_artifact["paths"]["/forms/api/v1/field-kinds"]["get"]
    assert [p["name"] for p in operation["parameters"]] == ["workspace_id"]
    assert operation["parameters"][0]["required"] is True
