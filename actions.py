"""Action subscriptions of stapel-forms.

Handlers are idempotent-minded (delivery is at-least-once — outbox retries,
broker redelivery). Transport is chosen by ``STAPEL_COMM`` (in-process in a
monolith, bus consumer in microservices); the handler code is identical.

Two consumers:

- ``user.deleted`` → the GDPR provider's erasure of an authenticated
  respondent's answers;
- this module's OWN ``form.submission.received`` → the notify subscriber.
  Reacting to our own event rather than calling the notifier inline is
  what makes the auto-notify survive the transaction: the row is committed
  before anybody is told about it, and a notification service outage can
  never roll back a respondent's answer.
"""
import logging

from stapel_core.comm import on_action

from .events import FORM_SUBMISSION_RECEIVED

logger = logging.getLogger(__name__)


@on_action("user.deleted")
def handle_user_deleted(event):
    """Erase a user's form answers (GDPR Art. 17)."""
    from .gdpr import FormsGDPRProvider

    user_id = event.payload.get("user_id")
    if not user_id:
        logger.error("user.deleted event without user_id: %s", event.event_id)
        return
    FormsGDPRProvider().delete(user_id)


@on_action(FORM_SUBMISSION_RECEIVED)
def handle_submission_received(event):
    """Notify the form's configured recipients, behind the cooldown."""
    from .models import Form
    from .notifications import notify_submission_received

    form_id = event.payload.get("form_id")
    form = Form.objects.filter(id=form_id).first()
    if form is None:
        return
    notify_submission_received(form)


__all__ = ["handle_user_deleted", "handle_submission_received"]
