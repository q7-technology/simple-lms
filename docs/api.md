# Simple LMS — API

Base path `/v1`. JSON in, JSON out. Dates are `YYYY-MM-DD`, times ISO 8601
in UTC. Interactive docs are at `/docs`.

## Shared rules

- **Auth:** `Authorization: Bearer <token>`. A token comes from
  `POST /v1/auth/login` (email and password) or `POST /v1/auth/pin-login`
  (code and PIN). The desktop and the learner app use these endpoints and
  nothing else: the API is the only door.
- **Errors:** a missing, ended or unknown token is `401`. Signed in but not
  allowed is `403` with `{ "detail", "code" }`. Validation problems are
  `422` with `{ "errors": [{ "field", "message" }] }`. Something that is not
  there (or not yours to see) is `404` with `{ "detail" }`. Well formed but
  not possible as things stand is `409` with `{ "detail", "code" }`.
- **Never deleted:** people and competencies are deactivated, not deleted.
  The training record and the extras and waivers are append-only: the latest
  row for a person and competency is the one that counts.
- **Codes and keys:** a person's code is kept upper case (`ll042` finds
  `LL042`); role and competency keys are kept lower case. Emails are kept
  lower case.

## Who may do what

| Permission | Scopes (signed in with a password) |
| --- | --- |
| `learner` | `training:read`, `training:write` |
| `supervisor` | `training:read`, `training:write`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify` |
| `admin` | `*` |

`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket. A session signed in with a **PIN** carries
`training:read` and `training:write` only, whoever it is: a PIN is short, so
it opens the learner app's own training and nothing more. A supervisor sees their own team (the people whose supervisor they
are); a manager or admin sees everyone. Only an admin adds or changes a
manager or an admin (`403 { "code": "admin_only" }`).

## Sign in

### POST /v1/auth/login
`{ "email", "password" }` → `200`
```json
{
  "token": "lms_s.…",
  "person": { "id": 2, "code": "MG001", "name": "Mel Grant", "email": "mel@example.com.au",
              "permission": "manager", "method": "password",
              "scopes": ["training:read", "…"], "idle_seconds": 43200 }
}
```
A wrong password, an unknown email, or someone with no password is `401`
`{ "detail": "wrong email or password", "code": "wrong_password" }`. Five
wrong in a row lock the password for 15 minutes (`"code": "locked"`).

### POST /v1/auth/pin-login
`{ "code": "LL042", "pin": "2468" }` → `200`, the same shape with
`"method": "pin"` and `"idle_seconds": 900`. A wrong PIN or unknown code is
`401 { "code": "wrong_pin" }`. Five wrong PINs lock the PIN
(`"code": "locked"`) until a manager sets a new one.

A session ends on sign-out, after its idle time without a request (15
minutes for a PIN, 12 hours for a password), after 12 hours (PIN) or 14 days
(password) in all, when the person's PIN or password is changed, or when they
are deactivated.

### POST /v1/auth/logout
Ends the session whose token is sent. `204`, even if it had already ended.

### GET /v1/auth/me
The `person` object above, for the session's token.

The first admin is made on the command line:
`lms create-user --code AD001 --name "…" --email … [--permission admin]`
(prompts for the password, at least 12 characters).

## People

`people:read` to list and read, `people:write` to change.

- `POST /v1/people` — `{ "code", "name", "email"?, "permission"?
  ("learner"), "supervisor"? (a code), "roles"? ([keys]), "pin"? (4 to 8
  digits), "password"? (12 or more) }` → `201`. A code or email already
  taken is `422`. A supervisor must be active and have the supervisor,
  manager or admin permission.
- `GET /v1/people?active=true|false&q=&role=` — `{ "items", "total" }` by
  name. `q` matches part of the code, name or email, as typed (`%` and `_`
  are only themselves, not wildcards); `role` is a role key.
- `GET /v1/people/{code}`
- `PATCH /v1/people/{code}` — any of `name`, `email`, `permission`,
  `supervisor`; `null` clears an email or a supervisor. Nobody is their own
  supervisor. Nobody changes their own permission (`409 { "code": "self" }`).
  Taking someone below supervisor while they still supervise active people
  is `409 { "code": "has_team" }`: give their team another supervisor first.
- `PUT /v1/people/{code}/roles` — `{ "roles": [keys] }`, in full.
- `POST /v1/people/{code}/pin` — `{ "pin" }`: a new PIN, which also unlocks
  a locked one. Their PIN sessions end.
