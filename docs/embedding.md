# Putting a form on a website

Everything a front-end needs to render a stapel-forms form and accept an
answer from a stranger. Copy-pasteable; nothing here requires an account,
a session, a workspace or a capability.

The whole public surface is **two routes**, and this document is the
contract for both.

---

## 1. Get the form's public id

A form's only public handle is its `public_id` — a 22-character random
token, **not** the row's UUID. It is minted at creation and shown in the
Django admin on the form's page (`Public link`), or returned by
`GET /forms/api/v1/forms/<uuid>` as `public_id`.

Two properties worth knowing before you paste it into a page:

- **It is a capability, not a secret name.** Anyone holding it can fetch
  the schema and answer the form. That is the point — it is what a
  stranger on your marketing site holds.
- **It can be rotated** (`POST /forms/<uuid>/rotate-link`) without
  re-keying the form. Rotating invalidates every embed of the old handle,
  which is exactly what you want after a leak and exactly what you do not
  want by accident. **Anything embedded in a page you cannot redeploy
  quickly should use a stable, memorable handle instead** — a host may set
  `public_id` to a readable slug (a host's feedback form is literally
  `acme-feedback`).

---

## 2. Fetch the schema

```
GET https://<your-host>/forms/api/v1/public/<public_id>/
```

```jsonc
{
  "public_id": "acme-feedback",
  "version_id": "9aa1b2c3-...",     // echo this back on submit
  "version": 3,
  "fields": [
    {
      "slug": "full_name",
      "name": "Full name",           // the label to render
      "mandatory": true,
      "config": {"type": "string", "maxLength": 200, "multiline": false}
    },
    {
      "slug": "plan",
      "name": "Plan",
      "mandatory": true,
      "config": {
        "type": "select",
        "options": [{"value": "basic", "label": "Basic"},
                    {"value": "pro",   "label": "Pro"}]
      }
    }
  ],
  "meta": {
    "title": "Contact us",
    "description": "We answer within a day.",
    "submit_label": "Send",
    "confirmation_text": "Thanks — we will be in touch."
  }
}
```

`config.type` is a **stapel-attributes** field kind. The kinds a form may
use are `string`, `int`, `float`, `bool`, `select`, `date`, `header`,
`hex_color`, `hierarchical_select`, `convertible_unit` (the deployment's
`STAPEL_FORMS["FIELD_KINDS"]` allowlist). Note:

- **config keys are camelCase** (`maxLength`, `minLength`, `allowCustom`);
- a **`header`** field is a section caption. It takes no answer — render it
  and do not send a value for it;
- `meta.title` / `meta.description` are what the respondent should see;
  the admin-facing `Form.title` is a different, internal string and is
  never served here.

**Status codes.** `200` normal. `404` — unknown handle, soft-deleted form,
or a form that has never been published; all three answer byte-identically
so the endpoint cannot be used to enumerate forms. `410` — the form is
**closed** (its handle was public by definition, so a renderer needs to
tell "closed" from "broken link"). `429` — throttled.

The envelope carries no workspace id, no internal id, no author and no
counts, and it never will; treat any other field as absent.

---

## 3. Send an answer

```
POST https://<your-host>/forms/api/v1/public/<public_id>/submissions/
Content-Type: application/json
```

```json
{
  "answers": {"full_name": "Ada Lovelace", "plan": "pro"},
  "version_id": "9aa1b2c3-...",
  "captcha_token": "<token, when your captcha tier asks for one>"
}
```

- `answers` is `{slug: value}` — the slugs from `fields[]`, and nothing
  else. An unknown slug is refused (`error.400.forms_unknown_field`)
  rather than ignored: on a public endpoint an unexpected key is a client
  probing what reaches storage.
- **Send `version_id`.** It is what you echo from the schema you rendered.
  Omit it and the answer is validated against whatever is active at the
  moment it lands; send it and a publish racing your respondent becomes a
  clean `409 error.409.forms_version_superseded` instead of a silent
  mis-validation against a form they never saw.
- Do not send a value for a `header` field.

**Success — `201`:**

```json
{"accepted": true, "confirmation": "Thanks — we will be in touch."}
```

Render `confirmation`. There is deliberately **no submission id**: there
is no public read of responses, so an id would be a handle to nothing.

**Refusals.**

| Status | Meaning |
|---|---|
| `400` | validation. Per-field detail in `params.fields[]`, each with `params.field` naming the slug — route each onto its control. |
| `404` | unknown handle / unpublished / deleted |
| `409` | `forms_version_superseded` — re-fetch the schema and ask the respondent to confirm |
| `410` | the form is closed |
| `413` | body over `MAX_SUBMISSION_BYTES` (64 KB default) |
| `429` | throttled |

Per-field errors use the **stapel-attributes** error family
(`error.400.feature_*`, `error.400.description_*`) — those 12 keys are in
`docs/errors.json` and are the ones a respondent hits most, so make sure
your generated error bundle includes them.

