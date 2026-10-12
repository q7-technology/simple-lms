# Simple LMS — design

A small, open-source, self-hosted learning management system for workplace
training: inductions, online modules, practical sign-offs, outside tickets and
licences, and signed policies. It answers one question for a business and its
auditors: is each person current for everything their job needs? It sits
beside Simple WMS, Simple TMS and Platen and works without any of them.

## Decisions

| Question | Decided |
| --- | --- |
| Who it is for | Workplace training and compliance, not public courses or RTOs |
| Kinds of training | All four: online modules, supervisor sign-off, outside tickets, signed policies |
| Sign-in | Code + PIN, email + password, and Microsoft Entra ID, each switchable |
| Entra first sign-in | Matched to an existing person by Entra id, then email; never created |
| Who needs what | By role, plus one-off extras or waivers for a person, with a note |
| Module content | Pages (text, image, PDF, video, link) and a quiz; files stored on the host |
| Reminders | Email reminders and an in-app to-do list; no SMS |
| Sister apps in version one | None changed; the LMS publishes signed events and a competency API |
| Left out of version one | SCORM, sites and departments, SMS, offline sign-off, payments, AVETMISS |
| Shape | A separate app, its own repo, the same stack and rules as its siblings |

## Stack

Python 3.12 + FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, a
Postgres-table queue drained by a worker (no Redis), Vite + React + TypeScript
+ Tailwind for a desktop app and a learner PWA, Docker Compose behind Caddy.
The same choices as Simple WMS and Simple TMS, so one person can look after
all of them.

## The idea: competencies

A **competency** is anything a person can be current for. It has one of four
kinds:

| Kind | Earned by | Expiry |
| --- | --- | --- |
| `module` | Passing the module's quiz | Optional refresher, e.g. 24 months |
| `practical` | A supervisor signing off a checklist | Optional refresher |
| `ticket` | Uploading a photo, number and expiry; a manager verifies it | The date on the card |
| `policy` | Reading and signing a policy version | None; a new version needs a new signature |

A **role** lists the competencies it requires. A **person** has roles, and may
have extras (required for them alone) or waivers (not required, with a note).

A person's **status** for a competency is worked out from their records and
today's date: `current`, `expiring` (within 30 days), `lapsed`, `missing`,
`waived` or `not_required`.

## Four rules that never bend

1. **The training record is append-only.** Never UPDATE or DELETE a
   `competency_record`, `quiz_attempt` or `signoff` row. A mistake is
   corrected by a new row (`revoked`, with a note). People are deactivated,
   never deleted.
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

## People and sign-in

A **person** has a code (e.g. `LL042`), a name, and optionally an email, an
Entra object id, a PIN, roles and a supervisor. One record serves every way
of signing in.

- **Code + PIN**: learner app only. Five wrong tries locks it until a manager
  resets it. Sessions end on sign-out or after 15 minutes idle, so a shared
  tablet is safe.
- **Email + password**: either app.
- **Microsoft Entra ID**: OIDC, with tenant id, client id and secret in
  `.env`. First sign-in matches a person by Entra id, then by email. An
  unmatched account is refused: "Ask your manager to add you."

Each method can be turned off in settings.

**Permissions** are separate from training roles:

| | Learner | Supervisor | Manager | Admin |
| --- | --- | --- | --- | --- |
| Do own training, upload own tickets | ✓ | ✓ | ✓ | ✓ |
| Sign off practicals for others | | ✓ | ✓ | ✓ |
| See the matrix | own | own team | all | all |
| Verify tickets, waive, edit roles and competencies | | | ✓ | ✓ |
| Users, sign-in settings, webhooks, API keys | | | | ✓ |

A supervisor's **team** is the people whose supervisor is them.

## Learner app

A PWA at `/learn/`, phone first, also used on a shared tablet. Online only in
version one; the app shell is cached as in the Simple TMS driver app.

- **My training**: a to-do list in three parts, Overdue, Due soon and Done.
- **Module player**: one page at a time, then the quiz; pass or fail with the
  score; try again after a fail. Progress is kept if the learner leaves.
- **Sign a policy**: read it, then a typed name and a finger signature.
- **Add a ticket**: photo of the front and back, type, number, expiry. It
  waits for a manager's check.
