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
| `learner` | `training:read` |
| `supervisor` | `training:read`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write` |
| `admin` | `*` |

A session signed in with a **PIN** carries `training:read` only, whoever it
is: a PIN is short, so it opens the learner app's own training and nothing
more. A supervisor sees their own team (the people whose supervisor they
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
  "refresher_months"?: 1 to 240 }` → `201`.
- `GET /v1/competencies?kind=&active=` — `{ "items", "total" }` by name;
  `GET /v1/competencies/{key}`
- `PATCH /v1/competencies/{key}` — `name` and/or `refresher_months` (`null`
  for none). The kind cannot change.
- `POST /v1/competencies/{key}/deactivate`, `/reactivate` — a deactivated
  competency is asked of nobody; its records stay.

Each competency: `{ "id", "key", "name", "kind", "refresher_months", "active", "created_at" }`.
In step 1 every kind is recorded by hand; modules, practicals, tickets and
policies get their own ways in with later build steps.

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
     "created_at": "…" }]
  ```
- `POST /v1/people/{code}/records` (`records:write`) — `{ "competency",
  "granted_on", "expires_on"?, "note"? }` → `201`. `granted_on` can't be in
  the future; `expires_on` (the last good day, e.g. a ticket's card date)
  must be after it. Nobody records their own (`403 { "code": "own_record" }`).
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
`{ "person": { "code", "name" }, "today", "items": [{ "key", "name", "kind", "status", "granted_on", "expires_on" }] }`.
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).

## System

- `GET /v1/health` → `{ "status": "ok" }` once the database answers.
