"""DRF views for stapel-forms.

Two surfaces with opposite postures live in this file, and the split is the
point:

- the **public** pair (``/public/<public_id>/`` and its submissions) is
  ``AllowAny``, declares ``stapel_anonymous_access = ANONYMOUS_ALLOWED``,
  answers with a dedicated envelope, and stands on the abuse ladder
  (throttle → size gate → captcha → caps → cooldown, spec §5.2). Its
  error vocabulary is uniform on purpose: unknown / deleted / draft are
  one byte-identical 404;
- the **admin** surface is ``IsNotAnonymousUser`` + ``authorize()`` on
  every request, scoped by ``workspace_id``.

Presenter-canonical (§55): a view resolves its presenter through
``get_presenter`` and returns ``StapelResponse(Serializer(presenter.present(
...)))`` — it never instantiates a ``dto.py`` dataclass itself (SWAP002)
and never imports the concrete presenter class (SWAP001).
"""
from __future__ import annotations

import functools

from django.http import StreamingHttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from stapel_core.django.api.errors import StapelErrorResponse, StapelResponse
from stapel_core.django.api.permissions import ANONYMOUS_ALLOWED, IsNotAnonymousUser
from stapel_core.django.captcha import captcha_protected

from . import services
from .authz import DENY, UNAVAILABLE, Principal, authorize
from .conf import forms_settings
from .errors import (
    ERR_403_FORBIDDEN,
    ERR_413_BODY_TOO_LARGE,
    ERR_503_WORKSPACES,
)
from .export import csv_rows, export_filename
from .presenters import (
    get_form_presenter,
    get_submission_presenter,
    get_version_presenter,
    present_field_kinds,
    present_public_form,
    present_publish_result,
    present_resend_result,
    present_submit_result,
)
from .serializers import (
    DraftSerializer,
    FieldKindsSerializer,
    FormCreateSerializer,
    FormListQuerySerializer,
    FormPatchSerializer,
    FormSerializer,
    FormVersionSerializer,
    PublicFormSerializer,
    PublishResultSerializer,
    ResendResultSerializer,
    ResendSerializer,
    StateSerializer,
    SubmissionListQuerySerializer,
    SubmissionSerializer,
    SubmitResultSerializer,
    SubmitSerializer,
    WorkspaceQuerySerializer,
)


class SerializerSeamMixin:
    """Overridable serializer seam for every stapel-forms APIView.

    Host projects swap the request/response serializer of any view by
    subclassing and setting ``request_serializer_class`` /
    ``response_serializer_class`` — no need to rewrite the method bodies.
    """

    request_serializer_class = None
    response_serializer_class = None

    def get_request_serializer_class(self):
        return self.request_serializer_class

    def get_response_serializer_class(self):
        return self.response_serializer_class


