"""Django system checks for stapel-forms configuration.

Policy (docs/library-standard.md §3.7): E-level for configuration the
service cannot run with; W-level for entries that degrade lazily.

Two of the warnings here are confessions rather than diagnostics — they
exist because the alternative is a deployment that LOOKS protected. A
public form with no captcha backend and a retention policy no scheduler
runs both fail silently and identically to the working configuration,
which is precisely why they get a check instead of a paragraph in a README.
"""
from django.core import checks


@checks.register(checks.Tags.compatibility)
def check_field_kinds(app_configs, **kwargs):
    """E001: every allowlisted field kind must be a registered attribute type."""
    from stapel_attributes.registry import get_all_type_slugs

    from .conf import forms_settings

    try:
        configured = list(forms_settings.FIELD_KINDS or [])
    except Exception as exc:  # noqa: BLE001
        return [checks.Error(
            f"STAPEL_FORMS['FIELD_KINDS'] cannot be read: {exc}",
            id="stapel_forms.E001",
        )]
    known = set(get_all_type_slugs())
    unknown = [kind for kind in configured if kind not in known]
    if unknown:
        return [checks.Error(
            f"STAPEL_FORMS['FIELD_KINDS'] lists kinds no attribute type answers "
            f"for: {sorted(unknown)}. A kind nobody registered is a field the "
            f"builder can create and the submit endpoint always refuses.",
            hint="Register the type via STAPEL_ATTRIBUTES['EXTRA_TYPES'] or "
                 "register_feature_type(), or drop it from FIELD_KINDS.",
            id="stapel_forms.E001",
        )]
    if not configured:
        return [checks.Error(
            "STAPEL_FORMS['FIELD_KINDS'] is empty — no form could ever be published.",
            id="stapel_forms.E002",
        )]
    return []


@checks.register(checks.Tags.security)
def check_public_captcha(app_configs, **kwargs):
    """W001: open public forms with no captcha backend configured.

    Security canon H10 — "public registration ⇒ captcha configured or a
    conscious refusal" — extends verbatim to public forms. The refusal is
    the setting named in the hint; silence is not a refusal.
    """
    from django.conf import settings

    from .conf import forms_settings

    if forms_settings.ALLOW_UNCAPTCHAED_PUBLIC:
        return []
    captcha = getattr(settings, "STAPEL_CAPTCHA", None) or {}
    if captcha.get("SECRET"):
        return []
    if not _has_open_forms():
        return []
    return [checks.Warning(
        "This deployment has open public forms but no STAPEL_CAPTCHA['SECRET'] — "
        "the anonymous submit endpoint accepts every bot that finds the link.",
        hint="Configure a captcha backend, or set "
             "STAPEL_FORMS['ALLOW_UNCAPTCHAED_PUBLIC'] = True to say the "
             "refusal is deliberate.",
        id="stapel_forms.W001",
    )]


@checks.register(checks.Tags.compatibility)
def check_retention_scheduled(app_configs, **kwargs):
    """W002: a beat schedule that never runs the retention purge."""
    from django.conf import settings

    from .tasks import PURGE_TASK_NAME

    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", None)
    if not schedule:
        return []
    for entry in schedule.values():
        if isinstance(entry, dict) and entry.get("task") == PURGE_TASK_NAME:
            return []
    return [checks.Warning(
        "CELERY_BEAT_SCHEDULE has no entry for "
        f"{PURGE_TASK_NAME} — respondent answers will be kept forever "
        "regardless of STAPEL_FORMS['RETENTION_DAYS'].",
        hint="CELERY_BEAT_SCHEDULE = {**get_forms_beat_schedule(), ...} "
             "(stapel_forms.tasks), or run the forms_purge_expired management "
             "command from cron.",
        id="stapel_forms.W002",
    )]


@checks.register(checks.Tags.compatibility)
def check_gdpr_declaration(app_configs, **kwargs):
    """W003: the module holds PII the host has not declared to stapel-gdpr."""
    from django.conf import settings

    gdpr = getattr(settings, "STAPEL_GDPR", None)
    if gdpr is None:
        return []
    owners = gdpr.get("DATA_OWNERS") or []
    names = {o if isinstance(o, str) else (o or {}).get("name") for o in owners}
    if "forms" in names:
        return []
    return [checks.Warning(
        "stapel-forms stores respondent answers but \"forms\" is not in "
        "STAPEL_GDPR['DATA_OWNERS'] — the erasure closure will never complete "
        "for this data (gdpr.E002 raises this to an error on that side).",
        hint='Add "forms" to STAPEL_GDPR["DATA_OWNERS"] and bump DATA_OWNERS_VERSION.',
        id="stapel_forms.W003",
    )]


def _has_open_forms() -> bool:
    """True when at least one live form is accepting public submissions.

    Swallows every database error on purpose: system checks run before
    migrations on a fresh install, and a check that explodes at that moment
    replaces a useful warning with a broken boot.
    """
    from django.db import Error as DatabaseError

    from .models import STATE_OPEN, Form

    try:
        return Form.objects.filter(state=STATE_OPEN, deleted_at__isnull=True).exists()
    except (DatabaseError, Exception):  # noqa: B014 - includes ImproperlyConfigured
        return False


__all__ = [
    "check_field_kinds",
    "check_public_captcha",
    "check_retention_scheduled",
    "check_gdpr_declaration",
]
