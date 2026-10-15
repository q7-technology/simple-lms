# Simple LMS — API

Base path `/v1`. JSON in, JSON out. Dates are `YYYY-MM-DD`, times ISO 8601
in UTC. Interactive docs are at `/docs`.

## Shared rules

- **Auth:** `Authorization: Bearer <token>`. A token comes from
  `POST /v1/auth/login` (email and password), `POST /v1/auth/pin-login`
  (code and PIN) or `POST /v1/auth/entra/finish` (Microsoft). The desktop
  and the learner app use these endpoints and nothing else: the API is the
  only door. Another system calls with an **API key** (`lms_k.…`) as its
  bearer token instead: a key opens the competency API and nothing else
  (below).
- **Errors:** a missing, ended or unknown token is `401`. Signed in but not
  allowed is `403` with `{ "detail", "code" }`. Validation problems are
  `422` with `{ "errors": [{ "field", "message" }] }`. Something that is not
  there (or not yours to see) is `404` with `{ "detail" }`. Well formed but
  not possible as things stand is `409` with `{ "detail", "code" }`.
- **Never deleted:** people and competencies are deactivated, not deleted.
  The training record and the extras and waivers are append-only: the latest
  row for a person and competency is the one that counts. Every quiz attempt
  is kept, and a module version is frozen once it is published. A
  practical's checklist versions and every sign-off, with what it ticked,
  are kept as they were.
- **Codes and keys:** a person's code is kept upper case (`ll042` finds
  `LL042`); role and competency keys are kept lower case. Emails are kept
  lower case.

## Who may do what

| Permission | Scopes (signed in with a password) |
| --- | --- |
| `learner` | `training:read`, `training:write` |
| `supervisor` | `training:read`, `training:write`, `matrix:read`, `roles:read`, `competencies:read`, `signoffs:write` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify`, `printing:write` |
| `admin` | `*` (everything, `settings:write` among it: Settings, webhooks and API keys) |

`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket, reading a module and taking its quiz.
`signoffs:write` is signing off someone else's practical. A session signed
in with a **PIN** carries `training:read` and `training:write`, whoever it
is, and `signoffs:write` too for a supervisor, manager or admin: a PIN is
short, so it opens the learner app's own training, and signing off a
practical on the phone where the learner is, and nothing more. A session
signed in with **Microsoft** carries the person's own scopes, as a password
does.

A supervisor sees their own team (the people whose supervisor they are); a
manager or admin sees everyone. Only an admin adds or changes a
manager or an admin (`403 { "code": "admin_only" }`).

## Sign in

### GET /v1/auth/methods
No session needed: what a sign-in page offers. `200
{ "pin": true, "password": true, "entra": false }`, from Settings
(`sign_in_pin`, `sign_in_password`, `sign_in_entra`). `entra` is `true` only
when it is switched on and set up: `LMS_ENTRA_TENANT_ID`,
`LMS_ENTRA_CLIENT_ID` and `LMS_ENTRA_CLIENT_SECRET` in `.env`, and a web
address (`public_url`). A way switched off is refused before anything else
is looked at: `403 { "detail": "Signing in with Microsoft is switched off
here.", "code": "method_off" }` from `entra/start` and `entra/finish`, as
from `login` and `pin-login`.

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
With email and password sign-in switched off in Settings it is `403 {
"code": "method_off" }`, whatever is sent.

### POST /v1/auth/pin-login
`{ "code": "LL042", "pin": "2468" }` → `200`, the same shape with
`"method": "pin"` and `"idle_seconds": 900`. A wrong PIN or unknown code is
`401 { "code": "wrong_pin" }`. Five wrong PINs lock the PIN
(`"code": "locked"`) until a manager sets a new one. With code and PIN
sign-in switched off in Settings it is `403 { "code": "method_off" }`.

A session ends on sign-out, after its idle time without a request
(`idle_seconds`: 15 minutes for a PIN or for Microsoft in the learner app,
12 hours for a password or Microsoft on the desktop), after 12 hours
(PIN or Microsoft) or 14 days (password) in all, when the person's PIN or
password is changed, or when they are deactivated (a way switched off in
Settings refuses new sign-ins; sessions already open run their course). A Microsoft session lasts a working day at most because
Simple LMS hears nothing more from Microsoft once someone is signed in.

### Sign in with Microsoft
OpenID Connect's authorisation code flow with PKCE, done by the API, for
either app. The session token never goes in an address.

1. `POST /v1/auth/entra/start` — `{ "app": "desktop" | "learner",
   "verifier" }` → `200 { "url" }`. `verifier` is a random secret of 32 to
   128 letters, digits, `-` and `_` that the app keeps in the tab
   (`sessionStorage`) until step 3; only its hash is kept. The app sends the
   person to `url`, Microsoft's sign-in page for the tenant
   (`prompt=login` for the learner app, so a shared tablet always asks for
   the password; `prompt=select_account` for the desktop). More than 30
   starts in a minute from one address are refused: `429 { "code":
   "too_many_sign_ins" }` with `Retry-After: 60`. The address is the one
   Caddy says the request came from (`X-Forwarded-For`, which Caddy sets).