- `POST /v1/people/{code}/password` — `{ "password" }`: a new password,
  which also lifts a lock. Their password sessions end.
- `POST /v1/people/{code}/deactivate`, `/reactivate` — deactivating ends
  their sessions; their records stay. Nobody deactivates themselves (`409
  { "code": "self" }`), and someone who still supervises active people is
  `409 { "code": "has_team" }` until their team has another supervisor.

The `pin`, `password`, `deactivate` and `reactivate` calls answer `200` with
the person.

Each person:
```json
{ "id": 4, "code": "LL042", "name": "Kim Lee", "email": null, "permission": "learner",
  "supervisor": { "code": "SV001", "name": "Sam Vu" },
  "roles": [{ "key": "forklift-operator", "name": "Forklift operator" }],
  "active": true, "has_pin": true, "pin_locked": false, "has_password": false,
  "created_at": "…", "last_login_at": null }
```
A PIN or password is never returned.

## Roles

`roles:read` to list and read, `roles:write` to change.

- `POST /v1/roles` — `{ "key": "forklift-operator", "name": "Forklift operator" }` → `201`.
- `GET /v1/roles` — `{ "items", "total" }` by name; `GET /v1/roles/{key}`
- `PATCH /v1/roles/{key}` — `{ "name" }`
- `PUT /v1/roles/{key}/requirements` — `{ "competencies": [keys] }`, in
  full. An unknown competency is `422`, and so is adding a deactivated one;
  a deactivated competency the role already requires may stay.

Each role: `{ "id", "key", "name", "competencies": [{ "key", "name", "kind" }], "people", "created_at" }`,
where `people` is how many people have the role.

## Competencies

`competencies:read` to list and read, `competencies:write` to change.

- `POST /v1/competencies` — `{ "key": "site-induction", "name": "Site
  induction", "kind": "module" | "practical" | "ticket" | "policy",
  "refresher_months"?: 1 to 240, "card_expires"?: true }` → `201`.
  `card_expires` is for a ticket: whether its card has an expiry date that
  people type in (true unless said otherwise).
- `GET /v1/competencies?kind=&active=` — `{ "items", "total" }` by name;
  `GET /v1/competencies/{key}`
- `PATCH /v1/competencies/{key}` — `name`, `refresher_months` (`null` for
  none) and/or `card_expires`. The kind cannot change.
- `POST /v1/competencies/{key}/deactivate`, `/reactivate` — a deactivated
  competency is asked of nobody; its records stay.

Each competency: `{ "id", "key", "name", "kind", "refresher_months", "card_expires", "active", "created_at" }`.
Every kind can still be recorded by hand. Policies are signed in the
learner app and tickets sent in from it (below); modules and practicals get
their own ways in with later build steps.

## Extras and waivers

- `GET /v1/people/{code}/overrides` (`people:read`) — those in force, by
  competency name: `[{ "id", "competency": { "key", "name", "kind" }, "kind": "extra" | "waive", "note",
  "recorded_by": { "code", "name" }, "created_at" }]`.
- `POST /v1/people/{code}/overrides` (`people:write`) — `{ "competency",
  "kind": "extra" | "waive" | "clear", "note" }` → `201`. An extra asks this
  person for a competency their roles don't; a waiver lets them off one their
  roles do; a clear puts them back to what their roles say (`409 { "code":
  "nothing_to_clear" }` if there is nothing to clear). The note is required.
  Nobody adds an extra, waiver or clear for themselves, admins included
  (`403 { "code": "own_override" }`).
  The answer is the row just added, in the shape above.

## The training record

