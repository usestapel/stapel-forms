"""Draft → publish → open → close, and the immutability that hangs off it."""
import pytest

from stapel_forms import services
from stapel_forms.errors import (
    ERR_400_INVALID_RETENTION,
    ERR_400_NO_DRAFT,
    ERR_400_NOT_PUBLISHED,
    ERR_400_TOO_MANY_OPEN_FORMS,
    ERR_404_NOT_FOUND,
    ERR_410_CLOSED,
)
from stapel_forms.models import FormVersion, Submission

pytestmark = pytest.mark.django_db


def test_a_new_form_is_a_draft_with_a_public_handle(workspace_id, user):
    form = services.create_form(workspace_id=workspace_id, title="T", user=user)
    assert form.state == "draft"
    assert len(form.public_id) == 22
    assert form.active_version_id is None


def test_publish_without_a_draft_refuses(workspace_id, user):
    form = services.create_form(workspace_id=workspace_id, title="T", user=user)
    with pytest.raises(services.FormsError) as exc:
        services.publish(form, user=user)
    assert exc.value.error_key == ERR_400_NO_DRAFT


def test_publish_mints_version_one_and_clears_the_draft(workspace_id, user, simple_schema):
    form = services.create_form(
        workspace_id=workspace_id, title="T", user=user, draft_schema=simple_schema
    )
    version = services.publish(form, user=user)
    form.refresh_from_db()
    assert version.version == 1
    assert form.active_version_id == version.id
    assert form.draft_schema is None


def test_editing_a_live_form_publishes_the_next_version(published_form, user, simple_schema):
    edited = {**simple_schema, "meta": {**simple_schema["meta"], "title": "Sign up v2"}}
    services.save_draft(published_form, edited)
    second = services.publish(published_form, user=user)
    published_form.refresh_from_db()

    assert second.version == 2
    assert published_form.active_version_id == second.id
    first = FormVersion.objects.get(form=published_form, version=1)
    # The published version was frozen, not rewritten.
    assert first.schema["meta"]["title"] == "Sign up"


def test_a_version_with_submissions_cannot_be_deleted(published_form):
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        published_form.active_version.delete()


def test_open_requires_a_published_version(workspace_id, user):
    form = services.create_form(workspace_id=workspace_id, title="T", user=user)
    with pytest.raises(services.FormsError) as exc:
        services.set_state(form, "open")
    assert exc.value.error_key == ERR_400_NOT_PUBLISHED


def test_open_form_cap(published_form, workspace_id, user, simple_schema, settings):
    settings.STAPEL_FORMS = {"MAX_OPEN_FORMS_PER_WORKSPACE": 1}
    other = services.create_form(
        workspace_id=workspace_id, title="Other", user=user, draft_schema=simple_schema
    )
    services.publish(other, user=user)
    with pytest.raises(services.FormsError) as exc:
        services.set_state(other, "open")
    assert exc.value.error_key == ERR_400_TOO_MANY_OPEN_FORMS


def test_rotate_link_invalidates_the_old_handle(published_form):
    old = published_form.public_id
    services.rotate_link(published_form)
    assert published_form.public_id != old
    with pytest.raises(services.FormsError) as exc:
        services.resolve_public(old)
    assert exc.value.error_key == ERR_404_NOT_FOUND


@pytest.mark.parametrize("state,expected", [("draft", ERR_404_NOT_FOUND), ("closed", ERR_410_CLOSED)])
def test_public_resolution_discipline(published_form, state, expected):
    services.set_state(published_form, state)
    with pytest.raises(services.FormsError) as exc:
        services.resolve_public(published_form.public_id)
    assert exc.value.error_key == expected


def test_unknown_handle_and_deleted_form_answer_identically(published_form):
    with pytest.raises(services.FormsError) as unknown:
        services.resolve_public("definitely-not-a-real-handle")
    services.delete_form(published_form)
    with pytest.raises(services.FormsError) as deleted:
        services.resolve_public(published_form.public_id)
    assert unknown.value.error_key == deleted.value.error_key == ERR_404_NOT_FOUND


def test_soft_delete_stops_intake_but_keeps_rows(published_form):
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    services.delete_form(published_form)
    assert Submission.objects.filter(form=published_form).count() == 1
    with pytest.raises(services.FormsError):
        services.resolve_public(published_form.public_id)


def test_retention_override_may_only_shorten(workspace_id, user):
    services.create_form(
        workspace_id=workspace_id, title="T", user=user,
        settings={"retention_days": 30},
    )
    with pytest.raises(services.FormsError) as exc:
        services.create_form(
            workspace_id=workspace_id, title="T2", user=user,
            settings={"retention_days": 4000},
        )
    assert exc.value.error_key == ERR_400_INVALID_RETENTION
