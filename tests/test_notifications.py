"""The cooldown — what protects the form owner's inbox from a leaked link."""
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def sent(monkeypatch):
    from stapel_forms import notifications

    log = []
    monkeypatch.setattr(notifications, "_request", lambda t, r, v: log.append((t, tuple(r), v)))
    return log


def test_a_form_with_no_recipients_sends_nothing(published_form, sent):
    from stapel_forms import notifications, services

    services.update_form(published_form, settings={})
    assert notifications.notify_submission_received(published_form) is False
    assert sent == []


def test_the_first_submission_notifies(published_form, sent):
    from stapel_forms import notifications

    assert notifications.notify_submission_received(published_form) is True
    assert sent[0][1] == (("email", "sales@example.com"),)
    assert sent[0][2]["new_count"] == 1


def test_the_burst_behind_it_does_not(published_form, sent):
    from stapel_forms import notifications

    for _ in range(5):
        notifications.notify_submission_received(published_form)
    assert len(sent) == 1


def test_the_interim_count_rides_the_next_letter(published_form, sent, settings):
    from django.core.cache import cache

    from stapel_forms import notifications

    for _ in range(4):
        notifications.notify_submission_received(published_form)
    # Window elapses.
    cache.delete(notifications._COOLDOWN_KEY.format(form_id=published_form.id))
    notifications.notify_submission_received(published_form)

    assert [v["new_count"] for _t, _r, v in sent] == [1, 4]


def test_a_zero_cooldown_notifies_every_time(published_form, sent, settings):
    from stapel_forms import notifications

    settings.STAPEL_FORMS = {"NOTIFY_COOLDOWN_SECONDS": 0}
    for _ in range(3):
        notifications.notify_submission_received(published_form)
    assert len(sent) == 3


def test_the_cooldown_is_keyed_on_the_form_not_the_caller(
    published_form, sent, workspace_id, user, simple_schema
):
    from stapel_forms import notifications, services

    other = services.create_form(
        workspace_id=workspace_id, title="Other", user=user,
        settings={"notify_emails": ["sales@example.com"]},
        draft_schema=simple_schema,
    )
    services.publish(other, user=user)
    notifications.notify_submission_received(published_form)
    notifications.notify_submission_received(other)
    assert len(sent) == 2


def test_delivery_failure_never_loses_the_row(published_form, monkeypatch, caplog):
    from stapel_forms import services
    from stapel_forms.models import Submission

    def boom(*_a, **_k):
        raise RuntimeError("notifications down")

    monkeypatch.setattr(
        "stapel_core.notifications.publish.request_notification", boom, raising=False
    )
    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    assert Submission.objects.count() == 1


def test_the_routing_entries_are_quoted_for_the_host_bridge():
    from stapel_forms.notifications import (
        ROUTING_ENTRIES,
        TYPE_SUBMISSION_RECEIVED,
        TYPE_SUBMISSION_RESEND,
    )

    assert set(ROUTING_ENTRIES) == {TYPE_SUBMISSION_RECEIVED, TYPE_SUBMISSION_RESEND}
    for entry in ROUTING_ENTRIES.values():
        assert entry["channels"] == ["email", "telegram"]
        assert entry["group"] == "system"
        assert entry["transactional"] is True


def test_a_telegram_target_is_addressed_by_its_own_keyword(published_form, sent):
    from stapel_forms import notifications, services

    services.update_form(
        published_form,
        settings={"notify_emails": ["sales@example.com"],
                  "notify_telegram_chat_ids": ["-1001234567890"]},
    )
    notifications.notify_submission_received(published_form)
    assert sent[0][1] == (
        ("email", "sales@example.com"),
        ("telegram_chat_id", "-1001234567890"),
    )


def test_a_telegram_only_form_still_notifies(published_form, sent):
    from stapel_forms import notifications, services

    services.update_form(
        published_form, settings={"notify_telegram_chat_ids": ["-100999"]}
    )
    assert notifications.notify_submission_received(published_form) is True
    assert sent[0][1] == (("telegram_chat_id", "-100999"),)


def test_the_keyword_reaches_request_notification(published_form, monkeypatch):
    """The seam is stapel-core 0.31's direct telegram address, not a
    transport this module implements."""
    from stapel_forms import notifications, services

    calls = []
    monkeypatch.setattr(
        "stapel_core.notifications.publish.request_notification",
        lambda ntype, **kw: calls.append((ntype, kw)) or True,
    )
    services.update_form(
        published_form, settings={"notify_telegram_chat_ids": ["-100999"]}
    )
    notifications.notify_submission_received(published_form)
    assert calls[0][1]["telegram_chat_id"] == "-100999"
    assert "email" not in calls[0][1]
