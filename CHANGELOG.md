# Changelog

All notable changes to stapel-forms are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0 semver: **minor = breaking**, patch = compatible.

## [Unreleased]

## [0.6.0] — 2026-09-03

### The admin stopped being a peephole

The verdict this release answers, from the owner of a deployment using it:
«на фронте может и работает, но на бэке вообще неюзабельно и при большом
количестве откликов это каша».

He was right, and the reason is worth recording rather than fixing
quietly. Through 0.5.0 this module's admin was three read-only
`ModelAdmin`s, on a stated argument: workspace admins are not Django
staff, so form authors reach forms through the capability-gated REST
surface and the admin only needs to be a peephole for an operator on a
support ticket. That argument is sound — for a deployment whose form
authors **are** workspace members. It is wrong for the shape a host
actually runs first: a public form on a marketing site, answered by
strangers, read by staff. There is no workspace member to be. There is an
operator, a table of responses, and — until this release — a `JSONField`
rendered as its `repr`.

So the peephole became a surface, with the trust boundary unchanged.

- **Responses render as a table driven by the schema.** Columns are the
  labelled questions of the form, in the form's own order; a `select`
  shows the option label the respondent clicked (`Pro`) instead of the
  stored value (`["pro"]`), because `normalize_to_dao` already wrote the
  label down at submit time and nothing was reading it. Every question
  gets a cell including the ones left blank — a missing cell silently
  shifts every later cell against its header, which is a table that lies
  rather than a table with a gap.
- **Filters and paging that survive a real inbox.** Date window
  (`since`/`until`), case-insensitive substring search over answer text,
  optionally scoped to one question, and keyset paging that keeps the
  active filter in its cursor. The filters live in
  `services.list_submissions`, not in the admin view, so the REST surface
  and `@stapel/forms-react` inherit the same predicate — a filter that
  exists on one review screen and not the other is where a second
  implementation grows.
- **A form builder.** Add, remove, reorder, relabel, re-slug, toggle
  required; per-kind validation config. Saving publishes a **new version
  of the same form** — form identity is what a host embedded in their HTML
  (`public_id`), so an edit may never mint a new form, and the page says
  so in as many words.
- **The submission detail is a labelled table**, rendered against the
  version that response answered. The raw `answers` and `client_meta`
  fields are removed from the form rather than left beside it: leaving
  them re-creates exactly what this release removed.

**What the builder does NOT contain: a field-config editor.** The eleven
per-kind config widgets, their quirks and their translations come from
stapel-attributes' shipped `mountConfigEditor`, reached through a hidden
`ConfigEditorWidget` this page renders and reads the payload of — the same
public seam `stapel-categories` uses on its `config` field. No private
import, no second catalogue, and a kind registered upstream reaches this
builder with no release here. Writing a second config editor would have
been the drift this module spent §3 of MODULE.md avoiding on the client
side.

### The mandate is unchanged, and now proven by tests

`Submission` stays `@access.sensitive` (view MID, mutate HIGH) and the new
surface inherits it: the answers table is gated on the *submission's* view
permission, not the form's, because gating a view of respondent PII on
`forms.view_form` (LOW) would have been a security downgrade dressed as a
convenience. The forms changelist carries a response **count** and no
answer content, for the same reason.

The admin asks for **no workspace capability**, deliberately and now
explicitly tested. The capability layer gates the REST product surface; a
staff reviewer holding table permissions has no membership in the
workspace that owns a public feedback form, and requiring one would lock
them out of the deployment that needs this most. Two doors, still
independent, each shut by default.

### Versions stay out of the way without being taken away

The Form/FormVersion split is correct and is not flattened — a response is
only interpretable against the schema it answered. What changed is that an
operator no longer has to reason about it before reading anything:

- `FormVersion` is hidden from the admin index (`get_model_perms` → `{}`);
  its pages stay reachable as the audit trail.
- By default the table draws **the union of columns across every version**,
  led by the current schema's order, each cell marked with whether that
  row's own version defined the question. "Not asked" and "asked and left
  blank" are different facts about a respondent.
- The split surfaces as **one marker on the boundary row** where the schema
  changed.
- An **optional** version picker defaults to the current schema. It exists
  for the case the default cannot cover: a field ADDED later can be shown
  as blank on older rows, but a field REMOVED later cannot be shown at all,
  because the current schema no longer knows it. Picking a version redraws
  the table under exactly that version's columns.

### Added

- **`schema.diff_schemas(old, new)`** — added / removed / renamed /
  retyped / required-changed between two published schemas, plus a
  one-line summary. The identity rule it rests on: the **slug** is a
  question's identity, because the slug is what the answer is stored
  under. A relabelled field is a rename; a re-slugged one is a removal
  plus an addition, and calling that a rename would tell an author their
  history followed the field when it did not.
- **`schema.version_history(form)`** — every version with its publish
  time, active flag, response count and derived change summary. Derived,
  never authored: a hand-written changelog on an immutable row is a second
  source of truth that drifts the first time somebody is in a hurry.
- **`presenters.present_answer_rows`** / **`present_response_table`** /
  **`dao_display`** — the definition-driven projections the admin, the CSV
  and the notification all now share.
- **`services.form_answer_slugs(form)`** — every slug a form has published,
  from the schemas rather than from a scan of stored keys. It is what lets
  an unknown `field` filter answer **400** instead of an empty page: an
  empty page reads as "no matches", and a typo'd field name is a different
  fact.
- **`export.format_value`** — the display renderer, split out of
  `escape_cell` so three surfaces stop inventing their own. `escape_cell`
  keeps its own recursion: a list renders as `a, =b` and escaping only the
  joined result would hand a spreadsheet `=b` intact.
