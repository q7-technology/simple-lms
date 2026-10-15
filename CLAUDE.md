# Simple LMS — instructions for Claude Code

Read `docs/plans/2026-10-12-simple-lms-design.md` before touching anything. It
is the design, and the decisions in it are settled unless a human changes them
there first.

## What this is
An open source, self-hosted learning management system by Q7 Technology, for
workplace training: inductions, online modules, practical sign-offs, outside
tickets and licences, and signed policies. It answers one question for a
business and its auditors: is each person current for everything their job
needs? Desktop web app (managers, supervisors, admins), learner PWA (phone or
shared tablet), one Python API, one PostgreSQL database. It sits beside
Simple WMS, Simple TMS and Platen and works without any of them. Other
systems only ever talk to the API.

## Four rules that never bend
1. **The training record is append-only.** Never UPDATE or DELETE a
   `competency_record`, `quiz_attempt` or `signoff` row (nor a
   `person_override`, `policy_version` or `upload`; a `ticket_submission` is
   decided once and never deleted; a `module_version` is frozen once
   published, and its `module_page` and `quiz_question` rows change only
   while it is a draft; a `practical_version` and its `practical_item`
   rows, and a `signoff`'s `signoff_item` rows, are written together and
   never after). A mistake is corrected by a new row (`revoked`, with a
   note). People are deactivated, never deleted.
2. **Status is worked out, never stored by hand.** It comes from the records
   and the date, so it cannot drift. `competency.expiring` and
   `competency.lapsed` fire from the daily job, each once, each with an event
   id.
3. **Nobody grants their own competency.** A practical is signed off by a
   supervisor who is not the learner; a ticket is verified by a manager who is
   not the learner. A module pass is the only thing a learner earns alone.
4. **The API is the only door.** The desktop and the learner app are ordinary
   API clients with a session token, whichever way the person signed in. If
   the UI can do it, a partner can too.

## Stack (decided)
- API: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic.
- Database: PostgreSQL 16.
- Queue: a Postgres table drained by a Python worker with backoff (1 min, 5,
  30, 2 h), for webhooks, email and print jobs, and the daily job. No Redis
  or RabbitMQ. The worker (`python -m lms.worker`) drains the `outbox`.
- Front ends: Vite + React + TypeScript + Tailwind. One repo, two entry
  points: `apps/desktop` and `apps/learner`. The learner app is a PWA at
  `/learn/` whose service worker caches the app shell, as the Simple TMS
  driver app's does.
- Hosting: Ubuntu + Docker Compose: `api`, `worker`, `db`, `caddy`, static
  builds for both apps. Secrets in `.env` on the host.

## Repo layout
```
CLAUDE.md            this file
docs/plans/          the design and the implementation plans
docs/api.md          every endpoint: keep it in step with the routes
.github/workflows/   CI: the tests, both apps' builds, and a Compose start
api/                 FastAPI app (package lms), migrations, tests
apps/desktop/        the desktop app for managers, supervisors and admins
apps/learner/        the learner app, a PWA served at /learn/
deploy/Caddyfile     the only door in
docker-compose.yml   api, worker, db, caddy
```
`npm` commands run from the app's folder (`apps/desktop/` or `apps/learner/`):
`npm test`, `npm run typecheck`, `npm run build` (Caddy serves each app's
`dist`).

## Conventions
- Status: `current`, `expiring` (within 30 days), `lapsed`, `missing`,
  `waived`, `not_required`, worked out by `lms/services/status.py` and
  nowhere else. The latest record for a person and competency is the one
  that counts.
- Modules: a new version asks nobody to take it again (unlike a policy);
  passes still count and the refresher brings people back. The right
  answers (`correct`) go only to a caller with `competencies:write`; the API
  marks every attempt. Where a person is in a module (`module_progress`) is
  kept on the server, not the device, and is not part of the record.
- Files: written to disk as they arrive, checked by their first bytes, and
  served only through the API: a video is an MP4 (one of the brands in
  `lms/services/uploads.py`, never QuickTime) or a WebM up to 200 MB, and
  anything else 20 MB. Caddy refuses a bigger body first (210 MB on
  `/v1/uploads`, 16 MB elsewhere). A module's files open by `/v1/media/`
  links signed for one session; never put a session token in a URL, and
  keep the signature out of the logs (`lms/api/logs.py`).
