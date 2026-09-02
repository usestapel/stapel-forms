"""Service layer of stapel-forms — every mutation and its invariants.

The invariants enforced here (spec §3.2, §5.2, §6):

- a published ``FormVersion`` is immutable; publishing mints ``head+1`` and
  repoints ``active_version``, all inside one transaction with the emit;
- a submission is accepted only against the ACTIVE version (the grace
  window ships at 0), and only through
  ``validate → normalize_to_dao → store`` — never pass-through JSON;
- volume caps bound what one leaked public link can cost;
- erasure keeps the row and destroys the content, so response counts stay
  truthful; retention destroys the row, because after retention the count
  claim expires too.

Emits happen inside the mutating transaction (outbox canon).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import events, schema as schema_mod
from .conf import forms_settings
from .errors import (
    ERR_400_INVALID_RETENTION,
    ERR_400_INVALID_STATE,
    ERR_400_NO_DRAFT,
    ERR_400_NO_RECIPIENTS,
    ERR_400_NOT_PUBLISHED,
    ERR_400_TOO_MANY_OPEN_FORMS,
    ERR_400_UNKNOWN_FIELD,
    ERR_400_ANSWERS_NOT_OBJECT,
    ERR_404_NOT_FOUND,
    ERR_404_SUBMISSION_NOT_FOUND,
    ERR_409_SUBMISSION_CAP,
    ERR_409_VERSION_SUPERSEDED,
    ERR_410_CLOSED,
)
from .models import (
    FORM_STATES,
    STATE_CLOSED,
    STATE_DRAFT,
    STATE_OPEN,
    Form,
    FormVersion,
    Submission,
    generate_public_id,
)

logger = logging.getLogger(__name__)


class FormsError(Exception):
    """Service-level refusal carrying the HTTP mapping for the view layer."""

    def __init__(self, status: int, error_key: str, params: dict | None = None,
                 field_errors=None):
        super().__init__(error_key)
        self.status = status
        self.error_key = error_key
        self.params = params or {}
        self.field_errors = field_errors or []


# ─────────────────────────────────────────────────────────────────────
# Lookup
# ─────────────────────────────────────────────────────────────────────


def get_form(form_id, workspace_id) -> Form:
    form = Form.objects.filter(
        id=form_id, workspace_id=workspace_id, deleted_at__isnull=True
    ).first()
    if form is None:
        raise FormsError(404, ERR_404_NOT_FOUND)
    return form


def list_forms(workspace_id, *, state=None):
    qs = Form.objects.filter(workspace_id=workspace_id, deleted_at__isnull=True)
    if state:
        qs = qs.filter(state=state)
    return qs.order_by("-created_at")


def resolve_public(public_id: str) -> Form:
    """Resolve the public handle, with the uniform-404 discipline.

    Unknown handle, soft-deleted form and ``state=draft`` are one
    byte-identical 404: a stranger must not be able to tell an unpublished
    form from a typo. ``closed`` is a distinct 410 — that public_id was
    public by definition, and the renderer needs the difference to say
    "this form is closed" rather than "broken link".
    """
    form = Form.objects.select_related("active_version").filter(public_id=public_id).first()
    if form is None or form.deleted_at is not None or form.state == STATE_DRAFT:
        raise FormsError(404, ERR_404_NOT_FOUND)
    if form.state == STATE_CLOSED:
        raise FormsError(410, ERR_410_CLOSED)
    if form.active_version_id is None:
        # Open without a published version is a host-side inconsistency,
        # not a fact a respondent should learn anything from.
        raise FormsError(404, ERR_404_NOT_FOUND)
    return form


# ─────────────────────────────────────────────────────────────────────
# Authoring
# ─────────────────────────────────────────────────────────────────────


def create_form(*, workspace_id, title, user=None, settings=None, draft_schema=None) -> Form:
    with transaction.atomic():
        form = Form.objects.create(
            workspace_id=workspace_id,
            title=title,
            created_by=user,
            settings=_validated_settings(settings),
            draft_schema=(
                schema_mod.normalize_schema(draft_schema) if draft_schema is not None else None
            ),
        )
    return form


def update_form(form: Form, *, title=None, settings=None) -> Form:
    if title is not None:
        form.title = title
    if settings is not None:
        form.settings = _validated_settings(settings)
    form.save(update_fields=["title", "settings", "updated_at"])
    return form


def save_draft(form: Form, raw_schema) -> Form:
    """Store the builder's scratchpad. Deliberately NOT validated hard:
    a half-built draft must be savable, and publish is the gate."""
    form.draft_schema = schema_mod.normalize_schema(raw_schema)
    form.save(update_fields=["draft_schema", "updated_at"])
    return form


def publish(form: Form, *, user=None) -> FormVersion:
    """Freeze the draft as the next immutable version and activate it."""
    if not form.draft_schema:
        raise FormsError(400, ERR_400_NO_DRAFT)

    draft = schema_mod.normalize_schema(form.draft_schema)
    try:
        schema_mod.validate_schema(
            draft,
            allowed_kinds=set(forms_settings.FIELD_KINDS or ()),
            max_fields=int(forms_settings.MAX_FIELDS_PER_FORM),
        )
    except schema_mod.SchemaInvalid as exc:
        raise FormsError(400, exc.error_key, exc.params, exc.field_errors) from exc

    with transaction.atomic():
        locked = Form.objects.select_for_update().get(pk=form.pk)
        head = (
            FormVersion.objects.filter(form=locked)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0
        )
        version = FormVersion.objects.create(
            form=locked, version=head + 1, schema=draft, created_by=user
        )
        locked.active_version = version
        locked.draft_schema = None
        locked.save(update_fields=["active_version", "draft_schema", "updated_at"])
        events.emit_form_published(locked, version)

    form.refresh_from_db()
    return version


def set_state(form: Form, state: str) -> Form:
    if state not in dict(FORM_STATES):
        raise FormsError(400, ERR_400_INVALID_STATE, {"state": state})
    if state == STATE_OPEN:
        if form.active_version_id is None:
            raise FormsError(400, ERR_400_NOT_PUBLISHED)
        cap = int(forms_settings.MAX_OPEN_FORMS_PER_WORKSPACE or 0)
        if cap and form.state != STATE_OPEN:
            open_count = Form.objects.filter(
                workspace_id=form.workspace_id, state=STATE_OPEN, deleted_at__isnull=True
            ).count()
            if open_count >= cap:
                raise FormsError(400, ERR_400_TOO_MANY_OPEN_FORMS, {"limit": cap})

    was_open = form.state == STATE_OPEN
    with transaction.atomic():
        form.state = state
        form.save(update_fields=["state", "updated_at"])
        if state == STATE_CLOSED and was_open:
            events.emit_form_closed(form)
    return form


def rotate_link(form: Form) -> Form:
    """Mint a new public handle. Every distributed link dies — deliberate:
    that is the whole point of rotating after a leak."""
    form.public_id = generate_public_id()
    form.save(update_fields=["public_id", "updated_at"])
    return form


def delete_form(form: Form) -> Form:
    """Soft delete: intake stops immediately, rows survive for review until
    the trash purge cascades them."""
    with transaction.atomic():
        was_open = form.state == STATE_OPEN
        form.deleted_at = timezone.now()
        form.save(update_fields=["deleted_at", "updated_at"])
        if was_open:
            events.emit_form_closed(form)
    return form


def _validated_settings(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise FormsError(400, ERR_400_INVALID_RETENTION)
    settings = dict(raw)
    retention = settings.get("retention_days")
    if retention is not None:
        ceiling = forms_settings.RETENTION_DAYS
        try:
            retention = int(retention)
        except (TypeError, ValueError):
            raise FormsError(400, ERR_400_INVALID_RETENTION) from None
        # A per-form override may only SHORTEN. Lengthening past the module
        # ceiling is the open switch and needs the module setting raised —
        # otherwise one form's settings blob quietly rewrites the
        # deployment's retention promise.
        if retention < 1 or (ceiling and retention > int(ceiling)):
            raise FormsError(400, ERR_400_INVALID_RETENTION, {"limit": ceiling})
        settings["retention_days"] = retention
    return settings


# ─────────────────────────────────────────────────────────────────────
# Submission
# ─────────────────────────────────────────────────────────────────────


def submit(form: Form, *, answers, version_id=None, user_id=None, client_meta=None) -> Submission:
    """Accept one answered form.

    ``version_id`` is what the client echoes back from the schema it
    rendered. A racing publish therefore rejects the whole submit with
    409 rather than half-validating against a schema the respondent never
    saw — the renderer refetches and tells them the form changed.
    """
    active = form.active_version
    if active is None:
        raise FormsError(404, ERR_404_NOT_FOUND)
    if version_id is not None and str(version_id) != str(active.id):
        if not _within_grace(form, version_id):
            raise FormsError(409, ERR_409_VERSION_SUPERSEDED, {"version": active.version})

    cap = int(forms_settings.MAX_SUBMISSIONS_PER_FORM or 0)
    if cap and Submission.objects.filter(form=form).count() >= cap:
        raise FormsError(409, ERR_409_SUBMISSION_CAP, {"limit": cap})

    field_errors, unknown = schema_mod.validate_answers(active.schema, answers)
    if unknown is None:
        raise FormsError(400, ERR_400_ANSWERS_NOT_OBJECT)
    if unknown:
        raise FormsError(400, ERR_400_UNKNOWN_FIELD, {"field": unknown[0]})
    if field_errors:
        raise FormsError(400, field_errors[0].code, field_errors[0].params, field_errors)

    dao = schema_mod.to_dao(active.schema, answers)

    with transaction.atomic():
        submission = Submission.objects.create(
            workspace_id=form.workspace_id,
            form=form,
            version=active,
            answers=dao,
            submitted_by=user_id,
            client_meta=client_meta if forms_settings.STORE_CLIENT_META else None,
        )
        events.emit_submission_received(submission)
    return submission


def _within_grace(form: Form, version_id) -> bool:
    """Strict by default: the grace window ships at 0 seconds."""
    grace = int(forms_settings.ACCEPT_PREVIOUS_VERSION_SECONDS or 0)
    if grace <= 0:
        return False
    previous = (
        FormVersion.objects.filter(form=form)
        .exclude(pk=form.active_version_id)
        .order_by("-version")
        .first()
    )
    if previous is None or str(previous.id) != str(version_id):
        return False
    superseded_at = form.active_version.published_at
    return timezone.now() - superseded_at <= timedelta(seconds=grace)


# ─────────────────────────────────────────────────────────────────────
# Review
# ─────────────────────────────────────────────────────────────────────


def form_answer_slugs(form: Form) -> list:
    """Every question slug this form has ever published, newest first.

    Definition-driven, like everything else that reads answers: the set
    comes from the versions' schemas, never from scanning stored answer
    keys. That is what makes an unknown ``field`` scope answerable as a
    refusal instead of an empty page, and it stays bounded by
    ``MAX_FIELDS_PER_FORM`` per version.
    """
    seen = []
    for version in form.versions.all().order_by("-version"):
        for slug, _label in schema_mod.answer_columns(version.schema):
            if slug not in seen:
                seen.append(slug)
    return seen


def list_submissions(form: Form, *, before=None, limit=None, version=None,
                     since=None, until=None, q=None, field=None):
    """Keyset page, newest first (docs canon: no pagination framework).

    ``before`` is the PAGING cursor and ``since``/``until`` are the date
    FILTER — different axes on the same column, deliberately separate
    parameters so narrowing a window does not silently reset the caller's
    position in it (and so the admin's "next page" inside a filtered view
    keeps the filter).

    ``q`` matches answer text, case-insensitively, as a substring;
    ``field`` scopes it to one question. Unscoped, it ORs across every
    slug the form has published — bounded by the schema, not by a scan of
    whatever keys happen to be in storage. An erased submission carries
    ``answers = {}`` and is therefore never matched by content it no
    longer holds.
    """
    cap = int(forms_settings.MAX_PAGE_SIZE)
    limit = min(int(limit or cap), cap)
    qs = Submission.objects.filter(form=form)
    if version is not None:
        qs = qs.filter(version__version=version)
    if before is not None:
        qs = qs.filter(submitted_at__lt=before)
    if since is not None:
        qs = qs.filter(submitted_at__gte=since)
    if until is not None:
        qs = qs.filter(submitted_at__lte=until)

    needle = (q or "").strip()
    if field is not None:
        # A typo'd field name must not read as "no matches" — that is a
        # different fact, and reporting it as an empty page is how a
        # reviewer concludes a response does not exist.
        if field not in form_answer_slugs(form):
            raise FormsError(400, ERR_400_UNKNOWN_FIELD, {"field": field})
        if needle:
            qs = qs.filter(**{f"answers__{field}__value__icontains": needle})
    elif needle:
        from django.db.models import Q

        slugs = form_answer_slugs(form)
        if not slugs:
            return []
        predicate = Q()
        for slug in slugs:
            predicate |= Q(**{f"answers__{slug}__value__icontains": needle})
        qs = qs.filter(predicate)

    return list(qs.select_related("version").order_by("-submitted_at", "-id")[:limit])


def get_submission(submission_id, workspace_id) -> Submission:
    submission = (
        Submission.objects.select_related("form", "version")
        .filter(id=submission_id, workspace_id=workspace_id, form__deleted_at__isnull=True)
        .first()
    )
    if submission is None:
        raise FormsError(404, ERR_404_SUBMISSION_NOT_FOUND)
    return submission


def delete_submission(submission: Submission) -> None:
    """The practical channel for "please delete my response" mail, until
    an email-keyed GDPR subject exists upstream (spec §6)."""
    submission.delete()


def resend_submission(submission: Submission, *, recipients=None,
                      telegram_chat_ids=None) -> int:
    """Re-deliver one submission to the form's notify targets.

    Admin-initiated, therefore cooldown-independent (spec §11a): the
    cooldown exists to stop a respondent-driven flood, and an operator
    looking at a row is not a flood.

    An explicit destination override replaces the form's targets entirely
    rather than adding to them — "send this one to legal" must not also
    re-send it to everybody who already got it.
    """
    from .notifications import TARGET_KINDS, notify_resend, notify_targets

    override = [("email", e) for e in (recipients or []) if str(e).strip()]
    override += [
        (TARGET_KINDS["notify_telegram_chat_ids"], str(c).strip())
        for c in (telegram_chat_ids or [])
        if str(c).strip()
    ]
    targets = override or notify_targets(submission.form)
    if not targets:
        raise FormsError(400, ERR_400_NO_RECIPIENTS)
    return notify_resend(submission.form, submission, targets)


# ─────────────────────────────────────────────────────────────────────
# Retention / erasure
# ─────────────────────────────────────────────────────────────────────


def erase_user_submissions(user_id) -> int:
    """Erase content, keep the tombstone (spec §6).

    The row survives so response counts and per-version analytics stay
    truthful; the content, the client metadata and the attribution do not.
    Idempotent — an erased row erases to itself.
    """
    now = timezone.now()
    return Submission.objects.filter(submitted_by=user_id).update(
        answers={}, client_meta=None, submitted_by=None, erased_at=now
    )


def purge_expired() -> int:
    """Hard-delete submissions past their retention horizon.

    Per-form overrides may only shorten, so the module ceiling is the
    outer bound and a form with no override uses it. After retention the
    count claim expires too — these rows leave no tombstone.
    """
    ceiling = forms_settings.RETENTION_DAYS
    if not ceiling:
        return 0
    now = timezone.now()
    total = 0
    default_cutoff = now - timedelta(days=int(ceiling))

    overridden = {}
    for form_id, form_settings in Form.objects.exclude(settings={}).values_list(
        "id", "settings"
    ):
        days = (form_settings or {}).get("retention_days")
        if days:
            overridden[form_id] = int(days)

    if overridden:
        total += Submission.objects.filter(submitted_at__lt=default_cutoff).exclude(
            form_id__in=overridden
        ).delete()[0]
        for form_id, days in overridden.items():
            total += Submission.objects.filter(
                form_id=form_id, submitted_at__lt=now - timedelta(days=days)
            ).delete()[0]
    else:
        total += Submission.objects.filter(submitted_at__lt=default_cutoff).delete()[0]
    return total


def purge_deleted_forms(*, older_than_days: int | None = None) -> tuple:
    """Destroy soft-deleted forms and everything under them.

    Submissions must go before their versions: ``FormVersion`` is
    PROTECTed precisely so a version can never lose the answers that
    reference it by accident.
    """
    cutoff = timezone.now() - timedelta(days=int(older_than_days or forms_settings.RETENTION_DAYS or 0))
    doomed = Form.objects.filter(deleted_at__isnull=False, deleted_at__lt=cutoff)
    form_ids = list(doomed.values_list("id", flat=True))
    if not form_ids:
        return 0, 0
    submissions = Submission.objects.filter(form_id__in=form_ids).delete()[0]
    FormVersion.objects.filter(form_id__in=form_ids).delete()
    forms = Form.objects.filter(id__in=form_ids).delete()[0]
    return forms, submissions


__all__ = [
    "FormsError",
    "get_form",
    "list_forms",
    "resolve_public",
    "create_form",
    "update_form",
    "save_draft",
    "publish",
    "set_state",
    "rotate_link",
    "delete_form",
    "submit",
    "list_submissions",
    "get_submission",
    "delete_submission",
    "resend_submission",
    "erase_user_submissions",
    "purge_expired",
    "purge_deleted_forms",
]
