"""Django admin for stapel-forms — the operator's working surface.

Through 0.5.0 this file was a deliberate peephole: three read-only
``ModelAdmin``s, on the argument that workspace admins are not Django staff
and reach forms through the capability-gated REST surface instead. That
argument holds for a deployment whose form authors ARE workspace members.
It does not hold for the shape most hosts actually run first — a public
form on a marketing site, answered by strangers, read by staff. There is no
workspace member to be; there is an operator, a table, and (before this
release) a ``JSONField`` rendered as its ``repr``.

So the peephole became a surface, with the trust boundary unchanged:

**This is the STAFF door.** It is gated by Django model permissions
computed from the ``@access`` declaration by ``stapel_core.access``
(``Submission`` is ``@access.sensitive`` — view MID, mutate HIGH). It asks
for **no workspace capability**, deliberately: the capability layer in
``authz.py`` gates the REST product surface, and requiring a workspace
membership here would lock a staff reviewer out of exactly the deployment
that needs this most — a public form nobody is a member of. Two doors,
still independent, each shut by default.

What the surface adds over a raw model view, and why each is a mechanism
rather than a decoration:

- **the answers table** is driven by the schema (``present_response_table``),
  so columns are labelled questions in the form's current order and every
  stored answer has a column to land in;
- **the builder** publishes a new version of the SAME form. Form identity
  is what a host embedded (``public_id`` lives in someone's HTML), so an
  edit may never mint a new form, and the page says so;
- **versions are not a top-level object.** ``FormVersion`` stays registered
  (its change page is reachable and is the audit trail) but is hidden from
  the app index, and in the table it is one subtle marker on the row where
  the schema changed. The model split is right; making an operator reason
  about it before they can read a response is not.
"""
from __future__ import annotations

import json

from django.contrib import admin, messages
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import Form, FormVersion, Submission

#: Rows per admin page. Independent of ``MAX_PAGE_SIZE`` (the API's keyset
#: cap): this is a rendering choice about a browser table, not a contract
#: with a client.
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


