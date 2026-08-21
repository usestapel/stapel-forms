"""i18n error keys of stapel-forms.

Only ``error.<status>.forms_<slug>`` keys are OWNED by this package —
human-readable strings are translations, never literals in responses. The
English registry below is the source; ``translations/errors.<lang>.json``
ships the localized catalogues in the same release (owning keys means
shipping their catalogues).

Per-field answer validation is stapel-attributes' pipeline, so the submit
path returns its ``error.400.feature_*`` family at the TOP level of a
refusal (``services.submit`` re-raises ``field_errors[0].code``). Those
keys are registered — and translated — by stapel-attributes; this module
only makes sure the registration RUNS wherever forms is mounted, so the
emitted ``docs/errors.json`` lists every key this API can actually return.
"""
from stapel_core.django.api.errors import ErrorKeysView, register_service_errors

# stapel-attributes is an embedded (non-app) library: autodiscovery never
# reaches its errors module, so without this import its 12 feature-validation
# keys enter the registry only as a side effect of serializer imports —
# errors.json emission then depends on whether the schema was built first.
# The embedding app forces the registration deterministically. Same line as
# stapel-listings/stapel-categories, which embed the same engine; ownership
# stays with stapel_attributes (register_service_errors infers it from the
# calling package), so nothing here double-owns the keys or their catalogues.
import stapel_attributes.errors

# ── Schema authoring / publish ───────────────────────────────────────
ERR_400_INVALID_SCHEMA = "error.400.forms_invalid_schema"
ERR_400_KIND_NOT_ALLOWED = "error.400.forms_kind_not_allowed"
ERR_400_TOO_MANY_FIELDS = "error.400.forms_too_many_fields"
ERR_400_DUPLICATE_SLUG = "error.400.forms_duplicate_slug"
ERR_400_EMPTY_SCHEMA = "error.400.forms_empty_schema"
ERR_400_NO_DRAFT = "error.400.forms_no_draft"
ERR_400_INVALID_STATE = "error.400.forms_invalid_state"
ERR_400_NOT_PUBLISHED = "error.400.forms_not_published"
ERR_400_TOO_MANY_OPEN_FORMS = "error.400.forms_too_many_open"
ERR_400_INVALID_RETENTION = "error.400.forms_invalid_retention"
ERR_400_NO_RECIPIENTS = "error.400.forms_no_recipients"

# ── Submission ───────────────────────────────────────────────────────
ERR_400_UNKNOWN_FIELD = "error.400.forms_unknown_field"
ERR_400_ANSWERS_NOT_OBJECT = "error.400.forms_answers_not_object"
ERR_403_FORBIDDEN = "error.403.forms_forbidden"
ERR_404_NOT_FOUND = "error.404.forms_not_found"
ERR_404_SUBMISSION_NOT_FOUND = "error.404.forms_submission_not_found"
ERR_409_VERSION_SUPERSEDED = "error.409.forms_version_superseded"
ERR_409_SUBMISSION_CAP = "error.409.forms_submission_cap"
ERR_410_CLOSED = "error.410.forms_closed"
ERR_413_BODY_TOO_LARGE = "error.413.forms_body_too_large"
ERR_503_WORKSPACES = "error.503.forms_workspaces_unavailable"

