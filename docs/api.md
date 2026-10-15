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
  row for a person and competency is the one that counts. Every quiz attempt
  is kept, and a module version is frozen once it is published.
- **Codes and keys:** a person's code is kept upper case (`ll042` finds
  `LL042`); role and competency keys are kept lower case. Emails are kept
  lower case.

## Who may do what

| Permission | Scopes (signed in with a password) |
| --- | --- |
| `learner` | `training:read`, `training:write` |
| `supervisor` | `training:read`, `training:write`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify` |
| `admin` | `*` (everything, `settings:write` among it) |

`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket, reading a module and taking its quiz. A
session signed in with a **PIN** carries
`training:read` and `training:write` only, whoever it is: a PIN is short, so
it opens the learner app's own training and nothing more.

A supervisor sees their own team (the people whose supervisor they are); a
manager or admin sees everyone. Only an admin adds or changes a
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
With email and password sign-in switched off in Settings it is `403 {
"code": "method_off" }`, whatever is sent.

### POST /v1/auth/pin-login
`{ "code": "LL042", "pin": "2468" }` → `200`, the same shape with
`"method": "pin"` and `"idle_seconds": 900`. A wrong PIN or unknown code is
`401 { "code": "wrong_pin" }`. Five wrong PINs lock the PIN
(`"code": "locked"`) until a manager sets a new one. With code and PIN
sign-in switched off in Settings it is `403 { "code": "method_off" }`.

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
learner app, tickets sent in from it and modules taken in it (below);
practicals get their own way in with a later build step.

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
     "quiz": null, "created_at": "…" }]
  ```
  `policy_version` is the policy version a grant is for; `signed_name` and
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one; `quiz` is
  `{ "version", "score", "pass_mark" }` when the person passed a module's
  quiz (recorded as theirs).
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

## Files

Tickets' photos (or a PDF), policy signatures, and a module page's
picture, PDF or video. Sent before the ticket, signature or page that names
them; kept on the host under `LMS_UPLOAD_DIR` (`/data/uploads`), named by a
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
- `GET /v1/uploads/{id}` — the file. Any signed-in session may ask (a PIN
  one too), but only someone who may see the file's owner gets it: that
  person, their supervisor, and managers and admins. Anyone else gets `404`
  (and so does a file missing from disk). Sent with `Cache-Control: private, no-store`,
  `Content-Security-Policy: default-src 'none'; sandbox`,
  `X-Content-Type-Options: nosniff` and `Content-Disposition:
  <how>; filename="<id>.<ext>"`, where `<how>` is `inline` for an image or
  a video and `attachment` for a PDF (which shows blank under the sandbox,
  so it is saved instead). Sent from disk a piece at a time, never read
  into memory whole.

A ticket or signature may only name the caller's own uploads of the right
purpose. Each upload goes on one record or ticket only: the database holds
each signature to one record and each photo to one ticket.

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
  "code": "inactive" }`.
- `GET /v1/people/{code}/attempts?competency=` (`training:read`; your own,
  your team's, or anyone's for a manager; anyone else is `404`) — every
  attempt, newest first, in the shape above.

`version` is the one the learner read: if a newer one was published
meanwhile, progress and attempts are `409 { "code": "new_version" }`, and
they start the new one. A key that is not a module is `404` on all of these,
and so are reading, progress and attempts before a version is published.

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
  what is lapsed and what is expiring, for everyone (none when nothing is).

`lms daily-job [--on YYYY-MM-DD]` queues them now (as if today were that
date); nothing is queued twice. A date it can't read is refused with exit
code 2.

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

### GET /v1/settings
→ `200`, every key: `{ "value", "source" }`, where `source` is `here`,
`env` (`.env` gives a value other than the default) or `default`. The password is never sent: `"smtp_password": { "set":
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

Switching `sign_in_password` off is `409 { "code": "last_way_in" }` while
it is the only way an admin can sign in (a PIN session never carries an
admin's scopes), which until Microsoft Entra sign-in arrives is always. A
switched-off method is refused at sign-in (`403 method_off`); sessions
already open run their course. The `lms` command line never signs in, so it
works whatever is switched off, and `lms clear-setting <key>` puts any
setting back to `.env` or the default.

### POST /v1/settings/test-email
Queues an email to the caller's own address through the outbox → `202 {
"to" }`; the worker sends it within a few seconds. No email address is
`409 { "code": "no_email" }`; no email server (host and from address) is
`409 { "code": "no_mail_server" }`. Each press sends one.

## System

- `GET /v1/health` → `{ "status": "ok" }` once the database answers.
