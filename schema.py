"""The attributes adapter — the one seam between forms and the field engine.

A form schema is ``{"fields": [FeatureDef dict, ...], "meta": {...}}``: the
exact dicts ``stapel_attributes.coerce_feature_defs`` accepts. This module
holds everything forms must add ON TOP of that engine, and nothing that
duplicates it. Every deviation below was measured against the real library
(spec §12 risk 1 spike, 2026-08-21) rather than assumed:

1. ``validate_dto_structured`` IGNORES answers for slugs the schema does
   not define — silently, returning ``valid=True``. Correct for listings
   (a category's attribute set is advisory); wrong for a public form,
   where an unknown key is a hostile client probing what lands in storage.
   Forms rejects it explicitly (``error.400.forms_unknown_field``).
2. Its per-field ``params`` carry ``{"feature", "slug"}`` — the fleet's
   frontend field-error convention reads ``params.field``. The adapter
   adds ``field`` (keeping ``slug`` and ``feature``, which the attributes
   error catalogue's message templates interpolate).
3. ``normalize_to_dao`` is LENIENT by design: it skips whatever fails to
   normalize and happily stores a value the validator rejected (an invalid
   ``select`` option round-trips into the DAO). It therefore may never run
   on unvalidated input — :func:`validate_answers` is not optional, and a
   non-dict payload makes it raise outright.
4. ``header`` fields are auto-generated: the engine ignores an answer to
   one and regenerates the header DAO from the config, so smuggling is
   already impossible — but a client that answers a header is confused
   about the contract, and forms says so instead of dropping it silently.

Field configs are validated by ``validate_configs_structured``, which
checks the KNOWN keys of each type. Unknown keys are dropped by the
dataclass parser, so a typo (``max_length`` for ``maxLength``) is a cap
that silently does not exist — :func:`validate_schema` refuses those too.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

#: Reserved schema meta keys. ``logic`` is deliberately absent-by-default:
#: conditional branching is not in v1, and reserving the key keeps adding
#: it later additive.
META_KEYS = ("title", "description", "confirmation_text", "submit_label")


@dataclass(frozen=True)
class FieldError:
    """One per-field refusal, in the shape the HTTP layer serializes."""

    field: str
    code: str
    message: str
    params: Dict[str, Any]


class SchemaInvalid(Exception):
    """A draft schema that may not be published. Carries per-field detail."""

    def __init__(self, error_key: str, params: Optional[dict] = None,
                 field_errors: Optional[List[FieldError]] = None):
        super().__init__(error_key)
        self.error_key = error_key
        self.params = params or {}
        self.field_errors = field_errors or []


def normalize_schema(raw: Any) -> dict:
    """Coerce an authored schema into the stored shape.

    Accepts the full envelope or a bare field list; anything else is a
    schema error rather than a 500 three layers down.
    """
    from .errors import ERR_400_INVALID_SCHEMA

    if isinstance(raw, list):
        raw = {"fields": raw}
    if not isinstance(raw, dict):
        raise SchemaInvalid(ERR_400_INVALID_SCHEMA)
    fields = raw.get("fields")
    if not isinstance(fields, list):
        raise SchemaInvalid(ERR_400_INVALID_SCHEMA)
    meta = raw.get("meta") or {}
    if not isinstance(meta, dict):
        raise SchemaInvalid(ERR_400_INVALID_SCHEMA)
    normalized_fields = []
    for entry in fields:
        if not isinstance(entry, dict):
            raise SchemaInvalid(ERR_400_INVALID_SCHEMA)
        normalized_fields.append(entry)
    return {"fields": normalized_fields, "meta": meta}


def schema_fields(schema: Any) -> List[dict]:
    """The field-def list of a stored schema (never raises on a stored row)."""
    if isinstance(schema, dict):
        fields = schema.get("fields")
        if isinstance(fields, list):
            return [f for f in fields if isinstance(f, dict)]
    return []


def schema_meta(schema: Any) -> dict:
    if isinstance(schema, dict) and isinstance(schema.get("meta"), dict):
        return schema["meta"]
    return {}


def validate_schema(schema: dict, *, allowed_kinds, max_fields: int) -> None:
    """Refuse a draft that may not become a published version.

    Order matters: caps and the kind allowlist first (cheap, and they are
    the security-relevant gates), per-field config validity last.
    """
    from stapel_attributes.validation import validate_configs_structured

    from .errors import (
        ERR_400_DUPLICATE_SLUG,
        ERR_400_EMPTY_SCHEMA,
        ERR_400_INVALID_SCHEMA,
        ERR_400_KIND_NOT_ALLOWED,
        ERR_400_TOO_MANY_FIELDS,
    )

    fields = schema_fields(schema)
    if not fields:
        raise SchemaInvalid(ERR_400_EMPTY_SCHEMA)
    if len(fields) > max_fields:
        raise SchemaInvalid(ERR_400_TOO_MANY_FIELDS, {"limit": max_fields})

    seen = set()
    for entry in fields:
        slug = entry.get("slug")
        if not slug or not isinstance(slug, str):
            raise SchemaInvalid(ERR_400_INVALID_SCHEMA)
        if slug in seen:
            raise SchemaInvalid(ERR_400_DUPLICATE_SLUG, {"slug": slug})
        seen.add(slug)
        config = entry.get("config")
        if not isinstance(config, dict):
            raise SchemaInvalid(ERR_400_INVALID_SCHEMA, {"slug": slug})
        kind = config.get("type")
        if kind not in allowed_kinds:
            raise SchemaInvalid(ERR_400_KIND_NOT_ALLOWED, {"kind": kind, "slug": slug})
        unknown = _unknown_config_keys(kind, config)
        if unknown:
            # A dropped key is a constraint that silently does not exist —
            # the failure mode is a form that looks capped and is not.
            raise SchemaInvalid(
                ERR_400_INVALID_SCHEMA, {"slug": slug, "key": sorted(unknown)[0]}
            )

    result = validate_configs_structured(fields)
    if not result.valid:
        raise SchemaInvalid(
            ERR_400_INVALID_SCHEMA, field_errors=_field_errors(result)
        )


def _unknown_config_keys(kind: str, config: dict) -> set:
    """Config keys the type's dataclass would drop on the floor."""
    from dataclasses import fields as dataclass_fields

    from stapel_attributes.registry import get_feature_type

    try:
        feature_type = get_feature_type(kind)
    except (ValueError, KeyError):
        return set()
    known = {f.name for f in dataclass_fields(feature_type.config_class)}
    return set(config) - known


