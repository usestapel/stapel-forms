"""``forms.form.exists`` — the save-time form-reference check for other modules."""
import json
from pathlib import Path

import pytest

from stapel_core.comm import call
from stapel_core.comm.exceptions import SchemaValidationError

pytestmark = pytest.mark.django_db

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "functions" / "forms.form.exists.json"


@pytest.fixture
def form(workspace_id, user, simple_schema):
    from stapel_forms import services

    return services.create_form(
        workspace_id=workspace_id, title="Secret draft title", user=user, draft_schema=simple_schema
    )


def _ask(public_id):
    return call("forms.form.exists", {"public_id": public_id})


def test_unknown_handle():
    assert _ask("no-such-form") == {"exists": False, "published": False}


def test_draft_exists_but_is_not_published(form):
    assert _ask(form.public_id) == {"exists": True, "published": False}


def test_open_form_is_published(form, user):
    from stapel_forms import services

    services.publish(form, user=user)
    services.set_state(form, "open")
    assert _ask(form.public_id) == {"exists": True, "published": True}


def test_closed_form_is_not_published(form, user):
    from stapel_forms import services

    services.publish(form, user=user)
    services.set_state(form, "open")
    services.set_state(form, "closed")
    assert _ask(form.public_id) == {"exists": True, "published": False}


def test_soft_deleted_form_does_not_exist(form, user):
    from stapel_forms import services

    services.publish(form, user=user)
    services.set_state(form, "open")
    services.delete_form(form)
    assert _ask(form.public_id) == {"exists": False, "published": False}


def test_rotated_handle_no_longer_exists(form):
    from stapel_forms import services

    old = form.public_id
    services.rotate_link(form)
    assert _ask(old) == {"exists": False, "published": False}
    assert _ask(form.public_id)["exists"] is True


def test_answer_carries_no_form_content(form):
    answer = _ask(form.public_id)
    assert set(answer) == {"exists", "published"}
    assert "Secret draft title" not in json.dumps(answer)


@pytest.mark.parametrize("payload", [{}, {"public_id": ""}, {"public_id": "x" * 33}, {"public_id": "a", "extra": 1}])
def test_malformed_payload_rejected(settings, payload):
    settings.STAPEL_COMM = {**getattr(settings, "STAPEL_COMM", {}), "VALIDATE_SCHEMAS": True}
    with pytest.raises(SchemaValidationError):
        call("forms.form.exists", payload)


def test_schema_file_matches_registered_schema():
    from stapel_forms.functions import FORM_EXISTS_SCHEMA

    file_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    body = {k: v for k, v in file_schema.items() if k not in ("$schema", "title", "description", "$defs")}
    assert body == FORM_EXISTS_SCHEMA
