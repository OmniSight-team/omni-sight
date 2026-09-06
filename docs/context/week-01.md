# Context notes — Sprint 1

## OMNI-102 · PostgreSQL running under Docker Compose

### Why this ticket exists

`docker-compose.yml` is the deployment target for the whole system, and it started
empty. Postgres is the first service added to it because OMNI-105/106 (users table,
login) need a real database to authenticate against.

### What was built

**`docker-compose.yml`** — a single `postgres` service:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

- **Image:** `postgres:16-alpine` — small, standard Postgres 16.
- **Credentials:** never hardcoded. `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
  are all read from the environment, which Docker Compose fills in from `.env`.
- **Port:** `${POSTGRES_PORT:-5432}` — configurable, defaults to 5432.
- **Healthcheck:** `pg_isready` against the configured user/db, so `docker compose ps`
  reports `healthy` only once Postgres actually accepts connections.
- **Named volume:** `postgres_data`, mounted at Postgres's data directory, so the
  database survives a container restart or `docker compose down`.

**`.env.example`** — the matching placeholder keys, committed so anyone cloning the
repo knows what to fill in:

```
POSTGRES_USER=changeme
POSTGRES_PASSWORD=changeme
POSTGRES_DB=omnisight
POSTGRES_PORT=5432
```

**`.env`** — your real copy of the above. Gitignored (matched by `*.env` in
`.gitignore`), confirmed to never show up in `git status`.

### The stale-volume incident

The first `docker compose up -d` failed to authenticate:

```
FATAL:  role "changeme" does not exist
```

Investigation showed a volume named `phase-b_postgres_data` already existed on disk,
created **2026-08-22** — before this `docker-compose.yml` was even written. Postgres
only runs its initialization (creating the configured user/db) the *first* time a data
directory is empty; against that old, already-initialized volume, the current `.env`
credentials didn't match whatever it was created with.

Since it held no real data, the fix was to wipe it and start clean:

```bash
docker compose down -v   # removes containers, network, AND the named volume
docker compose up -d     # recreates everything, Postgres initializes fresh from .env
```

### Verification performed

1. **Reachability** — connected via `psql` from inside the container:
   ```bash
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT current_database(), current_user;"
   ```
   Returned `omnisight` / `changeme` — confirms the credentials in `.env` actually
   work against the running container.

2. **Persistence** — proved the named volume survives a stop/start cycle:
   - Created a throwaway table and inserted one row.
   - `docker compose down` (**without** `-v`, so the volume is kept).
   - `docker compose up -d` again.
   - Queried the table — the row was still there.
   - Dropped the throwaway table to leave the database clean.

### Result

- `docker compose up -d` starts Postgres, reachable on `localhost:5432`.
- Stopping and starting again keeps the data (proven above).
- No credentials are hardcoded anywhere in `docker-compose.yml`.
- All five OMNI-102 checklist items and its acceptance criterion are satisfied.

---

## OMNI-103 · FastAPI service skeleton

### Why this ticket exists

`services/query` is the API behind the dashboard, and every later slice (auth,
role enforcement, everything else in this sprint) adds to it. It needed a real,
running skeleton before any of that could land.

### What was built

**Dependencies**, added to the `omnisight-query` workspace member (never the root
project):

```bash
uv add fastapi "uvicorn[standard]" sqlalchemy alembic "psycopg[binary]" \
       pydantic-settings pyjwt argon2-cffi --package omnisight-query
uv add --dev httpx --package omnisight-query
```

`argon2-cffi` was already declared in `services/query/pyproject.toml` from an
earlier attempt, so it didn't show up as "newly installed" — confirmed instead by
importing it directly.

**`services/query/app/main.py`** — the FastAPI entry point:

```python
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.logging_conf import configure_logging
from app.settings import settings

configure_logging()
logger = logging.getLogger("app.request")

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        },
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        extra={"extra_fields": {"path": request.url.path, "error": str(exc)}},
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

**`services/query/app/settings.py`** — pydantic-settings, no config literals in
`main.py`:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    app_name: str = "omnisight-query"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5432


settings = Settings()
```

`REPO_ROOT` is computed from the file's own location rather than the process's
current working directory, so `.env` (which lives at the repo root, not inside
`services/query`) resolves correctly no matter where the app is launched from.

**`services/query/app/logging_conf.py`** — a small `JsonFormatter` that renders
every log record as one JSON line on stdout, used by both the request-logging
middleware and the error handler above.

### Verification performed

1. **`/health`** — `curl` returned `{"status":"ok"}`, `200`.
2. **Settings load from `.env`** — `from app.settings import settings` resolved
   `app_name`, `postgres_db`, `postgres_port` from the real `.env` file,
   regardless of the shell's current directory.
3. **JSON request logging** — hitting `/health` produced this log line:
   ```json
   {"level": "INFO", "logger": "app.request", "message": "request", "method": "GET", "path": "/health", "status_code": 200, "duration_ms": 2.75}
   ```
4. **Error handler** — added a temporary `/_broken` route that raised
   `RuntimeError`, hit it, confirmed the *client* got back clean JSON:
   ```
   HTTP/1.1 500 Internal Server Error
   content-type: application/json

   {"detail":"internal server error"}
   ```
   (Uvicorn still logs its own server-side traceback to the console for
   observability — that's separate from, and doesn't affect, what the HTTP
   response body contains.) Removed the temporary route afterward.
5. **`/docs` and `/openapi.json`** — both `200` via
   `uv run uvicorn app.main:app --app-dir services/query`.

### A port-conflict detour

A couple of test runs left a stray `uvicorn` process holding port 8000/8010
after `pkill` didn't catch it (Windows process naming didn't match the pattern).
Fixed each time by finding the actual PID via `netstat -ano` and force-killing it
with `taskkill //F //PID <pid>` — not a code issue, just leftover local dev
processes.

### Result

- `/health` answers `200` with `{"status": "ok"}`.
- A deliberately broken route returns JSON, never an HTML traceback.
- Settings come from `.env` via pydantic-settings; no literals in `main.py`.
- Every request is logged as one JSON line.
- All checklist items and the acceptance criterion for OMNI-103 are satisfied.

