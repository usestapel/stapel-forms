# Changelog

All notable changes to stapel-forms are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0 semver: **minor = breaking**, patch = compatible.

## [Unreleased]

## [0.2.0] — 2026-08-21

Additive. Minor (pre-1.0: minor = breaking) because the
**stapel-attributes floor moves to 0.4.6** — a dependency floor a consumer
must act on is not a patch, even when nothing in the API changed shape.

Closes the two upstream asks the `@stapel/forms-react` 0.1.0 build filed
against this module (`tasks/stapel-forms-design.md` §11c deltas 1 and 2).

### Added

- **`GET /forms/api/v1/field-kinds`** (`forms.manage`) — the form builder's
  dictionary: every registered field kind with its stapel-attributes
  `config_form()` declaration, passed through verbatim, plus the
  `config_widgets` vocabulary those declarations draw from. Read from the
  live registry on each call, so built-ins ← `EXTRA_TYPES` ← runtime
  registrations all reach the builder with no release of this module or of
  the React pair.

  Every *registered* kind is listed, not just the allowlisted ones (a schema
  published before a kind left `FIELD_KINDS` still has to render); `allowed`
  is what says which kinds may be offered for a new field. A kind with no
  declared config form appears with an empty `fields` list, and an
  allowlisted kind the registry does not carry appears with
  `"registered": false` — both listed rather than omitted, because an
  omission reads as "this kind does not exist" and a builder would silently
  drop the field.

  This deletes the pair's `widgets/configForms.ts`, a hand-written
  TypeScript mirror of `BUILTIN_FORMS` that could drift silently against the
  upstream defaults it pinned blind.

- **`tests/test_contract.py`** — the part of the contract gate that runs on
  every interpreter in the CI matrix. `make contract-check` needs the pinned
  3.12 plus stapel-tools; these tests read the *committed* artifacts and
  assert the two properties a stale artifact breaks in silence: every
  mounted route is described in `docs/schema.json`, and every error key the
  API can return is declared in `docs/errors.json` **under its true owner**.

### Fixed

- **`docs/errors.json` now carries the `error.400.feature_*` family** (63 →
  75 keys). The submit path returns stapel-attributes' validation codes at
  the top level of a per-field refusal, but the artifact declared none of
  them, so frontend bundles generated from it missed exactly the errors a
  respondent is most likely to see and rendered them as raw keys.

  Fixed by the fleet's existing line — `import stapel_attributes.errors` in
  this module's `errors.py`, the same forcing import stapel-listings and
  stapel-categories carry, because an embedded non-app library is never
  reached by `autodiscover_modules("errors")`. It is a **re-export, not a
  claim**: `register_service_errors` infers ownership from the calling
  package, so the keys stay owned (and translated) by stapel-attributes,
  and `STAPEL_FORMS_ERRORS` / the `/error-keys/` listing still carry only
  `error.<status>.forms_*`. `tests/test_contract.py` asserts the `owner`
  field so a future "fix" that copies the strings in — taking on a
  catalogue obligation that is upstream's — goes red.

  Known consequence: stapel-attributes ships no `translations/errors.<lang>.
  json`, so emission now prints `[warning:unshipped]` for its 12 keys.
  Declared and English-covered; localizing them is upstream work
  (MODULE.md §12.6).

### Changed

- **`stapel-attributes>=0.4.6`** (was `>=0.4.5`). `StringConfig.multiline` —
  the textarea-vs-input hint the pair's `string` widget reads — does not
  exist on 0.4.5, so a form authored with it would be refused by this
  module's own unknown-config-key gate rather than degrading gracefully.

  0.4.6 also added `FeatureValidationResult.warnings` for unrecognized
  config keys. **Nothing here surfaces them, deliberately:**
  `schema.validate_schema` runs the same set-difference one step earlier and
  answers `400 error.400.forms_invalid_schema`, so this module is strictly
  stricter and the engine never reaches the branch that populates
  `warnings`. Documented in MODULE.md §5 rather than wired to a field that
  could never be non-empty.

- Contract artifacts regenerated: **14 paths** (was 13), **75 error keys**
  (was 63). `docs/capabilities.json`, `docs/llms.txt` and `README.md`
  re-emitted with them.

- `e2e/run_e2e.py` drives the new route over real HTTP — the catalogue's
  shape and its refusal of a session-less caller.

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
