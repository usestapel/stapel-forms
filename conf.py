"""Settings namespace for stapel-forms.

All configuration is read through ``forms_settings`` (lazily, at call time)
— never via module-level ``os.getenv`` (values would freeze at import).
Resolution order per key: ``settings.STAPEL_FORMS`` dict -> flat Django
setting of the same name -> environment variable -> the default below.

Every switch that widens the public attack surface ships CLOSED (spec §5.2):
throttles on, captcha confession off, client metadata unstored, submissions
accepted only for the active version, event payloads ids-only, retention
finite. Opening any of them is an explicit host decision.

There are no ``import_strings`` in v1: the extension seams of this module
are the stapel-attributes type registry (server side) and the
``@stapel/forms-react`` widget/slot registries (client side), not a
dotted-path strategy.
"""
from stapel_core.conf import AppSettings

#: Attribute kinds a form schema may use. The allowlist is the builtin set
#: of stapel-attributes; a host that registers a custom kind adds it here
#: too, so "registered somewhere in the process" never silently becomes
#: "answerable by strangers on a public URL". Kinds implying binary
#: payloads are absent because there is no anonymous attachment path
#: (spec §5.4) — closing them here is what keeps that verdict enforced
#: rather than merely documented.
DEFAULT_FIELD_KINDS = [
    "string",
    "int",
    "float",
    "bool",
    "select",
    "date",
    "header",
    "hex_color",
    "hierarchical_select",
    "convertible_unit",
]

#: AppSettings-shaped literal dict (capability-config.md §2): a top-level
#: DEFAULTS lets the capabilities.json emitter introspect axis keys/kinds
#: without re-parsing the AppSettings() call.
DEFAULTS = {
    # ── Schema surface ───────────────────────────────────────────────
    "FIELD_KINDS": DEFAULT_FIELD_KINDS,
    # A form nobody can finish is not a form. The cap bounds both the
    # builder and the CSV column count.
    "MAX_FIELDS_PER_FORM": 64,

    # ── Abuse ladder (spec §5.2) ─────────────────────────────────────
    # Size gate applied BEFORE the JSON parse, so a hostile body never
    # reaches the parser.
    "MAX_SUBMISSION_BYTES": 65536,
    # Bounds hostile storage growth behind one leaked public link: past
    # the cap the form answers submits as if it were closed.
    "MAX_SUBMISSIONS_PER_FORM": 10000,
    "MAX_OPEN_FORMS_PER_WORKSPACE": 100,
    # DRF resolves scoped rates from the global DEFAULT_THROTTLE_RATES
    # setting, which a library cannot own — the rates are read from this
    # namespace instead (the stapel-workspaces / stapel-geo canon).
    # None disables a throttle: a conscious act, never the default.
    "SUBMIT_THROTTLE": "20/h",
    "PUBLIC_SCHEMA_THROTTLE": "120/h",
    # The confession switch (security canon H10, mirroring docs'
    # ALLOW_UNEXPIRING_DOWNLOAD_URLS): a deployment with open public forms
    # and no captcha secret gets forms.W001 until it says, in so many
    # words, that it meant to run its public forms uncaptchaed.
    "ALLOW_UNCAPTCHAED_PUBLIC": False,

    # ── Respondent privacy ───────────────────────────────────────────
    # Rate limiting and netintel classification work off the request and
    # the cache; nothing needs the respondent's IP on disk. A host that
    # must keep forensics turns this on, and the data then falls under the
    # same retention clock as the answers.
    "STORE_CLIENT_META": False,
    # Finite by default: anonymous respondents are outside the fleet's
    # user-keyed GDPR apparatus (verified gap, spec §6), so retention is
    # the honest mechanism rather than an implied promise.
    "RETENTION_DAYS": 365,
    # Cadence is configuration, not a literal (crontab kwargs).
    "PURGE_SCHEDULE": {"hour": 4, "minute": 40},

    # ── Notifications ────────────────────────────────────────────────
    # The protected resource is the form owner's inbox, not this service's
    # CPU (the invitation lesson): at most one auto-notify per form per
    # window, with the interim count folded into the next one. Admin-
    # initiated resend is deliberately NOT subject to this (spec §11a).
    "NOTIFY_COOLDOWN_SECONDS": 600,
    # Whether the AUTOMATIC "you have a new response" letter carries the
    # answers themselves. Ships CLOSED, like every other switch here that
    # widens exposure, and for the ordinary reason: answers are respondent
    # PII and email is the least controlled channel this module touches —
    # it leaves the deployment, lands in inboxes nobody administers, and
    # gets forwarded. The letter always carries the fact and a deep link to
    # review the response under the admin's own authentication, which is
    # navigation rather than content and costs no disclosure. A host that
    # wants the content in the mail says so here.
    #
    # This does NOT gate `POST /submissions/<id>/resend`: that is an
    # authenticated operator holding `responses.manage` asking for one
    # named response to go to one named address, which is the "send this
    # one to legal" case, not a standing subscription.
    "NOTIFY_INCLUDE_ANSWERS": False,
    # Absolute base URL of the site serving the Django admin, e.g.
    # "https://app.example.com". Used to build the review link in a
    # notification. Empty (the default) means the link is OMITTED rather
    # than emitted as a relative path: a relative href in an email is not a
    # link, it is a bug report from the recipient. A library cannot know
    # its own public origin, and guessing one from a request would put
    # whatever Host header the submitting stranger sent into the operator's
    # mail.
    "ADMIN_BASE_URL": "",

    # ── Versioning ───────────────────────────────────────────────────
    # Strict active-version-only submits (spec §3.2 verdict 2). The grace
    # window ships at 0: a racing publish rejects an in-flight fill
    # wholesale with error.409.forms_version_superseded rather than
    # half-validating it against a schema the respondent never saw.
    "ACCEPT_PREVIOUS_VERSION_SECONDS": 0,

    # ── Response review ──────────────────────────────────────────────
    # Keyset paging cap (docs canon: no pagination framework).
    "MAX_PAGE_SIZE": 100,
    # Rows per CSV export request; the response carries a keyset
    # continuation cursor rather than materializing the whole table.
    "EXPORT_PAGE_SIZE": 1000,
}

forms_settings = AppSettings("STAPEL_FORMS", defaults=DEFAULTS)

__all__ = ["forms_settings", "DEFAULTS", "DEFAULT_FIELD_KINDS"]
