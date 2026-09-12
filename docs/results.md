# Results

Every measurement, written the week it's taken.

## TC-10 · Protect every endpoint with authentication and role-based authorization — 2026-09-05

**Suite:** `services/query/tests/test_tc10_auth.py`
**Run:** `uv run pytest` — 15 passed, 0 failed.

Endpoints covered (every protected route in `services/query`; `/auth/login`
is the public entry point and `/health` is deliberately public, so neither is
in scope for TC-10):

| Endpoint | Valid token, correct role → 200 | Valid token, insufficient role → 403 | No / expired / tampered token → 401 |
|---|:--:|:--:|:--:|
| `GET /auth/me` | pass | n/a — no role restriction beyond "authenticated" | pass |
| `GET /nav` | pass | n/a — no role restriction beyond "authenticated" | pass |
| `POST /auth/logout` | pass | n/a — no role restriction beyond "authenticated" | pass |
| `GET /admin/ping` | pass | pass | pass |

`/admin/ping` is the only route gated to a specific role (admin) rather than
"any authenticated user," so it's the only one where the 403 condition
applies — that's exactly why it was added in OMNI-107, to make the 403 path
real and testable. "No / expired / tampered" is tested as three separate
cases per endpoint in the suite (no `Authorization` header; a token with
`exp` in the past, signed with the real secret; a valid token with its last
character flipped) — all three return 401 everywhere.

**Test users:** two accounts created at the start of the run
(`tc10-admin@omnisight.local`, `tc10-operator@omnisight.local`) and deleted
at the end — confirmed no `tc10-*` rows remain in `users` after the suite
finishes.

**Requires:** Postgres running (`docker compose up -d`) — the suite hits the
real database, same as everything else verified this sprint.

## NFR-9 · Tokens expire after 15 minutes of inactivity; accounts lock after 5 failed logins — 2026-09-05

**Suite:** `services/query/tests/test_nfr9_lockout_expiry.py`
**Run:** `uv run pytest` — 2 passed, 0 failed.

| Test | Result |
|---|:--:|
| Five failed logins lock the account | pass |
| A token past its inactivity window is rejected | pass |

**Five failed logins:** a throwaway account attempts login with a wrong
password five times in a row. After the fifth, `failed_attempts = 5` and
`locked_until` is set in the future (`account_lockout_minutes` ahead of
`now()`) — confirmed directly against the database. A sixth attempt with the
**correct** password is still refused (`401`), proving the lock is enforced
before password verification, not after.

**Idle token rejected:** a JWT signed with the real `jwt_secret_key` but with
`exp` one minute in the past (simulating a session idle past its 15-minute
window) is rejected with `401` on a protected route. This exercises the same
expiry check that OMNI-108's sliding renewal (`X-Access-Token` header) relies
on — a token that's never renewed because no request was made with it
eventually expires exactly this way.

**Test user:** one throwaway account (`nfr9-lockout-test@omnisight.local`)
created before the test and deleted after — confirmed no `nfr9-*` rows
remain in `users` afterward.

**Requires:** Postgres running (`docker compose up -d`).

## NFR-5 · On any failure or crash, video or stored data lost = 0 — 2026-09-12

**Method:** live checks against the running stack (`docker compose up -d`),
not a `pytest` suite — this is proving real container/volume behavior, not
application logic. All three checks used a real uploaded video, not a
fixture.

| Check | Result |
|---|:--:|
| `docker compose restart` — row and file survive | pass |
| `docker compose down` + `up -d` — row and file survive | pass |
| Kill `query` mid-upload — no orphan row | pass |

**`docker compose restart`:** uploaded a real 5-second, 21,086-byte MP4
(`sha256: 36afef16…b895f`), confirmed via `GET /videos/{id}` and a checksum
of the file on disk. Restarted every container in place. Checksum after
restart: identical. `GET /videos/{id}` after restart: identical record,
same id, same `size_bytes`, same `duration_s`.