- **Sign off** (supervisors): choose a person from the team and a practical,
  tick each item, add a note or photo, sign; the learner then signs on the
  same device to confirm.

## Desktop app

For managers, supervisors and admins.

- **Matrix**: people down the side, competencies across the top, each cell
  green, amber, red or grey. Filter by role, supervisor or status. A cell
  opens that person's history for it. Export to CSV.
- **People**: add and edit, roles, supervisor, extras and waivers with a note,
  reset a PIN, deactivate.
- **Roles**: the competencies each role requires.
- **Competencies**: one editor per kind: module pages, quiz questions and pass
  mark; practical checklist items; ticket type and whether it expires; policy
  versions. Each can have a refresher period.
- **Inbox**: tickets waiting to be checked: approve, or reject with a reason.
- **Settings**: sign-in methods, SMTP, reminder days, webhooks, API keys.

## How it connects

**Events out.** HMAC-signed webhooks, each with an event id, sent through the
queue and retried after 1 min, 5, 30 and 2 h: `competency.granted`,
`competency.revoked`, `competency.expiring` (once, at 30 days),
`competency.lapsed`, `person.updated`.

**Competency API.** `GET /v1/people/{code}/competencies` and
`GET /v1/people/{code}/competencies/{key}` return `{status, expires_on}`.
When Simple TMS later refuses a driver whose licence or induction has lapsed,
it uses this or the events. Nothing in Simple WMS or Simple TMS changes for
version one.

**Printing.** Certificates of completion and a skills card listing a person's
current competencies are sent to Platen (or any print service) as `template`
+ JSON `data` through the queue. The LMS never renders a document.

**Email.** SMTP settings in `.env`, sent through the queue. Learners with an
email get reminders at 30, 14 and 0 days; managers get a digest of expiring
and lapsed items each Monday. Learners without an email rely on My training
and their supervisor.

## Data

Tables: `person`, `session`, `role`, `person_role`, `competency`,
`role_requirement`, `person_override`, `module_page`, `quiz_question`,
`practical_item`, `policy_version`, `quiz_attempt`, `signoff`,
`signoff_item`, `ticket_submission`, `competency_record`, `upload`, `outbox`,
`event_seen`.

**Uploads** go to a `/data/uploads` volume, named by a random id, and are
served only through the API to people allowed to see them. Images, PDF,
MP4 and WebM; 200 MB for video, 20 MB for anything else. Videos play as
uploaded, with no transcoding.

**The daily job** runs in the worker: it finds what has become expiring or
lapsed, fires the events, and queues the reminders and the Monday digest.

**Retention**: every record is kept. A person who leaves is deactivated.

## Look: Game Mode, like its siblings

- **The desktop is a training yard.** Each role is a small building; each
  person is a figure beside their role's building, coloured by how current
  they are. Every screen opens as a drawer over the yard, as in Simple WMS.
  The matrix is always one click away. Drawn in SVG: no game engine.
- **The learner app is like the scanner.** Big buttons, one thing at a time,
  a "Ding!" on a pass, and a ring for "3 of 5 done".
- **Game touches are per viewer**, kept in the browser, never on the server.

Until step 7 the desktop opens on the matrix.

## Testing

- API: pytest against a real Postgres. Status worked out from records and
  dates; append-only enforcement; no self sign-off or self-verification;
  quiz pass mark and re-sits; a new policy version needing a new signature;
  Entra matching (by id, by email, refused); PIN lock-out; webhook retry;
  expiring and lapsed each firing once.
- Apps: Vitest for the module player, the quiz and the sign-off flow.
- End to end: make a role → give it to a person → they pass a module, sign a
  policy and upload a ticket → a manager verifies it → a supervisor signs off
  a practical → the matrix is green → move the clock on → amber, then red,
  with the events and emails sent.

## Build order

Each step is usable before the next starts.

1. Skeleton: repo, Docker, people, PIN and password sign-in, roles and
   competencies, the matrix, records entered by hand from the desktop.
2. Policies and tickets: signing, upload and verify, expiry, the daily job
   and email reminders.
3. Modules: page editor, uploads, the player, quizzes.
4. Practicals: checklists and supervisor sign-off on the phone.
5. Entra sign-in.
6. Outward links: webhooks, the competency API, Platen certificates and
   skills cards.
7. Game Mode: the training yard.