2. Microsoft sends them to `GET /v1/auth/entra/callback?code=&state=` (the
   redirect URI registered in Entra: the web address in Settings, or
   `LMS_PUBLIC_URL`, then `/v1/auth/entra/callback`).
   The API swaps the code for an ID token (with the client secret and the
   PKCE verifier), checks it (signed by a key the tenant publishes, RS256;
   issuer `…/<tenant>/v2.0`; audience the client id; `exp`, `nbf`, `iat`
   with a minute's leeway; the nonce it sent; `tid` the configured tenant),
   and matches the person: by Entra object id (`oid`); else, the first time,
   by `email` when Microsoft says the tenant owns its domain (`xms_edov`),
   keeping the object id from then on. Someone matched by nobody, someone
   deactivated, or someone already linked to another Microsoft account is
   refused, never added. Either way it answers `303` to the app's sign-in
   page under the web address, `…/sign-in` or `…/learn/sign-in`, with
   `#entra=<hand-off code>`, or `#entra_error=` with `not_matched` (ask your
   manager to add you), `method_off`, or `failed` (anything else: cancelled
   at Microsoft, more than 10 minutes there, a state used before, a token
   that doesn't check out, or keys from Microsoft that make no sense). The
   access log leaves its query string out, and what Microsoft says when a
   sign-in didn't finish (`error`, `error_description`) is logged on one
   line, 300 characters at most. The tenant's signing keys are fetched
   again after a day, or sooner for a token naming a key it doesn't
   publish, but not within 5 minutes of the last fetch: until then such a
   token is refused.
3. `POST /v1/auth/entra/finish` — `{ "code", "verifier" }` → `200`, the
   same shape as `login` with `"method": "entra"`, and `"idle_seconds":
   900` when the learner app started it (perhaps a shared tablet, so as for
   a PIN) or `43200` for the desktop. A hand-off code works once, within 2 minutes,
   with the verifier its app started with; otherwise `401 { "detail": "that
   Microsoft sign-in has finished or expired; try again" }`.

### POST /v1/auth/logout
Ends the session whose token is sent. `204`, even if it had already ended.

### GET /v1/auth/me
The `person` object above, for the session's token.

The first admin is made on the command line:
`lms create-user --code AD001 --name "…" --email … [--permission admin]`
(prompts twice for the password, at least 12 characters).

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
  a locked one. Their PIN sessions end. Every PIN set (here, or with a new
  person) is kept with who set it, append-only: whoever set it knows it, so
  they don't sign that person off for a week (see Signing off).
- `POST /v1/people/{code}/password` — `{ "password" }`: a new password,
  which also lifts a lock. Their password sessions end.
- `POST /v1/people/{code}/entra/unlink` — forgets their Microsoft account:
  their next Microsoft sign-in is matched by email again. Their Microsoft
  sessions end.
- `POST /v1/people/{code}/deactivate`, `/reactivate` — deactivating ends
  their sessions; their records stay. Nobody deactivates themselves (`409
  { "code": "self" }`), and someone who still supervises active people is
  `409 { "code": "has_team" }` until their team has another supervisor.

The `pin`, `password`, `entra/unlink`, `deactivate` and `reactivate` calls
answer `200` with the person.

Each person:
```json
{ "id": 4, "code": "LL042", "name": "Kim Lee", "email": null, "permission": "learner",
  "supervisor": { "code": "SV001", "name": "Sam Vu" },
  "roles": [{ "key": "forklift-operator", "name": "Forklift operator" }],
  "active": true, "has_pin": true, "pin_locked": false, "has_password": false,
  "entra_linked": false, "created_at": "…", "last_login_at": null }
```
A PIN or password is never returned, nor a Microsoft object id:
`entra_linked` says whether they have signed in with Microsoft.

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
  people type in (true unless said otherwise). Sent for any other kind it is
  `422`.
- `GET /v1/competencies?kind=&active=` — `{ "items", "total" }` by name;
  `GET /v1/competencies/{key}`
- `PATCH /v1/competencies/{key}` — `name`, `refresher_months` (`null` for
  none) and/or `card_expires` (a ticket only, else `422`). The kind cannot
  change.
- `POST /v1/competencies/{key}/deactivate`, `/reactivate` — a deactivated
  competency is asked of nobody; its records stay.

Each competency: `{ "id", "key", "name", "kind", "refresher_months", "card_expires", "active", "created_at" }`;
`card_expires` is `null` for anything but a ticket.
Every kind can still be recorded by hand. Policies are signed in the
learner app, tickets sent in from it and modules taken in it, and
practicals are signed off on a supervisor's phone (below).

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
     "quiz": null, "signoff": null, "created_at": "…" }]
  ```
  `policy_version` is the policy version a grant is for; `signed_name` and
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one; `quiz` is
  `{ "version", "score", "pass_mark" }` when the person passed a module's
  quiz (recorded as theirs); `signoff` is `{ "version", "ticked", "note",
  "photo", "supervisor_signature", "learner_signature", "learner_pin_set_at",
  "learner_pin_set_by" }` when a practical was signed off on the phone
  (recorded by whoever signed it off): the checklist version, the text of
  each item ticked in order, upload ids for the photo (or `null`) and both
  signatures, and when the learner's PIN was last set and by whom (`{ "code",
  "name" }`), as it was at the sign-off: both `null` for a PIN set before
  PIN changes were kept.
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
the date in the time zone in Settings (or `LMS_TIMEZONE`; default
`Australia/Melbourne`).

A **policy** with a version published counts only for its newest version:
a grant for an older version (or from before there were versions) is
`missing` again until they sign the new one.

## The matrix

### GET /v1/matrix
`matrix:read`. Filters: `role` (key), `supervisor` (code), `status` (comma
separated: people with at least one cell in it). An unknown status,
`not_required` (the columns are only what the people shown are asked for,
so it would match nobody), or a supervisor code that is nobody, is `422`. Active people by name; a
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
`waiting` is true while a ticket they sent in waits for a manager's check;
`card_expires` is `null` for anything but a ticket.
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).

## The competency API

For other systems (Simple TMS checking a driver before a run, say) with an
API key carrying `competencies:read`, and for anyone signed in with
`competencies:read` who may see the person (a supervisor their team, a
manager or admin everyone; anyone else is `404`). A learner's own is
`GET /v1/people/{code}/training`. Status is worked out today, as for the
matrix.

### GET /v1/people/{code}/competencies
Everything their roles and extras ask of them, waived or not, by name:
```json
{
  "person": { "code": "LL042", "name": "Kim Lee", "active": true },
  "today": "2026-10-12",
  "competencies": [
    { "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket",
      "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-11" }
  ]
}
```

### GET /v1/people/{code}/competencies/{key}
One competency, whether it is asked of them or not:
`{ "person": { "code", "name", "active" }, "today", "key", "name", "kind", "status", "granted_on", "expires_on" }`.
`status` is `not_required` when it isn't asked of them, or the competency
is deactivated. An unknown code or key is `404`.

`expires_on` is the last good day (`null` when it doesn't run out, or there
is no grant). Someone deactivated has left: `active` is `false` and their
status is still worked out from their records. A revoked or unknown key is
`401`; a key used anywhere else is `403 { "code": "key_not_allowed" }`.

## Files

Tickets' photos (or a PDF), signatures, a module page's picture, PDF or
video, and a sign-off's photo. Sent before the ticket, signature, page or
sign-off that names them; kept on the host under `LMS_UPLOAD_DIR` (`/data/uploads`), named by a
random id, and written to disk as they arrive (never held in memory whole).

- `POST /v1/uploads?purpose=…` — the file as the request body (any
  `Content-Type`: what counts is its first bytes) → `201 { "id", "purpose",
  "content_type", "size_bytes", "created_at" }`.

  | Purpose | Who (scope) | What it may be | Up to |
  | --- | --- | --- | --- |
  | `ticket` | `training:write` | JPEG, PNG or PDF | 20 MB |
  | `signature` | `training:write` | PNG | 1 MB |
  | `page-image` | `competencies:write` | JPEG or PNG | 20 MB |
  | `page-pdf` | `competencies:write` | PDF | 20 MB |
  | `page-video` | `competencies:write` | MP4 or WebM | 200 MB |
  | `signoff-photo` | `signoffs:write` | JPEG or PNG | 20 MB |

  An MP4 is one whose `ftyp` box names a major brand of `isom`, `iso2`,
  `iso4`, `iso5`, `iso6`, `mp41`, `mp42`, `avc1`, `dash` or `M4V `; a WebM
  one whose EBML header's DocType is `webm`.
  Anything else is `415 { "code": "unsupported_type" }` (a QuickTime `.mov`,
  a Matroska `.mkv` or a HEIC photo too: most browsers won't play them, so
  convert to MP4 or JPEG first; videos play as uploaded, with no
  transcoding). Bigger than its
  purpose allows is `413 { "code": "too_large" }`: before the body is read
  when its `Content-Length` says so, and otherwise as soon as the body
  passes the limit (it is never read further). An unknown purpose is `422`,
  and a purpose the caller may not send `403`, before any of the body is
  read. In front of the API, Caddy refuses a body over 210 MB on
  `/v1/uploads` (and over 16 MB anywhere else in `/v1`) with its own `413`,
  before the API sees it.

  Each person may send so much in any 24 hours, counted from the files kept
  (a file refused isn't counted): of their own (`ticket` and `signature`
  together), 30 files and 200 MB by default (`upload_files_per_day` and
  `upload_mb_per_day` in Settings); a supervisor's, manager's or admin's
  own (`ticket`, `signature` and `signoff-photo` together: a sign-off is
  two signatures and a photo), 200 files and 2 GB; of module files (the
  `page-` purposes together), 200 files and 5 GB. Past that is `429 { "code":
  "too_many_uploads", "detail": "You've sent 30 files in the last 24
  hours, the most for a day. You can send more after 2:15 pm." }` (the time
  in the Settings time zone, with the day when it isn't today; a
  `Retry-After` header in seconds), before the body is read: a body whose
  `Content-Length` would go past the day's megabytes too ("That would take
  you past the 200 MB a person can send in a day. …"; one bigger than a
  whole day's has no time to wait for). Checked again, with the sender
  locked, once the body is in, so files sent at once can't slip past.