---

## OMNI-104 · Shared settings and contracts in `common`

### Why this ticket exists

`services/common` exists so the five services can't quietly disagree on basics
like what roles exist or how `.env` gets read. Better to establish that now, with
two types, than to retrofit it later across twenty.

### What was built

**`services/common/omnisight_common/roles.py`** — the shared role enum:

```python
from enum import StrEnum


class Role(StrEnum):
    OPERATOR = "operator"
    ANALYST = "analyst"
    ADMIN = "admin"
```

**`services/common/omnisight_common/settings.py`** — the shared settings base
every service's own settings class builds on:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")
```

`REPO_ROOT` is computed from this file's own location, not the process's working
directory, so `.env` (at the repo root) resolves the same way no matter which
service imports it or where it's launched from.

**`services/common/omnisight_common/__init__.py`** — exports both:

```python
from omnisight_common.roles import Role
from omnisight_common.settings import CommonSettings

__all__ = ["Role", "CommonSettings"]
```

`pydantic-settings` was added as a real dependency of `omnisight-common` itself
(`uv add pydantic-settings --package omnisight-common`), since it's now actually
used there, not just re-exported.

**`services/query/app/settings.py`** was refactored to stop duplicating the
`.env`-path logic and inherit from the shared base instead:

```python
from omnisight_common import CommonSettings


class Settings(CommonSettings):
    app_name: str = "omnisight-query"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5432


settings = Settings()
```

`omnisight-common` was already wired as a workspace dependency of
`omnisight-query` (`[tool.uv.sources] omnisight-common = { workspace = true }`
in `services/query/pyproject.toml`), so no new dependency wiring was needed —
just the import.

### Verification performed

1. **`from omnisight_common import Role` inside the query service**:
   ```bash
   uv run --package omnisight-query python -c "from omnisight_common import Role; print(list(Role))"
   ```
   → `[<Role.OPERATOR: 'operator'>, <Role.ANALYST: 'analyst'>, <Role.ADMIN: 'admin'>]`

2. **No `PYTHONPATH` tricks, different working directory** — ran from inside
   `services/query` with `PYTHONPATH` explicitly unset (`env -u PYTHONPATH`),
   importing both `Role` and the refactored `Settings`:
   ```
   Role: [<Role.OPERATOR: 'operator'>, <Role.ANALYST: 'analyst'>, <Role.ADMIN: 'admin'>]
   settings: omnisight-query omnisight 5432
   ```
   Confirms the workspace link resolves through `uv` alone — no path hacks.

3. **App still boots** — ran `uvicorn app.main:app` after the settings refactor;
   `/health` still returned `{"status":"ok"}`.

### Result

- `Role` and `CommonSettings` live in `omnisight_common`, importable from any
  workspace member.
- `services/query`'s settings now inherit `.env` handling from the shared base
  instead of duplicating it.
- All three checklist items and the acceptance criterion for OMNI-104 are
  satisfied.

---

## OMNI-105 · Users table, migration, seeded admin

### Why this ticket exists

FR-10 (authenticate users) needs somewhere real to authenticate against. The
data model — including the two NFR-9 columns needed later in OMNI-108 — was
added now rather than in a second migration.

### What was built

**`services/query/app/db.py`** — the SQLAlchemy `Base`, `engine` and
`SessionLocal`, built from `settings.database_url`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.settings import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

`Settings` gained `postgres_host` (default `"localhost"`) and a
`database_url` property assembling the connection string — still no
literals, still sourced from `.env` through the OMNI-104 base.

**`services/query/app/models.py`** — the `User` model, matching the ticket's
data model exactly:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`role` uses `omnisight_common.Role` directly — one enum, shared with the rest
of the system (OMNI-104). `values_callable` is needed because SQLAlchemy's
`Enum` defaults to storing a Python enum's *member names*
(`OPERATOR`/`ANALYST`/`ADMIN`); the ticket's spec calls for lowercase values,
so the callable tells it to store `.value` instead.

**`services/query/alembic/`** — initialized with `alembic init alembic`, then
`env.py` edited to:
- add `services/query` to `sys.path` (so `app.*` imports resolve),
- set `sqlalchemy.url` from `settings.database_url` instead of `alembic.ini`,
- point `target_metadata` at `Base.metadata`.

`alembic.ini`'s placeholder `sqlalchemy.url` was commented out with a note
that it's overridden at runtime, so it can't be mistaken for the real config.

First migration, `create users table`, generated via `alembic revision
--autogenerate` and applied via `alembic upgrade head`.

**`scripts/seed_admin.py`** — idempotent seed script:

```python
def seed_admin() -> None:
    with SessionLocal() as session:
        existing = session.query(User).filter_by(email=settings.admin_email).first()
        if existing:
            print(f"admin account already exists: {existing.email}")
            return

        admin = User(
            email=settings.admin_email,
            password_hash=ph.hash(settings.admin_password),
            role=Role.ADMIN,
            is_active=True,
        )
        session.add(admin)
        session.commit()
        print(f"seeded admin account: {admin.email}")