class TokenPathNoLogMixin:
    """Keep the public handle out of the logs.

    Replicated from stapel-workspaces (``views.TokenPathNoLogMixin``, the
    invitation flow) — it is not in stapel-core yet, and upstreaming it
    into ``stapel_core.django.api`` is a separate one-file core PR. Django's
    ``log_response`` writes ``request.path`` for every 4xx/5xx, which would
    persist the public_id in plaintext logs on every 404 probe or throttle
    429; the documented ``_has_been_logged`` flag suppresses exactly that.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code >= 400:
            response._has_been_logged = True
        return response


class SubmitThrottle(ScopedRateThrottle):
    """Per-IP ceiling on the anonymous submit path.

    DRF resolves scoped rates from the global ``DEFAULT_THROTTLE_RATES``
    setting, which a library cannot own — the rate comes from the module
    namespace instead (the stapel-workspaces / stapel-geo canon). ``None``
    disables it, which is a host's conscious act.
    """

    scope = "forms-submit"

    def get_rate(self):
        return forms_settings.SUBMIT_THROTTLE


class PublicSchemaThrottle(ScopedRateThrottle):
    """Enumeration backstop on the anonymous schema fetch."""

    scope = "forms-public-schema"

    def get_rate(self):
        return forms_settings.PUBLIC_SCHEMA_THROTTLE


def _maps_forms_errors(method):
    """Translate service refusals into the unified error envelope."""

    @functools.wraps(method)
    def wrapper(self, request, *args, **kwargs):
        try:
            return method(self, request, *args, **kwargs)
        except services.FormsError as exc:
            params = dict(exc.params)
            if exc.field_errors:
                params["fields"] = [
                    {"field": fe.field, "code": fe.code, "params": fe.params}
                    for fe in exc.field_errors
                ]
            return StapelErrorResponse(exc.status, exc.error_key, params)

    return wrapper


def _access_error(request, workspace_id, *actions):
    """authorize() each required action; an error response or None.
    deny -> 403, unavailable -> 503 (never 403-on-outage)."""
    principal = Principal.from_request(request)
    for action in actions:
        verdict = authorize(workspace_id=workspace_id, principal=principal, action=action)
        if verdict == DENY:
            return StapelErrorResponse(403, ERR_403_FORBIDDEN)
        if verdict == UNAVAILABLE:
            return StapelErrorResponse(503, ERR_503_WORKSPACES)
    return None


def _acting_user(request):
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


def _client_meta(request):
    """Respondent forensics — collected only where the host asked for it."""
    if not forms_settings.STORE_CLIENT_META:
        return None
    from stapel_core.netintel import client_ip

    return {
        "ip": client_ip(request),
        "ua": request.META.get("HTTP_USER_AGENT", "")[:512],
    }


_WORKSPACE_PARAM = OpenApiParameter(
    name="workspace_id", type=str, location=OpenApiParameter.QUERY, required=True
)


# ─────────────────────────────────────────────────────────────────────
# Public surface
# ─────────────────────────────────────────────────────────────────────


@extend_schema(tags=["Forms / public"])
class PublicFormView(TokenPathNoLogMixin, SerializerSeamMixin, APIView):
    """Fetch a form's active schema by its public handle."""

    permission_classes = [permissions.AllowAny]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    throttle_classes = [PublicSchemaThrottle]
    throttle_scope = "forms-public-schema"
    response_serializer_class = PublicFormSerializer

    @extend_schema(responses={200: PublicFormSerializer})
    @_maps_forms_errors
    def get(self, request, public_id):
        form = services.resolve_public(public_id)
        return StapelResponse(
            self.get_response_serializer_class()(present_public_form(form)).data
        )


@extend_schema(tags=["Forms / public"])
class PublicSubmitView(TokenPathNoLogMixin, SerializerSeamMixin, APIView):
    """Answer a form. The only public write in this module."""

    permission_classes = [permissions.AllowAny]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    throttle_classes = [SubmitThrottle]
    throttle_scope = "forms-submit"
    request_serializer_class = SubmitSerializer
    response_serializer_class = SubmitResultSerializer

    @extend_schema(request=SubmitSerializer, responses={201: SubmitResultSerializer})
    @captcha_protected(action="forms.submit")
    @_maps_forms_errors
    def post(self, request, public_id):
        # Size gate BEFORE the parse: a hostile body must not reach the
        # JSON parser at all. DRF has already read the stream by the time a
        # serializer runs, so Content-Length is the honest check here, and
        # DATA_UPLOAD_MAX_MEMORY_SIZE remains the host's outer bound.
        limit = int(forms_settings.MAX_SUBMISSION_BYTES or 0)
        declared = request.META.get("CONTENT_LENGTH") or 0
        try:
            declared = int(declared)
        except (TypeError, ValueError):
            declared = 0
        if limit and declared > limit:
            return StapelErrorResponse(413, ERR_413_BODY_TOO_LARGE, {"limit": limit})

        form = services.resolve_public(public_id)
        body = self.get_request_serializer_class()(data=request.data)
        body.is_valid(raise_exception=True)
        user = _acting_user(request)
        services.submit(
            form,
            answers=body.validated_data["answers"],
            version_id=body.validated_data.get("version_id"),
            user_id=getattr(user, "pk", None),
            client_meta=_client_meta(request),
        )
        return StapelResponse(
            self.get_response_serializer_class()(present_submit_result(form)).data,
            status=201,
        )


# ─────────────────────────────────────────────────────────────────────
# Admin surface — forms
# ─────────────────────────────────────────────────────────────────────