- `GET /v1/uploads/{id}` — the file. Any signed-in session may ask (a PIN
  one too), but only someone who may see the file's owner gets it: that
  person, their supervisor, and managers and admins. A sign-off's photo and
  signatures are sent from the supervisor's phone, so they are the
  supervisor's; whoever may see the learner they sign off gets them too.
  Anyone else gets `404`
  (and so does a file missing from disk). Sent with `Cache-Control: private, no-store`,
  `Content-Security-Policy: default-src 'none'; sandbox`,
  `X-Content-Type-Options: nosniff` and `Content-Disposition:
  <how>; filename="<id>.<ext>"`, where `<how>` is `inline` for an image or
  a video and `attachment` for a PDF (which shows blank under the sandbox,
  so it is saved instead). Sent from disk a piece at a time, never read
  into memory whole.

A ticket, signature or sign-off may only name the caller's own uploads of
the right purpose. Each upload goes on one record, ticket or sign-off only:
the database holds each signature to one record or sign-off and each photo
to one ticket or sign-off, and the API holds a signature to one of either.

- `GET /v1/media/{id}?session=&expires=&sig=` — a module page's file, by
  the link the API puts in the page (`file.link`, below). No token: an
  `<img>`, a `<video>` or a new tab can't send one, and a token never goes
  in a URL. The link names one file and the session it was made for, and
  is signed with that session's secret; it lasts 6 hours or until the
  session ends (signed out, idle, or too old, or its person deactivated),
  whichever is first, and opening it counts as using the session. Each
  page's file gets its own link, made fresh for the session asking. Ranges are honoured
  (`Accept-Ranges: bytes`, `206` with `Content-Range`, `416` past the end),
  so a phone can seek a video. Sent with the type its first bytes say,
  `Cache-Control: private, no-store`, `Content-Security-Policy: default-src
  'none'; sandbox`, `nosniff`, and `inline` (a picture or video) or
  `attachment` (a PDF). A wrong, expired or ended link is `404`, as is a
  link to anything that is not a page's file; one whose `session`,
  `expires` or `sig` is malformed or out of range is `422`. The API's
  access log leaves out a media link's query, so the logs never hold a
  link that opens a file.

