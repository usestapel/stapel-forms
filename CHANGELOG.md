# Changelog

All notable changes to stapel-forms are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0 semver: **minor = breaking**, patch = compatible.

## [Unreleased]

## [0.4.0] — 2026-08-26

**The caveat is gone from the contract.** No route, status code or payload
*shape* changed — but the **meaning** of one status did, and it is published
in a machine-readable artifact that consumers gate on, so this is a minor
(pre-1.0: minor = breaking) on two counts: the **stapel-core floor moves to
0.47.0**, and every `capabilities[].gates.behavior` in
`docs/capabilities.json` now says something different about what a 403 means.

0.3.0 shipped an honest untruth-in-waiting. It could not fix the underlying
defect from outside this module, so it published the defect *inside* the
contract instead: every capability entry warned that a 403 meant EITHER "not
granted" OR "no verdict was reached", because stapel-core's
`require_capability` logged a `FunctionCallError` and returned `None`, the
`unavailable` → 503 branch in `authz.py` could therefore never fire, and a
workspaces outage was indistinguishable from a denial. It pinned that with
`test_a_workspaces_outage_still_renders_403_not_503` — a test asserting the
wrong-shaped behaviour on purpose — explicitly so the caveat would die with
the defect rather than outlive it.

stapel-core **0.47.0** fixed the defect. That test went red on the first run
against it. This release is the death it was written for.

### Changed

- **A workspaces outage now renders 503, not 403.** Core 0.47.0's
  `require_capability` has three answers instead of two — a membership,
  `None` ("the service was asked and said no": a verdict), and
  `WorkspaceLookupUnavailable` ("the question could not be asked") — so the
  `unavailable` branch `authz.authorize` has carried since day 1 fires.
  A refusal and an outage are now different statuses with different error
  keys: `403 error.403.forms_forbidden` vs
  `503 error.503.forms_workspaces_unavailable`.

  **What a consumer must do:** stop treating a 403 from a gated route as
  possibly-an-outage. It is a permission decision and may be cached as one.
  A 503 is "ask again", and a client that retried through 403s will now see
  the retry-worthy case labelled as such.

- **The `gates.behavior` line in every capability entry is rewritten.**
  Before: *"a 403 from these routes means EITHER the capability is not
  granted OR the workspaces service rendered no verdict … the 503 branch in
  stapel_forms.authz cannot fire."* After: *"A 403 from them is a VERDICT …
  a workspaces outage is a separate answer with a separate status — 503
  `error.503.forms_workspaces_unavailable` … the two are no longer the same
  byte on the wire."* Regenerated into `docs/capabilities.json` from
  `docs/capabilities.meta.json`.

  Deleted rather than softened, deliberately. A stale caveat here would not
  be merely out of date, it would be **false** — it would tell a client that
  a real permission decision might be an outage, and clients code around
  what the contract says. The whole point of publishing the limitation
  machine-readably in 0.3.0 was that it would be removable, and this is the
  removal.

- **Floor: `stapel-core>=0.47.0`** (was `>=0.45.0`). Not a courtesy bump:
  0.4.0's contract *asserts* that 403 and 503 are distinguishable, and on an
  older core they are not, so a deployment reading this artifact against
  core 0.46 would be told something untrue about its own behaviour.
  `authz.authorize` also passes `strict=True` explicitly — a keyword that
  does not exist below 0.47.0 — so the skew is a `TypeError` on the first
  gated request rather than a silent return to 403-on-outage.

  Note the asymmetry in core, documented there rather than accidental, and
  left alone here: `require_capability` and `require_role` default to
  `strict=True` (whatever they return goes straight into a 403), while
  `get_membership` keeps `strict=False` because it is a reader with
  legitimate non-authorization callers. This module calls only
  `require_capability`, and only from `authz.authorize`.

- **`test_a_workspaces_outage_still_renders_403_not_503` is replaced by two
  tests that pin the outcomes apart**, which is the property that matters
  and which neither one alone establishes (a gate that answered 503 to
  everything would satisfy the first):

  - `test_a_workspaces_outage_renders_503_not_403` — `DELETE /submissions/<id>`,
    a **real** grant for `forms.responses.manage` so the outage is the only
    possible cause of a refusal, with `stapel_core.comm.call` patched to
    raise. Patched at the comm call rather than at `require_capability`,
    because core's own except-branch is the thing under test.
  - `test_a_genuine_denial_renders_403_not_503` — the same route with
    workspaces answering normally and every *other* forms capability
    granted, so the 403 is specifically about the string this route asks
    for.

  `test_every_capability_publishes_what_the_gate_cannot_see` became
  `test_every_capability_publishes_how_a_refusal_reads`: it now asserts the
  `behavior` line names **both** statuses and carries none of the retired
  caveat's phrases, so the untruth cannot be reintroduced by a future edit.

- MODULE.md §3 and §4 say plainly that a 403 is a verdict; §12.3 is closed
  and kept as the worked example of the mechanism — debt published in the
  contract, pinned by a test that asserts the defect, deleted when the test
  goes red.

### Not changed, and why

- **`docs/schema.json` still emits `info.version: "0.0.0"`** — the
  `stapel-api-lint` **SCHEMA001** reported in 0.3.0 stays open **on
  purpose**. It is not a missing emitter setting: `SPECTACULAR_SETTINGS` is
  deliberately unset in `_codegen_settings.py` because drf-spectacular
  freezes its settings singleton at import time, which is exactly the state
  the monolith aggregate emits under, and every one of the 24 sibling
  libraries in the fleet emits `0.0.0` for the same reason. Setting it here
  alone would trade a fleet-wide lint finding for a fleet-wide byte-identity
  divergence. Closing it is one change to the shared harness convention, not
  a line in this module.

