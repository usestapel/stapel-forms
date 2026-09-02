"""Presenters for stapel-forms — the DTO-building layer (§55).

Presenter discipline (enforced by SWAP001/SWAP002 in `stapel-verify`):
views NEVER instantiate a `dto.py` dataclass directly — every DTO is built
by a presenter resolved through `get_presenter(KEY, default=...)`, so a
host project can reshape any envelope via `STAPEL_SWAP` without forking
this module.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from stapel_core.django.api.presenters import Presenter, PresenterField
from stapel_core.django.swappable import declare_swap, get_presenter

from .dto import (
    FieldKindDTO,
    FieldKindsDTO,
    PublicFormDTO,
    PublishResultDTO,
    ResendResultDTO,
    SubmitResultDTO,
)
from .models import Form, FormVersion, Submission
from .schema import schema_fields, schema_meta

FORM_PRESENTER_KEY = "FORMS_FORM_PRESENTER"
DEFAULT_FORM_PRESENTER = "stapel_forms.presenters.FormPresenter"
VERSION_PRESENTER_KEY = "FORMS_VERSION_PRESENTER"
DEFAULT_VERSION_PRESENTER = "stapel_forms.presenters.FormVersionPresenter"
SUBMISSION_PRESENTER_KEY = "FORMS_SUBMISSION_PRESENTER"
DEFAULT_SUBMISSION_PRESENTER = "stapel_forms.presenters.SubmissionPresenter"

declare_swap(FORM_PRESENTER_KEY, DEFAULT_FORM_PRESENTER)
declare_swap(VERSION_PRESENTER_KEY, DEFAULT_VERSION_PRESENTER)
declare_swap(SUBMISSION_PRESENTER_KEY, DEFAULT_SUBMISSION_PRESENTER)


class FormPresenter(Presenter):
    """Presents a Form row to its workspace's admins.

    Example:
        {
            "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "workspace_id": "5cc26b64-0717-4562-b3fc-2c963f66a001",
            "title": "Contact us",
            "public_id": "k3JhQ2Zt8uY1sVb7cD9xLg",
            "state": "open",
            "active_version": 3,
            "active_version_id": "9aa1...",
            "draft_schema": null,
            "settings": {"notify_emails": ["sales@example.com"]},
            "submission_count": 240,
            "created_at": "2026-08-21T10:00:00+00:00",
            "updated_at": "2026-08-21T10:00:00+00:00",
            "deleted_at": null
        }
    """

    model = Form
    fields = ("title", "state", "public_id")
    custom_fields = {
        "id": PresenterField(type=str, source=lambda dao: str(dao.id)),
        "workspace_id": PresenterField(type=str, source=lambda dao: str(dao.workspace_id)),
        "active_version": PresenterField(
            type=Optional[int],
            source=lambda dao: dao.active_version.version if dao.active_version_id else None,
            default=None,
            help_text="Ordinal of the version currently served to respondents.",
        ),
        "active_version_id": PresenterField(
            type=Optional[str],
            source=lambda dao: str(dao.active_version_id) if dao.active_version_id else None,
            default=None,
        ),
        "draft_schema": PresenterField(
            type=Optional[dict],
            source=lambda dao: dao.draft_schema,
            default=None,
            help_text="The builder's scratchpad; null once published.",
        ),
        "settings": PresenterField(type=dict, source=lambda dao: dao.settings or {}),
        "submission_count": PresenterField(
            type=int,
            source=lambda dao: getattr(dao, "submission_count", None) or dao.submissions.count(),
            default=0,
        ),
        "created_at": PresenterField(type=str, source=lambda dao: dao.created_at.isoformat()),
        "updated_at": PresenterField(type=str, source=lambda dao: dao.updated_at.isoformat()),
        "deleted_at": PresenterField(
            type=Optional[str],
            source=lambda dao: dao.deleted_at.isoformat() if dao.deleted_at else None,
            default=None,
        ),
    }


class FormVersionPresenter(Presenter):
    """Presents one published, immutable schema version."""

    model = FormVersion
    fields = ("version",)
    custom_fields = {
        "id": PresenterField(type=str, source=lambda dao: str(dao.id)),
        "form_id": PresenterField(type=str, source=lambda dao: str(dao.form_id)),
        "schema": PresenterField(type=dict, source=lambda dao: dao.schema or {}),
        "published_at": PresenterField(type=str, source=lambda dao: dao.published_at.isoformat()),
        "created_by": PresenterField(
            type=Optional[str],
            source=lambda dao: str(dao.created_by_id) if dao.created_by_id else None,
            default=None,
        ),
        "submission_count": PresenterField(
            type=int,
            source=lambda dao: getattr(dao, "submission_count", None) or dao.submissions.count(),
            default=0,
        ),
    }


class SubmissionPresenter(Presenter):
    """Presents one response to a workspace reviewer.

    ``answers`` is presented as ``{slug: value}`` rather than the raw DAO
    dicts: the DAO carries display metadata copied from the schema (name,
    order, badge flags), which the reviewer already has from the version
    and which would otherwise be repeated on every row.
    """

    model = Submission
    fields = ()
    custom_fields = {
        "id": PresenterField(type=str, source=lambda dao: str(dao.id)),
        "form_id": PresenterField(type=str, source=lambda dao: str(dao.form_id)),
        "version": PresenterField(type=int, source=lambda dao: dao.version.version),
        "version_id": PresenterField(type=str, source=lambda dao: str(dao.version_id)),
        "answers": PresenterField(type=dict, source=lambda dao: present_answers(dao)),
        "submitted_by": PresenterField(
            type=Optional[str],
            source=lambda dao: str(dao.submitted_by) if dao.submitted_by else None,
            default=None,
            help_text="Respondent user id, or null for an anonymous respondent.",
        ),
        "submitted_at": PresenterField(type=str, source=lambda dao: dao.submitted_at.isoformat()),
        "client_meta": PresenterField(
            type=Optional[dict],
            source=lambda dao: dao.client_meta,
            default=None,
            help_text="Only populated where the host turned STORE_CLIENT_META on.",
        ),
        "erased_at": PresenterField(
            type=Optional[str],
            source=lambda dao: dao.erased_at.isoformat() if dao.erased_at else None,
            default=None,
            help_text="Set when the answers were erased; the row is kept so counts stay truthful.",
        ),
    }


def get_form_presenter() -> type[Presenter]:
    return get_presenter(FORM_PRESENTER_KEY, default=DEFAULT_FORM_PRESENTER)


def get_version_presenter() -> type[Presenter]:
    return get_presenter(VERSION_PRESENTER_KEY, default=DEFAULT_VERSION_PRESENTER)


def get_submission_presenter() -> type[Presenter]:
    return get_presenter(SUBMISSION_PRESENTER_KEY, default=DEFAULT_SUBMISSION_PRESENTER)


# ── Envelope builders (no backing model) ─────────────────────────────


def present_public_form(form) -> PublicFormDTO:
    """The anonymous envelope. Everything it does not carry is deliberate."""
    version = form.active_version
    return PublicFormDTO(
        public_id=form.public_id,
        version_id=str(version.id),
        version=version.version,
        fields=_public_fields(version.schema),
        meta=_public_meta(version.schema),
    )


def present_submit_result(form) -> SubmitResultDTO:
    meta = schema_meta(form.active_version.schema) if form.active_version_id else {}
    return SubmitResultDTO(accepted=True, confirmation=meta.get("confirmation_text") or "")


def present_publish_result(version) -> PublishResultDTO:
    return PublishResultDTO(
        version_id=str(version.id),
        version=version.version,
        published_at=version.published_at.isoformat(),
    )


def present_resend_result(sent: int) -> ResendResultDTO:
    return ResendResultDTO(sent=sent)


def present_field_kinds(*, allowed_kinds) -> FieldKindsDTO:
    """The builder's field-kind catalogue, read from the live registry.

    Read from ``stapel_attributes.config_form.form_declarations()`` on every
    call rather than snapshotted: the registry is built-ins <- ``EXTRA_TYPES``
    <- runtime registrations, so a host type registered after import must
    show up without a restart of anything but the process that registered it.

    Every REGISTERED kind is listed, not just the allowlisted ones — a
    schema published before a kind left ``STAPEL_FORMS['FIELD_KINDS']`` still
    has to render, and ``allowed`` is what tells the builder which kinds it
    may offer for a NEW field. Kinds that declare no config form (upstream's
    ``convertible_unit``) appear with an empty ``fields`` list, which is the
    signal to fall back rather than the absence of one.
    """
    from stapel_attributes.config_form import FIELD_KINDS, form_declarations

    allowed = set(allowed_kinds or ())
    declarations = form_declarations()

    kinds = [
        FieldKindDTO(
            kind=slug,
            label_key=declaration.get("label_key") or f"admin.attributes.type.{slug}",
            allowed=slug in allowed,
            registered=True,
            fields=list(declaration.get("fields") or []),
        )
        for slug, declaration in declarations.items()
    ]
    # An allowlisted kind the registry does not carry is a host
    # misconfiguration, but the honest answer is to say so rather than to
    # omit the kind and let the builder infer it never existed.
    kinds.extend(
        FieldKindDTO(
            kind=slug,
            label_key=f"admin.attributes.type.{slug}",
            allowed=True,
            registered=False,
            fields=[],
        )
        for slug in allowed - set(declarations)
    )
    kinds.sort(key=lambda entry: entry.kind)

    return FieldKindsDTO(
        kinds=kinds,
        config_widgets={
            widget: list(params) for widget, params in sorted(FIELD_KINDS.items())
        },
    )


def dao_display(dao) -> str:
    """The readable rendering of one stored answer DAO.

    Prefers the DAO's own ``labels`` over its ``value``: a ``select``
    stores ``["pro"]`` and carries ``["Pro"]`` beside it, and the option
    label is what the respondent actually clicked. Reading the value
    instead is how a review screen ends up showing machine slugs to a
    person — the single most common complaint about raw-JSON response
    views, and free to fix because the normalizer already wrote the label
    down at submit time.
    """
    from .export import format_value

    if not isinstance(dao, dict):
        return format_value(dao)
    labels = dao.get("labels")
    if labels:
        return format_value(labels)
    return format_value(dao.get("value"))


def present_answer_rows(submission, *, schema=None) -> List[dict]:
    """One row per QUESTION of the answered version, in schema order.

    The projection every review surface needs and none of them should
    build twice: the admin responses table, the submission detail, and the
    notification report all read this. Driven by the *schema*, never by
    the answer dict, which is what buys the three properties a raw-JSON
    view cannot have:

    - **order** is the order the respondent was asked in, not dict
      insertion order;
    - **labels** are what the respondent saw, not storage slugs;
    - **an unanswered question still gets a row.** A blank cell is
      information, and dropping it silently shifts every later cell
      against its column header — a table that lies rather than a table
      with a gap.

    ``schema`` defaults to the version this submission answered. That is
    the version FK earning its keep: a question deleted by a later publish
    is still the question this respondent was asked, so an old response
    keeps rendering under the schema it answered rather than decaying into
    orphan keys.
    """
    from .schema import answer_columns

    if schema is None:
        schema = submission.version.schema
    answers = submission.answers or {}
    rows = []
    for slug, label in answer_columns(schema):
        dao = answers.get(slug)
        rows.append(
            {
                "slug": slug,
                "label": label,
                "value": dao.get("value") if isinstance(dao, dict) else dao,
                "display": dao_display(dao),
                # `answered` is not `bool(display)`: "false" and "0" are
                # answers that render falsy, and a reviewer must be able to
                # tell "said no" from "did not say".
                "answered": slug in answers,
            }
        )
    return rows


def present_response_table(form, submissions, *, versions=None) -> dict:
    """``{"columns": [...], "rows": [...]}`` — a whole review page at once.

    The projection the version FK exists to make possible, and the one a
    raw ``answers`` dump cannot produce. Columns are the **union across
    every published version**, led by the CURRENT schema's order so the
    table reads the way the form currently reads; questions that only
    older versions had keep their column after it rather than dropping
    out. Without the union, every answer to a since-renamed or
    since-deleted question has nowhere to land and disappears from review
    — which is precisely the "каша" a mutable schema would guarantee.

    Each cell records ``in_schema``: whether the row's OWN version defined
    that question. "Not asked" and "asked and left blank" are different
    facts about a respondent and a reviewer must be able to tell them
    apart; both render blank, only one is a gap in the data.

    ``versions`` may be passed pre-fetched to keep this to one query.
    """
    from .schema import answer_columns

    if versions is None:
        versions = list(form.versions.all().order_by("-version"))

    active_id = form.active_version_id
    ordered = sorted(
        versions,
        # The active version leads, then the rest newest-first: the table's
        # column order is "how this form reads today".
        key=lambda v: (v.id != active_id, -v.version),
    )

    columns: List[dict] = []
    seen = set()
    per_version: Dict[Any, set] = {}
    for version in ordered:
        slugs = set()
        for slug, label in answer_columns(version.schema):
            slugs.add(slug)
            if slug not in seen:
                seen.add(slug)
                columns.append({"slug": slug, "label": label})
        per_version[version.id] = slugs

    rows = []
    previous_version_id = None
    for submission in submissions:
        answers = submission.answers or {}
        defined = per_version.get(submission.version_id, set(answers))
        cells = []
        for column in columns:
            slug = column["slug"]
            dao = answers.get(slug)
            cells.append(
                {
                    "slug": slug,
                    "display": dao_display(dao) if slug in answers else "",
                    "in_schema": slug in defined,
                }
            )
        rows.append(
            {
                "submission": submission,
                "id": str(submission.id),
                "submitted_at": submission.submitted_at,
                "version": submission.version.version,
                "erased": submission.erased_at is not None,
                "cells": cells,
                # The ONLY place the version split surfaces: a marker on the
                # boundary row where the schema actually changed. Not a
                # column the reviewer has to read on every row, and never a
                # step they must take before seeing anything.
                "schema_changed": (
                    previous_version_id is not None
                    and submission.version_id != previous_version_id
                ),
            }
        )
        previous_version_id = submission.version_id

    return {"columns": columns, "rows": rows}


def present_answers(submission) -> Dict[str, Any]:
    """``{slug: value}`` from the stored DAO shapes, headers omitted."""
    answers = submission.answers or {}
    flat: Dict[str, Any] = {}
    for slug, dao in answers.items():
        if not isinstance(dao, dict):
            flat[slug] = dao
            continue
        if dao.get("type") == "header":
            continue
        flat[slug] = dao.get("value")
    return flat


def _public_fields(schema) -> List[dict]:
    """Field defs, stripped of anything that is not rendering input.

    ``FeatureDef`` carries listing-oriented flags (show_at_title,
    show_as_badge) that mean nothing to a form renderer; passing them
    through would invite a client to depend on them.
    """
    out = []
    for entry in schema_fields(schema):
        out.append(
            {
                "slug": entry.get("slug"),
                "name": entry.get("name") or entry.get("slug"),
                "mandatory": bool(entry.get("mandatory")),
                "config": entry.get("config") or {},
            }
        )
    return out


def _public_meta(schema) -> dict:
    from .schema import META_KEYS

    meta = schema_meta(schema)
    return {key: meta[key] for key in META_KEYS if key in meta}


__all__ = [
    "FORM_PRESENTER_KEY",
    "VERSION_PRESENTER_KEY",
    "SUBMISSION_PRESENTER_KEY",
    "DEFAULT_FORM_PRESENTER",
    "DEFAULT_VERSION_PRESENTER",
    "DEFAULT_SUBMISSION_PRESENTER",
    "FormPresenter",
    "FormVersionPresenter",
    "SubmissionPresenter",
    "get_form_presenter",
    "get_version_presenter",
    "get_submission_presenter",
    "present_public_form",
    "present_submit_result",
    "present_publish_result",
    "present_resend_result",
    "present_field_kinds",
    "present_answers",
    "present_answer_rows",
    "dao_display",
]