## Modules

A module is a competency of kind `module`: a version of pages (text, a
picture, a PDF, a video or a link), then a multiple-choice quiz with a pass
mark. One draft at a time is written and saved in full as often as needed,
then published, which freezes it: its pages, questions and pass mark never
change again (the database refuses), so an attempt is always marked
against what was asked. A change after that is a new version, started as a
copy of the last. People take the newest published version; a new version
asks nobody to take it again (passes so far still count). The database also
holds an attempt to a published version, and a grant from a quiz to a
passing attempt by the same person for the same competency.

Each version, as its editors see it (`correct` is only there for them):
```json
{ "id": 3, "version": 2, "pass_mark": 80, "published_at": null, "published_by": null,
  "pages": [
    { "kind": "text", "title": "Welcome", "body": "Sign in at the gatehouse.", "url": null, "file": null },
    { "kind": "video", "title": "Lifting safely", "body": null, "url": null,
      "file": { "id": "…", "content_type": "video/mp4", "size_bytes": 48211234,
                "link": "/v1/media/…?session=…&expires=…&sig=…" } },
    { "kind": "link", "title": "SafeWork", "body": null, "url": "https://www.safework.nsw.gov.au", "file": null }],
  "questions": [{ "prompt": "Where do you sign in?", "options": ["The gatehouse", "The canteen"], "correct": 0 }],
  "created_at": "…", "saved_at": "…" }
```

- `GET /v1/modules/{key}/versions` (`competencies:read`) — newest first: the
  draft, if there is one, then those published. With the right answers
  (`correct`) only for a caller with `competencies:write`: anyone else (a
  supervisor, who may yet sit it) gets the questions without them.
- `POST /v1/modules/{key}/draft` (`competencies:write`) → `201`, the next
  version: a copy of the newest published one, or empty with a pass mark of
  80. One at a time (`409 { "code": "draft_exists" }`). A deactivated
  module is `409 { "code": "inactive" }`.
- `PUT /v1/modules/{key}/draft` (`competencies:write`) — the draft in full,
  replacing what was there: `{ "pass_mark": 1–100, "pages": [{ "kind",
  "title", "body"?, "file"?, "url"? }], "questions": [{ "prompt", "options",
  "correct" }], "based_on"? }` → `200`. A text page needs its `body` (plain text; line
  breaks are kept, nothing else is formatting); a picture, PDF or video page
  needs `file`, an upload of purpose `page-image`, `page-pdf` or
  `page-video`; a link page needs `url`, an `https://` or `http://` address
  with a site in it (no spaces).
  On the others `body` is an optional line or two under it. A question has
  2 to 6 answers, and `correct` (counting from 0) is one of them. Up to 100
  pages and 50 questions. Anything amiss is `422` on that field (e.g.
  `pages.2.file`). No draft is `404`; one published meanwhile is `409 {
  "code": "published" }`. `saved_at` changes with every save: send the one
  you loaded as `based_on`, and a draft someone else saved since is `409 {
  "code": "changed" }` rather than overwritten (reload it to see theirs).
- `POST /v1/modules/{key}/draft/publish` (`competencies:write`) → `200`,
  frozen, and the one people take from now. It needs a page and a question
  (`409 { "code": "incomplete" }`). A deactivated module is `409 { "code":
  "inactive" }`, checked once the module is locked, so one deactivated
  meanwhile is never published; one published meanwhile is `409 { "code":
  "published" }`.