```

Checks by email before inserting — running it twice is a no-op the second
time. Password hashed with `argon2-cffi`'s `PasswordHasher`. `ADMIN_EMAIL` /
`ADMIN_PASSWORD` added to `.env.example` and `.env`, same pattern as the
Postgres credentials.

### Two environment issues found along the way

1. **`.env` had CRLF line endings** on the Postgres lines — a Windows-editor
   artifact. That meant `POSTGRES_PASSWORD` was literally `changeme\r`, not
   `changeme`. Invisible in most contexts, but `psycopg`/SQLAlchemy sent it
   verbatim, causing password-authentication failures. Fixed by normalizing
   `.env` to LF (`sed -i 's/\r$//' .env`) and recreating the Postgres volume
   so it initialized fresh with the corrected password.

2. **Port 5432 conflict** — even after fixing the line endings, connections
   from the host still failed authentication, while `docker compose exec ...
   psql` (which stays inside the container's network namespace) worked fine.
   `netstat` showed **two** processes listening on `0.0.0.0:5432`: Docker's
   own proxy, and a native Windows PostgreSQL 15 service
   (`postgresql-x64-15`, unrelated to this project). Host-side connections to
   `localhost:5432` were landing on the native instance, not the container.
   Fixed by stopping that Windows service — the container's own port mapping
   was already correct.

### Verification performed

1. **Table shape** — `\d users` in `psql` matches the ticket's spec exactly,
   including `failed_attempts` and `locked_until`.
2. **Seed idempotency** — ran `scripts/seed_admin.py` twice; the second run
   printed `admin account already exists` instead of inserting a duplicate.
3. **Row + hash check**:
   ```sql
   SELECT count(*) FROM users WHERE email='admin@omnisight.local';        -- 1
   SELECT email, role, is_active, left(password_hash, 20), length(password_hash)
   FROM users;
   -- admin@omnisight.local | admin | t | $argon2id$v=19$m=655... | 97
   ```
   Confirms exactly one row, and `password_hash` is a genuine Argon2 hash
   (97 characters, `$argon2id$...` prefix), never the plaintext password.

### Result

- The `users` table exists after `alembic upgrade head`, matching the spec.
- The seeded admin account exists exactly once, with a hashed password.
- Running the seed script again does not create a duplicate.
- All checklist items and the acceptance criterion for OMNI-105 are
  satisfied.

---

## OMNI-106 · Login endpoint, hashing and JWT

### Why this ticket exists

FR-10 — authenticate users before they can reach any system feature. Up to
now the users table existed but nothing checked a password against it.

### What was built

**`services/query/app/security.py`** — the one place Argon2 hashing and JWT
handling live:

```python
def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[JWT_ALGORITHM])
```

`scripts/seed_admin.py` (from OMNI-105) was refactored to call
`hash_password` from here instead of instantiating its own `PasswordHasher` —
one hashing implementation, not two.

Settings gained `jwt_secret_key` (a real random secret, generated with
`secrets.token_urlsafe(48)` and placed in `.env`; only a placeholder in
`.env.example`) and `access_token_expire_minutes` (default `15` — already the
NFR-9 value, though the inactivity-based sliding renewal is OMNI-108's job,
not this ticket's).

**`services/query/app/schemas.py`** — `LoginRequest`, `TokenResponse`,
`UserResponse`.

**`services/query/app/auth.py`** — the `/auth` router:

- `POST /auth/login` — looks up the user by email, verifies the password,
  updates `last_login_at`, returns a JWT carrying `sub` (user id) and `role`.
  On failure (wrong email *or* wrong password), raises the same
  `401 {"detail": "invalid email or password"}` either way — never reveals
  which part was wrong.
- `get_current_user` — a dependency that reads the `Authorization: Bearer`
  header, decodes the JWT, and loads the user. Uses
  `HTTPBearer(auto_error=False)` rather than the default `HTTPBearer()`,
  because FastAPI's default raises `403` for a missing header — the ticket
  requires `401` for *any* invalid-or-missing token, so the check is done
  manually.
- `GET /auth/me` — returns `{id, email, role}` for the current user.
- `POST /auth/logout` — requires a valid token too (matches real usage even
  though JWTs are stateless; there's no revocation list, so this is a
  formality — the client is expected to discard the token).

`app/db.py` gained a `get_db()` generator dependency (yields a `SessionLocal`,
closes it after the request) used by all of the above.

### Verification performed

1. **Correct credentials** — `POST /auth/login` with the real seeded admin
   credentials → `200`, JSON containing a JWT and `"role":"admin"`.
2. **Wrong password vs. wrong email** — both produced the exact same body,
   byte-identical:
   ```
   {"detail":"invalid email or password"}   status:401
   ```
3. **`/auth/me`**:
   - valid token → `200 {"id":1,"email":"admin@omnisight.local","role":"admin"}`
   - no token → `401 {"detail":"invalid or expired token"}`
   - garbage token → same `401`
4. **Expiry is actually checked, not just the signature** — crafted a token
   signed with the real secret but with `exp` one minute in the past; `/auth/me`
   still rejected it with `401`.
5. **`last_login_at`** — queried the row directly after login; timestamp had
   updated to the login time.
6. **`/auth/logout`** with a valid token → `200 {"detail":"logged out"}`.

### Result

- `/auth/login`, `/auth/me`, `/auth/logout` all behave as specified.
- Passwords are never stored in plaintext; hashing lives in one shared module.
- Both the JWT signature and its expiry are verified on every protected
  request.
- All checklist items and the acceptance criterion for OMNI-106 are
  satisfied.

---

## OMNI-107 · Role enforcement on every protected route

### Why this ticket exists

NFR-7 — 100% of endpoints must reject requests lacking a valid token or
sufficient role. Explicitly called out as the graded part of the week, so it
needed one shared mechanism, not a check copy-pasted into each route.

### What was built

**`services/query/app/deps.py`** — the one dependency module every protected
route depends on. `get_current_user` moved here from `auth.py` (no behavior
change, just a shared home), and a new `require_role` dependency *factory*:

```python
def require_role(*allowed_roles: Role):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=INSUFFICIENT_ROLE_MESSAGE)
        return current_user

    return dependency
```

A route declares its allowed roles with `Depends(require_role(Role.ADMIN))` —
the role check itself lives in exactly one place, and it reads the role off
the JWT's claims (enforced by `get_current_user`/`decode_access_token`), never
from anything the client could control unilaterally like a UI state.

**`services/query/app/admin.py`** — the admin-only route the ticket asks for,
so the 403 path is real and testable:

```python
@router.get("/ping")
def admin_ping(current_user: User = Depends(require_role(Role.ADMIN))) -> dict[str, str]:
    return {"status": "ok", "admin": current_user.email}