## [0.3.0] — 2026-08-26

Additive at the HTTP layer — no route, status code or payload changes — but
minor (pre-1.0: minor = breaking) on two counts a consumer must act on: the
**stapel-core floor moves to 0.45.0**, and `stapel_forms.views` no longer
exports a local `SerializerSeamMixin`.

Closes the gap a frontend agent hit and correctly refused to paper over:
`forms.responses.manage` was enforced on two endpoints and named in
`authz.py` and in prose, and appeared in **no** machine-readable artifact
this module ships. `docs/schema.json` documented those endpoints as
`**Permissions:** IsNotAnonymousUser` — true, and useless to a UI deciding
whether to offer a delete button. A deployment could therefore not express
who may read and manage form responses, and the responses surface had to be
shown to everyone or hidden from everyone.

### Added

- **The workspace capability projection.** All four capabilities
  (`forms.view`, `forms.manage`, `forms.responses.view`,
  `forms.responses.manage`) are now published in three places, all derived
  from the gate that enforces them:

  - `docs/capabilities.json` grows a `capabilities[]` section next to
    `axes[]`, and deliberately mirrors its shape —
    `{key, gates: {operations[], behavior}, curated: {summary, business_label}}`
    — so a consumer walks both with the same code. `axes` answers "what may
    this deployment do"; `capabilities` answers "who in it may do it".
    `gates.operations` is derived, `curated` is hand-written in
    `docs/capabilities.meta.json` under the same loud missing/extra check
    the axes already get.
  - `docs/schema.json` carries `"x-stapel-capability": "<capability>"` on
    each of the 16 gated operations — the field a generated client can gate
    on. The two anonymous respondent routes carry none, and a test asserts
    they never will.
  - each operation's rendered description gains a `**Capability:** …` line
    beside core's existing `**Permissions:** …` one.

- **`stapel_forms.authz.capability_for(action)`** — the workspace capability
  answering a forms action, and the only place the mapping is read. Reach
  for it instead of writing a `"forms.*"` literal in caller code.

- **`stapel_forms.views.gated(action)`** — the decorator that declares AND
  enforces one handler's action, and **`AdminAPIView`** / 
  **`CapabilityAwareAutoSchema`**, the base and the schema that carry it.

- `tests/test_capability_projection.py` — 45 tests. Every gated route is
  driven twice (granted only its published capability: must not refuse;
  granted every other capability: must refuse), the URLconf is walked to
  prove no admin handler is undeclared, and the committed artifacts are
  checked against the enforced set. It needs no sibling service: the
  in-process `workspaces.check_capability` fake in `conftest.py` answers
  from an explicit grant table.

### Changed

- **Projection and enforcement are now one object, not two that agree.**
  `@gated("responses.manage")` is the only place an action is named. The
  decorator stamps it on the request — which is what `_access_error()` reads
  to call `authorize()` — and on the function, which is what the OpenAPI
  schema reads to publish it. There is no second place to type the string,
  so the contract cannot advertise a capability the endpoint will not
  honour. Supporting consequences: an admin handler that reaches the gate
  without `@gated` raises `ImproperlyConfigured` rather than defaulting to
  an action; `@gated("typo")` is a `ValueError` at import; emission fails if
  an enforced capability is projected by no operation or the schema projects
  one `authz` does not enforce; and a changed declaration surfaces as
  artifact drift in `make contract-check`.

- `authz.CAPABILITIES` is now **derived** from `ACTION_CAPABILITIES` rather
  than restated beside it. The two lists were identical, which is precisely
  the state a hand-kept pair is in right up until it isn't.

- Every view derives from the canonical
  `stapel_core.django.api.views.StapelAPIView`; admin views go through the
  local `AdminAPIView`, which adds `permission_classes` and the
  capability-projecting schema. **The local `SerializerSeamMixin` copy is
  deleted** — a host that imported `stapel_forms.views.SerializerSeamMixin`
  imports it from `stapel_core.django.api.views` instead. The attributes and
  getters are unchanged.

- `_access_error(request, workspace_id)` and
  `_scoped_form` / `_scoped_submission(request, id)` no longer take an
  action argument: they read the declaration.

- **Floor: `stapel-core>=0.45.0`.** `StapelAPIView` (0.37.0) and
  `PermissionAwareAutoSchema` are hard imports at module load, so an older
  core is an ImportError on boot rather than a degraded feature.

- The `llms.txt` budget rises 5000 → 5200 for the `capability_for` surface
  entry (measured ~5017), raised deliberately per the note in the Makefile
  rather than by trimming `intent` lines to fit.

### Known limitations, stated rather than papered over

- **A 403 from a gated route still means either "not granted" or "the
  workspaces service is unreachable".** Re-verified against stapel-core
  0.45.0: `require_capability` logs a `FunctionCallError` and returns
  `None`; it never raises `WorkspaceLookupUnavailable`, so the `unavailable`
  → 503 branch in `authz.py` cannot fire. This is the one thing the
  capability cannot tell a client, so it is published in every
  `capabilities[].gates.behavior` rather than left in prose, and
  `test_a_workspaces_outage_still_renders_403_not_503` pins the current
  behaviour — the day the one-file core change lands, that test goes red and
  the caveat gets deleted instead of outliving the defect (MODULE.md §12.3).

- **`llms.txt` still cannot show which capability gates which route.**
  `stapel_tools.llms_txt` has no section for the new block, so an agent
  reading the context file alone has to open `docs/capabilities.json` or the
  `x-stapel-capability` field in `docs/schema.json`. Teaching the generator
  the section is a stapel-tools change (MODULE.md §12.6); hand-writing the
  table into `capabilities.meta.json` would re-create exactly the
  second copy this release removed.

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