---

## 4. A copy-pasteable embed

No framework, no build step. Drop this in a page, set the two constants.

```html
<div id="stapel-form"></div>
<script>
(async function () {
  const BASE = "https://app.example.com/forms/api/v1";
  const PUBLIC_ID = "acme-feedback";

  const root = document.getElementById("stapel-form");
  const res = await fetch(`${BASE}/public/${PUBLIC_ID}/`);
  if (!res.ok) { root.textContent = res.status === 410
      ? "This form is closed." : "This form is unavailable."; return; }
  const form = await res.json();

  const el = document.createElement("form");
  el.innerHTML = `<h2>${form.meta.title ?? ""}</h2>
                  <p>${form.meta.description ?? ""}</p>`;

  for (const f of form.fields) {
    const t = f.config.type;
    if (t === "header") { el.insertAdjacentHTML("beforeend", `<h3>${f.name}</h3>`); continue; }
    const label = document.createElement("label");
    label.textContent = f.name + (f.mandatory ? " *" : "");
    let input;
    if (t === "select") {
      input = document.createElement("select");
      if (!f.mandatory) input.add(new Option("", ""));
      for (const o of f.config.options ?? []) input.add(new Option(o.label, o.value));
    } else if (t === "bool") {
      input = document.createElement("input"); input.type = "checkbox";
    } else if (t === "string" && f.config.multiline) {
      input = document.createElement("textarea");
    } else {
      input = document.createElement("input");
      input.type = t === "int" || t === "float" ? "number" : t === "date" ? "date" : "text";
    }
    input.name = f.slug;
    input.required = !!f.mandatory;
    label.appendChild(input);
    el.appendChild(label);
  }

  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = form.meta.submit_label || "Send";
  el.appendChild(button);

  el.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    const answers = {};
    for (const f of form.fields) {
      if (f.config.type === "header") continue;
      const node = el.elements[f.slug];
      let value = node.type === "checkbox" ? node.checked : node.value;
      if (value === "" && !f.mandatory) continue;      // omit, do not send ""
      if (f.config.type === "int")   value = parseInt(value, 10);
      if (f.config.type === "float") value = parseFloat(value);
      answers[f.slug] = value;
    }
    const post = await fetch(`${BASE}/public/${PUBLIC_ID}/submissions/`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({answers, version_id: form.version_id}),
    });
    if (post.status === 201) {
      const body = await post.json();
      root.textContent = body.confirmation || "Thank you.";
      return;
    }
    button.disabled = false;
    if (post.status === 409) { root.prepend("This form was just updated — please reload."); return; }
    if (post.status === 429) { root.prepend("Too many attempts. Try again later."); return; }
    const err = await post.json().catch(() => ({}));
    for (const fieldError of err?.params?.fields ?? []) {
      console.warn(fieldError.params?.field, fieldError.message);
    }
  });

  root.replaceChildren(el);
})();
</script>
```

For a React host, do not write this by hand — `@stapel/forms-react` ships
`<StapelForm publicId="…" />`, which needs no session, no workspace and no
auth, only `createFormsRuntime({ baseUrl })`.

---

## 5. Throttling and captcha — what your embed will actually hit

Both public routes are throttled per module namespace, and both ship
**on**:

| Setting | Default | Guards |
|---|---|---|
| `PUBLIC_SCHEMA_THROTTLE` | `120/h` | the GET |
| `SUBMIT_THROTTLE` | `20/h` | the POST |
| `MAX_SUBMISSION_BYTES` | `65536` | checked against `Content-Length` **before** the JSON parse |
| `MAX_SUBMISSIONS_PER_FORM` | `10000` | past the cap the form answers submits as if closed |

A `429` is normal traffic for a public form, not an incident: show a
retry message, do not silently swallow it.

**Captcha** is netintel-tiered through `@captcha_protected`: whether a
token is required at all is decided per request from the caller's
reputation, so your embed should send `captcha_token` when it has one and
omit it otherwise — do not gate your own UI on a fixed rule. A deployment
with open public forms and no captcha secret raises `stapel_forms.W001`
until it either configures `STAPEL_CAPTCHA["SECRET"]` or records the
decision with `STAPEL_FORMS["ALLOW_UNCAPTCHAED_PUBLIC"] = True`.

---

## 6. What you are promising the respondent

Worth putting in your page's own words, because the module cannot say it
for you:

- Answers are stored as typed values and **retained for a finite time**
  (`RETENTION_DAYS`, 365 by default; a form may shorten it, never
  lengthen past the deployment ceiling).
- Respondent IP/User-Agent are **not stored** unless the host turned
  `STORE_CLIENT_META` on.
- A signed-in respondent's answers are in their GDPR export and are erased
  with their account. **An anonymous respondent has no self-service
  erasure channel** — retention and `DELETE /submissions/<id>` are the
  mechanisms. If your form collects sensitive categories, say so in
  `meta.description`.
