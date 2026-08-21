"""v1 URL set — paths here are relative to the ``api/v1/`` mount contributed
by the root ``urls.py`` (api-versioning.md §2).

The ``public/`` prefix is not decoration: it is the one part of this URL
space a reverse proxy can be pointed at without also exposing the admin
surface, and it makes "which routes are anonymous" answerable by reading
the file rather than by auditing permission classes.
"""
from typing import NamedTuple

from django.urls import path

from .errors import FormsErrorKeysView
from .views import (
    FieldKindsView,
    FormDetailView,
    FormDraftView,
    FormListCreateView,
    FormPublishView,
    FormRotateLinkView,
    FormStateView,
    FormSubmissionListView,
    FormVersionListView,
    PublicFormView,
    PublicSubmitView,
    SubmissionDetailView,
    SubmissionExportView,
    SubmissionResendView,
)

urlpatterns = [
    # Public (anonymous) surface — exactly two routes.
    path("public/<str:public_id>/", PublicFormView.as_view(), name="forms-public-form"),
    path(
        "public/<str:public_id>/submissions/",
        PublicSubmitView.as_view(),
        name="forms-public-submit",
    ),
    # Admin surface.
    #
    # The builder's dictionary. Workspace-scoped like every other admin
    # route (the capability answer is per workspace) even though the
    # catalogue itself is process-wide.
    path("field-kinds", FieldKindsView.as_view(), name="forms-field-kinds"),
    path("forms", FormListCreateView.as_view(), name="forms-forms"),
    path("forms/<uuid:form_id>", FormDetailView.as_view(), name="forms-form-detail"),
    path("forms/<uuid:form_id>/draft", FormDraftView.as_view(), name="forms-form-draft"),
    path("forms/<uuid:form_id>/publish", FormPublishView.as_view(), name="forms-form-publish"),
    path("forms/<uuid:form_id>/state", FormStateView.as_view(), name="forms-form-state"),
    path(
        "forms/<uuid:form_id>/rotate-link",
        FormRotateLinkView.as_view(),
        name="forms-form-rotate-link",
    ),
    path("forms/<uuid:form_id>/versions", FormVersionListView.as_view(), name="forms-form-versions"),
    path(
        "forms/<uuid:form_id>/submissions",
        FormSubmissionListView.as_view(),
        name="forms-form-submissions",
    ),
    path(
        "forms/<uuid:form_id>/submissions/export",
        SubmissionExportView.as_view(),
        name="forms-form-submissions-export",
    ),
    path("submissions/<uuid:submission_id>", SubmissionDetailView.as_view(), name="forms-submission"),
    path(
        "submissions/<uuid:submission_id>/resend",
        SubmissionResendView.as_view(),
        name="forms-submission-resend",
    ),
    # The listing the stapel-translate error collector reads.
    path("error-keys/", FormsErrorKeysView.as_view(), name="forms-error-keys"),
]


class GateEntry(NamedTuple):
    """One gated URL block (capability-config.md §2 p.2). ``flags`` compose
    with OR; empty flags = always on."""

    name: str
    flags: tuple
    patterns: tuple


#: forms has no per-method config gates: the public/admin split is a
#: permission decision, not a mountable one, and turning the public routes
#: off by configuration would give a host a way to break every distributed
#: link without changing a form's state. Declared as a registry entry
#: anyway so the capabilities.json emitter has a uniform mechanism.
GATE_REGISTRY: dict = {
    "forms.api": GateEntry("forms.api", (), tuple(urlpatterns)),
}
