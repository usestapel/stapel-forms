"""Retention, erasure and the difference between them.

Erasure keeps the row (the count stays truthful); retention destroys it
(after the horizon the count claim expires too). Getting these two the
wrong way round is how a "we deleted your data" promise turns into a
number that quietly disagrees with itself.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from stapel_forms.models import Submission

pytestmark = pytest.mark.django_db


def _age(submission, days):
    Submission.objects.filter(pk=submission.pk).update(
        submitted_at=timezone.now() - timedelta(days=days)
    )


def test_erasure_keeps_the_tombstone(published_form, user):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"}, user_id=user.pk)
    services.erase_user_submissions(user.pk)

    row = Submission.objects.get()
    assert row.answers == {} and row.client_meta is None
    assert row.submitted_by is None and row.erased_at is not None


def test_erasure_is_idempotent(published_form, user):
    from stapel_forms import services

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"}, user_id=user.pk)
    assert services.erase_user_submissions(user.pk) == 1
    assert services.erase_user_submissions(user.pk) == 0
    assert Submission.objects.count() == 1


def test_gdpr_export_returns_the_answers_themselves(published_form, user):
    from stapel_forms import services
    from stapel_forms.gdpr import FormsGDPRProvider

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"}, user_id=user.pk)
    export = FormsGDPRProvider().export(user.pk)
    assert export["submissions"][0]["answers"]["full_name"] == "Ann"
    assert export["submissions"][0]["form_title"] == "Sign up"
    assert export["submissions"][0]["version"] == 1


def test_gdpr_export_of_a_stranger_is_empty(published_form, user):
    from stapel_forms import services
    from stapel_forms.gdpr import FormsGDPRProvider

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    assert FormsGDPRProvider().export(user.pk) == {"submissions": []}


def test_retention_destroys_the_row(published_form, settings):
    from stapel_forms import services

    settings.STAPEL_FORMS = {"RETENTION_DAYS": 30}
    old = services.submit(published_form, answers={"full_name": "Old", "plan": "pro"})
    services.submit(published_form, answers={"full_name": "New", "plan": "pro"})
    _age(old, 45)

    assert services.purge_expired() == 1
    assert Submission.objects.get().answers["full_name"]["value"] == "New"


def test_a_per_form_override_shortens_the_horizon(published_form, settings):
    from stapel_forms import services

    settings.STAPEL_FORMS = {"RETENTION_DAYS": 365}
    services.update_form(published_form, settings={"retention_days": 7})
    row = services.submit(published_form, answers={"full_name": "Old", "plan": "pro"})
    _age(row, 10)

    assert services.purge_expired() == 1


def test_retention_off_purges_nothing(published_form, settings):
    from stapel_forms import services

    settings.STAPEL_FORMS = {"RETENTION_DAYS": None}
    row = services.submit(published_form, answers={"full_name": "Old", "plan": "pro"})
    _age(row, 9999)
    assert services.purge_expired() == 0


def test_purging_a_deleted_form_cascades_versions_and_answers(published_form, settings):
    from stapel_forms import services
    from stapel_forms.models import Form, FormVersion

    services.submit(published_form, answers={"full_name": "Ann", "plan": "pro"})
    services.delete_form(published_form)
    Form.objects.filter(pk=published_form.pk).update(
        deleted_at=timezone.now() - timedelta(days=400)
    )

    forms, cascaded = services.purge_deleted_forms()
    assert (forms, cascaded) == (1, 1)
    assert not FormVersion.objects.exists()
    assert not Submission.objects.exists()


def test_the_task_reports_what_it_destroyed(published_form, settings, caplog):
    from stapel_forms import services
    from stapel_forms.tasks import purge_expired_submissions

    settings.STAPEL_FORMS = {"RETENTION_DAYS": 30}
    row = services.submit(published_form, answers={"full_name": "Old", "plan": "pro"})
    _age(row, 45)

    assert purge_expired_submissions() == {"submissions": 1, "forms": 0, "cascaded": 0}


def test_the_beat_schedule_names_the_stable_task(settings):
    pytest.importorskip("celery")
    from stapel_forms.tasks import PURGE_TASK_NAME, get_forms_beat_schedule

    entry = get_forms_beat_schedule()["forms-retention-purge"]
    assert entry["task"] == PURGE_TASK_NAME


def test_the_management_command_runs(published_form):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("forms_purge_expired", stdout=out)
    assert "forms_purge_expired" in out.getvalue()
