"""Models for stapel-forms — form, immutable published version, submission.

The central decision this schema carries (spec §3.2): a published
``FormVersion`` is immutable, editing a live form publishes the next one,
and every ``Submission`` FKs the exact version it answered. A response is
only interpretable against the schema it answered; a version row gives both
cheap grouping ("the 240 responses to version 3") and exact interpretation,
at one row per publish instead of one schema snapshot per response.

House rules (docs/library-standard.md §3.8): cross-service references are
UUID fields, not FKs; the user model only via ``settings.AUTH_USER_MODEL``;
index/constraint names <= 30 chars.

Staff-mandate declarations (``stapel_core.access``): ``Submission`` is
``@access.sensitive`` (answers are respondent PII — staff view requires MID
clearance, any mutation HIGH), while ``Form`` and ``FormVersion`` stay on
the implicit ``standard`` preset. That MAC gates the
Django-admin peephole and staff tooling; the workspace capabilities in
``authz.py`` gate the product surface — two independent doors.
"""
import secrets
import uuid

from django.conf import settings as django_settings
from django.db import models
from stapel_core.access import access

#: Lifecycle. Only ``open`` accepts submissions; ``draft`` is indis-
#: tinguishable from "no such form" on the public surface (§5.1), while
#: ``closed`` is a distinct 410 because its public_id was public already.
STATE_DRAFT = "draft"
STATE_OPEN = "open"
STATE_CLOSED = "closed"
FORM_STATES = (
    (STATE_DRAFT, "Draft"),
    (STATE_OPEN, "Open"),
    (STATE_CLOSED, "Closed"),
)

#: 16 random bytes, urlsafe-base64 => 22 characters.
PUBLIC_ID_BYTES = 16


def generate_public_id() -> str:
    return secrets.token_urlsafe(PUBLIC_ID_BYTES)


class Form(models.Model):
    """Identity and lifecycle of a questionnaire.

    Fields here describe the CONTAINER, not the questionnaire, which is why
    none of them version: the admin-facing title, the notification
    recipients, the state and the retention override can all change without
    invalidating a single stored answer. What respondents actually saw —
    rendered title, description, confirmation text — lives in the version's
    schema meta instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True)
    title = models.CharField(max_length=255)
    #: The ONLY public handle. A dedicated random token rather than the row
    #: UUID: rotating it after a leak must not re-key the row, and the pk
    #: never travels to an anonymous caller.
    public_id = models.CharField(
        max_length=32, unique=True, db_index=True, default=generate_public_id
    )
    state = models.CharField(max_length=16, choices=FORM_STATES, default=STATE_DRAFT)
    active_version = models.ForeignKey(
        "FormVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: The builder's scratchpad. Never served on the public surface.
    draft_schema = models.JSONField(null=True, blank=True)
    #: ``{"notify_emails": [...], "retention_days": int | None}``.
    settings = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "forms_form"
        indexes = [
            models.Index(fields=["workspace_id", "state"], name="forms_form_ws_state"),
        ]

    def __str__(self):
        return self.title


class FormVersion(models.Model):
    """A schema frozen at publish. Never edited, never deleted while a
    submission references it (``PROTECT`` from ``Submission``)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="versions")
    #: Monotonic per form, starting at 1.
    version = models.PositiveIntegerField()
    #: ``{"fields": [FeatureDef dicts], "meta": {...}}``.
    schema = models.JSONField()
    published_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "forms_form_version"
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(
                fields=["form", "version"], name="forms_version_unique"
            ),
        ]

    def __str__(self):
        return f"{self.form_id} v{self.version}"


@access.sensitive  # answers are respondent PII (admin-suite AS-5)
class Submission(models.Model):
    """One answered form.

    ``answers`` holds DAO shapes produced by
    ``stapel_attributes.normalize_to_dao`` over the version's configs —
    never pass-through JSON, which is what makes it impossible for a
    hostile client to smuggle keys into storage.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    #: Denormalized so scoping and purge need no join.
    workspace_id = models.UUIDField(db_index=True)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="submissions")
    version = models.ForeignKey(FormVersion, on_delete=models.PROTECT, related_name="submissions")
    answers = models.JSONField(default=dict, blank=True)
    #: FK-less user id — survives user erasure (the docs
    #: ``DocumentUpdate.author_id`` precedent). Null = anonymous respondent.
    submitted_by = models.UUIDField(null=True, blank=True, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    #: ``{"ip": ..., "ua": ...}``, only when STORE_CLIENT_META is on.
    client_meta = models.JSONField(null=True, blank=True)
    #: Tombstone: answers purged, row still counted, so response counts and
    #: per-version analytics stay truthful ("300 responses, 2 erased").
    erased_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "forms_submission"
        ordering = ("-submitted_at", "-id")
        indexes = [
            models.Index(fields=["form", "-submitted_at"], name="forms_sub_form_time"),
        ]

    def __str__(self):
        return f"{self.form_id} @ {self.submitted_at:%Y-%m-%d}"
