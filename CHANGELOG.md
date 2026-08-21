# Changelog

All notable changes to stapel-forms are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0 semver: **minor = breaking**, patch = compatible.

## [Unreleased]

## [0.1.0] — 2026-08-21

First release. Admin-defined forms, anonymous responses, response review.

### Added — the module

- **`Form` / `FormVersion` / `Submission`.** A published version is
  immutable; editing a live form publishes the next one; every response FKs
  the exact version it answered (`PROTECT`). A response is only
  interpretable against the schema it answered, and a version row buys both
  cheap grouping and exact interpretation at one row per publish rather than
  one schema snapshot per response.
- **The schema is a list of stapel-attributes `FeatureDef`s.** No field-type
  class, no validation of its own: the fleet already has exactly one
  field-type vocabulary and this is its third consumer. A host that
  registers a custom attribute kind gets it here by adding it to
  `FIELD_KINDS`.
- **Two anonymous endpoints** — `GET /public/<public_id>/` and
  `POST /public/<public_id>/submissions/` — behind a dedicated public
  presenter, module-namespaced throttles, a `Content-Length` gate before the
  JSON parse, `@captcha_protected`, per-form and per-workspace volume caps,
  and `TokenPathNoLogMixin`. Unknown handle, soft-deleted form and draft
  answer one byte-identical 404; closed answers 410.
- **Capability-gated admin REST** for authoring, publishing, state, link
  rotation, versions, response review, deletion and **resend**
  (`POST /submissions/<id>/resend`, admin-initiated and therefore
  cooldown-independent).
- **CSV export** — streamed, keyset-paged with the cursor in
  `X-Forms-Next-Before`, and escaping formula leads server-side so every
  consumer inherits the guard.
- **`form.published` / `form.closed` / `form.submission.received`**, emitted
  inside the mutating transaction, carrying **ids only**: the outbox has no
  retention and a durable bus fans out to every subscriber, so respondent
  answers do not ride it.
- **Notification targets addressed by keyword** — `notify_emails` and
  `notify_telegram_chat_ids` map to the `request_notification` keyword that
  addresses each, so adding a channel is a registry entry rather than a
  branch at a call site. Auto-notify is cooldown-gated per form and folds
  the interim count into the next letter.
- **GDPR provider + finite retention.** Erasure keeps the tombstone so
  counts stay truthful; retention destroys the row, because after the
  horizon the count claim expires too.
- **System checks** `stapel_forms.E001/E002` (field kinds),
  `W001` (open public forms with no captcha), `W002` (unscheduled
  retention), `W003` (undeclared GDPR data owner).
- Contract quintet in `docs/`, `error-keys/` listing view for the translate
  collector, ru/es error catalogues, read-only Django admin, e2e script.

### Known gaps, stated rather than implied

- **Anonymous respondents have no self-service erasure channel.**
  stapel-gdpr keys every subject on `user_id`, and an email typed into a
  field is opaque answer content. v1 answers with finite retention, a purge
  that runs, and an admin delete endpoint. An email-keyed subject is
  upstream platform work.
- **`forms.submission_received` / `forms.submission_resend` are not yet in
  `NOTIFICATION_ROUTING`.** Hosts bridge them through
  `STAPEL_NOTIFICATIONS["TYPES"]` — the exact entries are in MODULE.md §9
  and exported as `stapel_forms.notifications.ROUTING_ENTRIES`. Without the
  bridge, nobody is told about a response.
- **A workspaces outage currently renders 403, not 503.** The `unavailable`
  branch in `authz.py` is live and correct, but stapel-core's
  `require_capability` collapses denial and outage into the same `None`.
  The fix belongs in core.
- **The ru/es catalogues ship unreviewed** (`origin=seed:authored`). They
  are authored, not machine-translated, but no human has approved them and
  the provenance sidecar says so rather than claiming otherwise.
- **`TokenPathNoLogMixin` is a replica** of the stapel-workspaces original,
  with the origin named in its docstring. Two copies is the moment to
  upstream it into `stapel_core.django.api`.

### Deliberate non-goals

File-upload fields (stapel-cdn cannot take custody of an anonymous
stranger's bytes and cannot gate reads); conditional logic and branching
(`meta.logic` is reserved); multi-language form content; a realtime response
feed; honeypot fields; quotas or billing on submission volume; a webhook
layer.