def _parse_moment(raw, *, end_of_day=False):
    """Accept either a date (from ``<input type=date>``) or a timestamp.

    The filter inputs are dates, but a caller pasting an ISO timestamp out
    of the API should not get a silent empty page.

    Two traps, both of which produce a filter that looks like it works:

    - **`parse_date` is tried first.** On Python 3.11+ `parse_datetime`
      delegates to `datetime.fromisoformat`, which happily accepts a bare
      `2026-09-01` and returns midnight — so asking it first would swallow
      every date input and silently ignore `end_of_day`, making an
      inclusive "to" bound exclusive and hiding a whole day of responses.
    - **the result is always made aware.** A naive datetime handed to a
      filter under `USE_TZ` is interpreted in the current zone with a
      warning, not an error, so the boundary quietly moves by the UTC
      offset.
    """
    if not raw:
        return None

    import datetime as dt

    from django.utils import timezone

    day = parse_date(raw)
    if day is not None:
        moment = dt.datetime.combine(day, dt.time.max if end_of_day else dt.time.min)
    else:
        moment = parse_datetime(raw)
        if moment is None:
            return None
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    """The primary object. A form, its responses, and its schema."""

    list_display = ("title", "state", "schema_version", "responses_link", "public_link", "updated_at")
    list_filter = ("state",)
    search_fields = ("id", "title", "workspace_id", "public_id")
    readonly_fields = ("public_id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "state", "public_id")}),
        (_("Notifications and retention"), {"fields": ("settings",)}),
        (_("Advanced"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    # ── list columns ──────────────────────────────────────────────────
    #
    # Note what is NOT here: any answer content. `Form` is `standard`
    # (view=LOW) and `Submission` is `sensitive` (view=MID), so a preview
    # column of "the latest response" would hand respondent PII to staff
    # the mandate does not clear for it. A COUNT is not content.

    @admin.display(description=_("Schema"), ordering="active_version__version")
    def schema_version(self, obj):
        if not obj.active_version_id:
            return format_html('<span style="color:#999">{}</span>', _("not published"))
        return f"v{obj.active_version.version}"

    @admin.display(description=_("Responses"))
    def responses_link(self, obj):
        count = obj.submissions.count()
        return format_html(
            '<a href="{}"><b>{}</b></a>',
            reverse("admin:forms_form_responses", args=[obj.id]),
            count,
        )

    @admin.display(description=_("Public link"))
    def public_link(self, obj):
        return format_html('<code>{}</code>', obj.public_id)

    # ── extra views ───────────────────────────────────────────────────

    def get_urls(self):
        return [
            path(
                "<uuid:form_id>/responses/",
                self.admin_site.admin_view(self.responses_view),
                name="forms_form_responses",
            ),
            path(
                "<uuid:form_id>/publish/",
                self.admin_site.admin_view(self.publish_view),
                name="forms_form_publish",
            ),
        ] + super().get_urls()

    def _submission_admin(self):
        return self.admin_site._registry[Submission]

    def responses_view(self, request, form_id):
        """The answers table.

        Gated on the SUBMISSION's view permission, not the form's: it is
        submissions that are `@access.sensitive`, and gating this on
        `forms.view_form` (LOW) would render respondent PII to staff the
        declaration puts a level above.
        """
        from . import services
        from .presenters import present_response_table
        from .schema import version_history

        if not self._submission_admin().has_view_permission(request):
            return self._denied(request)

        form = Form.objects.filter(id=form_id).first()
        if form is None:
            raise Http404

        since = _parse_moment(request.GET.get("since"))
        until = _parse_moment(request.GET.get("until"), end_of_day=True)
        query = (request.GET.get("q") or "").strip()
        field = (request.GET.get("field") or "").strip() or None
        before = _parse_moment(request.GET.get("before"))
        try:
            pinned = int(request.GET["version"]) if request.GET.get("version") else None
        except (TypeError, ValueError):
            pinned = None
        try:
            per_page = min(int(request.GET.get("per_page") or DEFAULT_PER_PAGE), MAX_PER_PAGE)
        except (TypeError, ValueError):
            per_page = DEFAULT_PER_PAGE

        try:
            # One row over the page size: the cheap "is there a next page"
            # answer that a keyset cursor gives without a COUNT(*), which
            # is the whole reason this survives thousands of rows.
            rows = services.list_submissions(
                form,
                before=before,
                since=since,
                until=until,
                q=query or None,
                field=field,
                version=pinned,
                limit=per_page + 1,
            )
            invalid_field = None
        except services.FormsError as exc:
            rows, invalid_field = [], exc.params.get("field", field)

        has_next = len(rows) > per_page
        rows = rows[:per_page]

        # Default: columns are the union across every version, led by the
        # active schema's order — the reviewer picks a form and gets a
        # table, never a version prompt.
        #
        # Pinned: columns are EXACTLY that version's, which is the case the
        # picker exists for. A field ADDED later can be shown under the
        # current schema as blank for older rows; a field REMOVED later
        # cannot be shown at all, because the current schema no longer
        # knows it. Pinning the version is the only way those answers are
        # readable, which is why the picker is reachable rather than gone.
        versions = list(form.versions.all().order_by("-version"))
        if pinned is not None:
            versions = [v for v in versions if v.version == pinned]
        table = present_response_table(form, rows, versions=versions or None)

        next_url = None
        if has_next and rows:
            params = request.GET.copy()
            params["before"] = rows[-1].submitted_at.isoformat()
            next_url = f"{request.path}?{params.urlencode()}"

        context = {
            **self.admin_site.each_context(request),
            "title": _("Responses — %(form)s") % {"form": form.title},
            "opts": self.model._meta,
            "form_obj": form,
            "columns": table["columns"],
            "rows": table["rows"],
            "has_next": has_next,
            "next_url": next_url,
            "per_page": per_page,
            "filter_since": request.GET.get("since", ""),
            "filter_until": request.GET.get("until", ""),
            "filter_q": request.GET.get("q", ""),
            "filter_field": field or "",
            "invalid_field": invalid_field,
            "field_choices": services.form_answer_slugs(form),
            # The optional picker. Defaults to the current schema (empty
            # selection), lists every version with when it went live, what
            # it changed and how many responses it holds — so an empty
            # version is visibly skippable.
            "history": version_history(form),
            "pinned_version": pinned,
            "can_manage": self._submission_admin().has_delete_permission(request),
        }
        return TemplateResponse(request, "admin/forms/responses.html", context)

    def publish_view(self, request, form_id):
        """Publish the edited schema as the next version of THIS form."""
        from . import services
        from .schema import SchemaInvalid

        form = Form.objects.filter(id=form_id).first()
        if form is None:
            raise Http404
        if not self.has_change_permission(request, form):
            return self._denied(request)
        if request.method != "POST":
            return redirect(reverse("admin:forms_form_change", args=[form.id]))

        try:
            schema = json.loads(request.POST.get("schema") or "{}")
        except ValueError:
            self.message_user(request, _("The schema is not valid JSON."), messages.ERROR)
            return redirect(reverse("admin:forms_form_change", args=[form.id]))

        try:
            services.save_draft(form, schema)
            version = services.publish(form, user=request.user)
        except (SchemaInvalid, services.FormsError) as exc:
            detail = getattr(exc, "error_key", str(exc))
            fields = getattr(exc, "field_errors", None) or []
            if fields:
                detail += " — " + "; ".join(f"{f.field}: {f.message or f.code}" for f in fields)
            self.message_user(
                request,
                _("Nothing was published: %(detail)s") % {"detail": detail},
                messages.ERROR,
            )
            return redirect(reverse("admin:forms_form_change", args=[form.id]))

        self.message_user(
            request,
            _(
                "Published v%(version)s. The public link is unchanged and "
                "older responses stay readable under the schema they answered."
            )
            % {"version": version.version},
            messages.SUCCESS,
        )
        return redirect(reverse("admin:forms_form_change", args=[form.id]))

    def _denied(self, request):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    # ── the builder on the change page ────────────────────────────────

    change_form_template = "admin/forms/change_form.html"

    def render_change_form(self, request, context, *args, **kwargs):
        """Feed the builder, and let stapel-attributes feed its own half.

        ``attributes_probe`` is a real ``ConfigEditorWidget`` rendered with
        no value. Its inline script no-ops (it bails when the config has no
        ``type``), but its ``json_script`` block publishes the declarations,
        the resolved locale and the merged message catalogues — the exact
        payload the shipped editor expects. The builder reads THAT rather
        than assembling its own copy, so this module imports no private
        helper, keeps no second catalogue, and a kind or a translation
        added upstream reaches the builder with no release here.

        This is the same reuse `stapel-categories` gets by putting the
        widget on a `config` field; the builder just needs it for fields
        that do not exist until somebody clicks "add".
        """
        from django.templatetags.static import static
        from stapel_attributes import get_config_editor_widget

        from .conf import forms_settings

        obj = kwargs.get("obj") or context.get("original")
        schema = None
        if obj is not None and obj.pk:
            schema = obj.draft_schema or (
                obj.active_version.schema if obj.active_version_id else None
            )
        context["attributes_probe"] = get_config_editor_widget("config")().render(
            "__stapel_forms_probe", None, attrs={"id": "id___stapel_forms_probe"}
        )
        # A DICT, not `json.dumps(...)`. The template hands this to
        # `json_script`, which serializes it — so pre-dumping would encode it
        # twice and `JSON.parse` in the browser would hand the builder a
        # string, every `payload.x` undefined and the editor silently empty.
        context["builder_payload"] = {
                "schema": schema or {"fields": [], "meta": {}},
                # The same bundle the attributes widget imports. Named from
                # `static()` rather than hardcoded so a hashed-manifest
                # storage resolves it the same way for both mounts.
                "attributesBundle": static("stapel_attributes/attributes-admin.js"),
                "allowedKinds": list(forms_settings.FIELD_KINDS or []),
                "maxFields": int(forms_settings.MAX_FIELDS_PER_FORM),
                "activeVersion": (
                    obj.active_version.version
                    if obj is not None and obj.pk and obj.active_version_id
                    else None
                ),
                "publishUrl": (
                    reverse("admin:forms_form_publish", args=[obj.id])
                    if obj is not None and obj.pk
                    else None
                ),
                "responsesUrl": (
                    reverse("admin:forms_form_responses", args=[obj.id])
                    if obj is not None and obj.pk
                    else None
                ),
        }
        return super().render_change_form(request, context, *args, **kwargs)


@admin.register(FormVersion)
class FormVersionAdmin(_ReadOnlyAdmin):
    """Registered but hidden from the app index.

    The rows are the audit trail of what respondents were asked and must
    stay reachable (a link from a response opens one). What must NOT happen
    — the owner's ruling — is an operator meeting "Form versions" as a
    top-level table they have to reason about before they can read an
    answer. `get_model_perms` returning empty is Django's own idiom for
    exactly that: URLs live, index entry gone.
    """

    list_display = ("form", "version", "published_at")
    search_fields = ("id", "form__id")

    def get_model_perms(self, request):
        return {}


@admin.register(Submission)
class SubmissionAdmin(_ReadOnlyAdmin):
    """One response, rendered against the schema it answered.

    `@access.sensitive` gates this at MID to view and HIGH to delete; the
    class only removes add/change, which are not operations on a response
    at all — a stored answer is what a respondent said, and editing it
    would be forging a record rather than correcting one.
    """

    list_display = ("id", "form", "schema_version", "submitted_at", "submitted_by", "erased_at")
    list_filter = ("form",)
    search_fields = ("id", "form__id", "workspace_id")
    readonly_fields = ("answers_table", "form", "submitted_at", "submitted_by", "erased_at")
    # `answers` and `client_meta` are deliberately excluded: the table below
    # is the same content, readable. Leaving the raw field alongside it
    # re-creates the thing this release removed.
    exclude = ("answers", "client_meta", "version", "workspace_id")

    @admin.display(description=_("Schema"))
    def schema_version(self, obj):
        return f"v{obj.version.version}"

    @admin.display(description=_("Answers"))
    def answers_table(self, obj):
        from django.template.loader import render_to_string

        from .presenters import present_answer_rows

        if obj is None or obj.pk is None:
            return ""
        return mark_safe(
            render_to_string(
                "admin/forms/submission_answers.html",
                {
                    "rows": present_answer_rows(obj),
                    "erased": obj.erased_at is not None,
                    "version": obj.version.version,
                },
            )
        )