STAPEL_FORMS_ERRORS = {
    ERR_400_INVALID_SCHEMA: "The form schema is not valid",
    ERR_400_KIND_NOT_ALLOWED: "Field kind {kind} may not be used in a form",
    ERR_400_TOO_MANY_FIELDS: "The form has more fields than the limit allows",
    ERR_400_DUPLICATE_SLUG: "Field slug {slug} appears more than once",
    ERR_400_EMPTY_SCHEMA: "A form must have at least one field to publish",
    ERR_400_NO_DRAFT: "There is no draft to publish",
    ERR_400_INVALID_STATE: "Unknown form state",
    ERR_400_NOT_PUBLISHED: "The form has no published version yet",
    ERR_400_TOO_MANY_OPEN_FORMS: "This workspace already has the maximum number of open forms",
    ERR_400_INVALID_RETENTION: "The retention override may only shorten the module retention period",
    ERR_400_NO_RECIPIENTS: "No notification recipient is configured for this form",
    ERR_400_UNKNOWN_FIELD: "The submission answers a field the form does not have",
    ERR_400_ANSWERS_NOT_OBJECT: "Answers must be an object keyed by field slug",
    ERR_403_FORBIDDEN: "You do not have access to this form",
    ERR_404_NOT_FOUND: "Form not found",
    ERR_404_SUBMISSION_NOT_FOUND: "Submission not found",
    ERR_409_VERSION_SUPERSEDED: "The form changed while you were filling it in",
    ERR_409_SUBMISSION_CAP: "This form has reached its submission limit",
    ERR_410_CLOSED: "This form is closed",
    ERR_413_BODY_TOO_LARGE: "The submission exceeds the size limit",
    ERR_503_WORKSPACES: "Workspace membership service is unavailable",
}

#: What a client can actually DO about each refusal (core's REMEDIATION_VOCAB).
#: Declared rather than left to the heuristic: the difference between
#: "fix your input" and "wait and retry" is the difference between a
#: respondent editing a field and a respondent giving up.
STAPEL_FORMS_REMEDIATION = {
    ERR_400_INVALID_SCHEMA: "fix_input",
    ERR_400_KIND_NOT_ALLOWED: "fix_input",
    ERR_400_TOO_MANY_FIELDS: "fix_input",
    ERR_400_DUPLICATE_SLUG: "fix_input",
    ERR_400_EMPTY_SCHEMA: "fix_input",
    ERR_400_NO_DRAFT: "fix_input",
    ERR_400_INVALID_STATE: "fix_input",
    ERR_400_NOT_PUBLISHED: "fix_input",
    ERR_400_TOO_MANY_OPEN_FORMS: "contact_support",
    ERR_400_INVALID_RETENTION: "fix_input",
    ERR_400_NO_RECIPIENTS: "fix_input",
    ERR_400_UNKNOWN_FIELD: "fix_input",
    ERR_400_ANSWERS_NOT_OBJECT: "fix_input",
    ERR_403_FORBIDDEN: "contact_support",
    ERR_404_NOT_FOUND: "verify",
    ERR_404_SUBMISSION_NOT_FOUND: "verify",
    ERR_409_VERSION_SUPERSEDED: "retry",
    ERR_409_SUBMISSION_CAP: "contact_support",
    ERR_410_CLOSED: "contact_support",
    ERR_413_BODY_TOO_LARGE: "fix_input",
    ERR_503_WORKSPACES: "wait_and_retry",
}

register_service_errors(STAPEL_FORMS_ERRORS, remediation=STAPEL_FORMS_REMEDIATION)

#: The stapel-attributes keys this module's API can return, listed (not
#: re-registered) so the contract test can assert the artifact carries them.
#: Not merged into :data:`STAPEL_FORMS_ERRORS`: that map is what the
#: ``/error-keys/`` view publishes as *forms-owned*, and claiming these here
#: would hand this package a catalogue obligation that is upstream's.
ATTRIBUTE_VALIDATION_ERRORS = tuple(sorted(stapel_attributes.errors.ATTRIBUTES_ERRORS))


class FormsErrorKeysView(ErrorKeysView):
    """The error-key listing the stapel-translate collector reads.

    Mounted at ``error-keys/`` (the stapel-cdn / workspaces / profiles
    convention). Without it the collector reports this service as having
    no endpoint and its catalogues never get regenerated — stapel-docs
    shipped without one, which is the omission this module does not repeat.
    """

    def get_service_errors(self):
        return STAPEL_FORMS_ERRORS


__all__ = (
    [name for name in dir() if name.startswith("ERR_")]
    + [
        "STAPEL_FORMS_ERRORS",
        "STAPEL_FORMS_REMEDIATION",
        "ATTRIBUTE_VALIDATION_ERRORS",
        "FormsErrorKeysView",
    ]
)
