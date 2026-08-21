"""Scheduled work of stapel-forms — retention that actually runs.

A retention policy nobody schedules is a promise, not a mechanism (the
DOCS-02 lesson, carried over verbatim): ``RETENTION_DAYS`` and the
management command would exist and nothing would run them, so respondent
answers would live forever behind a setting that says otherwise. This
module is the schedulable form, and ``checks.py`` warns when a host has a
beat schedule with no entry pointing at it.

Celery is OPTIONAL. :func:`purge_expired_submissions` is a plain callable a
cron, a systemd timer or any scheduler can invoke; when celery is installed
it is additionally registered as a shared task under the stable name below.

Wire it into a host's beat schedule:

    from stapel_forms.tasks import get_forms_beat_schedule

    CELERY_BEAT_SCHEDULE = {
        **get_forms_beat_schedule(),
        ...
    }
"""
import logging

logger = logging.getLogger(__name__)

#: The name a beat schedule must reference (stable across refactors).
PURGE_TASK_NAME = "stapel_forms.tasks.purge_expired_submissions"


def purge_expired_submissions() -> dict:
    """Destroy submissions past their retention horizon, and the contents
    of forms deleted long enough ago.

    Returns and logs the counts: retention that runs invisibly cannot be
    monitored, and a job nobody can observe is indistinguishable from a job
    that stopped running.
    """
    from .services import purge_deleted_forms, purge_expired

    submissions = purge_expired()
    forms, cascaded = purge_deleted_forms()
    logger.info(
        "forms retention purge: %s expired submission(s), %s deleted form(s) "
        "with %s submission(s)",
        submissions,
        forms,
        cascaded,
    )
    return {"submissions": submissions, "forms": forms, "cascaded": cascaded}


def get_forms_beat_schedule() -> dict:
    """Beat entry for the retention purge, on the configured cadence."""
    from celery.schedules import crontab

    from .conf import forms_settings

    schedule = dict(forms_settings.PURGE_SCHEDULE or {})
    return {
        "forms-retention-purge": {
            "task": PURGE_TASK_NAME,
            "schedule": crontab(**schedule),
        },
    }


try:  # pragma: no cover — exercised by whichever profile the host installs
    from celery import shared_task
except ImportError:
    pass
else:
    purge_expired_submissions = shared_task(name=PURGE_TASK_NAME)(
        purge_expired_submissions
    )


__all__ = ["PURGE_TASK_NAME", "purge_expired_submissions", "get_forms_beat_schedule"]
