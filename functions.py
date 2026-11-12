"""comm Function providers of stapel-forms.

- ``forms.form.exists {public_id}`` -> ``{exists, published}`` — lets another
  module (a CMS ``form`` block) validate a form reference at save time.

Everything this module CALLS goes the other way: ``workspaces.check_capability``
through the core client (``authz.py``), and nothing else.
"""
from stapel_core.comm import function

FORM_EXISTS_SCHEMA = {
    "type": "object",
    "properties": {
        "public_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 32,
            "description": "The form's public handle (Form.public_id).",
        },
    },
    "required": ["public_id"],
    "additionalProperties": False,
}


@function("forms.form.exists", schema=FORM_EXISTS_SCHEMA)
def form_exists(payload: dict) -> dict:
    """Whether a public form handle names a form, and whether it is live.

    ``exists`` is false for an unknown or soft-deleted form. ``published``
    is true exactly when the public surface serves the form as fillable —
    state ``open`` with an active version, what ``GET public/forms/{id}/``
    answers 200 for. A draft or closed form answers ``published: false``.
    Nothing else about the form (title, schema, workspace) leaves this
    Function, so a caller cannot read unpublished content through it.
    """
    from .models import STATE_OPEN, Form

    row = (
        Form.objects.filter(public_id=str(payload["public_id"]), deleted_at__isnull=True)
        .values("state", "active_version_id")
        .first()
    )
    if row is None:
        return {"exists": False, "published": False}
    return {
        "exists": True,
        "published": row["state"] == STATE_OPEN and row["active_version_id"] is not None,
    }


__all__ = ["FORM_EXISTS_SCHEMA", "form_exists"]