def validate_answers(schema: dict, answers: Any):
    """Validate a submitted answer set against a published schema.

    Returns ``(field_errors, unknown_slugs)``; both empty means the payload
    may be normalized. Raises nothing — the caller maps to HTTP.
    """
    from stapel_attributes.validation import validate_dto_structured

    fields = schema_fields(schema)
    if not isinstance(answers, dict):
        return [], None  # signalled by unknown_slugs=None: not an object

    known = {f.get("slug") for f in fields}
    headers = {f.get("slug") for f in fields if (f.get("config") or {}).get("type") == "header"}
    unknown = sorted((set(answers) - known) | (set(answers) & headers))
    if unknown:
        return [], unknown

    result = validate_dto_structured(fields, answers)
    if result.valid:
        return [], []
    return _field_errors(result), []


def to_dao(schema: dict, answers: dict) -> dict:
    """Normalize validated answers into stored DAO shapes.

    Only ever called after :func:`validate_answers` returned clean — the
    engine's normalizer skips rather than refuses.
    """
    from stapel_attributes.validation import normalize_to_dao

    return normalize_to_dao(schema_fields(schema), answers)


def answer_columns(schema: dict) -> List[tuple]:
    """``[(slug, label)]`` for review/export, in schema order.

    Headers are section captions rather than questions and get no column.
    """
    columns = []
    for entry in schema_fields(schema):
        config = entry.get("config") or {}
        if config.get("type") == "header":
            continue
        slug = entry.get("slug")
        columns.append((slug, entry.get("name") or slug))
    return columns


def _field_errors(result) -> List[FieldError]:
    errors = []
    for row in result.results:
        if getattr(row.status, "value", row.status) == "ok":
            continue
        params = dict(row.params or {})
        # The fleet's frontend reads params.field to route an error onto a
        # control; the attributes engine names the same thing `slug`.
        params.setdefault("field", row.slug)
        if row.ref_value is not None:
            params.setdefault("ref_value", row.ref_value)
        errors.append(
            FieldError(
                field=row.slug,
                code=row.localizable_error or "error.400.feature_invalid_type",
                message=row.message or "",
                params=params,
            )
        )
    return errors


__all__ = [
    "META_KEYS",
    "FieldError",
    "SchemaInvalid",
    "normalize_schema",
    "schema_fields",
    "schema_meta",
    "validate_schema",
    "validate_answers",
    "to_dao",
    "answer_columns",
]
