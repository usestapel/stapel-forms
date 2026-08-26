# MODULE.md — stapel-forms

Integration reference for **stapel-forms**: what it stores, what it exposes,
what it asks of a host, and which of its switches are decisions rather than
tuning. `README.md` is the introduction; this is the contract.

Design of record: `tasks/stapel-forms-design.md` in the stapel workspace
(§11a carries the architect's verdicts closing every open fork).

---

## 1. What it is

An **L2 data-plane module**. Three tables, all workspace-keyed:

| Model | Table | Role |
|---|---|---|
| `Form` | `forms_form` | identity, lifecycle, public handle, draft scratchpad, settings |
| `FormVersion` | `forms_form_version` | one immutable published schema, `(form, version)` unique |
| `Submission` | `forms_submission` | one answered form, FK to the exact version it answered |

App label `forms`. UUID primary keys. Soft delete on `Form` (`deleted_at`);
`Submission` is hard-deleted by retention and tombstoned by erasure — see §7.

Isolation-tier hosts list `forms` in `DATA_PLANE_APPS`; there is no schema
impact, only the `workspace_id` discipline every root entity here already has.

---

## 2. Mounting

```python
INSTALLED_APPS = [..., "stapel_forms"]

# urls.py — the module bakes in the api/v1 segment (api-versioning.md §2)
path("forms/", include("stapel_forms.urls"))     # -> /forms/api/v1/...
```

Nothing else is required to boot. What a host adds to make it *useful* is in
§9.

---

## 3. HTTP surface

### Public (anonymous, `AllowAny`, `stapel_anonymous_access = ANONYMOUS_ALLOWED`)

```
GET  /forms/api/v1/public/<public_id>/                        200 | 404 | 410 | 429
POST /forms/api/v1/public/<public_id>/submissions/            201 | 400 | 404 | 409 | 410 | 413 | 429
```

The GET envelope is `{public_id, version_id, version, fields[], meta{}}` and
carries nothing else — no workspace, no internal id, no author, no counts. The
POST body is `{answers: {slug: value}, version_id?, captcha_token?}`; it
answers `{accepted, confirmation}` and deliberately **not** a submission id
(there is no public read of responses).

`version_id` is what the client echoes from the schema it rendered. Omit it
and the submit is validated against whatever is active *now*; send it and a
racing publish becomes a clean `409 error.409.forms_version_superseded`
instead of a silent mis-validation. Clients should send it.

Both views carry `TokenPathNoLogMixin` — the handle never reaches an error log.

### Admin (`IsNotAnonymousUser` + `authorize()`, `?workspace_id=` required)

| Route | Method | Capability |
|---|---|---|
| `/field-kinds` | GET | `forms.manage` |
| `/forms` | GET | `forms.view` |
| `/forms` | POST | `forms.manage` |
| `/forms/<uuid>` | GET | `forms.view` |
| `/forms/<uuid>` | PATCH, DELETE | `forms.manage` |
| `/forms/<uuid>/draft` | PUT | `forms.manage` |
| `/forms/<uuid>/publish` | POST | `forms.manage` |
| `/forms/<uuid>/state` | POST | `forms.manage` |
| `/forms/<uuid>/rotate-link` | POST | `forms.manage` |
| `/forms/<uuid>/versions` | GET | `forms.view` |
| `/forms/<uuid>/submissions` | GET | `forms.responses.view` |
| `/forms/<uuid>/submissions/export` | GET | `forms.responses.view` |
| `/submissions/<uuid>` | GET | `forms.responses.view` |
| `/submissions/<uuid>` | DELETE | `forms.responses.manage` |
| `/submissions/<uuid>/resend` | POST | `forms.responses.manage` |
| `/error-keys/` | GET | staff (the translate collector's listing) |

There is no `forms.responses.export` capability: an export is a read.

**This table is not the source.** Each capability is declared once, on the
handler, with `@gated("responses.manage")`; the table above is prose that
follows it. The declaration is what `authorize()` is asked for and what the
contract publishes — see §4.

`deny` → 403, `unavailable` → 503, never 403-on-outage.

**Known limitation, stated rather than papered over:** re-verified against
stapel-core **0.45.0** — `require_capability` still collapses "denied" and
"workspaces peer unreachable" into the same `None` (a `FunctionCallError` is
logged and returns `None`; `WorkspaceLookupUnavailable` is never raised out
of it), so in practice an outage renders 403. The `unavailable` branch in
`authz.py` is live and correct; making it fire is a one-file stapel-core
change, not a per-module workaround that would re-implement the capability
call and its cache. Because a client cannot tell the two apart, every entry
of the capability projection carries the caveat in its
`gates.behavior`, and `tests/test_capability_projection.py` pins the current
behaviour so that the day core fixes it, the stale warning in the contract
goes red instead of quietly outliving the defect.

### `GET /field-kinds` — the builder's dictionary

The form builder is data-driven off stapel-attributes' `config_form()`
declarations, and this route is where it reads them. Before it existed the
only way to have them client-side was to mirror `BUILTIN_FORMS` in
TypeScript — a table that drifts silently, and drifts worst on the quirks
(`hex_color.allowCustom` defaults FALSE where `int`/`float`/`string` default
TRUE; `header.style` defaults to `h2`, which matches neither option).

```json
{
  "kinds": [
    {
      "kind": "string",
      "label_key": "admin.attributes.type.string",
      "allowed": true,
      "registered": true,
      "fields": [
        {"name": "minLength", "kind": "number", "label_key": "…", "params": {"step": 1}},
        {"name": "multiline", "kind": "checkbox", "label_key": "…", "default": false}
      ]
    }
  ],
  "config_widgets": {"number": ["step"], "text": ["placeholder"], "checkbox": []}
}
```

- `fields` is upstream's declaration **verbatim** (`FormField.to_dict()`), so
  a kind gaining a config field upstream needs no release here.
- Read from the live registry on every call: **built-ins ← `EXTRA_TYPES` ←
  runtime registrations**. A host type registered through
  `STAPEL_ATTRIBUTES["EXTRA_TYPES"]` reaches the builder with no release of
  this module *or* of the React pair.
- **Every registered kind is listed**, not just the allowlisted ones — a
  schema published before a kind left `STAPEL_FORMS["FIELD_KINDS"]` still has
  to render. `allowed` is what says which kinds may be offered for a *new*
  field.
- A kind that declares **no** config form (upstream's `convertible_unit`)
  appears with `"fields": []`; a kind the host allowlisted that the registry
  does not carry appears with `"registered": false`. Both are listed rather
  than omitted, because an omission reads as "this kind does not exist" and
  a builder would silently drop the field.
- `config_widgets` is upstream's `config_form.FIELD_KINDS`: the *widget*
  vocabulary a declaration's `kind` draws from. Named apart from `kinds`
  deliberately — this module's own `FIELD_KINDS` setting is the feature-type
  allowlist, and two different things under one name is a rendering bug
  waiting to happen.

`forms.manage`, not `forms.view`: the catalogue names every type a deployment
registered, host types included, and a principal who cannot build a form has
no use for the builder's dictionary.

### Response listing and export paging

Keyset, newest first: `?before=<iso8601>&limit=<n>` (`MAX_PAGE_SIZE` caps it),
plus `?version=<n>` to restrict to one schema version. The export streams CSV
and returns its continuation cursor in the **`X-Forms-Next-Before`** response
header — Z-suffixed, because a bare `+00:00` in a query string decodes to a
space and the second page would silently 400.

### Error keys — owned vs. surfaced

`docs/errors.json` carries **75** keys: 42 core-owned, 21 owned here, and the
12 `error.400.feature_*` / `error.400.description_*` keys owned by
**stapel-attributes**. That last group is not decoration — per-field answer
validation *is* the attributes pipeline, so `POST /public/<id>/submissions/`
puts one of those codes at the top level of a per-field refusal (plus the
whole set under `params.fields[]`). An artifact that omitted them meant every
frontend bundle generated from it missed exactly the errors a respondent is
most likely to see, and they rendered as raw keys.

The mechanism is one line in `errors.py`:

```python
import stapel_attributes.errors  # forces the registration
```

stapel-attributes is an embedded (non-app) library, so Django's
`autodiscover_modules("errors")` never reaches it and the keys would
otherwise enter the registry only as a side effect of whichever serializer
happened to import first. The same line appears in stapel-listings and
stapel-categories, which embed the same engine.

**This is a re-export, not a claim.** `register_service_errors` infers the
owner from the *calling* package, so the keys stay owned by
`stapel_attributes`; `STAPEL_FORMS_ERRORS` and the `/error-keys/` listing the
stapel-translate collector reads carry only `error.<status>.forms_*`. Copying
the English strings into this module's registry instead would have taken on a
catalogue obligation that is upstream's — `tests/test_contract.py` asserts the
`owner` field so that mistake goes red.

Consequence, stated rather than hidden: stapel-attributes ships **no**
`translations/errors.<lang>.json`, so emission prints
`[warning:unshipped] 'stapel_attributes' owns 12 declared code(s) but ships no
errors catalog in any language`. The keys are declared and English-covered;
localizing them is an upstream contribution (§12.6), and until it lands a
frontend bundle either falls back to English or carries its own strings.

An alternative exists for a host that would rather not rely on the import:
`settings.STAPEL_ERROR_MODULES = ["stapel_attributes.errors"]`, which
`generate_error_keys` also honours. It is redundant here and harmless.

---

## 4. Capabilities

Four workspace capability strings, and — since 0.3.0 — one source for all of
them:

```python
# stapel_forms/authz.py
ACTION_CAPABILITIES = {
    "view":             "forms.view",
    "manage":           "forms.manage",
    "responses.view":   "forms.responses.view",
    "responses.manage": "forms.responses.manage",
}
CAPABILITIES = tuple(ACTION_CAPABILITIES.values())   # derived, not restated
```

### Where a consumer reads them

| Artifact | Shape | For |
|---|---|---|
| `docs/capabilities.json` → `capabilities[]` | `{key, gates:{operations[], behavior}, curated:{summary, business_label}}` | a deployment, a catalogue, a role-editor UI: what each grant means and exactly which operations it opens |
| `docs/schema.json` → per operation | `"x-stapel-capability": "forms.responses.manage"` | a generated client: which capability gates *this* call |
| the rendered description of each operation | `**Capability:** \`forms.responses.manage\`` | whoever is reading Swagger |
| `stapel_forms.authz.capability_for(action)` | the string | server-side callers, instead of typing `"forms.*"` literals |

The `capabilities[]` entry deliberately mirrors an `axes[]` entry — same
`key` / `gates.operations` / `gates.behavior` / `curated` shape — so a
consumer walks both with the same code. `axes` answers *what may this
deployment do*; `capabilities` answers *who in it may do it*.

### Why the projection cannot lie

A capability that answers "yes" while the endpoint answers 403 is worse than
no capability at all, because a UI trusts it and renders a control that leads
to a refusal. Nothing here asserts that the published string and the enforced
string agree — they are **the same object**:

```
@gated("responses.manage")            ← the only place the action is named
        │
        ├─ sets it on the request  → _access_error() → authorize() → workspaces
        └─ sets it on the function → CapabilityAwareAutoSchema
                                        → x-stapel-capability in schema.json
                                        → capabilities[] in capabilities.json
```

Consequences worth knowing:

- an admin handler that reaches the gate without `@gated` raises
  `ImproperlyConfigured` — an undeclared action is a loud failure, never a
  default;
- `@gated("typo")` is a `ValueError` at import, so a mistyped action never
  boots;
- emission fails if a capability `authz` enforces is projected by no
  operation, or if the schema projects a capability `authz` does not enforce;
- `make contract-check` catches a changed declaration as artifact drift.

On top of that, `tests/test_capability_projection.py` drives **every** gated
route twice — granted only its published capability (must not refuse) and
granted every other capability (must refuse) — so the contract is checked
behaviourally as well as structurally.

**What the capability cannot tell you:** whether a 403 means "not granted" or
"the workspaces service is unreachable". See §3.

### Granting them

Declared in full on day 1 so a host's role overlay never has to migrate.
stapel-workspaces ships no per-module defaults — only `owner` has `*` — so a
host grants them:

```python
STAPEL_WORKSPACES = {
    "ROLES": {
        # An entry REPLACES the whole role; there is no deep merge.
        "admin": ["forms.view", "forms.manage",
                  "forms.responses.view", "forms.responses.manage", ...],
        "member": ["forms.view", ...],
    }
}
```

Separately, `Submission` is declared `@access.sensitive` for the staff mandate
(`stapel_core.access`): staff view needs MID clearance, any mutation HIGH.
That governs Django admin and staff tooling and is orthogonal to the workspace
capabilities above — two doors, both shut by default.

---

## 5. The schema

A form schema is:

```json
{
  "fields": [ {"slug": "...", "name": "...", "mandatory": false, "config": {"type": "string", "maxLength": 200}} ],
  "meta": {"title": "...", "description": "...", "confirmation_text": "...", "submit_label": "..."}
}
```

`fields` are **stapel-attributes `FeatureDef` dicts** — the same structures a
category uses to type a listing. Config keys are the attribute type's own, and
they are **camelCase** (`maxLength`, `minLength`, `allowCustom`). A key the
type does not know is dropped by its dataclass parser, so `max_length` would
be a length cap that silently does not exist — `publish` refuses those rather
than shipping a form that looks capped and is not.

**On `FeatureValidationResult.warnings` (stapel-attributes 0.4.6):** the
engine now reports an unrecognized config key as a non-blocking warning
instead of dropping it in silence. Nothing here surfaces it, and that is not
an oversight — `schema.validate_schema` runs the *same* set-difference against
the type's config dataclass one step earlier and answers
`400 error.400.forms_invalid_schema`. This module is strictly stricter, so the
engine never reaches the branch that would populate `warnings` on a publish.
Should that gate ever soften, the warnings are already on the result object
and only need a field on the publish envelope.

`meta.logic` is reserved and unused: conditional branching is a v2 fork, and
reserving the key keeps adding it additive.

### Lifecycle

```
draft ──PUT /draft──> draft_schema ──POST /publish──> FormVersion(n+1), active
                                                     └─ POST /state {open} ──> accepting
                                                                             └─ {closed} ──> 410
```

Publishing validates the draft (field cap → kind allowlist → duplicate slugs →
unknown config keys → per-field config validity), mints `head+1`, repoints
`active_version` and clears the draft — all in one transaction with the
`form.published` emit.

Form-level fields that do **not** version: the admin-facing title, the notify
recipients, the state, the retention override. They describe the container.
The rendered title, description and confirmation text live in the schema meta,
because respondents saw them.

---

## 6. Events

Emitted inside the mutating transaction (outbox canon). Schemas in
`schemas/emits/`.

| Action | Payload |
|---|---|
| `form.published` | `{form_id, workspace_id, version}` |
| `form.closed` | `{form_id, workspace_id}` |
| `form.submission.received` | `{form_id, form_version, submission_id, workspace_id}` |

**Ids only.** The outbox has no retention and a durable bus fans out to every
subscriber, so respondent answers do not ride it; a consumer that needs
content fetches it under `forms.responses.view`.

Consumed: `user.deleted` (→ GDPR erasure) and this module's own
`form.submission.received` (→ the notify subscriber, so a notification outage
can never roll back a respondent's answer).

Provided comm Functions: **none** in v1. `forms.get_schema` has no consumer
today — the renderer uses HTTP and so can a server-side caller. `functions.py`
exists so the first real one has an obvious home.

---

## 7. Respondent data: retention, erasure, GDPR

**Authenticated respondents** are inside the platform apparatus.
`FormsGDPRProvider(section="forms")` registers itself in `apps.py:ready()`:

- `export(user_id)` returns their submissions **with the answers in full** —
  unlike stapel-docs, where content is workspace work product. A form answer
  is something the respondent wrote about themselves into somebody else's
  questionnaire; it is theirs.
- `delete(user_id)` / `anonymize(user_id)` **erase content, keep the
  tombstone**: `answers={}`, `client_meta=None`, `submitted_by=None`,
  `erased_at=now()`. The row survives so counts stay truthful ("300 responses,
  2 erased"). Idempotent.

A host **must** also declare the section, or the closure never completes:

```python
STAPEL_GDPR = {"DATA_OWNERS": [..., "forms"]}   # omitting it is gdpr.E002
```

`stapel_forms.W003` warns about exactly this.

**Anonymous respondents** have no self-service erasure channel, and the module
says so rather than implying one. stapel-gdpr keys every subject on `user_id`;
an email typed into a field is opaque answer content. What v1 gives instead:

1. finite retention — `RETENTION_DAYS = 365`, per-form overrides in
   `Form.settings.retention_days` may only **shorten** (lengthening past the
   module ceiling requires raising the ceiling, so one form cannot rewrite the
   deployment's promise);
2. a purge that runs — see §8;
3. `DELETE /submissions/<id>` under `forms.responses.manage`, the practical
   channel for a request arriving by email.

---

## 8. Scheduling the retention purge

```python
from stapel_forms.tasks import get_forms_beat_schedule

CELERY_BEAT_SCHEDULE = {**get_forms_beat_schedule(), ...}
```

Celery is optional: `stapel_forms.tasks.purge_expired_submissions` is a plain
callable any scheduler can invoke, and `manage.py forms_purge_expired` is the
cron form. `stapel_forms.W002` fires when a host has a beat schedule with no
entry pointing at `PURGE_TASK_NAME` — a retention policy nobody schedules is a
promise, not a mechanism.

---

## 9. Integration checklist

1. **Grant capabilities** in `STAPEL_WORKSPACES["ROLES"]` (§4) — without this
   every admin request denies.
2. **Configure a captcha backend** (`STAPEL_CAPTCHA["SECRET"]`) or set
   `STAPEL_FORMS["ALLOW_UNCAPTCHAED_PUBLIC"] = True` to record that the
   refusal is deliberate. `stapel_forms.W001` warns while neither is true and
   an open public form exists.
3. **Declare the GDPR section** (§7).
4. **Schedule the purge** (§8).
5. **Register the notification types** — see the TODO below.
6. Optionally set `DATA_PLANE_APPS` to include `forms` on an isolation-tier
   host.

### ⚠️ TODO — notification routing (must be done by the host until the upstream lands)

This module requests two notification types:

| Type | When |
|---|---|
| `forms.submission_received` | a form was answered (cooldown-gated, `{form_id, form_title, new_count}`) |
| `forms.submission_resend` | an admin re-sent one response (`{form_id, form_title, submission_id, submitted_at, answers}`) |

Both route to `email` and `telegram` — the telegram channel shipped in
stapel-notifications 0.13.0 and the direct `telegram_chat_id` address in
stapel-core 0.31.0, so a form can name a chat with no account behind it.

**Neither is registered in `stapel_notifications.routing.NOTIFICATION_ROUTING`
yet.** That entry is a cross-repo contribution landing in a later release wave
(the `workspace.*` family is the precedent). `manage.py check_notifications`
will flag both call sites until it does, and an unregistered type does not get
delivered.

Until then a host bridges them, verbatim:

```python
STAPEL_NOTIFICATIONS = {
    "TYPES": {
        "forms.submission_received": {
            "channels": ["email", "telegram"], "group": "system", "transactional": True,
        },
        "forms.submission_resend": {
            "channels": ["email", "telegram"], "group": "system", "transactional": True,
        },
    },
}
```

The same two dicts are exported as `stapel_forms.notifications.ROUTING_ENTRIES`
so the bridge and the future upstream entry cannot drift.

A host that wants its own copy also adds templates to
`DEFAULT_EMAIL_TEMPLATES` (e.g.
`"forms.submission_received": "notifications/email/forms_submission_received.html"`).

### Where a form's notifications go

`Form.settings` names destinations, and each maps to the
`request_notification` keyword that addresses it — adding a channel is an
entry in `stapel_forms.notifications.TARGET_KINDS`, never a branch at a call
site:

```python
form.settings = {
    "notify_emails": ["sales@example.com"],
    "notify_telegram_chat_ids": ["-1001234567890"],   # a chat, no account behind it
}
```

`POST /submissions/<id>/resend` takes `{"recipients": [...]}` and/or
`{"telegram_chat_ids": [...]}` to override those for one send. An override
**replaces** the form's targets rather than adding to them: "send this one to
legal" must not also re-send it to everybody who already got it.

---

## 10. Extension seams

| Seam | Kind | What it changes |
|---|---|---|
| `STAPEL_FORMS["FIELD_KINDS"]` | allowlist | which attribute kinds a form may ask |
| stapel-attributes type registry | merge registry | the field vocabulary itself — contribute a type there, not here |
| `STAPEL_SWAP` presenter keys | swap | `FORMS_FORM_PRESENTER`, `FORMS_VERSION_PRESENTER`, `FORMS_SUBMISSION_PRESENTER` |
| `SerializerSeamMixin` | class override | request/response serializer of any view |

Since 0.3.0 the seam is core's canonical one: every view here derives from
`stapel_core.django.api.views.StapelAPIView` (admin views through the local
`AdminAPIView`, which adds the capability-projecting schema), and the local
copy of `SerializerSeamMixin` is deleted. The attributes and getters a host
overrides are unchanged.

The anonymous envelope is deliberately **not** swappable: it is the one shape
whose contents are a security decision. Neither is the capability of a route:
`@gated` is a declaration, not a seam — a host that could re-point it would
be able to widen an endpoint without the contract saying so.

There are no dotted-path `import_strings` in this module. The seams are the
attributes registry server-side and the `@stapel/forms-react` widget/slot
registries client-side — not a storage backend.

---

## 11. Deliberate non-goals

- **File-upload fields.** stapel-cdn refuses unattributable principals by
  design, has no service-side byte ingest, and — decisive — no auth-gated
  download. A stranger's résumé served world-readable by URL is the open
  switch the security programme closes. Kinds implying binary payloads are
  simply absent from `FIELD_KINDS`; the honest path is an upstream cdn
  contribution.
- **Conditional logic / branching / multi-page.** A rules engine on both sides
  of the wire. `meta.logic` is reserved.
- **Multi-language form content.** Labels are admin-authored strings.
- **Realtime response feed.** Polling. The stream name
  `forms:ws:<workspace_id>` is reserved for when the realtime substrate lands;
  modules do not open sockets.
- **Honeypot fields.** No fleet precedent; captcha + throttle + caps cover the
  class.
- **Quotas or billing on submission volume.** The caps are abuse bounds, not
  metering.
- **A webhook/reaction layer.** `stapel-webhooks` does not exist; this module
  emits the fact and hardwires exactly one reaction. When the layer lands it
  subscribes to `form.submission.received` and nothing here migrates.

---

## 12. Upstream contributions this module is waiting on

Recorded so they are debts rather than folklore:

1. **`TokenPathNoLogMixin` into `stapel_core.django.api`.** It lives in
   stapel-workspaces; this module replicates the six lines with the origin
   named in the docstring. Two copies is the moment to upstream.
2. **`NOTIFICATION_ROUTING` entries** for the two types in §9. The telegram
   channel itself already landed (notifications 0.13.0 / core 0.31.0), so
   this is the last piece: two dict entries and their email templates.
3. **`require_capability` distinguishing outage from denial** in stapel-core,
   which is what would make the `unavailable` → 503 branch in §3 fire.
   Re-verified still open on core 0.45.0. It is now the ONE thing the
   capability projection has to publish a caveat about, so closing it also
   removes a line from every `capabilities[].gates.behavior`;
   `tests/test_capability_projection.py::test_a_workspaces_outage_still_renders_403_not_503`
   goes red the moment it lands, which is how the caveat gets deleted
   instead of outliving the defect.
4. **An email-keyed GDPR subject** in stapel-gdpr, which is what would give
   anonymous respondents a self-service erasure channel (§7).
5. ~~**A `multiline` param on the attributes `string` type**~~ — **landed** in
   stapel-attributes 0.4.6 (the floor this module now pins), declared in
   `config_form._string_form()` and served through `GET /field-kinds`.
6. **A `capabilities` section in `stapel_tools.llms_txt`.** The generator
   renders header / axes / operations / errors / extension_points / requires
   / surface, and has no section for the workspace-capability block this
   module now emits into `docs/capabilities.json`. An agent reading
   `llms.txt` alone therefore still cannot see which capability gates which
   route — it has to open `capabilities.json` or the `x-stapel-capability`
   field in `schema.json`. Teaching the generator the section is a
   stapel-tools change; faking it with prose in `capabilities.meta.json`
   would be a second hand-kept copy of exactly the table this release
   stopped hand-keeping.
7. **`translations/errors.<lang>.json` in stapel-attributes.** It owns 12
   keys this module's API returns and ships catalogues for none of them, so
   `make contract` warns `unshipped` on every emission and a localized
   deployment renders that family in English (§3). The strings exist in the
   React pair's hand-authored ru/es bundles; upstreaming them is the fix.
