"""CSV export of responses — streamed, page-capped, injection-safe.

Two properties this module exists to guarantee:

1. **Streamed and page-capped.** An export is the one read whose size is
   chosen by whoever filled the form in, so it is never materialized: rows
   are generated lazily and a request returns at most ``EXPORT_PAGE_SIZE``
   of them plus a keyset cursor for the next call.
2. **Formula injection is escaped server-side.** Response review is where
   hostile content meets a spreadsheet: a cell beginning ``= + - @``
   (or a tab/CR, which some spreadsheets strip before parsing) is prefixed
   with an apostrophe. The guard lives here rather than in a UI so every
   consumer of the CSV inherits it, including the ones nobody has written.

Columns come from ONE schema version — which is exactly what the version FK
makes possible. Without it "the columns of this export" would be a
best-effort union over mutated schemas.
"""
from __future__ import annotations

import csv
import io

#: Leading characters a spreadsheet may treat as the start of a formula.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def format_value(value) -> str:
    """Render a stored answer value as a readable string, without escaping.

    Split out of :func:`escape_cell` in 0.6.0 because the CSV was not the
    only consumer any more: the admin's responses table and the
    notification report need the same rendering and must NOT get the
    spreadsheet guard — a leading apostrophe is protection in a cell and a
    typo in an email. Keeping one renderer is what stops "true"/"True"/
    "Yes" drifting apart across three surfaces.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={format_value(v)}" for k, v in value.items())
    return str(value)


def escape_cell(value) -> str:
    """Render a stored answer value as a CSV-safe string.

    The guard recurses on purpose. A list renders as ``a, =b`` and only the
    OUTER string starts with ``a`` — escaping just that would hand the
    spreadsheet ``=b`` intact, which some parsers evaluate after splitting
    on the comma. So every element is escaped as it is rendered, not the
    joined result. (`format_value` deliberately does not do this: an
    apostrophe is protection in a cell and a typo in an email.)
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return format_value(value)
    if isinstance(value, (list, tuple)):
        text = ", ".join(escape_cell(v) for v in value)
    elif isinstance(value, dict):
        text = ", ".join(f"{k}={escape_cell(v)}" for k, v in value.items())
    else:
        text = str(value)
    if text[:1] in _FORMULA_LEAD:
        return "'" + text
    return text


def export_filename(form) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in form.title)[:64]
    return f"{safe or 'form'}-responses.csv"


def csv_rows(form, *, version=None, before=None):
    """``(row_iterator, next_before)`` for one export page.

    The cursor is resolved eagerly (the page is queried once) so the caller
    can put it in a header before streaming starts; the ROWS stay lazy.
    """
    from .conf import forms_settings
    from .models import FormVersion, Submission
    from .schema import answer_columns

    target = None
    if version is not None:
        target = FormVersion.objects.filter(form=form, version=version).first()
    if target is None:
        target = form.active_version or form.versions.first()
    if target is None:
        return iter([]), None

    columns = answer_columns(target.schema)
    page_size = int(forms_settings.EXPORT_PAGE_SIZE)

    qs = Submission.objects.filter(form=form, version=target)
    if before is not None:
        qs = qs.filter(submitted_at__lt=before)
    rows = list(qs.order_by("-submitted_at", "-id")[:page_size])
    # The cursor is handed back in a header for the caller to put straight
    # into `?before=`, so it is emitted Z-suffixed rather than `+00:00`:
    # a bare `+` in a query string decodes to a space and the continuation
    # silently becomes a 400 on the second page.
    next_before = (
        rows[-1].submitted_at.isoformat().replace("+00:00", "Z")
        if len(rows) == page_size
        else None
    )

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        def flush():
            data = buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            return data

        writer.writerow(
            ["submission_id", "submitted_at", "submitted_by", "version"]
            + [label for _slug, label in columns]
        )
        yield flush()
        for row in rows:
            answers = row.answers or {}
            cells = []
            for slug, _label in columns:
                dao = answers.get(slug)
                cells.append(
                    escape_cell(dao.get("value") if isinstance(dao, dict) else dao)
                )
            writer.writerow(
                [
                    str(row.id),
                    row.submitted_at.isoformat(),
                    str(row.submitted_by) if row.submitted_by else "",
                    target.version,
                ]
                + cells
            )
            yield flush()

    return generate(), next_before


__all__ = ["escape_cell", "export_filename", "csv_rows"]