- `GET /v1/people/{code}/records?competency=` (`training:read`; your own,
  your team's, or anyone's for a manager; anyone else is `404`) — newest first; the first for a
  competency is the one that counts:
  ```json
  [{ "id": 7, "competency": { "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket" },
     "kind": "granted", "granted_on": "2026-03-01", "expires_on": "2031-03-01",
     "note": "LF 0012345, sighted", "recorded_by": { "code": "MG001", "name": "Mel Grant" },
     "policy_version": null, "signed_name": null, "signature": null, "ticket": null,
     "created_at": "…" }]
  ```
  `policy_version` is the policy version a grant is for; `signed_name` and
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one.
- `POST /v1/people/{code}/records` (`records:write`) — `{ "competency",
  "granted_on", "expires_on"?, "note"? }` → `201`. `granted_on` can't be in
  the future; `expires_on` (the last good day, e.g. a ticket's card date)
  must be after it. Nobody records their own (`403 { "code": "own_record" }`).
  A policy recorded by hand (signed on paper) is for its newest version.
  A deactivated person is `409 { "code": "inactive" }`; a deactivated
  competency is `422`. A wrong date is put right by recording the
  completion again with the right one.
- `POST /v1/people/{code}/records/revoke` (`records:write`) — `{
  "competency", "note" }` → `201`, a `revoked` row. Only a grant that counts
  now can be revoked (`409 { "code": "nothing_to_revoke" }`).

## Status

Worked out on every request, never stored:

| Status | When |
| --- | --- |
| `not_required` | no role or extra asks for it (or a waiver of something not asked) |
| `waived` | asked for, and waived |
| `missing` | asked for, and nothing granted (or the latest record is a revoke) |
| `current` | granted, and good for more than 30 days (or it never runs out) |
| `expiring` | granted, and its last good day is within 30 days (today included) |
| `lapsed` | granted, and its last good day has passed |

The last good day is the record's `expires_on` if it has one, else
`granted_on` plus the competency's refresher months, else never. Today is
the date in `LMS_TIMEZONE` (default `Australia/Melbourne`).

A **policy** with a version published counts only for its newest version:
a grant for an older version (or from before there were versions) is
`missing` again until they sign the new one.

## The matrix

### GET /v1/matrix
`matrix:read`. Filters: `role` (key), `supervisor` (code), `status` (comma
separated: people with at least one cell in it). An unknown status, or a
supervisor code that is nobody, is `422`. Active people by name; a
supervisor sees their own team. The columns are what any of them is asked
for, by name, and every person has a cell in every column:
```json
{
  "today": "2026-10-12",
  "competencies": [{ "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket" }],
  "people": [{
    "code": "LL042", "name": "Kim Lee",
    "roles": [{ "key": "forklift-operator", "name": "Forklift operator" }],
    "supervisor": { "code": "SV001", "name": "Sam Vu" },
    "cells": { "forklift-licence": { "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-01" } }
  }]
}
```

### GET /v1/matrix.csv
The same, with the same filters, as `text/csv`: `code, name, roles,
supervisor`, then a status column (`<name>`, e.g. `not required`) and an
expiry column (`<name> expires`) per competency, sent as an attachment named
`matrix-<today>.csv`. A cell that starts with `=`, `+`, `-`, `@`, a tab or a
carriage return is prefixed with `'`, so a spreadsheet doesn't run it.

### GET /v1/people/{code}/training
`training:read`; your own, your team's, or anyone's for a manager (anyone
else is `404`). What the
person is asked for and not let off, by name:
`{ "person": { "code", "name" }, "today", "items": [{ "key", "name", "kind", "status", "granted_on", "expires_on", "card_expires", "waiting" }] }`.
`waiting` is true while a ticket they sent in waits for a manager's check.
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).

## Files

Tickets' photos (or a PDF) and policy signatures. Sent before the ticket or
signature that names them; kept on the host under `LMS_UPLOAD_DIR`
(`/data/uploads`), named by a random id.

- `POST /v1/uploads?purpose=ticket|signature` (`training:write`) — the file
  as the request body (any `Content-Type`: what counts is its first bytes)
  → `201 { "id", "purpose", "content_type", "size_bytes", "created_at" }`.
  A ticket may be a JPEG, PNG or PDF of up to 20 MB; a signature a PNG of
  up to 1 MB. Anything else is `415 { "code": "unsupported_type" }`. Bigger
  than its purpose allows is `413 { "code": "too_large" }`: before the body
  is read when its `Content-Length` says so, and otherwise as soon as the
  body passes the limit (it is never read further). An unknown purpose is
  `422`, before any of the body is read.
- `GET /v1/uploads/{id}` — the file, for the person it belongs to, their
  supervisor, and managers and admins; anyone else gets `404` (and so does a
  file missing from disk). Sent with `Cache-Control: private, no-store`,
  `Content-Security-Policy: default-src 'none'; sandbox`,
  `X-Content-Type-Options: nosniff` and `Content-Disposition:
  <how>; filename="<id>.<ext>"`, where `<how>` is `inline` for an image and
  `attachment` for a PDF (which shows blank under the sandbox, so it is
  saved instead).

A ticket or signature may only name the caller's own uploads of the right
purpose. Each upload goes on one record or ticket only: the database holds
each signature to one record and each photo to one ticket.