@extend_schema(tags=["Forms"])
class FormListCreateView(SerializerSeamMixin, APIView):
    """List the workspace's forms, or create one."""

    permission_classes = [IsNotAnonymousUser]
    request_serializer_class = FormCreateSerializer
    response_serializer_class = FormSerializer

    @extend_schema(
        parameters=[
            _WORKSPACE_PARAM,
            OpenApiParameter(
                name="state", type=str, location=OpenApiParameter.QUERY, required=False
            ),
        ],
        responses={200: FormSerializer(many=True)},
    )
    @_maps_forms_errors
    def get(self, request):
        query = FormListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        workspace_id = query.validated_data["workspace_id"]
        denied = _access_error(request, workspace_id, "view")
        if denied:
            return denied
        rows = services.list_forms(workspace_id, state=query.validated_data.get("state"))
        presenter = get_form_presenter()
        return StapelResponse(
            self.get_response_serializer_class()(
                [presenter.present(row) for row in rows], many=True
            ).data
        )

    @extend_schema(request=FormCreateSerializer, responses={201: FormSerializer})
    @_maps_forms_errors
    def post(self, request):
        body = self.get_request_serializer_class()(data=request.data)
        body.is_valid(raise_exception=True)
        workspace_id = body.validated_data["workspace_id"]
        denied = _access_error(request, workspace_id, "manage")
        if denied:
            return denied
        form = services.create_form(
            workspace_id=workspace_id,
            title=body.validated_data["title"],
            user=_acting_user(request),
            settings=body.validated_data.get("settings"),
            draft_schema=body.validated_data.get("draft_schema"),
        )
        return StapelResponse(
            self.get_response_serializer_class()(get_form_presenter().present(form)).data,
            status=201,
        )


@extend_schema(tags=["Forms"])
class FormDetailView(SerializerSeamMixin, APIView):
    """Read, rename or soft-delete one form."""

    permission_classes = [IsNotAnonymousUser]
    request_serializer_class = FormPatchSerializer
    response_serializer_class = FormSerializer

    @extend_schema(parameters=[_WORKSPACE_PARAM], responses={200: FormSerializer})
    @_maps_forms_errors
    def get(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "view")
        if denied:
            return denied
        return StapelResponse(
            self.get_response_serializer_class()(get_form_presenter().present(form)).data
        )

    @extend_schema(
        parameters=[_WORKSPACE_PARAM],
        request=FormPatchSerializer,
        responses={200: FormSerializer},
    )
    @_maps_forms_errors
    def patch(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "manage")
        if denied:
            return denied
        body = self.get_request_serializer_class()(data=request.data)
        body.is_valid(raise_exception=True)
        form = services.update_form(
            form,
            title=body.validated_data.get("title"),
            settings=body.validated_data.get("settings"),
        )
        return StapelResponse(
            self.get_response_serializer_class()(get_form_presenter().present(form)).data
        )

    @extend_schema(parameters=[_WORKSPACE_PARAM], responses={204: None})
    @_maps_forms_errors
    def delete(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "manage")
        if denied:
            return denied
        services.delete_form(form)
        return StapelResponse(status=204)


@extend_schema(tags=["Forms"])
class FormDraftView(SerializerSeamMixin, APIView):
    """Replace the builder's scratchpad."""

    permission_classes = [IsNotAnonymousUser]
    request_serializer_class = DraftSerializer
    response_serializer_class = FormSerializer

    @extend_schema(
        parameters=[_WORKSPACE_PARAM], request=DraftSerializer, responses={200: FormSerializer}
    )
    @_maps_forms_errors
    def put(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "manage")
        if denied:
            return denied
        body = self.get_request_serializer_class()(data=request.data)
        body.is_valid(raise_exception=True)
        form = services.save_draft(form, body.validated_data["schema"])
        return StapelResponse(
            self.get_response_serializer_class()(get_form_presenter().present(form)).data
        )


@extend_schema(tags=["Forms"])
class FormPublishView(SerializerSeamMixin, APIView):
    """Freeze the draft as the next immutable version."""

    permission_classes = [IsNotAnonymousUser]
    response_serializer_class = PublishResultSerializer

    @extend_schema(
        parameters=[_WORKSPACE_PARAM], request=None, responses={201: PublishResultSerializer}
    )
    @_maps_forms_errors
    def post(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "manage")
        if denied:
            return denied
        version = services.publish(form, user=_acting_user(request))
        return StapelResponse(
            self.get_response_serializer_class()(present_publish_result(version)).data,
            status=201,
        )


@extend_schema(tags=["Forms"])
class FormStateView(SerializerSeamMixin, APIView):
    """Open or close the form for submissions."""

    permission_classes = [IsNotAnonymousUser]
    request_serializer_class = StateSerializer
    response_serializer_class = FormSerializer

    @extend_schema(
        parameters=[_WORKSPACE_PARAM], request=StateSerializer, responses={200: FormSerializer}
    )
    @_maps_forms_errors
    def post(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "manage")
        if denied:
            return denied
        body = self.get_request_serializer_class()(data=request.data)
        body.is_valid(raise_exception=True)
        form = services.set_state(form, body.validated_data["state"])
        return StapelResponse(
            self.get_response_serializer_class()(get_form_presenter().present(form)).data
        )


