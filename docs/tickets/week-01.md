# Sprint 1 — Sign in, and the shell

**Slice 1 · Stage A (Foundation) · 30 Aug – 05 Sep 2026**
Board: OmniSight Phase B · Assignee: Ahmad · Reviewer: Cyrine

> **By the end of this sprint:** log in with a real account, land inside the
> application, and stay logged in after a refresh. Nothing is reachable without a
> valid token.

**Covers:** FR-10 · NFR-7 · NFR-8 · NFR-9 · TC-10
**Ships in:** `infra/` · `services/common/` · `services/query/` · `frontend/` ·
`docker-compose.yml` · `.env.example`

---

## The first command

Run this before anything else. `frontend/` currently holds a placeholder
`Dockerfile` and `README.md`; `create-next-app` refuses a non-empty folder, so they
go first.

```bash
cd phase-b
rm frontend/Dockerfile frontend/README.md

npx create-next-app@latest frontend \
  --typescript --tailwind --eslint --app --src-dir \
  --import-alias "@/*" --use-npm
```

If it still prompts for anything (Turbopack, for example), accept the default.

Then put the placeholder Dockerfile back, so the repo still matches the structure
document:

```bash
touch frontend/Dockerfile
```

Next.js writes its own `frontend/README.md`. Leave it — it documents the app. The
folder's purpose is described in the root README.

**Check it works:**

```bash
cd frontend && npm run dev     # http://localhost:3000 shows the Next.js page
```

---

## Ticket order

Thirteen tickets. You have one day, so they are ordered so that stopping early
still leaves something that works. The cut line is marked after OMNI-109.

| # | Ticket | Est. |
|---|---|---|
| OMNI-100 | Put the repo under version control | 10 min |
| OMNI-101 | Scaffold the Next.js frontend | 20 min |
| OMNI-102 | PostgreSQL running under Docker Compose | 30 min |
| OMNI-103 | FastAPI service skeleton | 40 min |
| OMNI-104 | Shared settings and contracts in `common` | 20 min |
| OMNI-105 | Users table, migration, seeded admin | 45 min |
| OMNI-106 | Login endpoint, hashing and JWT | 60 min |
| OMNI-107 | Role enforcement on every protected route | 45 min |
| OMNI-108 | Token expiry and account lockout (NFR-9) | 45 min |
| OMNI-109 | Sign-in page, API client, protected routes | 75 min |
| — | **cut line — everything above this is the graded core** | |
| OMNI-110 | App shell, role-aware sidebar, empty dashboard | 60 min |
| OMNI-111 | Nginx and TLS in front (NFR-8) | 45 min |
| OMNI-112 | Run TC-10 and record it | 30 min |
| OMNI-113 | Verify NFR-9 and record it | 20 min |

---

## OMNI-100 · Put the repo under version control

**Why:** `phase-b/` is not a git repository yet. Nothing else should be built on
top of untracked work.

- [x] `git init` in `phase-b/`
- [x] Add `.pytest_cache/` to `.gitignore` — it appeared when uv sync ran and is
      not currently ignored
- [x] `git status` and confirm `.venv/`, `.pytest_cache/` and `data/*` contents are
      **not** listed
- [x] `git check-ignore -v data/dota/.gitkeep` reports no match (the folder shape is
      tracked, its contents are not)
- [x] First commit: `chore: repository skeleton and uv workspace`
- [-] Create the GitHub repo, private for now, and push

**Acceptance:** `git log` shows one commit; `uv.lock` is in it; no `.venv` files
are.

---

## OMNI-101 · Scaffold the Next.js frontend

**Why:** every screen from slice 5 onward lives inside this app. Getting it wrong
now is expensive later.

- [x] Run the command at the top of this file
- [x] `npm run dev` serves the default page on :3000
- [x] `touch frontend/Dockerfile` to restore the placeholder
- [x] Confirm `frontend/node_modules/` is ignored by the existing `.gitignore`
- [x] Commit: `feat(frontend): scaffold Next.js app`

**Acceptance:** the app builds and runs; `git status` is clean afterwards.

**Note:** the root `README.md` says the frontend is scaffolded with Vite. It is
Next.js. Fix that line in the same commit.

---

## OMNI-102 · PostgreSQL running under Docker Compose

**Why:** `docker-compose.yml` is the deployment. It starts empty; this is the first
service in it.

- [x] Write the `postgres` service into `docker-compose.yml`: image, named volume,
      healthcheck, port
- [x] Credentials and database name come from `.env`, never hardcoded
- [x] Add the matching keys to `.env.example` with placeholder values
- [x] Copy it to your own `.env` and fill it in — `.env` is gitignored, keep it that way
- [x] `docker compose up -d` and connect with `psql` to prove it is reachable
- [x] Named volume so the data survives `docker compose down`

