# CONFIG.MD — stapel-forms

Config registry for **stapel-forms** (`static-scaffold-and-config.md` §2).
One row per configuration key the module reads, its **source** (`env` = the
process environment / the `STAPEL_FORMS` settings dict), what it is for,
whether it is required, and its default.

All keys are read through `forms_settings`
(`stapel_forms.conf.AppSettings`, namespace `STAPEL_FORMS`).
Resolution order per key: `settings.STAPEL_FORMS` dict → a flat Django
setting of the same name → environment variable → the default below.
There are no `import_strings` keys in this module.

## stapel-forms

### Schema surface (source: env)

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| FIELD_KINDS | env | allowlist of stapel-attributes kinds a form schema may use. A kind registered in the attributes registry but absent here cannot be asked on a public URL. Kinds implying binary payloads are absent by construction — there is no anonymous attachment path (check `stapel_forms.E001` refuses kinds nothing answers for; `E002` refuses an empty list). | no | the ten builtins: string, int, float, bool, select, date, header, hex_color, hierarchical_select, convertible_unit |
| MAX_FIELDS_PER_FORM | env | ceiling on fields in a published version; also bounds the CSV column count. | no | 64 |

### Abuse ladder (source: env)

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| MAX_SUBMISSION_BYTES | env | `Content-Length` gate applied BEFORE the JSON parse; over it is 413 `error.413.forms_body_too_large`. 0 disables. | no | 65536 |
| MAX_SUBMISSIONS_PER_FORM | env | per-form row cap bounding what one leaked public link can cost; past it the submit answers 409 `error.409.forms_submission_cap`. 0 disables. | no | 10000 |
| MAX_OPEN_FORMS_PER_WORKSPACE | env | ceiling on simultaneously open forms in one workspace. 0 disables. | no | 100 |
| SUBMIT_THROTTLE | env | DRF scoped rate for the anonymous submit, per client IP (netintel-resolved, never raw XFF). A library cannot own `DEFAULT_THROTTLE_RATES`, so the rate lives here. `None` disables — a conscious act. | no | 20/h |
| PUBLIC_SCHEMA_THROTTLE | env | same, for the anonymous schema fetch — the enumeration backstop. `None` disables. | no | 120/h |
| ALLOW_UNCAPTCHAED_PUBLIC | env | the confession switch. Off: a deployment with an open public form and no `STAPEL_CAPTCHA["SECRET"]` gets `stapel_forms.W001`. On: the warning is silenced because the host says the refusal is deliberate. | no | False |

### Respondent privacy (source: env)

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| STORE_CLIENT_META | env | persist the respondent's IP and user-agent on each submission. Off: nothing needs them on disk — throttling and netintel classification work off the live request and the cache. On: that data falls under the same retention clock as the answers. | no | False |
| RETENTION_DAYS | env | how long a response lives before the purge destroys it. A per-form `settings.retention_days` may only SHORTEN this; lengthening past the ceiling requires raising it here, so one form cannot rewrite the deployment's promise. `None` keeps answers forever — an explicit host decision. | no | 365 |
| PURGE_SCHEDULE | env | crontab kwargs for the retention beat entry (`get_forms_beat_schedule()`). Cadence is configuration, not a literal. | no | {"hour": 4, "minute": 40} |

### Notifications (source: env)

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| NOTIFY_COOLDOWN_SECONDS | env | minimum gap between auto-notify letters for one form; submissions inside the window fold into the next letter as a count. Keyed on the form, not the caller — the protected resource is the owner's inbox. Admin-initiated resend is deliberately NOT subject to it. 0 notifies every time. | no | 600 |

### Versioning (source: env)

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| ACCEPT_PREVIOUS_VERSION_SECONDS | env | grace window during which a submit naming the previous version is still accepted after a publish. 0 (strict) refuses it wholesale with 409 `error.409.forms_version_superseded`, so the renderer refetches and tells the respondent rather than half-validating against a schema they never saw. | no | 0 |

### Response review (source: env)

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| MAX_PAGE_SIZE | env | service-side cap on `?limit=` for the keyset response listing. | no | 100 |
| EXPORT_PAGE_SIZE | env | rows per CSV export request; the continuation cursor comes back in the `X-Forms-Next-Before` header rather than materializing the whole table. | no | 1000 |

## Keys this module READS from other namespaces

| Key | Owner | Why it matters here |
|-----|-------|---------------------|
| STAPEL_CAPTCHA["SECRET"] | stapel-core | with no backend configured the captcha verifier is a no-op and every bot that finds a public link is accepted; `stapel_forms.W001` says so. |
| STAPEL_WORKSPACES["ROLES"] | stapel-workspaces | grants `forms.*` to roles. Without a grant every admin request denies; only `owner` has `*` by default. An entry REPLACES a whole role — there is no deep merge. |
| STAPEL_GDPR["DATA_OWNERS"] | stapel-gdpr | must include `"forms"`, or the erasure closure never completes (`gdpr.E002`; `stapel_forms.W003` warns from this side). |
| STAPEL_NOTIFICATIONS["TYPES"] | stapel-notifications | the host-side bridge for `forms.submission_received` / `forms.submission_resend` until the upstream `NOTIFICATION_ROUTING` entries land. See MODULE.md §9. |
| CELERY_BEAT_SCHEDULE | the host | must contain an entry whose `task` is `stapel_forms.tasks.purge_expired_submissions`, or retention never runs (`stapel_forms.W002`). |
| DATA_PLANE_APPS | the host | isolation-tier hosts list `forms`. No schema impact. |

## Per-form settings (not deployment config)

`Form.settings` is a JSON blob on the row, edited over the API, not a Django
setting. Recognized keys:

| Key | Purpose |
|-----|---------|
| notify_emails | `[str]` — email destinations for the auto-notify and resend. |
| notify_telegram_chat_ids | `[str]` — telegram chat destinations (no account behind them; stapel-core 0.31 `telegram_chat_id`). |
| retention_days | `int` — shortens this form's retention below `RETENTION_DAYS`. Lengthening past the module ceiling is refused with `error.400.forms_invalid_retention`. |
