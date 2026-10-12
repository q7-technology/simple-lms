# Simple LMS

An open source, self-hosted learning management system for workplace
training: inductions, online modules, practical sign-offs, outside tickets
and licences, and signed policies. It answers one question for a business and
its auditors: is each person current for everything their job needs? It sits
beside Simple WMS, Simple TMS and Platen and works without any of them.

Status: **build step 1, the skeleton.** People with a code and PIN or an
email and password, roles and the competencies each requires, extras and
waivers, completions recorded by hand on the desktop, the matrix (with a CSV
export), and a learner app that shows each person's training. Policies,
tickets, modules, practicals, Entra sign-in and the outward links come with
the next steps in `docs/plans/2026-10-12-simple-lms-design.md`.

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
docker-compose.yml   api, db, caddy
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

`create-user` asks for a password (12 characters or more) and makes an
admin unless you give `--permission`.

The desktop is at `https://<LMS_DOMAIN>/` (default `https://localhost/`,
self-signed): sign in with that email and password and it opens on the
matrix. Add competencies, then roles and what each requires, then people.
Click a cell to see that person's history for it and record a completion.

The learner app is at `https://<LMS_DOMAIN>/learn/`. A person signs in with
their code and PIN (set when they are added, or reset by a manager under
**People**), or their email and password, and sees **My training**: Overdue,
Due soon and Done. A PIN session ends after 15 minutes without a tap, and the
app forgets that person on the device then too, even if nobody touches it, so
a shared tablet is safe; signing out in one tab signs out the others. The PIN
form asks the browser not to remember a code or PIN (if a browser offers
anyway, say no on a shared tablet). Five wrong PINs lock
the PIN until a manager sets a new one; five wrong passwords lock the
password for 15 minutes.

The API runs its migrations each time it starts; it is at `/v1`, its
interactive docs at `/docs`, and it is also published on `127.0.0.1:8033`
(`LMS_API_PORT`) for local work. Rebuild an app (`npm run build`) after
pulling changes to it; Caddy serves each `dist` as it is.

On a machine that already runs Simple WMS or Simple TMS, their Caddy has
ports 80 and 443: set `LMS_HTTP_PORT` and `LMS_HTTPS_PORT` in `.env` (say
8280 and 8643) for local work. For a real domain beside a sibling, put the
LMS site on the Caddy that holds 80 and 443 and start only
`docker compose up -d db api`, as Simple TMS's README describes.

## Who may do what

| | Learner | Supervisor | Manager | Admin |
| --- | --- | --- | --- | --- |
| See their own training | ✓ | ✓ | ✓ | ✓ |
| See the matrix | | own team | everyone | everyone |
| Add and change people, roles, competencies, extras and waivers | | | ✓ | ✓ |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
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
```

Stop the `api` container first (`docker compose stop api`), as it holds
8033. Then `npm run dev` in `apps/desktop` (http://localhost:5176) or
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