**`docker compose down` + `up -d`:** same video, same checks, this time
after fully removing and recreating every container (not just restarting
them) — `docker compose ps -a` showed zero containers between the two
commands, confirming this genuinely tore down and rebuilt the stack, not a
no-op. `docker volume ls` confirmed `phase-b_postgres_data` and
`phase-b_video_storage` — the two volumes this check cares about — survived
the teardown untouched, which is the entire reason OMNI-205 used named
volumes rather than a bind mount to a temp directory. Checksum after:
identical. Login with an existing account and `GET /videos/{id}` both
succeeded with the same record, confirming both volumes (`postgres_data`
for the user row surviving login, `video_storage` for the file) came back
correctly, not just one of the two.

**Kill `query` mid-upload:** the real test, and the one that needed two
attempts to actually exercise. The first attempt sent a request through
nginx with an artificially slow client; killing `query` produced no
database row (correct) but also no partial file at all, because nginx
buffers a client's entire request body before forwarding it upstream by
default (`proxy_request_buffering on`) — the slow client only fooled nginx,
`query` itself had received nothing yet when it died. Second attempt went
directly to `query`'s own published port (bypassing nginx entirely) with a
real, unthrottled 480 MB upload, killing the container from inside the same
Python process that was sending it — timed off the client's own
byte-counter (`docker kill` fired automatically at 40% sent, 201,326,632 of
503,316,480 bytes), removing any dependency on guessing timing across
separate tool calls. The client's request ended with a genuine
`ConnectionAbortedError` (`WinError 10053`), confirming `query` really did
die mid-transfer, not after. After restarting `query`: zero rows for the
interrupted filename, and no orphaned `.part` file either — the row is only
ever created after `services/query/app/videos.py`'s
`staging_path.replace(final_path)` succeeds (OMNI-205), so an interruption
before that point — during either the network receive or query's own
copy-to-volume step — can only ever produce "nothing," never a row pointing
at something incomplete. A first attempt at 450 MB (a smaller multiplier,
sent without instrumented timing) actually completed — write, rename,
insert, probe, response — in well under the ~1–2 seconds it took to react
and issue `docker kill` manually from a separate command, which is itself a
data point: on this stack, a sub-500 MB upload can complete faster than an
operator can interrupt it by hand, which is exactly why the second attempt
timed the kill programmatically instead of by reflex.

**Requires:** Postgres, `query` and `ingestion` running
(`docker compose up -d`); Docker CLI access on the host to actually kill and
restart containers.

## Definition of done — the plan's own demo, fresh — 2026-09-12

**Method:** `docker compose down -v` (wiped `postgres_data`, `video_storage`
and `frontend_node_modules` — a genuinely empty state, not a reused dev
database), `docker compose up -d`, `alembic upgrade head`, two freshly
seeded accounts (one admin, one operator), then the plan's own four-part
demo run end to end.

| Demo step | Result |
|---|:--:|
| Register a camera against the simulator, Test Connection reports resolution and fps | pass — `640x360 @ 15.0 fps`, status `connected` |
| An invalid address reports a specific reason | pass — `error: "unreachable"` |
| Upload an MP4: correct duration and size | pass — 7.000s source, `duration_s: 7.0` exact; `size_mb: 0.03` matching the real file |
| Same upload survives a container restart | pass — file checksum and full record identical before/after `docker compose restart` |
| An operator account cannot delete a camera | pass — `403 {"detail":"insufficient role"}`, camera still present afterward |

All four ran against real containers, real ffmpeg-generated video, and a
real RTSP address served by the OMNI-201 simulator — not mocked, and not
reusing state left over from earlier tickets' verification.

`uv run pytest` afterward — **62 passed** — confirms the wipe and reseed
didn't leave the application itself in a state the rest of the suite
disagrees with.

**Not covered by this entry:** "Merged and pushed" — a git action, out of
scope for a results entry and not done as part of this check.