**Acceptance:** `docker compose up -d` starts Postgres; stopping and starting again
keeps the data.

---

## OMNI-103 · FastAPI service skeleton

**Why:** `services/query` is the API behind the dashboard. Everything in later
slices is added to this service.

- [x] Add the dependencies to the workspace member, not the root:

```bash
uv add fastapi "uvicorn[standard]" sqlalchemy alembic "psycopg[binary]" \
       pydantic-settings pyjwt argon2-cffi --package omnisight-query
uv add --dev httpx
```

- [x] Application entry point in `services/query/`, with `/health` returning
      `{"status": "ok"}`
- [x] Settings read from `.env` through pydantic-settings — no literals in code
- [x] JSON request logging
- [x] A single error handler that returns clean JSON, never an HTML traceback
- [x] `uv run uvicorn ...` serves it; `/docs` renders

**Acceptance:** `/health` answers 200; a deliberately broken route returns JSON,
not HTML.

---

## OMNI-104 · Shared settings and contracts in `common`

**Why:** `services/common` exists so the five services cannot quietly disagree.
Better to establish it with two types than to retrofit it with twenty.

- [x] Role enum in `omnisight_common`: `operator`, `analyst`, `admin`
- [x] The shared settings base every service reads its `.env` through
- [x] Import it from `services/query` and confirm the workspace link resolves
      without any `PYTHONPATH` tricks

**Acceptance:** `from omnisight_common import Role` works inside the query service.

---

## OMNI-105 · Users table, migration, seeded admin

**Why:** FR-10 needs somewhere to authenticate against.

Data model, from the plan:

```
users(id, email UNIQUE, password_hash, role, is_active, created_at, last_login_at)
role in {operator, analyst, admin}
```

Two extra columns are needed for NFR-9 in OMNI-108 — add them now rather than
writing a second migration:

```
failed_attempts INT DEFAULT 0
locked_until    TIMESTAMPTZ NULL
```

- [ ] SQLAlchemy model
- [ ] `alembic init`, configured to read the database URL from settings
- [ ] First migration, applied with `alembic upgrade head`
- [ ] Seed script in `scripts/` creating one admin account
- [ ] Confirm the row exists and `password_hash` is a hash, not a password

**Acceptance:** the table exists after `alembic upgrade head`; the seeded admin is
in it; running the seed twice does not create a duplicate.

---

## OMNI-106 · Login endpoint, hashing and JWT

**Why:** **FR-10** — *Authenticate users before accessing any system feature.*

API surface:

```http
POST /auth/login {email,password} -> {access_token, token_type, role}
GET  /auth/me -> {id, email, role}
POST /auth/logout
Any request without a valid token -> 401
```

- [ ] Passwords hashed with argon2 — plaintext is never stored **[NFR-7]**
- [ ] `POST /auth/login` verifies and issues a JWT carrying user id, role and an
      expiry **[FR-10]**
- [ ] Signature *and* expiry verified on every request — an expired token is
      rejected, not merely old
- [ ] `GET /auth/me` returns the current user from the token
- [ ] `POST /auth/logout`
- [ ] One error message for a wrong email and a wrong password, identical in both
      cases — it must not reveal whether an address exists
- [ ] `last_login_at` updated on success

**Acceptance:** correct credentials return a token; wrong password returns 401 with
no token; the two failure messages are byte-identical.

---

## OMNI-107 · Role enforcement on every protected route

**Why:** **NFR-7** — *100% of API endpoints and MCP tools reject requests lacking a
valid token or sufficient role.* This is the graded part of the week.

- [ ] A dependency that every protected route depends on — not a check written
      route by route
- [ ] The role travels on the token and is enforced server-side. Hiding a menu item
      in the UI is not enforcement
- [ ] Any request without a token, or with an expired or tampered one, returns 401
- [ ] A valid token with an insufficient role returns 403
- [ ] Add one admin-only route so the 403 path is real and testable

**Acceptance:** all three conditions behave correctly on at least two routes.

---

## OMNI-108 · Token expiry and account lockout

**Why:** **NFR-9** — *Authentication tokens expire after 15 minutes of inactivity,
and an account is locked after 5 consecutive failed login attempts.*

- [ ] Token lifetime 15 minutes, driven by inactivity rather than a fixed clock
- [ ] `failed_attempts` increments on each failed login and resets to zero on
      success
- [ ] At 5 consecutive failures the account locks — set `locked_until`
- [ ] A locked account is refused even with the correct password
- [ ] The lock duration comes from settings, not a literal

