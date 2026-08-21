"""Outbound notification for stapel-forms — one reaction, two triggers.

The module hardwires exactly one reaction to a submission (email to the
form's configured recipients) and no template engine, no SMTP, no channel
of its own: everything goes through
``stapel_core.notifications.publish.request_notification``, which accepts a
bare ``email=`` address — exactly what "notify the form's admin address"
needs. When ``stapel-webhooks`` eventually lands it subscribes to
``form.submission.received`` and nothing here has to move.

The two triggers are deliberately shaped differently:

- **auto-notify** fires off the module's own ``form.submission.received``
  and is COOLDOWN-GATED per form. The protected resource is the form
  owner's inbox, not this service's CPU (the invitation lesson): a leaked
  public link must not turn into an email flood, so interim submissions
  fold into the next letter as a count.
- **resend** is an explicit operator act on one stored submission and is
  therefore NOT cooldown-gated (spec §11a) — a cooldown that blocks an
  admin from re-sending a response they are looking at protects nobody.

Channels are whatever the routing entry says. Once the telegram channel
lands in stapel-notifications, ``Form.settings.notify_channels`` becomes
meaningful here for free — forms addresses channels only through routing.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Notification types this module requests. Registered upstream in
#: ``stapel_notifications.routing.NOTIFICATION_ROUTING``; until that
#: release wave lands, a host bridges them through
#: ``STAPEL_NOTIFICATIONS["TYPES"]`` (see MODULE.md § Integration).
TYPE_SUBMISSION_RECEIVED = "forms.submission_received"
TYPE_SUBMISSION_RESEND = "forms.submission_resend"

#: The routing entries the upstream PR adds, quoted here so a host that has
#: to bridge them can copy the exact shape rather than guess it.
ROUTING_ENTRIES = {
    TYPE_SUBMISSION_RECEIVED: {
        "channels": ["email"],
        "group": "system",
        "transactional": True,
    },
    TYPE_SUBMISSION_RESEND: {
        "channels": ["email"],
        "group": "system",
        "transactional": True,
    },
}

_COOLDOWN_KEY = "stapel_forms:notify:{form_id}"
_PENDING_KEY = "stapel_forms:notify_pending:{form_id}"


def notify_recipients(form) -> list:
    emails = (form.settings or {}).get("notify_emails") or []
    return [e for e in emails if isinstance(e, str) and e.strip()]


def notify_submission_received(form) -> bool:
    """Auto-notify for one new submission, behind the per-form cooldown.

    Returns True when a letter was requested. Inside the window the
    submission is counted instead, and the count travels with the next
    letter — so nothing is lost and nothing floods.
    """
    from .conf import forms_settings

    recipients = notify_recipients(form)
    if not recipients:
        return False

    cooldown = int(forms_settings.NOTIFY_COOLDOWN_SECONDS or 0)
    pending_key = _PENDING_KEY.format(form_id=form.id)
    if cooldown > 0:
        gate_key = _COOLDOWN_KEY.format(form_id=form.id)
        # add() is the atomic compare-and-set: only the request that wins
        # it sends, which keeps concurrent submits to one letter.
        if not cache.add(gate_key, 1, cooldown):
            try:
                cache.incr(pending_key)
            except ValueError:
                cache.set(pending_key, 1, cooldown * 4)
            return False

    new_count = 1
    held = cache.get(pending_key)
    if held:
        new_count += int(held)
        cache.delete(pending_key)

    _request(
        TYPE_SUBMISSION_RECEIVED,
        recipients,
        {
            "form_id": str(form.id),
            "form_title": form.title,
            "new_count": new_count,
        },
    )
    return True


def notify_resend(form, submission, recipients) -> int:
    """Re-deliver one submission's answers. No cooldown — admin-initiated.

    Answers travel in the notification variables, not on the event bus:
    this is a directed message to an address the workspace configured,
    which is a different trust boundary from a fan-out topic.
    """
    from .presenters import present_answers

    variables = {
        "form_id": str(form.id),
        "form_title": form.title,
        "submission_id": str(submission.id),
        "submitted_at": submission.submitted_at.isoformat(),
        "answers": present_answers(submission),
    }
    _request(TYPE_SUBMISSION_RESEND, recipients, variables)
    return len(recipients)


def _request(notification_type: str, recipients, variables: dict) -> None:
    from stapel_core.notifications.publish import request_notification

    for email in recipients:
        try:
            request_notification(
                notification_type,
                email=email,
                variables=variables,
                source_service="forms",
            )
        except Exception:  # noqa: BLE001 - delivery is best-effort, the row is committed
            logger.exception(
                "forms: could not request %s for form %s",
                notification_type,
                variables.get("form_id"),
            )


__all__ = [
    "TYPE_SUBMISSION_RECEIVED",
    "TYPE_SUBMISSION_RESEND",
    "ROUTING_ENTRIES",
    "notify_recipients",
    "notify_submission_received",
    "notify_resend",
]
