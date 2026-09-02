"""Outbound notification for stapel-forms — one reaction, two triggers.

The module hardwires exactly one reaction to a submission (tell the form's
configured destinations) and owns no template engine, no SMTP, no bot and
no channel: everything goes through
``stapel_core.notifications.publish.request_notification``, which accepts a
bare address — exactly what "notify the form's admin address" needs, with
no account behind it. When ``stapel-webhooks`` eventually lands it
subscribes to ``form.submission.received`` and nothing here has to move.

The two triggers are deliberately shaped differently:

- **auto-notify** fires off the module's own ``form.submission.received``
  and is COOLDOWN-GATED per form. The protected resource is the form
  owner's inbox, not this service's CPU (the invitation lesson): a leaked
  public link must not turn into an email flood, so interim submissions
  fold into the next letter as a count.
- **resend** is an explicit operator act on one stored submission and is
  therefore NOT cooldown-gated (spec §11a) — a cooldown that blocks an
  admin from re-sending a response they are looking at protects nobody.

A **target** is a destination plus the keyword that names it to
``request_notification``: ``notify_emails`` become ``email=`` and
``notify_telegram_chat_ids`` become ``telegram_chat_id=`` (stapel-core
0.31, alongside the telegram channel in stapel-notifications 0.13). Forms
never learns a transport — it names a destination and the routing entry
decides the rest, which is why adding a channel here was a keyword and not
a delivery path.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Form.settings key -> the request_notification keyword that addresses it.
#: Adding a channel is an entry here, never a branch at a call site.
TARGET_KINDS = {
    "notify_emails": "email",
    "notify_telegram_chat_ids": "telegram_chat_id",
}

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
        "channels": ["email", "telegram"],
        "group": "system",
        "transactional": True,
    },
    TYPE_SUBMISSION_RESEND: {
        "channels": ["email", "telegram"],
        "group": "system",
        "transactional": True,
    },
}

_COOLDOWN_KEY = "stapel_forms:notify:{form_id}"
_PENDING_KEY = "stapel_forms:notify_pending:{form_id}"


def notify_targets(form) -> list:
    """``[(keyword, address)]`` for every destination this form configured."""
    settings = form.settings or {}
    targets = []
    for key, keyword in TARGET_KINDS.items():
        for address in settings.get(key) or []:
            if isinstance(address, str) and address.strip():
                targets.append((keyword, address.strip()))
    return targets


def review_url(*, form=None, submission=None) -> str:
    """Absolute admin link to a response (or to a form's responses).

    Empty when the host has not configured ``ADMIN_BASE_URL``. Absent beats
    broken: a relative path in an email is not a link, and a library must
    not infer its own origin from a request whose Host header a stranger
    controlled.
    """
    from django.urls import NoReverseMatch, reverse

    from .conf import forms_settings

    base = (forms_settings.ADMIN_BASE_URL or "").rstrip("/")
    if not base:
        return ""
    try:
        if submission is not None:
            path = reverse("admin:forms_submission_change", args=[submission.id])
        else:
            path = reverse("admin:forms_form_responses", args=[form.id])
    except NoReverseMatch:
        # The host does not mount the Django admin. That is a legitimate
        # deployment, and it is not a reason to fail a notification.
        return ""
    return f"{base}{path}"


def answer_report(submission) -> list:
    """The answers as labelled rows, in schema order — the email's table."""
    from .presenters import present_answer_rows

    return [
        {"label": row["label"], "display": row["display"], "answered": row["answered"]}
        for row in present_answer_rows(submission)
    ]


def notify_submission_received(form, submission=None) -> bool:
    """Auto-notify for one new submission, behind the per-form cooldown.

    Returns True when a letter was requested. Inside the window the
    submission is counted instead, and the count travels with the next
    letter — so nothing is lost and nothing floods.
    """
    from .conf import forms_settings

    targets = notify_targets(form)
    if not targets:
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

    variables = {
        "form_id": str(form.id),
        "form_title": form.title,
        "new_count": new_count,
        # Navigation, not content: always present when the host configured
        # a base URL, whatever the disclosure setting says.
        "review_url": review_url(form=form, submission=submission),
    }

    # The answers ride along only when the host opted in AND this letter
    # stands for exactly ONE response. Inside the cooldown the interim
    # submissions fold into the next letter as a count, and attaching "the
    # answers" to a letter announcing three of them would attach one
    # response's content under a heading claiming several — wrong rather
    # than merely terse.
    if (
        forms_settings.NOTIFY_INCLUDE_ANSWERS
        and submission is not None
        and new_count == 1
    ):
        variables["answers"] = answer_report(submission)

    _request(TYPE_SUBMISSION_RECEIVED, targets, variables)
    return True


def notify_resend(form, submission, targets) -> int:
    """Re-deliver one submission's answers. No cooldown — admin-initiated.

    Answers travel in the notification variables, not on the event bus:
    this is a directed message to an address the workspace configured,
    which is a different trust boundary from a fan-out topic.
    """
    variables = {
        "form_id": str(form.id),
        "form_title": form.title,
        "submission_id": str(submission.id),
        "submitted_at": submission.submitted_at.isoformat(),
        # Labelled rows in schema order, not `{slug: value}`. The old shape
        # was the same unreadable projection the admin had — a recipient got
        # `plan: ["pro"]` where the respondent had clicked "Pro".
        "answers": answer_report(submission),
        "review_url": review_url(form=form, submission=submission),
    }
    _request(TYPE_SUBMISSION_RESEND, targets, variables)
    return len(targets)


def _request(notification_type: str, targets, variables: dict) -> None:
    """One request per destination, addressed by its own keyword.

    Failures are logged, never raised: the row is already committed, and a
    notification service being down is not a reason to lose a response.
    """
    from stapel_core.notifications.publish import request_notification

    for keyword, address in targets:
        try:
            request_notification(
                notification_type,
                variables=variables,
                source_service="forms",
                **{keyword: address},
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
    "TARGET_KINDS",
    "notify_targets",
    "notify_submission_received",
    "notify_resend",
]
