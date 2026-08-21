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
    "present_answers",
]