@extend_schema(tags=["Forms"])
class FormRotateLinkView(SerializerSeamMixin, APIView):
    """Mint a new public handle, invalidating every distributed link."""

    permission_classes = [IsNotAnonymousUser]
    response_serializer_class = FormSerializer

    @extend_schema(parameters=[_WORKSPACE_PARAM], request=None, responses={200: FormSerializer})
    @_maps_forms_errors
    def post(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "manage")
        if denied:
            return denied
        form = services.rotate_link(form)
        return StapelResponse(
            self.get_response_serializer_class()(get_form_presenter().present(form)).data
        )


@extend_schema(tags=["Forms"])
class FieldKindsView(SerializerSeamMixin, APIView):
    """The field kinds a form may be built from, with their config forms.

    The builder is data-driven off stapel-attributes' ``config_form()``
    declarations (spec §8) — before this route existed the only way to read
    them was to mirror them in the client, which is a table that drifts
    silently. Serving the registry makes the declaration the single source
    of truth again: a type registered through ``EXTRA_TYPES`` shows up in
    the builder with no client release.

    Nothing here is per-form, but it is not public either: the catalogue
    tells a reader which kinds a deployment registered, including host types
    whose slugs are internal vocabulary. It carries the same capability as
    form management (``forms.manage``) — a principal who cannot build a
    form has no use for the builder's dictionary.
    """

    permission_classes = [IsNotAnonymousUser]
    response_serializer_class = FieldKindsSerializer

    @extend_schema(parameters=[_WORKSPACE_PARAM], responses={200: FieldKindsSerializer})
    @_maps_forms_errors
    def get(self, request):
        query = WorkspaceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        denied = _access_error(request, query.validated_data["workspace_id"], "manage")
        if denied:
            return denied
        return StapelResponse(
            self.get_response_serializer_class()(
                present_field_kinds(allowed_kinds=forms_settings.FIELD_KINDS)
            ).data
        )


@extend_schema(tags=["Forms"])
class FormVersionListView(SerializerSeamMixin, APIView):
    """The form's published versions, newest first."""

    permission_classes = [IsNotAnonymousUser]
    response_serializer_class = FormVersionSerializer

    @extend_schema(
        parameters=[_WORKSPACE_PARAM], responses={200: FormVersionSerializer(many=True)}
    )
    @_maps_forms_errors
    def get(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "view")
        if denied:
            return denied
        presenter = get_version_presenter()
        rows = form.versions.all()
        return StapelResponse(
            self.get_response_serializer_class()(
                [presenter.present(row) for row in rows], many=True
            ).data
        )


# ─────────────────────────────────────────────────────────────────────
# Admin surface — responses
# ─────────────────────────────────────────────────────────────────────


@extend_schema(tags=["Forms / responses"])
class FormSubmissionListView(SerializerSeamMixin, APIView):
    """Keyset page of a form's responses, newest first."""

    permission_classes = [IsNotAnonymousUser]
    response_serializer_class = SubmissionSerializer

    @extend_schema(
        parameters=[
            _WORKSPACE_PARAM,
            OpenApiParameter(
                name="before", type=str, location=OpenApiParameter.QUERY, required=False,
                description="Keyset cursor: return responses submitted strictly before this timestamp.",
            ),
            OpenApiParameter(
                name="limit", type=int, location=OpenApiParameter.QUERY, required=False
            ),
            OpenApiParameter(
                name="version", type=int, location=OpenApiParameter.QUERY, required=False,
                description="Restrict to responses answering this schema version.",
            ),
        ],
        responses={200: SubmissionSerializer(many=True)},
    )
    @_maps_forms_errors
    def get(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "responses.view")
        if denied:
            return denied
        query = SubmissionListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = services.list_submissions(
            form,
            before=query.validated_data.get("before"),
            limit=query.validated_data.get("limit"),
            version=query.validated_data.get("version"),
        )
        presenter = get_submission_presenter()
        return StapelResponse(
            self.get_response_serializer_class()(
                [presenter.present(row) for row in rows], many=True
            ).data
        )