**Acceptance:** five wrong passwords lock the account; the sixth attempt is refused
with the right password; an idle session stops working after 15 minutes.

---

## OMNI-109 · Sign-in page, API client, protected routes

**Why:** FR-10 has to be visible, not just true in the database.

- [ ] Sign-in screen: email, password, submit, and one error message that never
      reveals whether the address exists
- [ ] One API client, in one file, that attaches the token to every request and
      redirects to sign-in on any 401 — never a `fetch` call scattered in a component
- [ ] Token persisted so a refresh keeps the session
- [ ] Protected route wrapper: an unauthenticated visit to any internal URL lands
      on sign-in

**Acceptance:** sign in with the seeded admin and reach the app; refresh and stay
signed in; open an internal URL in a private window and get bounced to sign-in.

> **Cut line.** If the day runs out here, you have shipped FR-10 end to end with
> NFR-7 and NFR-9 enforced. That is the defensible core. Everything below is
> genuinely deferrable to next week — **except** the role checks in OMNI-107, which
> are not.

---

## OMNI-110 · App shell, role-aware sidebar, empty dashboard

**Why:** FR-9's frame. Building it now means every later slice fills a tile that is
already on screen.

- [ ] Top bar: product name, notifications area, account menu
- [ ] Left sidebar with the ten product routes
- [ ] Role-aware sidebar: entries a role may not use are not rendered at all
- [ ] Operations Dashboard as the home screen, with every tile present but empty —
      alerts needing attention, camera health, activity, recent reports, storage
- [ ] Each empty tile labelled with the slice that will fill it

**Acceptance:** signing in lands on the dashboard; an operator and an admin see
different sidebars.

---

## OMNI-111 · Nginx and TLS in front

**Why:** **NFR-8** — *100% of traffic encrypted with TLS 1.2+; plaintext bytes = 0.*

- [ ] `nginx` service in `docker-compose.yml`, config in `infra/nginx/`
- [ ] Self-signed certificate for development, generated by a script in `scripts/`
      and gitignored — never commit a key, not even a throwaway one
- [ ] TLS 1.2 minimum
- [ ] Nginx proxies to the API and to the frontend
- [ ] Plain HTTP redirects to HTTPS

**Acceptance:** the app is reachable over `https://localhost`; plain HTTP redirects;
the browser's certificate warning is the expected self-signed one.

---

## OMNI-112 · Run TC-10 and record it

**Why:** **TC-10** — *Protect every endpoint with authentication and role-based
authorization.* Recording it is part of the test, not paperwork after it.

- [ ] Test file under `tests/` hitting **every** protected endpoint under three
      conditions:
  1. valid token, correct role → 200
  2. valid token, insufficient role → 403
  3. no token, or expired or invalid → 401
- [ ] `uv run pytest` passes
- [ ] Write the result into `docs/results.md` today — date, endpoints covered,
      pass or fail per condition

**Acceptance:** the suite passes, and `docs/results.md` has a TC-10 entry dated
this week.

---

## OMNI-113 · Verify NFR-9 and record it

- [ ] Test: five failed logins lock the account
- [ ] Test: a token past its inactivity window is rejected
- [ ] Record both in `docs/results.md` under NFR-9

**Acceptance:** both tests pass and are recorded.

---

## Definition of done for the sprint

Copied from the plan's "Proof it works" — this is what you demonstrate to Cyrine:

> Sign in with the seeded account and reach the application. Wrong password is
> rejected with no token issued. Any internal URL without a token returns you to
> sign-in. A refresh keeps you signed in. TC-10 passes in all three conditions.

- [ ] All of the above is true on a fresh `docker compose up -d`
- [ ] `docs/results.md` has this week's TC-10 and NFR-9 entries
- [ ] Everything committed and pushed
- [ ] Slice 1 ticked off on the tracker

---

## Working with Claude Code

One ticket per session. Paste the ticket, then this:

> Here is ticket OMNI-1xx from our sprint board. Implement exactly what it asks
> and nothing more. The repo is a uv workspace — add Python dependencies with
> `uv add <pkg> --package omnisight-query`, never with pip and never to the root
> project. Settings come from `.env` through pydantic-settings; no configuration
> literals in code. When you are done, show me the diff and tell me which
> acceptance criteria you verified and how.

Two things worth insisting on, because they cost days later if they slip:

- **Role checks belong in one dependency**, not repeated per route. Ask for it that
  way even if Claude Code offers something quicker.
- **No secrets in the repo.** If a generated file contains a password, a key or a
  certificate, it is gitignored before it is committed, not after.