```

`app/auth.py` was updated to import `get_current_user` from `app.deps`
instead of defining its own copy.

### Verification performed

Needed a non-admin user to exercise the 403 path, so a temporary `operator`
role account was created directly via `SessionLocal`, used for the tests
below, then deleted afterward.

**`/admin/ping`**:
| condition | result |
|---|---|
| no token | `401 {"detail":"invalid or expired token"}` |
| tampered token | `401` (same message) |
| valid token, operator role | `403 {"detail":"insufficient role"}` |
| valid token, admin role | `200 {"status":"ok","admin":"admin@omnisight.local"}` |

**`/auth/me`**:
| condition | result |
|---|---|
| no token | `401 {"detail":"invalid or expired token"}` |
| valid token, operator role | `200` — any authenticated role is allowed here, since `/auth/me` has no role restriction, only `require_role`-gated routes do |

Together the two routes demonstrate all three conditions (401 for
missing/tampered tokens, 403 for insufficient role, 200 for a valid
sufficient-role token), matching the acceptance criterion.

### Result

- Role enforcement lives in one dependency (`require_role`), used by every
  route that needs it — not re-implemented per route.
- The role travels on the JWT and is checked server-side; nothing about
  enforcement depends on the UI.
- All checklist items and the acceptance criterion for OMNI-107 are
  satisfied.

---

## OMNI-108 · Token expiry and account lockout

### Why this ticket exists

NFR-9: tokens expire after 15 minutes of *inactivity* (not a fixed clock from
login), and an account locks after 5 consecutive failed logins. Both columns
for this (`failed_attempts`, `locked_until`) were already added to the table
back in OMNI-105 for exactly this purpose.

### What was built

**Sliding token expiry**, in `services/query/app/deps.py`. A JWT's `exp`
claim is still a fixed timestamp (JWTs can't be mutated after issuance), so
"driven by inactivity" is implemented by renewing the token on every
successful authenticated request:

```python
RENEWED_TOKEN_HEADER = "X-Access-Token"


def get_current_user(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    ...
    response.headers[RENEWED_TOKEN_HEADER] = create_access_token(user.id, user.role.value)
    return user
```

Every protected route already depends on `get_current_user` (OMNI-107), so
every authenticated request transparently returns a fresh token with a new
15-minute window in the `X-Access-Token` header. Keep making requests and the
session never expires; stop, and the last-issued token's `exp` eventually
passes — the same expiry check from OMNI-106 then rejects it.

**Lockout logic**, in `services/query/app/auth.py`'s `login`:

```python
if user is not None and user.locked_until is not None and user.locked_until > now:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS_MESSAGE)

if user is None or not verify_password(payload.password, user.password_hash):
    if user is not None:
        user.failed_attempts += 1
        if user.failed_attempts >= settings.max_failed_attempts:
            user.locked_until = now + timedelta(minutes=settings.account_lockout_minutes)
        db.commit()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS_MESSAGE)

user.failed_attempts = 0
user.last_login_at = now
db.commit()
```

The lock check runs **before** password verification — a locked account is
refused even with the correct password, and the failure message is the same
`INVALID_CREDENTIALS_MESSAGE` used everywhere else in login, so a locked
account isn't distinguishable from a wrong password from outside.

Settings gained `max_failed_attempts` (default `5`) and
`account_lockout_minutes` (default `15`) — the lockout *duration* is
config-driven per the ticket, while the count of 5 itself (an NFR-9 constant)
was also placed in settings for consistency, though the ticket only required
the duration to avoid literals.

### Verification performed

Used a temporary `operator`-role test account, deleted afterward.

1. **Lockout**: 5 requests with a wrong password, then a 6th with the
   *correct* password:
   ```
   attempts 1-5 (wrong password): 401 {"detail":"invalid email or password"}
   attempt 6 (correct password):  401 {"detail":"invalid email or password"}
   ```
   DB check: `failed_attempts = 5`, `locked_until` ≈ 15 minutes ahead of
   `now()`.
2. **Reset on success** — manually cleared `locked_until`, logged in with the
   correct password → `200`, and `failed_attempts` back to `0`.
3. **Sliding renewal** — logged in, then called `/auth/me` twice a few
   seconds apart; each response's `X-Access-Token` header carried a JWT whose
   `exp` was later than the previous one by roughly the elapsed time.
4. **Idle/expired token rejected** — crafted a token (signed with the real
   secret) whose `exp` was 5 minutes in the past, simulating inactivity past
   the 15-minute window → `401 {"detail":"invalid or expired token"}`.

### Result

- Five wrong passwords lock the account; the sixth attempt is refused even
  with the right password.
- The lock duration and failure threshold both come from settings.
- Active use slides a token's effective expiry forward; idle tokens still
  expire on schedule.
- All checklist items and the acceptance criterion for OMNI-108 are
  satisfied.

---

## OMNI-109 · Sign-in page, API client, protected routes

### Why this ticket exists

FR-10 has to be visible, not just true in the database — everything through
OMNI-108 was API-only, reachable with `curl` but not from a browser.

### What was built

**Backend CORS** (needed for the browser to call the API cross-origin at
all): `services/query/app/main.py` gained `CORSMiddleware`, restricted to
`settings.frontend_origin` (default `http://localhost:3000`, not hardcoded),
with `expose_headers=[RENEWED_TOKEN_HEADER]` so the browser's JS is actually
allowed to read the `X-Access-Token` header from OMNI-108 — browsers hide
custom response headers cross-origin unless explicitly exposed.

**`frontend/src/lib/api-client.ts`** — the one file every request goes
through:

```typescript
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

  const renewedToken = response.headers.get("X-Access-Token");
  if (renewedToken) setToken(renewedToken);

  const data = await response.json().catch(() => null);

  if (response.status === 401) {
    if (token) {
      clearToken();
      if (typeof window !== "undefined") window.location.href = "/sign-in";
    }
    throw new ApiError(401, data?.detail ?? "unauthorized");
  }

  if (!response.ok) throw new ApiError(response.status, data?.detail ?? "request failed");
  return data as T;
}
```

Two design points worth calling out:
- It also reads `X-Access-Token` on *every* response and re-persists it,
  which is what actually makes OMNI-108's sliding-expiry renewal work from
  the browser's side — without this, the backend could renew all it wants
  but the browser would keep sending the stale, eventually-expiring token.
- The redirect-on-401 only fires if a token was already attached to the
  request. A `/auth/login` call with bad credentials also returns 401, but
  there's no token on that request — so it's left for the caller (the
  sign-in form) to show inline, instead of being treated as "the session
  died" and bounced.