- Game Mode: the desktop opens on the classroom (`lib/classroom.ts` works
  it out from `GET /v1/matrix`, in Simple WMS's isometric view from
  `lib/iso.ts`; nothing in the API is for it) and every other route opens in
  `ScreenPanel` over it. A new desktop screen is a line in
  `apps/desktop/src/ui/screens.ts` and a route in `App.tsx`; its own dialogs
  are `aria-modal="true"`, so Escape closes them before the panel. Game
  touches are per viewer, kept in the browser (`lms.game`,
  `lms.learner.game`) and never sent to the API, and everything the
  classroom offers stays reachable with Game Mode off.
- Sign-in: code and PIN (learner app), email and password, or Microsoft
  Entra ID, each switchable in Settings (`sign_in_*`; `lms clear-setting
  sign_in_password` is the way back in). The Entra tenant, client and
  secret stay in `.env`. Entra is OIDC's code flow with PKCE, done by the API; the app
  gets a one-time hand-off code after the `#`, never a token in a URL. A
  Microsoft sign-in never creates a person: match by `entra_oid`, else the
  first time by `email` with `xms_edov`, never by `preferred_username`.
- Sign-offs: who may sign off whom is `practicals.may_sign_off()` and
  nowhere else. The learner confirms on the supervisor's phone with their
  PIN, which counts against their five tries and is never stored or logged;
  never give the learner a session on someone else's device.
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
  publishes signed events and a competency API.
- Events: queued by `lms/services/events.py` in the same transaction as the
  change, one outbox row per webhook, signed by the worker with
  `X-LMS-Signature` exactly as Simple WMS signs its own. Anything new that
  grants or revokes a competency calls `events.granted` or `events.revoked`;
  anything that changes what another system keeps about a person calls
  `events.person_updated` (how they sign in, a PIN, a password or a
  Microsoft account, is not that). The daily job's expiring and lapsed go
  through `events.once`, so each fires once. The catalogue is in
  `docs/api.md`.
- Webhooks: public addresses only (`lms/services/webhooks.py` checks where
  the connection is made; `LMS_WEBHOOK_ALLOW_PRIVATE`, in `.env` only, lets
  one in), no redirects followed, and every send by the worker (webhook,
  print job or email) held to `LMS_WORKER_SEND_DEADLINE_SECONDS`. Each kind
  has a loop of its own in `lms/worker.py`, so a slow receiver never holds
  up email.
- API keys: for systems, not people; shown once, only the hash kept. A key
  opens the competency API and nothing else. Webhooks and keys are an
  admin's (`settings:write`), on the Settings screen; a webhook's secret is
  shown once too.
- Settings: everyday settings (sign-in methods, the quiz wait, reminder
  days, the daily hour and time zone, the email server, the web address,
  Platen's address, key and printers, the upload limits) are read only
  through `lms/services/settings.py` (`settings.current()`), never from
  `lms.config` directly: a value set on the Settings screen wins over
  `.env`, which wins over the default, and changes reach every process
  within seconds. A new everyday setting goes there, with its `.env`
  fallback if it has one. What is needed before the app starts or could
  lock everyone out (database, ports, domain, upload folder, Caddy) stays
  in `.env` only, as do the worker's limits and whether a webhook may be
  internal. A secret (the email password, Platen's key) is write-only:
  never sent back. Their table, `setting`, came in migration `0003b`;
  practicals came in `0004`, Entra sign-in in `0005`, the outward links
  (webhooks, API keys, events seen) in `0006`, and the next migration
  (`0007`) goes after it.
- Printing: Simple LMS never renders a document. Certificates and skills
  cards go to Platen (or any print service) as `template` + JSON `data`
  through the queue.
- Build order is in the design under "Build order". Finish a step so it is
  usable before starting the next.
- Tests: pytest for the API against a real PostgreSQL, Vitest for the apps.
- Australian English in copy. No "utilise", no "leverage".
- Git: no `Co-Authored-By` lines, no tooling or generated-by trailers, no
  session links. A commit message is the subject line and, if needed, a
  short body about the change. Nothing else.
