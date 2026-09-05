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