- `GET /v1/modules/{key}` (`training:read`) — the version to take now, as
  the learner sees it: `{ "key", "name", "version": { "id", "version",
  "pass_mark", "pages": [ … ], "questions": [{ "prompt", "options" }] },
  "resume_at", "retry_at", "retry_at_text" }`. Never which answer is right. `resume_at` is
  the page they left off at (counting from 0; one past the last page is the
  quiz), on any device; `0` for a version they haven't opened. `retry_at`
  is when the caller may next try the quiz after too many goes in a row
  that didn't pass (below), or `null` when they may try now;
  `retry_at_text` is the same ready to show, in the time zone in Settings
  (`"2:15 pm"`, or `"1:00 am on Fri 16 Oct"` when it isn't today). `404`
  until a version is published. A deactivated module is `409 { "code":
  "inactive", "detail": "Site induction isn't in use any more" }`, here,
  for progress and for attempts; its editors still see its versions, and
  the place a learner was at comes back if it is reactivated.
- `PUT /v1/modules/{key}/progress` (`training:write`) — `{ "version",
  "page" }` → `204`: where the caller is now, theirs alone. Kept on the
  server, so nothing of theirs stays on a shared tablet. A page past the
  quiz is `422`. Only the newest published version takes progress (below).
  A deactivated module is `409 { "code": "inactive" }`.
- `POST /v1/modules/{key}/attempts` (`training:write`) — your own go at the
  quiz: `{ "version", "answers": [ … ] }`, one answer per question in order,
  counting from 0 → `201 { "id", "competency", "version", "correct",
  "total", "score", "pass_mark", "passed", "created_at", "retry_at",
  "retry_at_text" }`, the last two as for the module, worked out once the
  attempt is kept: the fail that starts the wait has them at once. Marked here:
  `score` is out of 100, rounded down, and a pass is a score of at least the
  pass mark. Every attempt is kept, pass or fail; try again as often as
  needed, but after a few goes in a row that didn't pass (the caller's last
  three at this module by default, any version, the last saved, with no
  pass after them) wait the minutes in Settings (60 by default; 0 for no
  wait) from the last of them: a go before then is `429 { "code":
  "cooldown", "detail": "Three tries in a row didn't pass: try again after
  2:15 pm", "retry_at": "<ISO>", "retry_at_text": "2:15 pm" }` (the time
  in the Settings time zone, with the day when it isn't today; a
  `Retry-After` header in seconds), and nothing is kept. It is worked out from the
  attempts, once the person is locked, so goes sent at once can't slip
  past. A pass is a grant from today, recorded as the learner's own (the
  one thing anybody earns alone), and the competency's refresher, if any,
  says when it runs out; it also starts the module from the top next time.
  Not one answer per question is `422` on `answers`, and one out of range
  on that answer (e.g. `answers.3`); a deactivated module is `409 {
  "code": "inactive" }`, checked once the module is locked (after the
  person), so a go sent while it is being deactivated is refused too.
- `GET /v1/people/{code}/attempts?competency=` (`training:read`; your own,
  your team's, or anyone's for a manager; anyone else is `404`) — every
  attempt, newest first, in the shape above.

`version` is the one the learner read: if a newer one was published
meanwhile, progress and attempts are `409 { "code": "new_version" }`, and
they start the new one. A key that is not a module is `404` on all of these,
and so are reading, progress and attempts before a version is published.

## Practicals

A practical is a competency of kind `practical`: a checklist of things a
supervisor watches the learner do, published whole and never changed (the
database refuses), so a sign-off always says what was ticked. A change is a
new version; supervisors tick the newest from then on, and a new version
asks nobody to be signed off again (sign-offs so far still count).

- `POST /v1/practicals/{key}/versions` (`competencies:write`) — `{ "items":
  [ … ], "note"? }` → `201`, the next version (1, 2, 3 …): 1 to 50 items, in
  the order they are ticked, each up to 300 characters. A deactivated
  practical is `409 { "code": "inactive" }`.
- `GET /v1/practicals/{key}/versions` (`competencies:read`) — newest first:
  `[{ "id", "version", "items": [{ "id", "text" }], "note", "published_by":
  { "code", "name" }, "created_at" }]`.
- `GET /v1/practicals/{key}` (`training:read`) — the checklist to tick now:
  `{ "key", "name", "version": { … } }`; `404` until one is published. A
  deactivated practical is `409 { "code": "inactive" }`, except for its
  editors (`competencies:write`).

A key that is not a practical is `404` on all of these.

## Signing off

`signoffs:write`. A supervisor signs off their own team; a manager or admin
signs off anyone. Nobody signs off themselves, admins included.

- `GET /v1/signoffs/people` — the people the caller may sign off (their
  team, or every active person for a manager or admin; never themselves),
  by name, each with the practicals they are asked for and not let off:
  `[{ "code", "name", "practicals": [{ "key", "name", "status", "expires_on" }] }]`.
