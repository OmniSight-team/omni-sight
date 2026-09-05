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
