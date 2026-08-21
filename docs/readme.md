## What this is

Admin-defined **forms** with **anonymous responses**. A workspace admin
defines a form's schema, the form gets a non-enumerable public handle, anyone
holding that handle can fetch the schema and answer it without an account, and
the admin reviews the answers.

Two decisions carry the whole design.

**The schema is a list of [stapel-attributes](https://github.com/usestapel/stapel-attributes)
`FeatureDef`s.** There is no `FormField` class here, no field-type enum, no
validation of its own: the fleet already has exactly one field-type vocabulary
— the same one that types a marketplace listing — and forms is its third
consumer. A host that registers a custom attribute kind gets it in forms for
free.

**A published version is immutable, and every response records which version
it answered.** Editing a live form publishes the next version; it never
rewrites a published one. A response is only interpretable against the schema
it answered — delete a field or narrow a choice list under a mutable schema
and `budget=3` becomes an orphan nobody can read. Snapshotting the schema into
every response would preserve meaning but destroy identity: "the 240 responses
to version 3" would become a JSON scan, and an export would have no stable
column set. A version row buys both, at one row per publish instead of one
snapshot per response.

## Quick start

```bash
pip install stapel-forms
```

```python
INSTALLED_APPS = [
    # ...
    "stapel_forms",
]

# urls.py
path("forms/", include("stapel_forms.urls"))   # -> /forms/api/v1/...
```

The admin surface asks the `workspaces.check_capability` comm Function
(fail-closed, deny-by-default) — install stapel-workspaces or provide that
Function, and grant `forms.*` to the roles that should have it. The two
respondent endpoints need none of that.

## The public surface is exactly two routes

```
GET  /forms/api/v1/public/<public_id>/               -> the active schema
POST /forms/api/v1/public/<public_id>/submissions/   -> 201 {accepted, confirmation}
```

`public_id` is a 22-character random token, not the row's UUID: rotating it
after a leak must not re-key the row, and the primary key never travels to an
anonymous caller. What the GET returns is a dedicated envelope — no workspace
id, no internal id, no author, no counts, no sibling forms — built by its own
presenter rather than the admin one with fields removed, because dropping
fields is how leaks happen the day somebody adds one.

Unknown handle, soft-deleted form and unpublished draft all answer **one
byte-identical 404**. A closed form answers **410**, because its handle was
public by definition and the renderer needs the difference between "this form
is closed" and "broken link".

## What a hostile submitter can and cannot do

Stated, because a security posture nobody wrote down is a security posture
nobody can check.

**Can**: burn its own IP budget; fill a form with garbage that passes typed
validation; consume rows up to the form's cap.

**Cannot**: enumerate forms (uniform 404 behind a throttled GET); learn the
workspace or any other tenant fact; store bytes outside typed answer values
(no file fields, and nothing reaches disk except what the version's own
configs produced through `normalize_to_dao`); make the module send mail at
attack rate (the notify cooldown is keyed on the form, and folds the interim
count into the next letter); read anything back (there is no public read of
responses — the POST returns confirmation text, not even a submission id); or
poison a reviewer's spreadsheet (CSV export escapes formula leads server-side,
so every consumer inherits the guard).

The ladder behind that: module-namespaced throttles, a `Content-Length` gate
before the JSON parse, netintel-tiered captcha (`@captcha_protected`), a
per-form submission cap, a per-workspace open-form cap, and the recipient-side
cooldown. Every one ships on; the confession switch is
`ALLOW_UNCAPTCHAED_PUBLIC`.

## Privacy, said plainly

Form answers are **respondent PII**. This module guarantees typed storage,
finite retention, erasure for authenticated respondents, and admin deletion.

It does **not** give anonymous respondents a self-service erasure channel.
stapel-gdpr keys every subject on `user_id`, and an email a stranger typed
into a field is opaque answer content, not a subject key — an email-keyed
subject is upstream platform work, not something a form module should fake.
What v1 answers with instead is a finite default retention (365 days, per-form
overrides may only shorten it), a purge job that actually runs, and
`DELETE /submissions/<id>` for the request that arrives by email.

Hosts collecting sensitive categories should say so in the form's own
description.

## Reacting to a response

```python
# The module's own reaction: tell the form's destinations, cooldown-gated.
# Each key maps to the request_notification keyword that addresses it, so a
# telegram chat needs no account behind it.
form.settings = {
    "notify_emails": ["sales@example.com"],
    "notify_telegram_chat_ids": ["-1001234567890"],
}

# Anything else subscribes to the fact:
@on_action("form.submission.received")
def route_it(event):
    ...  # {form_id, form_version, submission_id, workspace_id}
```

Events carry **ids only**. The outbox has no retention and a durable bus fans
out to every subscriber, so a respondent's answers never ride it; a consumer
that needs content reads it under `forms.responses.view`.

## Not in v1, deliberately

File-upload fields (the platform CDN cannot take custody of an anonymous
stranger's bytes and cannot gate reads — a résumé served world-readable by URL
is the open switch, not the feature); conditional logic and branching (the
schema reserves `meta.logic`); multi-language form content; a realtime
response feed; honeypot fields; quotas or billing on submission volume; draft
respondent saves, response editing and quiz scoring.