- `POST /v1/people/{code}/signoffs` — on the supervisor's phone, with the
  learner beside them: `{ "competency", "version", "ticked": [item ids],
  "note"?, "photo"?, "supervisor_signature", "learner_signature",
  "learner_pin" }` → `201`, the record (above): a grant from today, recorded
  by the caller, with `signoff` filled in; the competency's refresher, if
  any, says when it runs out. `ticked` is every item on that version, and
  nothing else (`422` on `ticked`). `photo` is an upload of purpose
  `signoff-photo`; both signatures are uploads of purpose `signature`; all
  three are the caller's own, sent from the phone (`422` on the field
  otherwise). The two signatures differ, and each, like the photo, goes on
  one record or sign-off only (`422`: sign or take it again).
  `learner_pin` is the learner's own PIN, typed by them on the phone to say
  it was them: never kept. It is checked last, and counts against the same
  five tries as signing in: a wrong one is `422` on `learner_pin` ("that
  isn't Kim Lee's PIN: try again"), the fifth locks the PIN until a manager
  resets it, and a locked PIN, or none (someone who signs in with a
  password), is `422` there too. `version` is the checklist ticked: if a
  newer one was published meanwhile, `409 { "code": "new_version" }`, and
  it is ticked again. Signing off yourself is `403 { "code": "own_signoff"
  }`; someone a supervisor may not sign off is `404`; a learner (no
  `signoffs:write`) is `403`. An unknown competency is `404`, one that is
  not a practical `422` on `competency`, one with no checklist yet `404`,
  and a deactivated practical or person `409 { "code": "inactive" }`. The
  caller who set the learner's PIN in the last 7 days knows it, so their
  sign-off is `409 { "code": "you_set_their_pin" }` ("You set Kim Lee's PIN
  this week: ask another supervisor or manager to sign them off"), checked
  before the PIN so it costs no try; anyone else may sign them off.

A sign-off is put right like any grant: revoke it with a note
(`POST /v1/people/{code}/records/revoke`).

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

## Printing

Certificates of completion and skills cards go to Platen (or any print
service that takes the same job): Simple LMS renders nothing. It queues a
template's name and the JSON it binds to, and the worker hands the job to
Platen's `/intake/jobs` with `Authorization: Bearer
<platen_key>` and `X-LMS-Job-Id`, retried after 1 minute, 5, 30 and 2
hours. Platen's address, key and printers are Settings (`platen_url`,
`platen_key`, `certificate_printer`, `skills_card_printer`, below), or
`LMS_PLATEN_*` in `.env`. Platen's answer that it has the job is the end of
it here; Platen's own screens say whether it printed. Both are
`printing:write`, for someone who may see the person, and answer
`202 { "job_id", "template", "printer" }` once queued. Until Platen's
address is set both are `409 { "code": "printing_not_set_up" }`.

- `POST /v1/people/{code}/records/{id}/certificate` — for the completion
  that counts now: one recorded again since, or revoked, is
  `409 { "code": "not_current" }`; another person's record is `404`.
  Printed on `certificate_printer`.
- `POST /v1/people/{code}/skills-card` — what they are current for today
  (`current` or `expiring`, asked of them or not), by name; nothing is
  `409 { "code": "nothing_current" }`. Printed on `skills_card_printer`,
  or the certificates' printer.

What Platen is sent (make a page template in Platen with each id and
publish it; every value is text, never null, and `good_until` is empty for
what doesn't run out):
```json
{ "job_id": "…", "template": "lms-certificate", "version": "v1", "printer": "office", "copies": 1,
  "reference": { "type": "record", "ref": "12" },
  "data": { "certificate_no": "12", "person_name": "Kim Lee", "person_code": "LL042",
            "competency": "Forklift licence", "kind": "Ticket or licence",
            "completed_on": "1 Jan 2025", "good_until": "11 Nov 2026",
            "recorded_by": "Mel Grant", "issued_on": "12 Oct 2026" } }
```
```json
{ "job_id": "…", "template": "lms-skills-card", "version": "v1", "printer": "office", "copies": 1,
  "reference": { "type": "person", "ref": "LL042" },
  "data": { "person_name": "Kim Lee", "person_code": "LL042", "roles": "Forklift operator",
            "issued_on": "12 Oct 2026", "count": 2,
            "lines": [{ "competency": "Forklift licence", "kind": "Ticket or licence",
                        "completed_on": "1 Jan 2025", "good_until": "11 Nov 2026" },
                      { "competency": "Site induction", "kind": "Online module",
                        "completed_on": "1 Jan 2026", "good_until": "1 Jan 2028" }] } }
```
Platen gives a page template a row for each entry in `lines`, with the
rest beside it.

## Emails and the daily job

The worker sends email through the email server in Settings (or
`LMS_SMTP_*` in `.env`) from the outbox, trying a failed one again after 1
minute, 5, 30 and 2 hours, then leaving it `failed`. Without a host and a
from address emails wait in the outbox, untried. Links in them start with
the web address in Settings (or `LMS_PUBLIC_URL`; none without it). Each
day from the daily hour (6 am by default, in the Settings time zone) it
queues:

- a reminder to each active person with an email when something they are
  asked for reaches a reminder day (30, 14 and 0 days left by default, 0
  being the last good day itself), each once; a day missed still gets the
  reminder it owed, and each says the real days left. Its outbox key is
  `reminder:<person id>:<competency id>:<last good day>:<reminder day>`,
  so each reminder day sends at most once. Adding a day can send a second
  reminder for the same expiry (change 14 to 10, and someone with 10 days
  left who had the 14-day email gets the 10-day one too);
- on Mondays, a digest for each active manager and admin with an email of
  what is lapsed and what is expiring, for everyone (none when nothing is);
- `competency.expiring` and `competency.lapsed` for the webhooks (below),
  each once.

`lms daily-job [--on YYYY-MM-DD]` queues them now (as if today were that
date) and says how many reminders, digests and events it queued; nothing
is queued twice. A date it can't read is refused with exit code 2.

## Settings

Everyday settings, changed by an admin (`settings:write`; anyone else is
`403`) and taken up by the API and the worker within a few seconds, with no
restart. Each value is the one set here, else the one in `.env`, else the
default. What has to be known before the app starts (the database, ports,
the domain, the upload folder, Caddy) is in `.env` only.

| Key | Value | `.env` | Default |
| --- | --- | --- | --- |
| `sign_in_pin` | code and PIN sign-in on | | `true` |
| `sign_in_password` | email and password sign-in on | | `true` |
| `sign_in_entra` | Microsoft sign-in on (offered once `LMS_ENTRA_*` and `public_url` are set) | | `true` |
| `quiz_cooldown_tries` | quiz goes in a row that didn't pass before the wait, 1 to 20 | | `3` |
| `quiz_cooldown_minutes` | the wait, 0 to 525600 (0: none) | `LMS_QUIZ_COOLDOWN_MINUTES` | `60` |
| `reminder_days` | whole days 0 to 365, at least one, up to 10 (kept furthest first, each once) | | `[30, 14, 0]` |
| `daily_hour` | 0 to 23 | `LMS_DAILY_HOUR` | `6` |
| `timezone` | an IANA time zone | `LMS_TIMEZONE` | `"Australia/Melbourne"` |
| `smtp_host` | the email server, no spaces | `LMS_SMTP_HOST` | `""` |
| `smtp_port` | 1 to 65535 | `LMS_SMTP_PORT` | `587` |
| `smtp_user` | | `LMS_SMTP_USER` | `""` |
| `smtp_password` | write-only | `LMS_SMTP_PASSWORD` | `""` |
| `smtp_from` | e.g. `Simple LMS <lms@example.com.au>` | `LMS_SMTP_FROM` | `""` |
| `smtp_security` | `starttls`, `ssl` or `none` | `LMS_SMTP_SECURITY` | `"starttls"` |
| `public_url` | `https://…` (or `http://`), no trailing slash, or `""` | `LMS_PUBLIC_URL` | `""` |
| `platen_url` | Platen's intake, `https://…/intake/jobs` (or `http://`), or `""`: nothing prints | `LMS_PLATEN_URL` | `""` |
| `platen_key` | write-only: a key made in Platen for Simple LMS | `LMS_PLATEN_KEY` | `""` |
| `certificate_printer` | a Platen printer's id or name | `LMS_CERTIFICATE_PRINTER` | `"office"` |
| `skills_card_printer` | the same, or `""` for the certificates' printer | `LMS_SKILLS_CARD_PRINTER` | `""` |
| `upload_files_per_day` | files a person can send of their own (tickets, signatures) in 24 hours, 1 to 100000 | | `30` |
| `upload_mb_per_day` | megabytes of them, 1 to 1000000 | | `200` |

### GET /v1/settings
→ `200`, every key: `{ "value", "source" }`, where `source` is `here`,
`env` (`.env` gives a value other than the default) or `default`. The password and Platen's key are never sent: `"smtp_password": { "set":
true, "source": "env" }`.
```json
{ "daily_hour": { "value": 6, "source": "default" },
  "timezone": { "value": "Australia/Perth", "source": "here" },
  "smtp_password": { "set": false, "source": "default" }, "…": "…" }
```

### PUT /v1/settings
Only the keys sent change: `{ "daily_hour": 7, "smtp_password": "…" }` →
`200`, every setting as for GET. `null` removes the value set here, so it
comes from `.env` or the default again; an empty password (`""`) is set
here and clears one in `.env` too. A bad value is `422` on its key (e.g.
`timezone`, `reminder_days.0`), an unknown key is `422` on that key, and
nothing is saved unless every value is good. Who changed each setting last,
and when, is kept with it.

`sign_in_entra` also answers `"set_up"`: whether `LMS_ENTRA_*` and a web
address are there, so that its button shows when it is on. The tenant id,
client id and client secret are in `.env` only, never on the screen.

A change that would leave neither email and password nor Microsoft on and
set up is `409 { "code": "last_way_in" }`: a PIN session never carries an
admin's scopes, so one of them is the only way an admin can sign in.
Switching off the way your own session signed in is `409 { "code":
"own_method" }`: sign in another way first, so passwords are switched off
from a Microsoft session, which shows Microsoft works for an admin. A
switched-off method is refused at sign-in (`403 method_off`); sessions
already open run their course. The `lms` command line never signs in, so it
works whatever is switched off, and `lms clear-setting <key>` puts any
setting back to `.env` or the default.

### POST /v1/settings/test-email
Queues an email to the caller's own address through the outbox → `202 {
"to" }`; the worker sends it within a few seconds. No email address is
`409 { "code": "no_email" }`; no email server (host and from address) is
`409 { "code": "no_mail_server" }`. Each press sends one.

## Webhooks and events

Simple LMS tells other systems what happens by posting an event to each
webhook that wants it, as Simple WMS does: the same envelope and the same
signature, with `X-LMS-` headers where Simple WMS has `X-WMS-`. Events are
queued in the same transaction as the change (nothing is told of a change
that wasn't kept), sent by the worker, and a refusal (anything but `2xx`)
or no answer in time (10 seconds for any step, 15 in all) is tried again after 1 minute, 5, 30 and 2
hours, then left `failed` for an admin to send again. At least once: a
receiver keeps the `event_id`s it has had and ignores one it has seen.
Events, emails and print jobs each go out in a loop of their own, so a
receiver that hangs holds up no email; and once a webhook gives no answer
in time, the rest of its events wait for the worker's next pass rather
than each waiting out the deadline in turn.

### What is sent
`POST <the webhook's url>` with the envelope as the body:
```json
{ "event_id": "1b4e28ba-2fa1-41d2-883f-0016d3cca427", "event_type": "competency.granted",
  "occurred_at": "2026-10-12T01:30:00Z", "data": { … } }
```
and the headers `Content-Type: application/json`, `User-Agent:
simple-lms/0.1`, `X-LMS-Event-Id`, `X-LMS-Event-Type` and
`X-LMS-Signature: sha256=<hex>`, the HMAC-SHA256 of the exact bytes of the
body, keyed with the webhook's secret.

### Checking the signature
Check it against the raw body, before parsing it, in constant time:
```python
import hashlib, hmac

def verify(secret: str, body: bytes, header: str | None) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # on bytes: a header that isn't ASCII is a mismatch, not an exception
    return header is not None and hmac.compare_digest(expected.encode(),
                                                      header.strip().encode())
```

### The events
`person` is `{ "code", "name" }` and `competency` is `{ "key", "name",
"kind" }`. `status` is the person's status for it as the change leaves it
(it may be `not_required`, or `waived`), and `expires_on` the last good day
(`null` when it doesn't run out).

| Event | When | `data` |
| --- | --- | --- |
| `competency.granted` | a grant by hand, a ticket checked, a policy signed, a module passed, a practical signed off | `person`, `competency`, `record_id`, `granted_on`, `expires_on`, `status`, `recorded_by` |
| `competency.revoked` | a grant revoked | `person`, `competency`, `record_id`, `note`, `status`, `recorded_by` |
| `competency.expiring` | the daily job first finds it within 30 days of its last good day: once for each last good day, so a renewal is told afresh | `person`, `competency`, `status` (`expiring`), `granted_on`, `expires_on`, `days_left` |
| `competency.lapsed` | the daily job first finds its last good day has passed: once for each last good day | `person`, `competency`, `status` (`lapsed`), `granted_on`, `expires_on` |
| `person.updated` | a person added, their details or roles changed, deactivated or back; never a PIN, a password or a Microsoft account linked or unlinked (how they sign in is not what another system keeps) | `person`: `{ "code", "name", "email", "permission", "active", "supervisor": { "code", "name" } \| null, "roles": [{ "key", "name" }] }` |

Expiring and lapsed are fired once whoever was listening: a webhook added
later isn't told of what went before (the competency API says how things
stand now). Waivers, extras and role requirements change what is asked of
people without an event of their own.

### Managing them
`settings:write` (admins), on the desktop's Settings screen:

- `GET /v1/webhooks` — by name: `[{ "id", "name", "url", "events", "active",
  "waiting", "failed", "created_at" }]`, where `waiting` and `failed` count
  its deliveries still to go and given up on. `GET /v1/webhooks/{id}`.
- `POST /v1/webhooks` — `{ "name", "url" (http:// or https://), "events":
  ["competency.granted", …] or ["*"] }` → `201`, the webhook with its
  `secret` (`whsec_…`), **shown this once**. A name already taken is `422`.
- `PATCH /v1/webhooks/{id}` — any of `name`, `url`, `events`, `active`.
  Deliveries still waiting go to the new address; turned off, it gets
  nothing more and what was waiting for it is given up on.
- `POST /v1/webhooks/{id}/secret` — a new secret, shown this once: everything
  sent from now on (what is waiting included) is signed with it.
- `GET /v1/webhooks/{id}/deliveries?status=pending|done|failed` — the latest
  50, newest first: `[{ "id", "event_id", "event_type", "status", "attempts",
  "next_attempt_at", "last_error", "done_at", "created_at" }]`.
- `POST /v1/webhooks/{id}/deliveries/{delivery_id}/retry` — a failed
  delivery sent again from the start of the backoff, the same event with
  the same id. One that hasn't failed is `409 { "code": "not_failed" }`; a
  webhook turned off is `409 { "code": "inactive" }`.

### Where a webhook may point
A webhook goes to a public address. The worker won't connect to an
internal one for it: loopback (`127.0.0.1`, `::1`, `localhost`), private
(`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`), link-local (`169.254/16`,
a cloud's metadata service among them), shared (`100.64/10`) or otherwise
reserved, nor ever to an unspecified or multicast one. An IPv4 address
inside an IPv6 one (`::ffff:a.b.c.d`, NAT64's `64:ff9b::/96`, the old
`::a.b.c.d`) is checked as the IPv4 address it reaches, and a tunnel that
goes somewhere the address doesn't say (6to4's `2002::/16`, Teredo's
`2001::/32`) counts as internal. The address a name
resolves to is checked where the connection is made, each time an event is
sent, so a name pointed inside later is refused too (the delivery fails
with `ConnectError: refused: … is an internal address` and is tried again
as any failure is). `POST` and `PATCH /v1/webhooks` refuse an address that
is plainly internal (`localhost`, an internal IP) with a `422` on `url`.

To send to a receiver on the same machine (`http://host.docker.internal:<port>/…`
from Compose) or the local network, whoever runs the server sets
`LMS_WEBHOOK_ALLOW_PRIVATE=true` in `.env`: it is not on the Settings
screen. Platen's address is not held to this (it is often on the same
machine), but no redirect is followed for it either.

