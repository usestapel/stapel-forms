"""Action subscriptions of stapel-forms.

Handlers are idempotent-minded (delivery is at-least-once — outbox retries,
broker redelivery). Transport is chosen by ``STAPEL_COMM`` (in-process in a
monolith, bus consumer in microservices); the handler code is identical.

Three consumers:

- ``user.deleted`` → the GDPR provider's erasure of an authenticated
  respondent's answers;
- ``user.merged`` → the other half of that account life cycle: a guest
  folded into an existing account has its rows re-parented, not erased;
- this module's OWN ``form.submission.received`` → the notify subscriber.
  Reacting to our own event rather than calling the notifier inline is
  what makes the auto-notify survive the transaction: the row is committed
  before anybody is told about it, and a notification service outage can
  never roll back a respondent's answer.
"""
import logging

from django.core.exceptions import ValidationError
from stapel_core.comm import on_action

from .events import FORM_SUBMISSION_RECEIVED

logger = logging.getLogger(__name__)


class MergeTargetNotReady(RuntimeError):
    """A ``user.merged`` arrived before the surviving account exists here.

    Transient, not a bug: the guest has forms or answers to carry over but
    there is no local user row to point their FKs at yet. Raising is the
    comm layer's retry signal — ``deliver()`` wraps a failing handler in
    ``ActionDeliveryError`` and the outbox redelivers — so the transfer
    completes once the survivor's user projection lands. An operator seeing
    this in a redelivery loop is looking at an ordering lag, not a defect.
    """


@on_action("user.deleted")
def handle_user_deleted(event):
    """Erase a user's form answers (GDPR Art. 17)."""
    from .gdpr import FormsGDPRProvider

    user_id = event.payload.get("user_id")
    if not user_id:
        logger.error("user.deleted event without user_id: %s", event.event_id)
        return
    FormsGDPRProvider().delete(user_id)


@on_action("user.merged")
def handle_user_merged(event):
    """Carry a merged-away account's forms and answers over to the survivor.

    Re-parents the three columns this module keys by a user, in one
    transaction:

    * :class:`~stapel_forms.models.Form` ``created_by`` and
      :class:`~stapel_forms.models.FormVersion` ``created_by`` — who built
      the questionnaire and who published each immutable version;
    * :class:`~stapel_forms.models.Submission` ``submitted_by`` — the
      answers a signed-in respondent gave. An answer belongs to the person
      who typed it, and after the merge that person is the survivor.

    The opposite instruction to ``user.deleted``, which *destroys* the same
    answers: an account erasure means "this is my data, delete it", a merge
    means "this is still my data, under my other account". Answering only
    the first would leave a guest's responses attributed to an id that can
    no longer sign in — outside the survivor's export, and outside any
    future erasure request too, because none is ever made for a merged-away
    account.

    A submission already erased under the GDPR path carries
    ``submitted_by = None`` (the tombstone) and is therefore untouched here:
    a merge does not resurrect an attribution its owner asked to have
    removed.

    Two different "unknown id" situations, and conflating them loses data:

    * the guest owns nothing here (never answered, or a previous delivery
      already moved it all) — a genuine no-op, returned quietly;
    * the guest owns rows but the survivor has no user row here yet — NOT a
      no-op. :class:`MergeTargetNotReady` is raised so the event is
      redelivered, because returning success would let the outbox mark it
      delivered and strand the answers.
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction

    from .models import Form, FormVersion, Submission

    payload = event.payload or {}
    from_user_id = payload.get("from_user_id")
    into_user_id = payload.get("into_user_id")
    if not from_user_id or not into_user_id:
        logger.error("user.merged without from/into user id: %s", event.event_id)
        return
    if str(from_user_id) == str(into_user_id):
        return

    #: model -> the column naming a user on it.
    owned = (
        (Form, "created_by_id"),
        (FormVersion, "created_by_id"),
        (Submission, "submitted_by"),
    )

    with transaction.atomic():
        # Both reads and the decision they feed happen inside the transaction
        # and before the first write, so the "not yet" path below can never
        # leave half the rows moved.
        try:
            owns_something = any(
                model.objects.filter(**{column: from_user_id}).exists()
                for model, column in owned
            )
            # The survivor probe is read here, under the same guard, because a
            # malformed *into* id must not escape as a poison pill either.
            survivor_exists = (
                get_user_model().objects.filter(pk=into_user_id).exists()
            )
        except (ValidationError, ValueError, TypeError):
            # Django raises ValidationError (not ValueError) for a malformed
            # UUID; an id that cannot address a row here names nothing, and an
            # escaping exception is a poison pill no redelivery repairs.
            logger.warning("user.merged with unusable user ids: %s", event.event_id)
            return
        if not owns_something:
            # Quiet by design — this is also the at-least-once idempotency
            # path: a redelivery finds nothing left under the guest.
            return
        if not survivor_exists:
            raise MergeTargetNotReady(
                f"user.merged {from_user_id} -> {into_user_id}: the surviving "
                f"account has no user row in stapel-forms yet; redeliver once "
                f"its projection has landed"
            )

        moved = {
            model.__name__: model.objects.filter(**{column: from_user_id}).update(
                **{column: into_user_id}
            )
            for model, column in owned
        }

    logger.info(
        "user.merged %s -> %s: forms rows carried over (%s)",
        from_user_id, into_user_id, moved,
    )


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


__all__ = [
    "MergeTargetNotReady",
    "handle_submission_received",
    "handle_user_deleted",
    "handle_user_merged",
]
