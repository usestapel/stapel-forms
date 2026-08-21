"""GDPR data handler for stapel-forms.

The asymmetry with stapel-docs is deliberate and is the point of this
docstring. A document is co-produced workspace content, so erasure there
nulls authorship and keeps the text. A form answer is the opposite: the
respondent typed it about themselves, into somebody else's questionnaire.
It is THEIR data, so ``export`` returns the full answers and ``delete``
destroys them.

What survives is the tombstone: ``answers = {}``, ``client_meta = None``,
``submitted_by = None``, ``erased_at = now()``. The row is kept so response
counts and per-version analytics stay truthful ("300 responses, 2 erased")
— a count that silently shrinks is a different kind of lie from a retained
answer. Returning normally IS the receipt (the cdn lesson): the provider
returns only after the update has landed.

**The honest gap.** stapel-gdpr keys every provider and request on
``user_id``; an email a stranger typed into a form field is opaque answer
content, not a subject key. Anonymous respondents therefore have no
self-service erasure channel here. What v1 gives them instead is finite
retention (``tasks.purge_expired_submissions``) and an admin delete
endpoint. An email-keyed subject is an upstream stapel-gdpr contribution,
filed as its own program item.

Registered as a provider (monolith mode, ``apps.py:ready()``) and driven by
the ``@on_action("user.deleted")`` consumer (``actions.py``).
"""
from __future__ import annotations

import logging

from stapel_core.gdpr import GDPRProvider

logger = logging.getLogger(__name__)


class FormsGDPRProvider(GDPRProvider):
    section = "forms"

    def export(self, user_id) -> dict:
        """Every response the user submitted while signed in, in full."""
        from .models import Submission
        from .presenters import present_answers

        rows = (
            Submission.objects.select_related("form", "version")
            .filter(submitted_by=user_id)
            .order_by("submitted_at")
        )
        return {
            "submissions": [
                {
                    "id": str(row.id),
                    "form_title": row.form.title,
                    "version": row.version.version,
                    "submitted_at": row.submitted_at.isoformat(),
                    "answers": present_answers(row),
                }
                for row in rows
            ],
        }

    def delete(self, user_id) -> None:
        self.anonymize(user_id)

    def anonymize(self, user_id) -> None:
        """Erase content, keep the tombstone. Idempotent — an erased row
        erases to itself, so at-least-once redelivery is harmless.

        There is no lesser meaningful anonymization for free-text answers:
        "what is your address" answered in prose cannot be de-identified
        without destroying it, so ``anonymize`` and ``delete`` are one
        operation rather than a pretend gradient.
        """
        from .services import erase_user_submissions

        erased = erase_user_submissions(user_id)
        if erased:
            logger.info("forms: erased %s submission(s) of user %s", erased, user_id)


__all__ = ["FormsGDPRProvider"]