The worker also follows no redirect (a `3xx` is a refusal like any other),
takes no proxy from the environment, waits at most
`LMS_WORKER_HTTP_TIMEOUT_SECONDS` (10) for each step of an answer and
`LMS_WORKER_SEND_DEADLINE_SECONDS` (15) for the whole of it (a receiver
that sends its answer a byte at a time is cut off there, however often the
bytes come), and keeps only the start of a refusal's body as its
`last_error`. Print jobs to Platen and emails are held to the same
deadline.

## API keys

For other systems, not people. `settings:write` (admins), on the desktop's
Settings screen:

- `GET /v1/api-keys` — by name: `[{ "id", "name", "prefix", "scopes",
  "created_by": { "code", "name" }, "created_at", "last_used_at",
  "revoked_at" }]`. `prefix` is the key's first ten characters, to tell
  which is which; `last_used_at` is to the minute.
- `POST /v1/api-keys` — `{ "name", "scopes": ["competencies:read"] }` →
  `201`, the key with `key` (`lms_k.…`), **shown this once**: only its
  SHA-256 is kept. `competencies:read` is the one scope a key can have.
- `POST /v1/api-keys/{id}/revoke` — it stops working at once, for good
  (`409 { "code": "revoked" }` the second time). Keys are never deleted.

## System

- `GET /v1/health` → `{ "status": "ok" }` once the database answers.
