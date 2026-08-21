"""Emitted facts, their committed schemas, and the notify subscriber."""
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def captured(monkeypatch):
    """Record every emit while keeping schema validation live."""
    from stapel_core import comm

    seen = []
    original = comm.emit

    def spy(name, payload=None, **kwargs):
        event = original(name, payload, **kwargs)
        seen.append((name, payload))
        return event

    monkeypatch.setattr("stapel_forms.events.emit", spy)
    return seen


def test_publish_emits_form_published(captured, workspace_id, user, simple_schema):
    from stapel_forms import services

    form = services.create_form(
        workspace_id=workspace_id, title="T", user=user, draft_schema=simple_schema
    )
    services.publish(form, user=user)
    assert captured == [
        ("form.published",
         {"form_id": str(form.id), "workspace_id": str(workspace_id), "version": 1})
    ]


def test_closing_emits_once_and_only_from_open(captured, published_form):
    from stapel_forms import services

    services.set_state(published_form, "closed")
    services.set_state(published_form, "closed")
    assert [name for name, _ in captured if name == "form.closed"] == ["form.closed"]


def test_submission_event_carries_ids_only(captured, published_form):
    from stapel_forms import services

    submission = services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    name, payload = captured[-1]
    assert name == "form.submission.received"
    assert payload == {
        "form_id": str(published_form.id),
        "form_version": 1,
        "submission_id": str(submission.id),
        "workspace_id": str(published_form.workspace_id),
    }
    # The respondent's words never ride the bus.
    assert "Ann" not in str(payload)


def test_every_emit_has_a_committed_schema():
    """VALIDATE_SCHEMAS is on in the test settings, so an emit whose schema
    is missing or mismatched fails at the call site. This asserts the files
    are actually present, which a passing emit alone would not prove if the
    loader silently skipped them."""
    from pathlib import Path

    import stapel_forms
    from stapel_forms.events import FORM_CLOSED, FORM_PUBLISHED, FORM_SUBMISSION_RECEIVED

    root = Path(stapel_forms.__file__).parent / "schemas" / "emits"
    for name in (FORM_PUBLISHED, FORM_CLOSED, FORM_SUBMISSION_RECEIVED):
        assert (root / f"{name}.json").is_file()


def test_a_failing_emit_rolls_the_row_back(published_form, monkeypatch):
    """The outbox canon: the row and the announcement are one decision."""
    from stapel_forms import services
    from stapel_forms.models import Submission

    def boom(*_args, **_kwargs):
        raise RuntimeError("bus down")

    monkeypatch.setattr("stapel_forms.events.emit", boom)
    with pytest.raises(RuntimeError):
        services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    assert not Submission.objects.exists()


def test_user_deleted_erases_that_user_s_answers(published_form, user):
    from stapel_core.comm import emit

    from stapel_forms import services
    from stapel_forms.models import Submission

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"}, user_id=user.pk)
    services.submit(published_form, answers={"full_name": "Bob", "plan": "basic"})

    from django.db import transaction

    with transaction.atomic():
        emit("user.deleted", {"user_id": str(user.pk)})

    erased = Submission.objects.filter(erased_at__isnull=False)
    assert erased.count() == 1
    assert erased.get().answers == {}
    assert Submission.objects.filter(erased_at__isnull=True).get().answers["full_name"]["value"] == "Bob"


def test_the_notify_subscriber_runs_off_the_module_s_own_event(published_form, monkeypatch):
    from stapel_forms import notifications, services

    sent = []
    monkeypatch.setattr(notifications, "_request", lambda t, r, v: sent.append((t, v)))
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    assert [t for t, _ in sent] == ["forms.submission_received"]
    assert sent[0][1]["new_count"] == 1