## Policies

- `POST /v1/policies/{key}/versions` (`competencies:write`) — `{ "body",
  "note"? }` → `201`, the next version (1, 2, 3 …). Versions are never
  changed or deleted: what someone signed stays as they read it. Everyone
  asked for the policy needs to sign the new one. A deactivated policy is
  `409 { "code": "inactive" }`.
- `GET /v1/policies/{key}/versions` (`competencies:read`) — newest first:
  `[{ "id", "version", "body", "note", "published_by": { "code", "name" }, "created_at" }]`.
- `GET /v1/policies/{key}` (`training:read`) — the version to sign now:
  `{ "key", "name", "version": { … } }`; `404` until one is published.
- `POST /v1/policies/{key}/sign` (`training:write`) — your own signature:
  `{ "version", "signed_name", "signature" }` (an upload with purpose
  `signature`, yours) → `201`, the record (above), recorded as yours.
  `version` is the one you read: if a newer one came out meanwhile, `409 {
  "code": "new_version" }`. Once per version (`409 { "code":
  "already_signed" }`). The name is yours as Simple LMS has it, case and
  spacing aside (`422` on `signed_name`). A signature goes on one record
  only: one already used is `422` on `signature` ("this signature is already
  on a record: sign again"), and so is one that is not yours. A deactivated
  policy is `409 { "code": "inactive" }`; one with no version yet is `404`.

A key that is not a policy is `404` on all of these.

## Tickets

- `POST /v1/tickets` (`training:write`) — your own: `{ "competency",
  "number", "expires_on"?, "front", "back"? }` (`front` and `back` are your
  uploads with purpose `ticket`) → `201`, waiting. The competency must be an
  active ticket (`422`). `expires_on` (the card's last good day) is needed
  when the ticket's card expires and must be after today; it is left out
  when it doesn't (`422` either way). The back needs its own photo, not the
  front's, and a photo goes on one ticket only, waiting or decided (`422`:
  take a new one). One waits at a time for each ticket (`409 { "code":
  "already_waiting" }`).
- `GET /v1/tickets?status=pending|approved|rejected` (`tickets:verify`) —
  the inbox, oldest first (`pending` unless asked).
- `GET /v1/people/{code}/tickets` (`training:read`; your own, your team's,
  or anyone's for a manager; anyone else is `404`) — newest first.
- `POST /v1/tickets/{id}/approve` (`tickets:verify`) → `200`: a grant from
  today until the card's date, recorded by you, with the note `Ticket
  <number>, checked`. A card that ran out while it waited is `409 { "code":
  "card_ran_out" }`; the person or the competency deactivated while it
  waited is `409 { "code": "inactive" }`: send it back.
- `POST /v1/tickets/{id}/reject` (`tickets:verify`) — `{ "reason" }`
  (required) → `200`. The person sees the reason.

Nobody approves or rejects their own, admins included (`403 { "code":
"own_ticket" }`). A ticket is decided once (`409 { "code": "decided" }`).
Each ticket:
```json
{ "id": 7, "person": { "code": "LL042", "name": "Kim Lee" },
  "competency": { "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket" },
  "number": "LF0012345", "expires_on": "2031-03-01", "front": "…", "back": null,
  "status": "pending", "reason": null, "decided_by": null, "decided_at": null, "created_at": "…" }
```

## Emails and the daily job

The worker sends email through SMTP (`LMS_SMTP_*` in `.env`) from the
outbox, trying a failed one again after 1 minute, 5, 30 and 2 hours, then
leaving it `failed`. Without `LMS_SMTP_HOST` and `LMS_SMTP_FROM` emails
wait in the outbox, untried. Links in them start with `LMS_PUBLIC_URL`
(none without it). Each day from `LMS_DAILY_HOUR` (6 am by default, in
`LMS_TIMEZONE`) it queues:

- a reminder to each active person with an email when something they are
  asked for has 30, 14 or 0 days left (the last good day itself), each once;
  a day missed still gets the reminder it owed, and each says the real days
  left;
- on Mondays, a digest for each active manager and admin with an email of
  what is lapsed and what is expiring, for everyone (none when nothing is).

`lms daily-job [--on YYYY-MM-DD]` queues them now (as if today were that
date); nothing is queued twice. A date it can't read is refused with exit
code 2.

## System

- `GET /v1/health` → `{ "status": "ok" }` once the database answers.
