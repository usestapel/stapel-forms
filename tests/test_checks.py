"""The system checks — the ones that exist because silence looks like health."""
import pytest

from stapel_forms import checks

pytestmark = pytest.mark.django_db


def _ids(result):
    return [entry.id for entry in result]


def test_default_field_kinds_are_all_registered():
    assert checks.check_field_kinds(None) == []


def test_a_kind_nobody_registered_is_an_error(settings):
    settings.STAPEL_FORMS = {"FIELD_KINDS": ["string", "telepathy"]}
    assert _ids(checks.check_field_kinds(None)) == ["stapel_forms.E001"]


def test_an_empty_allowlist_is_an_error(settings):
    settings.STAPEL_FORMS = {"FIELD_KINDS": []}
    assert _ids(checks.check_field_kinds(None)) == ["stapel_forms.E002"]


def test_no_open_forms_means_no_captcha_warning(settings):
    settings.STAPEL_CAPTCHA = {}
    assert checks.check_public_captcha(None) == []


def test_open_forms_without_a_captcha_secret_warn(published_form, settings):
    settings.STAPEL_CAPTCHA = {}
    assert _ids(checks.check_public_captcha(None)) == ["stapel_forms.W001"]


def test_a_configured_captcha_silences_it(published_form, settings):
    settings.STAPEL_CAPTCHA = {"SECRET": "x"}
    assert checks.check_public_captcha(None) == []


def test_the_confession_switch_silences_it(published_form, settings):
    settings.STAPEL_CAPTCHA = {}
    settings.STAPEL_FORMS = {"ALLOW_UNCAPTCHAED_PUBLIC": True}
    assert checks.check_public_captcha(None) == []


def test_no_beat_schedule_means_no_retention_warning(settings):
    settings.CELERY_BEAT_SCHEDULE = {}
    assert checks.check_retention_scheduled(None) == []


def test_a_beat_schedule_without_the_purge_warns(settings):
    settings.CELERY_BEAT_SCHEDULE = {"something-else": {"task": "other.task"}}
    assert _ids(checks.check_retention_scheduled(None)) == ["stapel_forms.W002"]


def test_a_scheduled_purge_is_silent(settings):
    from stapel_forms.tasks import PURGE_TASK_NAME

    settings.CELERY_BEAT_SCHEDULE = {"forms": {"task": PURGE_TASK_NAME}}
    assert checks.check_retention_scheduled(None) == []


def test_gdpr_declaration_is_only_checked_when_gdpr_is_installed(settings):
    assert checks.check_gdpr_declaration(None) == []


def test_an_undeclared_data_owner_warns(settings):
    settings.STAPEL_GDPR = {"DATA_OWNERS": ["auth"]}
    assert _ids(checks.check_gdpr_declaration(None)) == ["stapel_forms.W003"]


def test_a_declared_data_owner_is_silent(settings):
    settings.STAPEL_GDPR = {"DATA_OWNERS": ["auth", "forms"]}
    assert checks.check_gdpr_declaration(None) == []