- **`docs/embedding.md`** — how to put a form on a site: the `public_id`,
  both endpoints with every status code, what a respondent sends and gets
  back, a dependency-free copy-pasteable embed, and the throttle/captcha
  behaviour an embed will actually hit.
- **`GET /forms/<id>/submissions`** gained `since`, `until`, `q` and
  `field`.

### Changed — breaking

- **The notification `answers` variable is now labelled rows**
  (`[{label, display, answered}]` in schema order), not `{slug: value}`.
  The old shape made a recipient read storage slugs and stored values —
  `plan: ["pro"]` where the respondent clicked "Pro". A host template
  iterating the old dict must be updated; there is no compatibility shim,
  because one that silently emitted both shapes is how a template ends up
  rendering the wrong one.
- **`ADMIN_BASE_URL` and `NOTIFY_INCLUDE_ANSWERS` are new settings.** The
  auto-notify letter now carries a deep **review link** to the response
  whenever `ADMIN_BASE_URL` is set (navigation, not content, so it is
  unconditional), and carries the **answers themselves only when
  `NOTIFY_INCLUDE_ANSWERS` is True — which it is not by default.**

  That default is the disclosure decision, made the way this module makes
  every other one: closed, and said out loud. Answers are respondent PII
  and email is the least controlled channel here — it leaves the
  deployment, lands in inboxes nobody administers, and gets forwarded. So
  the letter says what happened and where to read it under the admin's own
  authentication, and a host that wants the content in the mail says so.

  It does **not** gate `POST /submissions/<id>/resend`: that is an
  authenticated operator holding `responses.manage` sending one named
  response to one named address — the "send this one to legal" case, not a
  standing subscription.

  Answers also ride only when the letter stands for exactly **one**
  response. Inside the cooldown, interim submissions fold into the next
  letter as a count, and attaching one response's answers to a letter
  announcing three would be wrong rather than merely terse.
- **`ADMIN_BASE_URL` empty means the link is omitted, not relative.** A
  relative href in an email is not a link, it is a bug report from the
  recipient — and a library must not infer its own origin from a request
  whose `Host` header a submitting stranger controlled.

### Fixed

- **The admin date filter was off by a timezone and a day.** On Python
  3.11+ `django.utils.dateparse.parse_datetime` delegates to
  `datetime.fromisoformat`, which accepts a bare `2026-09-01` and returns
  midnight — so asking it before `parse_date` swallowed every date input,
  silently ignored the end-of-day bound (turning an inclusive "to" into an
  exclusive one and hiding a whole day of responses) and returned a naive
  datetime that `USE_TZ` then reinterpreted with a warning rather than an
  error. Both are the shape of bug that leaves a filter looking like it
  works.
- **`docs/errors.json` was stale**, missing
  `error.400.feature_invalid_rules` — a key stapel-attributes owns and the
  submit path can return. Two contract tests had been red against the
  current attributes release; re-emission fixes both.

### Notes for hosts

- The email TEMPLATE is still host-side. This module now sends a report
  worth rendering (`answers` rows + `review_url`); rendering it as a table
  is the template's job, and the upstream `NOTIFICATION_ROUTING` entries
  remain the recorded debt in MODULE.md §12.2.
- The MAC only bites where `stapel_core.access.MandateBackend` is in
  `AUTHENTICATION_BACKENDS`. A host running plain `ModelBackend` gets
  ordinary Django model permissions on these screens — which is a
  supported configuration, and is why the admin gates on
  `has_view_permission` (correct under either backend) rather than on
  clearance directly.

## [0.5.0] — 2026-08-30

### Added — `user.merged`: a guest's answers follow them into the account

This module knew one thing about an account's end: destroy the answers. When
a visitor who filled in a form as a guest signs in with an authenticator an
existing account already holds, stapel-auth folds the two and emits
`user.merged` — the opposite instruction. Nothing here answered it, so the
guest's responses stayed attributed to an id that can no longer sign in:
absent from the survivor's GDPR export, and outside any future erasure
request too, because none is ever made for an account that was *merged*
rather than closed. Nothing raises and nothing is logged when that happens —
the first report is a person saying their submission is not in their history.

- **`user.merged` is subscribed in `stapel_forms.actions`** and re-parents
  the three columns this module keys by a user, in one transaction:
  `Form.created_by`, `FormVersion.created_by` and `Submission.submitted_by`.
  An answer belongs to whoever typed it, and after the merge that is the
  survivor.
- **The erasure tombstone wins.** A submission already erased under
  `user.deleted` carries `submitted_by = None` and is therefore never matched
  here: a merge does not resurrect an attribution its owner asked to have
  removed. An anonymous answer (`submitted_by` NULL because nobody was signed
  in) stays anonymous for the same reason.
- **An ordering lag is retried; a bad id is not.** A guest who owns nothing
  here is a quiet no-op (also the at-least-once idempotency path); a guest who
  owns rows while the survivor has no user row here *yet* raises
  `MergeTargetNotReady`, so the outbox redelivers instead of marking the event
  delivered and stranding the answers. A malformed or missing id is logged and
  ACKed — `ValidationError` included, which is what Django raises for an
  uncoercible UUID and is not a `ValueError`, the guard a poison payload
  otherwise escapes through and loops on forever.
- `tests/test_user_merged.py` pins the rows moving, a redelivery moving
  nothing further, the tombstone and the anonymous answer staying put, every
  malformed shape ACKing, an event about users with no rows here doing
  nothing — and `stapel_core.lifecycle.E001` returning `[]`, so the pair
  cannot be broken again without a red test.

**Minor, not patch**: a new consumed action is public surface. Requires no
new stapel-core API; the E001 check that names the gap ships in stapel-core
0.52.1.

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
