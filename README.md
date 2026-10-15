# Simple LMS

An open source, self-hosted learning management system for workplace
training: inductions, online modules, practical sign-offs, outside tickets
and licences, and signed policies. It answers one question for a business and
its auditors: is each person current for everything their job needs? It sits
beside Simple WMS, Simple TMS and Platen and works without any of them.

Status: **build steps 1 to 5 and 7 are done.** People sign in with a
code and PIN, an email and password, or their Microsoft work account; roles
and the competencies each requires, extras and waivers, completions recorded
by hand on the desktop, the matrix (with a CSV export), and a learner app
that shows each person's training. People take online modules (pages, then
a quiz), sign policies, send in their tickets and are signed off on
practicals; a manager checks each ticket in the desktop's Inbox; the worker
emails reminders and a Monday digest. The desktop opens on a classroom, a
desk for each role with its people sitting at it in green, amber or red,
and every screen in a drawer over it; the learner app shows a ring for how
much is done and says Ding! out loud. The outward links (build step 6) are
still to come, as `docs/plans/2026-10-12-simple-lms-design.md` describes.

## What is in this repo

```
CLAUDE.md            rules for Claude Code when working here
docs/plans/          the design and the implementation plans
docs/api.md          every endpoint
.github/workflows/   CI: the tests, both apps' builds, and a Compose start
api/                 FastAPI app, migrations, tests
apps/desktop/        the desktop app (Vite + React)
apps/learner/        the learner app, a PWA at /learn/ (Vite + React)
deploy/Caddyfile     the only door in
docker-compose.yml   api, worker, db, caddy
```

## Getting started

```
git clone https://github.com/q7-technology/simple-lms
cd simple-lms
cp .env.example .env            # set POSTGRES_PASSWORD
(cd apps/desktop && npm ci && npm run build)
(cd apps/learner && npm ci && npm run build)
docker compose up -d
docker compose exec api lms create-user --code AD001 --name "Your Name" --email you@example.com
```

`create-user` asks for a password twice (12 characters or more) and makes an
admin unless you give `--permission`.

**Settings.** An admin changes the everyday settings on the desktop's
**Settings** screen, and they take effect within a few seconds, with no
restart: sign-in methods (code and PIN, email and password, Microsoft), the quiz wait,
the reminder days, the daily job's hour and the time zone, the email server
(with **Send a test email**), and the web address for links in emails.
Each says where its value comes from: set there, from `.env`, or the
default; a value set there wins over `.env`, so an install that only has
`.env` keeps working. What has to be known before Simple LMS starts, or
could lock everyone out, stays in `.env` only: the database and its
password, the ports, the domain, the upload folder and Caddy. Email and
password and Microsoft sign-in can't both be off, nor can an admin switch
off the way they signed in (see "Sign in with Microsoft" below), and
`docker compose exec api lms clear-setting <key>` puts any setting back to
`.env` or the default.

For email, fill in the email server under **Settings** (or `LMS_SMTP_*` in
`.env`, then `docker compose up -d api worker` again). Until it has a host
and a from address, emails wait in the outbox, untried, and nothing else is
held up.

The desktop is at `https://<LMS_DOMAIN>/` (default `https://localhost/`,
self-signed): sign in with that email and password and it opens on the
classroom. Add competencies, then roles and what each requires, then
people. Open **Matrix** in the bar along the top and click a cell to see that
person's history for it and record a completion.

**Game Mode.** The classroom is drawn in the same isometric view as Simple
WMS and Simple TMS: the board and the teacher's desk at the front, then a
desk for each role, three to a row, with the people who have that role
sitting at it (someone with two roles sits at both), coloured by how current
they are: red, with a "!", if anything asked of them has lapsed or is
missing; amber if something runs out within 30 days; green if the rest is
current; grey if nothing is asked. A desk seats six, those who need a look
first, and its label counts the rest ("Picker +12"). Click a desk's label to
open the matrix at that role, or a person to open them in People; someone
with no role yet has no desk, and the line under the heading counts them.
Every screen opens as a drawer over the classroom: ✕, Escape or a click on
the classroom goes back, and the bar along the top stays, so the matrix is
always one click away. **Game Mode** in the bar turns it all off for you, on
that computer: the desktop then opens on the matrix, each screen a page of
its own. It is kept in your browser, never in Simple LMS.