Token persistence is `localStorage` (survives a refresh, per the acceptance
criterion). `login`, `logout`, and `getCurrentUser` are thin wrappers around
`request` — no other file in the frontend calls `fetch` directly.

**`frontend/src/app/sign-in/page.tsx`** — email/password form; on failure
shows whatever message `ApiError` carries, which is already the backend's
byte-identical "invalid email or password" from OMNI-106, so the frontend
doesn't need its own logic to avoid revealing whether an address exists.

**Protected route wrapper** — `frontend/src/app/(app)/layout.tsx`, a client
component wrapping a route group (`(app)`, so it doesn't add a URL segment):
checks `getToken()` on mount and redirects to `/sign-in` immediately if
there's none. The former default Next.js home page
(`frontend/src/app/page.tsx`) was deleted and replaced by
`frontend/src/app/(app)/page.tsx` — the real `/` route, now behind the guard.

This split deliberately does only a *presence* check, not a round-trip to
`/auth/me`: an expired or tampered token that's still sitting in
`localStorage` gets past this guard, but the very first API call it makes
(e.g. `getCurrentUser()` on that page) hits the 401 handling in
`api-client.ts` and bounces to `/sign-in` anyway. The two checklist items
("API client redirects on 401" and "protected route wrapper") cover two
different cases by design: no token at all (instant, client-side) vs. an
invalid token (caught reactively on first use).

**Design pass** (after initial build): centered sign-in card on a muted
background with a small indigo logo mark, proper input focus rings, an error
message rendered as a red pill instead of plain text, and a spinner on the
submit button while signing in. The post-login page got a real top bar
(logo + "Sign out") and a card showing the signed-in user with a
role-colored badge (indigo/amber/emerald for admin/analyst/operator). Both
pages support light/dark via Tailwind's `dark:` variants. Deliberately left
minimal beyond that — the full sidebar/topbar/dashboard shell is OMNI-110.

### Verification performed

1. **Backend CORS** — cross-origin `POST /auth/login` with
   `Origin: http://localhost:3000` returned
   `access-control-allow-origin: http://localhost:3000` and
   `access-control-expose-headers: X-Access-Token`.
2. **`npm run build`** — compiled cleanly both before and after the design
   pass, with `/`, `/sign-in`, and `/_not-found` all present.
3. **Manual browser walkthrough**, done by the user directly: signing in
   with the seeded admin reached the app; refreshing the page kept the
   session; opening `http://localhost:3000` in a private window bounced to
   `/sign-in` (no token there); a wrong password showed the one generic
   error message.

### Result

- The app is reachable end-to-end from a browser: sign in, land inside,
  survive a refresh, get bounced when unauthenticated.
- Exactly one file (`api-client.ts`) owns tokens, headers, and 401 handling.
- All checklist items and the acceptance criterion for OMNI-109 are
  satisfied.

---

## OMNI-110 · App shell, role-aware sidebar, empty dashboard

### Why this ticket exists

FR-9's frame. Building the shell now means every later slice fills a tile or
route that's already on screen instead of bolting one on.

### First pass, then a correction

The ticket as originally written didn't list the actual ten product routes —
that list lives in a separate product document this repo doesn't contain. The
first pass shipped with a placeholder route/role map invented from the
README's service descriptions. The user then edited `week-01.md` directly to
paste in the real route table from that document, plus a requirement that
hadn't been in the ticket before:

> Put this map in `services/common`, beside the Role enum — not hardcoded in
> the frontend. The API needs the same map in slice 16 to enforce it
> server-side, and two copies will drift.

Everything below describes the corrected, final implementation — the
placeholder version was fully replaced, not left alongside it.

### The real route map

Nine in-app routes (Sign In is the tenth screen, but sits outside the shell):

| Route | Label | operator | analyst | admin |
|---|---|:--:|:--:|:--:|
| `/` | Operations Dashboard | ● | ● | ● |
| `/live` | Live Monitoring | ● | | ● |
| `/search` | Search | ● | ● | ● |
| `/alerts` | Alerts | ● | ● | ● |
| `/reports` | Incident Reports | | ● | ● |
| `/videos` | Video Archive | ● | ● | ● |
| `/cameras` | Cameras | ● | | ● |
| `/integrations` | Integrations | | | ● |
| `/admin` | Administration | | | ● |

Admin sees all nine, operator six, analyst five.

### What was built

**`services/common/omnisight_common/nav.py`** — the single source of truth:

```python
@dataclass(frozen=True)
class NavRoute:
    path: str
    label: str
    roles: tuple[Role, ...]


NAV_ROUTES: tuple[NavRoute, ...] = (
    NavRoute("/", "Operations Dashboard", (Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
    NavRoute("/live", "Live Monitoring", (Role.OPERATOR, Role.ADMIN)),
    ...
)
```

Exported from `omnisight_common/__init__.py` alongside `Role`.

**`services/query/app/nav.py`** — `GET /nav`, filtered server-side by the
caller's role (via the existing `get_current_user` dependency):

```python
@router.get("")
def get_nav(current_user: User = Depends(get_current_user)) -> list[dict[str, str]]:
    return [
        {"path": route.path, "label": route.label}
        for route in NAV_ROUTES
        if current_user.role in route.roles
    ]
```

This is what makes "not hardcoded in the frontend" concrete: the frontend
never sees the role/route mapping at all, only the already-filtered list for
whoever is asking. `frontend/src/lib/nav.ts` shrank to just the `Role` type
alias; `frontend/src/components/sidebar.tsx` fetches `/nav` on mount instead
of filtering a local array. The only thing still decided client-side is which
returned routes are clickable — `/` is the only page that exists yet, so
everything else renders with a "soon" badge. That's presentation, not a
role/security decision, so it stayed local to the sidebar rather than going
into the shared map.

**App shell**, otherwise as originally built:
- `frontend/src/lib/auth-context.tsx` — `AuthProvider`/`useAuth`, fetches the
  current user once and does the route guard (redirects to `/sign-in` if
  there's no token).
- `frontend/src/components/top-bar.tsx` — logo, notification bell, account
  menu (email, role, sign out).
- `frontend/src/components/app-shell.tsx` — composes `TopBar` + `Sidebar` +
  page content.
- `frontend/src/app/(app)/page.tsx` — the Operations Dashboard, five empty
  tiles (alerts needing attention, camera health, activity, recent reports,
  storage), each labelled with what will fill it (e.g. "Filled in when
  alerting ships").

### Verification performed

Created temporary operator and analyst test accounts (deleted afterward),
logged in as each via the real API, and called `/nav` directly:

- **admin** → all 9 routes.
- **operator** → 6: `/`, `/live`, `/search`, `/alerts`, `/videos`, `/cameras`
  — matches "operator six" exactly.
- **analyst** → 5: `/`, `/search`, `/alerts`, `/reports`, `/videos` — matches
  "analyst five" exactly.

`npm run build` compiled cleanly after the refactor. Browser extension
automation wasn't available this session, so the final click-through (sign in
as admin, see all 9; sign in as the temp operator, see 6, different set) was
done by the user directly against the running dev servers, confirmed working.

### Result

- The route/role map exists in exactly one place, in Python, ready for
  slice 16 to reuse for server-side enforcement without a second copy to
  drift.
- The sidebar renders whatever `/nav` returns — admin, operator, and analyst
  see verifiably different sets, matching the real product document.
- All checklist items and the acceptance criterion for OMNI-110 are
  satisfied.

---

## OMNI-111 · Nginx and TLS in front

### Why this ticket exists

NFR-8 — 100% of traffic encrypted with TLS 1.2+, plaintext bytes = 0. Up to
now the frontend (`:3000`) and backend (`:8000`) were both plain HTTP dev
servers, reachable directly.

### What was built

**`scripts/generate-dev-cert.sh`** — self-signed cert via `openssl`, CN
`localhost` with SANs for both `localhost` and `127.0.0.1`, 365 days, output
to `infra/nginx/certs/` (gitignored — added `infra/nginx/certs/` to the root
`.gitignore` before ever running the script, so the key was never at risk of
being committed).

**`infra/nginx/default.conf`**:

```nginx
server {
    listen 80;
    server_name localhost;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name localhost;

    ssl_certificate     /etc/nginx/certs/dev.crt;
    ssl_certificate_key /etc/nginx/certs/dev.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location ~ ^/(auth|admin|nav|health|docs|openapi\.json|redoc)(/|$) {
        proxy_pass http://host.docker.internal:8000;
        ...
    }

    location / {
        proxy_pass http://host.docker.internal:3000;
        ...
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

`host.docker.internal` (Docker Desktop's special DNS name for the host
machine) is what lets the containerized nginx reach the frontend/backend dev
servers still running directly on Windows, without containerizing them —
that's a bigger, separate piece of work (real Dockerfiles, the uv workspace
inside a container) that this ticket doesn't ask for. The path-based dispatch
(known API prefixes → backend, everything else → frontend) is a second,
intentional copy of routing knowledge alongside the Next.js rewrite added
below — acceptable here because it's infra routing, not the kind of
business-rule map (like OMNI-110's nav/role table) that actually drifts.

**`docker-compose.yml`** gained an `nginx` service: image `nginx:alpine`,
ports `80:80` and `443:443`, the config and cert directory mounted read-only.

### The bigger fix: making the frontend's own traffic encrypted too

Standing up nginx alone would satisfy the literal checklist, but not NFR-8's
actual point: if the frontend's page loads over HTTPS while its own JS still
calls `http://localhost:8000` directly for login, that's still plaintext
bytes on the wire — the exact thing this ticket exists to eliminate.

Fixed by making all API calls same-origin instead of absolute:

- `frontend/src/lib/api-client.ts` — `API_URL` now defaults to `""`
  (relative) instead of `http://localhost:8000`. A relative fetch always
  rides whatever connection the browser already has to the current page's
  origin — encrypted, if that origin is `https://`.
- `frontend/next.config.ts` — added `rewrites()` proxying `/auth`, `/admin`,
  `/nav`, `/health`, `/docs`, `/openapi.json`, `/redoc` to the backend. This
  is what makes relative paths resolve correctly even in the plain
  `npm run dev` workflow (bypassing nginx entirely) — Next's own dev server
  now does the same proxying nginx does, so the frontend code doesn't need
  to know or care which one is in front of it.
- `frontend/.env.local` / `.env.example` — `NEXT_PUBLIC_API_URL` changed from
  an absolute URL to empty (same-origin is now the default).

The CORS middleware from OMNI-109 was left in place (harmless, and still
useful for anything that calls the API directly rather than through a
same-origin proxy) rather than removed — not asked for, and removing working
config isn't free.

### Three real problems hit along the way

1. **Port 80/443 already partly taken.** Same class of issue as OMNI-105's
   Postgres port conflict: `netstat` showed `wslrelay.exe` (WSL2) already
   listening on `[::1]:80` and `[::1]:443` — specifically the IPv6 loopback
   address — with a lot of active traffic on it, clearly something load-
   bearing, not safe to kill. Since Windows resolves `localhost` to `::1`
   first, browser requests to `https://localhost` were being routed to
   `wslrelay`, not to Docker's nginx (bound on the IPv4 wildcard and a
   *wildcard* IPv6 address, which loses to `wslrelay`'s more specific `::1`
   binding). Fixed by using `https://127.0.0.1` instead of `https://localhost`
   — the cert's SAN already covers `127.0.0.1`, so no cert mismatch either.

2. **Missing WebSocket proxying.** The frontend loaded once (HTML/CSS/JS all
   200'd through nginx), but the browser showed a blank page. Root cause:
   `location /` had no `Upgrade`/`Connection` headers, so Next.js dev mode's
   hot-reload WebSocket couldn't connect through the proxy. Added
   `proxy_http_version 1.1;`, `proxy_set_header Upgrade $http_upgrade;`,
   `proxy_set_header Connection "upgrade";` to that location block.

3. **Next.js dev-mode cross-origin protection.** Even after the WebSocket
   fix, the frontend dev log showed:
   ```
   ⚠ Blocked cross-origin request to Next.js dev resource /_next/hmr from "127.0.0.1".
   Cross-origin access to Next.js dev resources is blocked by default for safety.
   ```
   Next.js (16.x) blocks dev-only resource requests whose `Host` header
   doesn't match the dev server's own expected origin — nginx proxies with
   the original `Host: 127.0.0.1`, which looks foreign to a dev server
   listening on `:3000`. Fixed by adding
   `allowedDevOrigins: ["localhost", "127.0.0.1"]` to `next.config.ts`.

A fourth issue turned up during manual testing but wasn't specific to nginx:
a hydration console warning turned out to be the Grammarly browser
extension injecting `data-gr-ext-installed`/`data-new-gr-c-s-check-loaded`
onto `<body>` before React hydrated — a well-known, harmless false positive
whenever a DOM-modifying extension is active. Silenced with
`suppressHydrationWarning` on `<body>` in `frontend/src/app/layout.tsx`,
React's documented fix for exactly this case.

### Verification performed

1. **Redirect** — `curl http://127.0.0.1/` → `301` to `https://127.0.0.1/`.
2. **TLS version** — default `openssl s_client` connection negotiated
   `TLSv1.3`; forcing a TLS 1.1 ClientHello (`-tls1_1 -cipher DEFAULT@SECLEVEL=0`,
   needed since modern OpenSSL clients refuse to even offer TLS 1.1 otherwise)
   got back a `tlsv1 alert protocol version` — nginx actively rejects
   anything below TLS 1.2.
3. **Both proxy targets work** — `POST https://127.0.0.1/auth/login`
   returned a real token (backend reachable); `GET https://127.0.0.1/sign-in`
   returned `200` (frontend reachable) — both over the same HTTPS origin.
4. **Manual browser walkthrough**, done by the user: certificate warning
   appeared on first visit (expected/self-signed, per acceptance), clicking
   through landed on a working sign-in page, address bar persistently shows
   "Not Secure" (expected — browsers never mark a self-signed cert as
   secure, regardless of the connection actually being encrypted).

### Result

- The app is reachable over HTTPS with a browser-flagged self-signed cert,
  exactly as the acceptance criterion describes.
- Plain HTTP redirects to HTTPS.
- TLS 1.1 and below are actively rejected; 1.2/1.3 negotiate fine.
- The frontend's own API traffic is same-origin, so going through nginx
  means the *entire* session — page and API calls alike — is encrypted, not
  just the initial page load.
- All checklist items and the acceptance criterion for OMNI-111 are
  satisfied.

---

## OMNI-112 · Run TC-10 and record it

### Why this ticket exists

TC-10 — protect every endpoint with authentication and role-based
authorization. Everything since OMNI-106 was verified manually with `curl`;
this ticket turns that into an automated, repeatable suite and a dated
record.

### A placement decision: not the root `tests/`

The ticket says "test file under `tests/`", but `tests/README.md` (written
before this sprint) says: *"Tests for a single service live beside that
service; what lives here is the cross-service test plan."* TC-10 here only
exercises `services/query`'s own endpoints — nothing cross-service — so the
suite went in `services/query/tests/`, following the repo's own documented
convention over the ticket's shorthand wording.

### What was built

**`services/query/tests/conftest.py`** — one line, adds `services/query` to
`sys.path` so test files can `import app.*` (the same problem `alembic/env.py`
and `scripts/seed_admin.py` solved the same way earlier this sprint —
`package = false` in `services/query`'s `pyproject.toml` means it's never
installed as an importable distribution, so every entry point that needs
`app.*` has to do this once).

**`services/query/tests/test_tc10_auth.py`** — 15 tests, using FastAPI's
`TestClient` against the real app (and the real database — Postgres has to
be up):

- **Endpoints covered:** `GET /auth/me`, `GET /nav`, `POST /auth/logout`,
  `GET /admin/ping`. `/auth/login` is deliberately excluded — it's the public
  entry point, not a protected route. `/health` is excluded too — it's
  deliberately public.
- **Condition 1 (valid token, correct role → 200)** — tested for all four.
- **Condition 2 (valid token, insufficient role → 403)** — only tested
  against `/admin/ping`, because it's the only route gated to a specific
  role rather than "any authenticated user." The other three accept any
  authenticated role by design, so there's no "insufficient" role to test
  against them — this mirrors exactly why OMNI-107 added `/admin/ping` in
  the first place: to make the 403 path real and testable somewhere.
- **Condition 3 (no / expired / tampered → 401)** — three separate cases per
  endpoint: no `Authorization` header at all; a token with `exp` in the past
  (signed with the real `jwt_secret_key`, so only the expiry — not the
  signature — is what's being tested); and a valid token with its last
  character flipped (tests signature verification specifically).

A `pytest` fixture creates two throwaway accounts
(`tc10-admin@omnisight.local`, `tc10-operator@omnisight.local`) before the
module's tests run and deletes them afterward — the same
create-test-user-then-clean-up pattern used manually throughout OMNI-107 and
OMNI-108, just automated now.

**`docs/results.md`** — the TC-10 entry: date, suite location, pass count,
and a table of endpoint × condition results with "n/a" cells explained (no
role restriction beyond authentication → no 403 case to test).

### Verification performed

1. `uv run pytest services/query/tests/` and the bare `uv run pytest` from
   repo root both discover and run the suite — **15 passed, 0 failed**.
2. Queried `users` for `email LIKE 'tc10-%'` after the run — **0 rows**,
   confirming the fixture's teardown actually ran and left no test data
   behind.

### Result

- Every protected endpoint in `services/query` is covered by an automated
  test for all three TC-10 conditions (where applicable).
- `uv run pytest` passes.
- `docs/results.md` has a TC-10 entry dated 2026-09-05.
- All checklist items and the acceptance criterion for OMNI-112 are
  satisfied.

---

## OMNI-113 · Verify NFR-9 and record it

### Why this ticket exists

NFR-9 — tokens expire after 15 minutes of inactivity, accounts lock after 5
consecutive failed logins. OMNI-108 built this; this ticket is the automated
proof, following the same pattern OMNI-112 just established for TC-10.

### What was built

**`services/query/tests/test_nfr9_lockout_expiry.py`** — two tests, reusing
the same `conftest.py` path setup as the TC-10 suite:

- **`test_five_failed_logins_lock_the_account`** — a throwaway account
  (`nfr9-lockout-test@omnisight.local`) attempts login with a wrong password
  five times in a row, then asserts directly against the database that
  `failed_attempts == 5` and `locked_until` is set in the future. A sixth
  attempt with the **correct** password is still asserted as `401` —
  confirming the lock is checked before password verification, not after
  (the same ordering OMNI-108 built specifically so a locked account can't
  be argued past with the right password).
- **`test_token_past_its_inactivity_window_is_rejected`** — crafts a JWT
  signed with the real `jwt_secret_key` but with `exp` one minute in the
  past, and asserts a protected route rejects it with `401`. This is
  mechanically the same expiry check TC-10's suite already exercises, but
  recorded here specifically under NFR-9's own acceptance criterion, framed
  as "a token past its inactivity window" rather than just "an expired
  token" — same code path, different angle of intent.

A `pytest` fixture creates the throwaway account before the test runs and
deletes it after, mirroring the pattern from OMNI-112's TC-10 suite exactly.

**`docs/results.md`** — an NFR-9 section added below the TC-10 entry: date,
suite location, pass count, and the reasoning behind each test (why the lock
check has to run before password verification; why the crafted-expiry
technique tests the check itself rather than just waiting out a real
15-minute window).

### Verification performed

1. `uv run pytest services/query/tests/test_nfr9_lockout_expiry.py` —
   **2 passed, 0 failed**.
2. Full suite together (`uv run pytest` from repo root, TC-10 + NFR-9) —
   **17 passed, 0 failed**.
3. Queried `users` for `email LIKE 'nfr9-%'` after the run — **0 rows**,
   confirming the fixture's teardown ran cleanly.

### A gap this ticket's own checklist surfaced

The sprint's "Definition of done" section (below OMNI-113 in `week-01.md`)
includes *"All of the above is true on a fresh `docker compose up -d`."*
Checking that honestly meant noticing it wasn't true yet: `docker-compose.yml`
only managed Postgres and nginx at this point — `frontend` and
`services/query` were still run manually via `npm run dev` and
`uv run uvicorn`, with empty placeholder `Dockerfile`s. That gap, and the
follow-up work to close it (containerizing both), is recorded separately —
see the note below this ticket's own section, since it wasn't part of any
numbered ticket.

### Result

- Both NFR-9 behaviors are covered by automated tests.
- `uv run pytest` passes (2 new tests; 17 total with TC-10).
- `docs/results.md` has an NFR-9 entry dated 2026-09-05.
- All checklist items and the acceptance criterion for OMNI-113 are
  satisfied.

---

## Post-sprint: containerizing `frontend` and `services/query`

Not a numbered ticket — raised by the user after OMNI-113 surfaced that the
Definition of Done's "fresh `docker compose up -d`" claim wasn't actually
true yet (see above). Since this was requested directly rather than derived
from a ticket, and touches the run model for the whole stack, it's recorded
here rather than folded into OMNI-113's own section.

**What was built:**
- `services/query/Dockerfile` — Python 3.13-slim + `uv`. Copies the *whole*
  workspace (`pyproject.toml`, `uv.lock`, all of `services/`) rather than
  just `services/query` and `services/common`, because `uv sync` validates
  workspace membership against the filesystem, not just the lockfile — a
  missing member directory (even an unused one like `services/ai_workers`)
  would break the sync. Runs `uv sync --frozen --package omnisight-query`,
  then `uvicorn --reload`.
- `frontend/Dockerfile` — Node 22 Alpine, `npm install`, `npm run dev`.
- `docker-compose.yml` — added `query` (port 8000) and `frontend` (port
  3000) services. Both bind-mount their source from the host, so edits still
  hot-reload live instead of requiring a rebuild; `frontend_node_modules` is
  a **named** volume layered over the bind mount, so the container's
  Linux-native `node_modules` isn't clobbered by the host's Windows one.
  `query` gets `POSTGRES_HOST=postgres` (container network name, overriding
  `.env`'s implicit `localhost` default) plus everything else from `.env`
  via `env_file`. `frontend` gets `API_PROXY_ORIGIN=http://query:8000` so its
  own `next.config.ts` rewrite (from OMNI-111) targets the query container
  by name instead of `localhost:8000`.
- `infra/nginx/default.conf` — `proxy_pass` targets changed from
  `host.docker.internal:8000`/`:3000` to `query:8000`/`frontend:3000`, since
  the upstreams are now containers on the same Docker network rather than
  processes on the host.

**Deliberately left alone:** migrations and seeding. `scripts/seed_admin.py`
and `alembic upgrade head` still run from the host via `uv run`, against
Postgres's exposed port `5432` — exactly as before. Containerizing the
*serving* process doesn't require containerizing one-off admin commands too,
and automating those into container startup wasn't asked for.

**Verification performed:** stopped every host-run dev server first (so
their ports were free), then ran the exact sequence the Definition of Done
describes — `docker compose down` followed by a plain `docker compose up -d`
(no `--build`, no manual steps). All four containers came up in dependency
order (postgres → query → frontend → nginx). Confirmed:
- `http://127.0.0.1` → `301` → `https://127.0.0.1`
- `POST https://127.0.0.1/auth/login` (through nginx → query container →
  postgres container) → real JWT, `200`
- `POST http://localhost:3000/auth/login` (frontend container's own
  Next.js rewrite to `query:8000`, bypassing nginx entirely) → `200`
- Full `uv run pytest` suite (17 tests) still passes, unaffected — it talks
  to Postgres directly via the exposed port, not through either container

**Result:** the Definition of Done's "All of the above is true on a fresh
`docker compose up -d`" item is now genuinely true, and was ticked in
`week-01.md` on that basis. Day-to-day workflow simplified to
`docker compose up -d` / `docker compose down` — no more separately running
`npm run dev` and `uv run uvicorn` by hand.