@extend_schema(tags=["Forms / responses"])
class SubmissionDetailView(SerializerSeamMixin, APIView):
    """Read or delete one response."""

    permission_classes = [IsNotAnonymousUser]
    response_serializer_class = SubmissionSerializer

    @extend_schema(parameters=[_WORKSPACE_PARAM], responses={200: SubmissionSerializer})
    @_maps_forms_errors
    def get(self, request, submission_id):
        submission, denied = _scoped_submission(request, submission_id, "responses.view")
        if denied:
            return denied
        return StapelResponse(
            self.get_response_serializer_class()(
                get_submission_presenter().present(submission)
            ).data
        )

    @extend_schema(parameters=[_WORKSPACE_PARAM], responses={204: None})
    @_maps_forms_errors
    def delete(self, request, submission_id):
        submission, denied = _scoped_submission(request, submission_id, "responses.manage")
        if denied:
            return denied
        services.delete_submission(submission)
        return StapelResponse(status=204)


@extend_schema(tags=["Forms / responses"])
class SubmissionResendView(SerializerSeamMixin, APIView):
    """Re-deliver one response to the form's notify targets.

    Admin-initiated and therefore cooldown-independent: the auto-notify
    cooldown suppresses a respondent-driven flood, and an operator asking
    for one letter is not one.
    """

    permission_classes = [IsNotAnonymousUser]
    request_serializer_class = ResendSerializer
    response_serializer_class = ResendResultSerializer

    @extend_schema(
        parameters=[_WORKSPACE_PARAM],
        request=ResendSerializer,
        responses={200: ResendResultSerializer},
    )
    @_maps_forms_errors
    def post(self, request, submission_id):
        submission, denied = _scoped_submission(request, submission_id, "responses.manage")
        if denied:
            return denied
        body = self.get_request_serializer_class()(data=request.data or {})
        body.is_valid(raise_exception=True)
        sent = services.resend_submission(
            submission,
            recipients=body.validated_data.get("recipients"),
            telegram_chat_ids=body.validated_data.get("telegram_chat_ids"),
        )
        return StapelResponse(
            self.get_response_serializer_class()(present_resend_result(sent)).data
        )


@extend_schema(tags=["Forms / responses"])
class SubmissionExportView(APIView):
    """Stream responses as CSV.

    Streamed and page-capped rather than materialized: an export is the one
    read whose size is chosen by whoever filled the form in. The
    formula-injection escape lives in ``export.py`` so every consumer of
    the CSV inherits it.
    """

    permission_classes = [IsNotAnonymousUser]

    @extend_schema(
        parameters=[
            _WORKSPACE_PARAM,
            OpenApiParameter(
                name="version", type=int, location=OpenApiParameter.QUERY, required=False,
                description="Export one schema version's responses (its columns are the header row).",
            ),
            OpenApiParameter(
                name="before", type=str, location=OpenApiParameter.QUERY, required=False,
                description="Keyset continuation, echoed back in the X-Forms-Next-Before header.",
            ),
        ],
        responses={(200, "text/csv"): None},
    )
    @_maps_forms_errors
    def get(self, request, form_id):
        form, denied = _scoped_form(request, form_id, "responses.view")
        if denied:
            return denied
        query = SubmissionListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows, next_before = csv_rows(
            form,
            version=query.validated_data.get("version"),
            before=query.validated_data.get("before"),
        )
        response = StreamingHttpResponse(rows, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{export_filename(form)}"'
        if next_before:
            # The continuation cursor rides a header, not the body: the body
            # is a CSV file, and a trailing JSON cursor inside it would end
            # up as a row in somebody's spreadsheet.
            response["X-Forms-Next-Before"] = next_before
        return response


# ─────────────────────────────────────────────────────────────────────
# Scoping helpers
# ─────────────────────────────────────────────────────────────────────


def _scoped_form(request, form_id, action):
    query = WorkspaceQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    workspace_id = query.validated_data["workspace_id"]
    denied = _access_error(request, workspace_id, action)
    if denied:
        return None, denied
    return services.get_form(form_id, workspace_id), None


def _scoped_submission(request, submission_id, action):
    query = WorkspaceQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    workspace_id = query.validated_data["workspace_id"]
    denied = _access_error(request, workspace_id, action)
    if denied:
        return None, denied
    return services.get_submission(submission_id, workspace_id), None


__all__ = [
    "SerializerSeamMixin",
    "TokenPathNoLogMixin",
    "SubmitThrottle",
    "PublicSchemaThrottle",
    "PublicFormView",
    "PublicSubmitView",
    "FormListCreateView",
    "FormDetailView",
    "FormDraftView",
    "FormPublishView",
    "FormStateView",
    "FormRotateLinkView",
    "FieldKindsView",
    "FormVersionListView",
    "FormSubmissionListView",
    "SubmissionDetailView",
    "SubmissionResendView",
    "SubmissionExportView",
]