**Policies.** Add a competency of kind *Signed policy*, open it under
**Competencies** and publish version 1 of its text. Each person asked for
it reads it in the learner app, types their name and signs with a finger.
Publishing version 2 asks once on the desktop, then asks everyone to sign
again; the matrix shows them red (missing) until they do. A policy signed on
paper can still be recorded by hand: it counts for the version people are
asked to sign now. Each signature goes on one record only.

**Modules.** Add a competency of kind *Online module* (with a refresher,
say 24 months, if it should be taken again) and open it under
**Competencies**. Start version 1 and add its pages: text, a picture (JPEG
or PNG), a PDF, a video (MP4 or WebM, up to 200 MB, played as uploaded: an
iPhone's `.mov` needs converting to MP4 first) or a link, which opens in a
new tab. Pictures and PDFs may be up to 20 MB. A file shows how much has
sent and can be cancelled while it goes. Move pages up and down or take
them out, write the quiz (2 to 6 answers a question, one of them right)
and the pass mark, and save the draft as often as you like. Closing it
with changes not saved asks first, and if someone else saved the draft
since you opened it, saving says so rather than undoing their work.
Publishing asks once, then freezes that version: its pages and questions
never change, so every attempt stays what was asked. To change it, start
the next version, a copy of the last; people keep taking the old one until
you publish it, and their passes still count: a new version asks nobody to
take it again, the refresher brings them back. The right answers are only
ever sent to those who may edit modules. In the learner app a person reads
one page at a time (where they are is kept by Simple LMS, so they can carry
on from any device), then takes the quiz: a pass says Ding! and counts as
current until the refresher runs out; a fail gives the score and another
go. After three goes in a row that didn't pass, they wait before the next:
an hour by default (both are in Settings; 0 minutes for no wait), and the
player says when they can try again as soon as the fail that starts the
wait is handed in. Every attempt
is kept. A video that is playing counts as a tap, so a
PIN session doesn't end in the middle of it.

**Tickets.** A competency of kind *Ticket or licence* says whether its card
has an expiry date. A person adds a photo of the front and back (or a PDF),
the number and the expiry in the learner app; each photo goes on one ticket
only. It waits in the desktop's **Inbox**, where a manager or admin who is
not them (nobody approves their own) checks the photos and approves it
(current until the card's date) or sends it back with a reason they see.

**Reminders.** Each morning (from 6 am by default, in the business's time
zone; both in Settings) the worker emails each person with an email when
something of theirs reaches a reminder day (30, 14 and 0 days left by
default; also in Settings), saying the real days left (a day the
worker missed still gets the reminder it owed), and on Mondays sends each
manager and admin with an email a digest of what is expiring and lapsed.
Each is sent once. A failed email is tried again after 1 minute, 5, 30 and
2 hours, then left `failed`. To queue them now:
`docker compose exec worker lms daily-job` (add `--on YYYY-MM-DD` to run it
as if today were that date, to try it out).

The learner app is at `https://<LMS_DOMAIN>/learn/`. A person signs in with
their code and PIN (set when they are added, or reset by a manager under
**People**), or their email and password, and sees **My training**: Overdue,
Due soon and Done, with a ring for how much is done ("3 of 5 done"). A pass
on a module or a signed policy says Ding!, out loud unless **Sound** beside
Sign out is off; that switch is the device's, so on a shared tablet it stays
as the last person left it. A PIN session ends after 15 minutes without a tap, and the
app forgets that person on the device then too, even if nobody touches it, so
a shared tablet is safe; signing out in one tab signs out the others. The PIN
form asks the browser not to remember a code or PIN (if a browser offers
anyway, say no on a shared tablet). Five wrong PINs lock
the PIN until a manager sets a new one; five wrong passwords lock the
password for 15 minutes.

The API runs its migrations each time it starts; it is at `/v1`, its
interactive docs at `/docs`, and it is also published on `127.0.0.1:8033`
(`LMS_API_PORT`) for local work. Rebuild an app (`npm run build`) after
pulling changes to it; Caddy serves each `dist` as it is. After editing
`deploy/Caddyfile`, `docker compose restart caddy` picks it up. Back up
the `uploads` volume (tickets' photos, policy signatures and modules'
pictures, PDFs and videos) along with the database: the records and pages
name the files in it. Files are written to disk as they arrive, never held
in memory whole, and Caddy refuses a body bigger than 210 MB on
`/v1/uploads` (16 MB anywhere else in `/v1`) before the API reads it. A
module's files open by links Simple LMS signs for each session, so a
session's token never goes in a URL, and the API's access log leaves out a
link's signature.

On a machine that already runs Simple WMS or Simple TMS, their Caddy has
ports 80 and 443: set `LMS_HTTP_PORT` and `LMS_HTTPS_PORT` in `.env` (say
8280 and 8643) for local work. For a real domain beside a sibling, put the
LMS site on the Caddy that holds 80 and 443 and start only
`docker compose up -d db api`, as Simple TMS's README describes.

## Sign in with Microsoft

People can sign in to either app with their Microsoft work account
(Microsoft Entra ID). Simple LMS never adds anyone this way: a manager adds
the person first, with the email Microsoft has for them, and their first
Microsoft sign-in is matched to them by that email. From then on it is
matched by their Microsoft account itself, whatever their email becomes.
Someone Simple LMS doesn't know is told "Ask your manager to add you."

Register Simple LMS in your tenant once, in the Microsoft Entra admin
center (an Application Administrator can):

1. **App registrations → New registration.** Name it *Simple LMS*. Supported
   account types: *Accounts in this organizational directory only* (single
   tenant). Redirect URI: platform *Web*, and
   `https://<LMS_DOMAIN>/v1/auth/entra/callback`: exactly the web address
   (**Settings → Web address**, or `LMS_PUBLIC_URL`) followed by
   `/v1/auth/entra/callback`, port and all if it isn't 443. Change the web
   address later and this must change with it.
   Register.
2. From **Overview**, copy the *Directory (tenant) ID* and the
   *Application (client) ID*.
3. **Certificates & secrets → New client secret.** Copy its *Value* (not
   its Secret ID) at once: it is shown once. It runs out (24 months at
   most): put a reminder in to make a new one and change `.env` before it
   does.
4. **API permissions.** Microsoft Graph's delegated `openid`, `profile` and
   `email` (the `User.Read` it starts with can stay). **Grant admin
   consent**, so nobody is asked.
5. **Token configuration → Add optional claim → ID:** tick `email` and
   `xms_edov` (if `xms_edov` isn't offered, add it to the manifest's
   `optionalClaims.idToken`). `xms_edov` is Microsoft saying your tenant
   owns the email's domain: without it a first sign-in can't be matched by
   email, and is refused.

Then in `.env` set `LMS_ENTRA_TENANT_ID`, `LMS_ENTRA_CLIENT_ID` and
`LMS_ENTRA_CLIENT_SECRET` (in `.env` only, not on the Settings screen: the
secret is a secret), make sure the web address is set (**Settings → Web
address**, or `LMS_PUBLIC_URL`), and `docker compose up -d api`. `LMS_ENTRA_AUTHORITY` is
Microsoft's address, `https://login.microsoftonline.com`, unless you point it
at a stand-in; it must be an `https://` address or the API won't start. Both sign-in pages now offer **Sign in with
Microsoft**. The learner app asks Microsoft for the password every time, so
a shared tablet never signs the next person in as the last; the desktop
lets people pick their account. Open Simple LMS at its web address to sign
in this way: Microsoft sends people back there, to the tab they started in.
A Microsoft session in the learner app ends
after 15 minutes without a tap, as a PIN's does, so a shared tablet is safe;
on the desktop, after 12 hours. Either lasts a working day (12
hours) at most, since Simple LMS hears nothing from Microsoft once someone
is in: deactivate a person who leaves, as always. If a person was matched
to the wrong account, **Unlink Microsoft** on their record under **People**.

Under **Settings → Sign-in** an admin switches each way of signing in on or
off: code and PIN, email and password, Microsoft (which says there whether
it is set up). Someone already signed in stays signed in until their
session ends. To keep anyone from being locked out, email and password or
Microsoft always stays on (a PIN never opens the desktop), and an admin
can't switch off the way they signed in: so to switch passwords off, sign
in with Microsoft first. If it goes wrong anyway (say the client secret ran
out with passwords off), anyone with the server's command line can put it
back: `docker compose exec api lms clear-setting sign_in_password`.

## Who may do what

| | Learner | Supervisor | Manager | Admin |
| --- | --- | --- | --- | --- |
| See their own training | ✓ | ✓ | ✓ | ✓ |
| Take a module, sign a policy, send in their own ticket | ✓ | ✓ | ✓ | ✓ |
| See the matrix | | own team | everyone | everyone |
| Add and change people, roles, competencies, extras and waivers | | | ✓ | ✓ |
| Write and publish a module's pages and quiz | | | ✓ | ✓ |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
| Approve or reject a ticket (never their own) | | | ✓ | ✓ |
| Unlink someone's Microsoft account | | | ✓ | ✓ |
| Add or change a manager or an admin | | | | ✓ |

A supervisor's team is the people whose supervisor they are, and only
someone with the supervisor, manager or admin permission can be one. Someone
who still supervises active people can't be taken below supervisor or
deactivated until their team has another supervisor, and nobody changes
their own permission or deactivates themselves. Signing in with a PIN only
ever shows your own training, whoever you are, and the desktop turns a
learner away to the learner app.

## Run the API outside Docker

```
docker compose up -d db         # Postgres on 127.0.0.1:5435
cd api
uv venv -p 3.12 && uv pip install -e ".[dev]"
export LMS_DATABASE_URL=postgresql+psycopg://lms:<POSTGRES_PASSWORD>@127.0.0.1:5435/lms
.venv/bin/alembic upgrade head
.venv/bin/lms create-user --code AD001 --name "Your Name" --email you@example.com
.venv/bin/uvicorn lms.api.app:app --reload --port 8033
.venv/bin/python -m lms.worker   # in another terminal, for email and the daily job
```

Outside Docker, set `LMS_UPLOAD_DIR` to a folder of your own (the default
is `/data/uploads`), and give the worker's terminal the same
`LMS_DATABASE_URL`. Stop the `api` and `worker` containers first
(`docker compose stop api worker`), as the API holds 8033.
Then `npm run dev` in `apps/desktop` (http://localhost:5176) or
`apps/learner` (http://localhost:5177/learn/); both send `/v1` to
`127.0.0.1:8033` (`LMS_API_URL` points them elsewhere).

## Tests

pytest against a real PostgreSQL, so the append-only triggers are exercised
for real. The suite creates and resets an `lms_test` database on the compose
`db` service, expecting `POSTGRES_PASSWORD=lms-dev` locally; point
`TEST_DATABASE_URL` elsewhere to use another server.

```
docker compose up -d db
(cd api && .venv/bin/pytest)
(cd apps/desktop && npm test)
(cd apps/learner && npm test)
```

## Stack

Python 3.12 + FastAPI · PostgreSQL 16 · Vite + React + TypeScript + Tailwind
· Docker Compose · Caddy. The same choices as Simple WMS and Simple TMS, so
one person can look after all of them.

## Licence

MIT © 2026 Q7 Technology
