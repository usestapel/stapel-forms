"""Emitted actions of stapel-forms (transactional outbox, at-least-once).

Call sites are the service layer, always inside the mutating transaction
(outbox canon). Payload schemas live in ``schemas/emits/`` and are enforced
in tests via ``VALIDATE_SCHEMAS``.

**Ids only, never answers** (spec §5.5 / §11a verdict 5). The outbox has no
retention and a durable bus fans out to every subscriber, so respondent PII
does not ride it: a consumer that needs content fetches it under
``forms.responses.view``. That also keeps the future reaction layer honest —
it routes facts, and content delivery stays an authorized read.
"""
from __future__ import annotations

from stapel_core.comm import emit

FORM_PUBLISHED = "form.published"
FORM_CLOSED = "form.closed"
FORM_SUBMISSION_RECEIVED = "form.submission.received"


def emit_form_published(form, version) -> None:
    emit(
        FORM_PUBLISHED,
        {
            "form_id": str(form.id),
            "workspace_id": str(form.workspace_id),
            "version": int(version.version),
        },
    )


def emit_form_closed(form) -> None:
    emit(
        FORM_CLOSED,
        {"form_id": str(form.id), "workspace_id": str(form.workspace_id)},
    )


def emit_submission_received(submission) -> None:
    emit(
        FORM_SUBMISSION_RECEIVED,
        {
            "form_id": str(submission.form_id),
            "form_version": int(submission.version.version),
            "submission_id": str(submission.id),
            "workspace_id": str(submission.workspace_id),
        },
    )


__all__ = [
    "FORM_PUBLISHED",
    "FORM_CLOSED",
    "FORM_SUBMISSION_RECEIVED",
    "emit_form_published",
    "emit_form_closed",
    "emit_submission_received",
]
