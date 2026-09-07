# Context notes — Sprint 2

## OMNI-200 · Ingestion service skeleton

### Why this ticket exists

Week 1 was one service. This is the second, and everything that touches video
from now on lives here — `query` owns the API and the database, `ingestion`
owns opening streams and files. Getting the skeleton and the network boundary
right this ticket is what OMNI-201/204/206 build on without re-deciding it.

### What was built

Branch: `slice-02-cameras-uploads`.

**Dependencies**, added to the `omnisight-ingestion` workspace member:

```bash
uv add fastapi "uvicorn[standard]" opencv-python-headless pydantic-settings \
       --package omnisight-ingestion
```

`opencv-python-headless`, not `opencv-python` — no display in the container,
and the headless build is far smaller. `omnisight-ingestion` already depended
on `omnisight-common` from the repo skeleton, so that link needed no new
wiring.

**`services/ingestion/app/main.py`**, **`settings.py`**, **`logging_conf.py`**
— a direct copy of `services/query`'s shape from OMNI-103/104, nothing
ingestion-specific yet:

```python
from omnisight_common import CommonSettings


class Settings(CommonSettings):
    app_name: str = "omnisight-ingestion"


settings = Settings()
```

`main.py` keeps the same JSON request-logging middleware, the same
`Exception` handler returning clean JSON instead of a traceback, and:

```python
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

No CORS middleware here, unlike query's — nothing in a browser ever calls
this service directly, so there's no cross-origin request to allow.

**`services/ingestion/Dockerfile`** — same shape as query's Dockerfile
(Python 3.13-slim, `uv sync --frozen --package omnisight-ingestion`, whole
workspace copied in so `uv sync` can resolve the `omnisight-common`
dependency), `uvicorn --reload` on `0.0.0.0:8000`.

**`docker-compose.yml`** — a new `ingestion` service, deliberately with
**no `ports:` entry**:

```yaml
ingestion:
  build:
    context: .
    dockerfile: services/ingestion/Dockerfile
  restart: unless-stopped
  env_file:
    - .env
  volumes:
    - ./services/common:/workspace/services/common
    - ./services/ingestion:/workspace/services/ingestion
```

`query` gets one new line, the base URL it will call ingestion at:

```yaml
environment:
  POSTGRES_HOST: postgres
  INGESTION_BASE_URL: http://ingestion:8000
depends_on:
  postgres:
    condition: service_healthy
  ingestion:
    condition: service_started
```

**`services/query/app/settings.py`** gained the matching field:

```python
ingestion_base_url: str = "http://localhost:8001"
```

Nothing calls it yet — OMNI-204 is the first real caller — but the ticket's
own line, *"the base URL comes from settings, never a literal,"* only means
something if the setting exists before the first caller does. The
`localhost:8001` default is for running query outside Docker; inside compose
it's always overridden to `http://ingestion:8000`.

`infra/nginx/default.conf` was left untouched — no route was added for
ingestion, which is what keeps it unreachable from a browser.

### A local-venv detour

Ran a bare `uv sync` after adding the ingestion dependencies to sanity-check
the lockfile, not realizing the workspace root has `package = false` and no
declared dependencies of its own — plain `uv sync` at the root installs
*only* the root's dev dependency group, and uninstalled every package
belonging to `query` and `ingestion` (`fastapi`, `sqlalchemy`, `pytest`,
`ruff`, everything) from the local `.venv`. Recovered with:

```bash
uv sync --all-packages
```

which restores every workspace member plus the dev group in one shot. This
only affected the local editor/tooling environment — the Docker images build
their own venvs from scratch via `uv sync --frozen --package <name>` inside
each Dockerfile, so they were never at risk. Worth remembering for next time:
`uv sync` alone is not "sync everything" in this workspace, `--all-packages`
is.

### Verification performed

Docker Desktop wasn't running at the start of this session; started it and
waited for the daemon before any of the below.

1. **Both images build** — `docker compose build ingestion query` completed
   for both, `opencv-python-headless` and its `numpy` dependency included.
2. **Both services run** — `docker compose up -d`; `docker compose ps` shows
   `ingestion` and `query` both `Up`.
3. **Query reaches ingestion, through settings, not a literal** — from
   inside the `query` container:
   ```python
   from app.settings import settings
   urllib.request.urlopen(settings.ingestion_base_url + "/health")
   # -> {'status': 'ok'}
   ```
   Ingestion's own JSON access log confirmed the same request:
   ```json
   {"level": "INFO", "logger": "app.request", "message": "request", "method": "GET", "path": "/health", "status_code": 200, "duration_ms": 9.94}
   ```
4. **Ingestion is not reachable from outside** — `docker compose port
   ingestion 8000` → `invalid IP:0` (no host port bound at all); confirmed
   `infra/nginx/default.conf` has no `ingestion` route.
5. **Nothing else broke** — `uv run ruff check services/ingestion
   services/query` reported zero issues in the new ingestion files (the 30
   findings it did report are all pre-existing in query's older files,
   untouched by this ticket); `uv run pytest` — **17 passed**, same as the
   end of Sprint 1.

### Result

- `services/ingestion` runs as its own container, health-checkable at
  `/health`, with the same settings/logging/error shape as `services/query`.
- It sits on the internal Docker network only — no published port, no nginx
  route — and query reaches it by name (`http://ingestion:8000`) through a
  settings field, never a hardcoded string.
- All checklist items and the acceptance criterion for OMNI-200 are
  satisfied.

---

## OMNI-201 · RTSP simulator with ten looping feeds

### Why this ticket exists

NFR-4 in slice 5 needs ten concurrent camera feeds, and there are no ten real
cameras to point at. Building the simulator now, in the same slice ingestion
was born in, means slices 3, 4 and 5 all have something real to test against
instead of inventing throwaway fixtures each time.

### What was built

**`infra/mediamtx/clips/`** (gitignored — scaffolding, not project data) —
five 10-second, 640×360 clips generated locally with `ffmpeg`'s synthetic
`lavfi` sources (`testsrc`, `testsrc2`, `smptebars`, `rgbtestsrc`,
`mandelbrot`), so each is visually distinct without needing to source or
license any real footage:

```bash
ffmpeg -f lavfi -i "testsrc=size=640x360:rate=15" -t 10 -pix_fmt yuv420p \
       -c:v libx264 -preset veryfast infra/mediamtx/clips/clip1.mp4
```

**`infra/mediamtx/mediamtx.yml`** — ten explicit paths, `cam01` … `cam10`,
each reusing one of the five clips across two paths. Every path's
`runOnInit` starts an `ffmpeg -stream_loop -1` process that republishes the
clip back into that same path — the standard MediaMTX pattern for looping a
local file over RTSP:

```yaml
paths:
  cam01:
    runOnInit: ffmpeg -re -stream_loop -1 -i /clips/clip1.mp4 -c copy -f rtsp rtsp://localhost:$RTSP_PORT/$MTX_PATH
    runOnInitRestart: yes
  # ... cam02 … cam10, same shape
```

**`docker-compose.yml`** — a `mediamtx` service using
`bluenviron/mediamtx:latest-ffmpeg` (the plain `mediamtx` image has no
ffmpeg binary, and the `runOnInit` hooks above need one), config and clips
mounted read-only. **No `ports:` entry** — same internal-only pattern as
`ingestion` from OMNI-200: nothing outside the Docker network can reach it,
and nothing needs to except `ingestion` itself.

**`docs/rtsp-simulator.md`** — the ten addresses
(`rtsp://mediamtx:8554/cam01` … `cam10`), a short explanation of how the
loop mechanism works, and how to check a feed yourself given that no host
port is published.

**Left undone, on purpose:** the checklist's last item — *"the address a
developer types into the Add Camera form is documented in the empty
state"* — is OMNI-208's own deliverable (the Cameras screen doesn't exist
yet). Listed here as a forward pointer in the ticket, not something OMNI-201
itself builds; left unchecked in `week-02.md` rather than checked
prematurely.

### Verification performed

1. **All ten paths come up** — `docker compose logs mediamtx` shows all of
   `cam01` through `cam10` reporting `stream is available and online, 1
   track (H264)`.
2. **A feed plays** — from inside the `mediamtx` container itself (its own
   RTSP server, no host port needed):
   ```bash
   docker compose exec mediamtx ffprobe -rtsp_transport tcp \
     -show_entries stream=codec_name,width,height,avg_frame_rate \
     rtsp://localhost:8554/cam01
   # codec_name=h264, width=640, height=360, avg_frame_rate=15/1
   ```
   Same result against `cam07` (a path reusing a different clip).
3. **A feed loops** — `ffprobe` against `cam03` with `-read_intervals
   "%+15"` (15 seconds of packets, longer than the clip's own 10-second
   duration) kept returning packets past `t=15s` with no interruption or
   error — proof the stream kept going past where a non-looping file would
   have ended.
4. **Reachable from another container, by Docker service name** — the
   actual pattern OMNI-204 will use. From inside the `ingestion` container:
   ```python
   import cv2
   cap = cv2.VideoCapture("rtsp://mediamtx:8554/cam02")
   ok, frame = cap.read()
   # opened: True, frame read: True, shape: (360, 640, 3)
   ```
5. **Ingestion is still not reachable from outside** and the rest of the
   stack still starts together cleanly — `docker compose up -d` (all six
   services now) came up with `mediamtx` showing no published port in
   `docker compose ps`, same as `ingestion`'s row.
6. **Nothing broke** — `uv run pytest` still **17 passed** (this ticket
   touched no Python).

### Result

- Ten distinct RTSP addresses, each serving a genuinely looping stream,
  reachable from inside the Docker network by service name — proven from a
  second container, not just from `mediamtx` itself.
- The simulator adds no attack surface: no host port, no nginx route.
- The addresses are written down in `docs/rtsp-simulator.md`.
- All checklist items but the OMNI-208 forward-reference (not yet buildable)
  and the acceptance criterion for OMNI-201 are satisfied.

---

## OMNI-202 · Cameras and videos tables, shared enums

### Why this ticket exists

FR-1a and FR-3 need somewhere to put both kinds of footage source — a live
camera and an uploaded file — before any endpoint can read or write either
one. Everything from OMNI-203 onward assumes these two tables already exist.

### What was built

**Four enums in `services/common`**, beside `Role` from week 1 —
`CameraStatus`, `Domain`, `VideoSource`, `VideoStatus` — one file each,
matching `roles.py`'s shape exactly:

```python
class CameraStatus(StrEnum):
    REGISTERED = "registered"
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"
```

Exported from `omnisight_common/__init__.py` alongside `Role`, so both
services import the same four values and neither can invent a fifth.

**`services/query/app/models.py`** gained `Camera` and `Video`, following the
plan's field list exactly. Two decisions the ticket called out by name:

- `group` is a reserved word in SQL. Rather than quote it forever, both the
  column and the model attribute are named `group_name` — sidestepping the
  reserved word instead of working around it on every query.
- `camera_id` on `Video` is nullable with a plain foreign key to `cameras.id`
  and no `ondelete` — uploads have no camera, and the missing cascade means a
  referenced camera can't be hard-deleted by accident, which lines up with
  OMNI-203's "soft delete only when a video references it" before that
  ticket exists to enforce it.

```python
camera_id: Mapped[int | None] = mapped_column(
    ForeignKey("cameras.id"), nullable=True, index=True
)
```

Both enum columns reuse a small helper instead of repeating the
`values_callable` lambda four times:

```python
def _enum_column(enum_cls: type, name: str):
    return Enum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])
```

**One alembic migration**, `62326bb11aff_create_cameras_and_videos_tables.py`,
autogenerated after adding `Camera` and `Video` to `alembic/env.py`'s model
imports — both tables, both indexes, in one revision as the ticket asked for.
Indexes on `videos.camera_id` and `videos.created_at`, the two columns the
archive filters on (OMNI-207).

### Verification performed

1. **Migration autogenerates cleanly** — `alembic revision --autogenerate`
   detected exactly the two new tables and the two new indexes, nothing
   spurious.
2. **Applies cleanly on a fresh database** — `docker compose down -v`, start
   only `postgres`, `alembic upgrade head` from the host: both migrations
   (`users`, then `cameras`/`videos`) ran in order with no errors.
3. **Shape matches the plan** — `psql \d cameras` and `\d videos` inside the
   postgres container: every column, type, nullability and default matches
   the plan's field list; `group_name` present, no `group` column anywhere;
   `videos_camera_id_fkey` present; `ix_videos_camera_id` and
   `ix_videos_created_at` both present.
4. **Full-stack acceptance check, not just the host-side one** — a real
   `docker compose down -v && up -d` (all six services) followed by running
   the migration from *inside* the `query` container itself:
   ```bash
   docker compose exec -w /workspace/services/query query \
     uv run --package omnisight-query alembic upgrade head
   ```
   Same clean result. `psql \dt` afterward shows `alembic_version`, `cameras`,
   `users`, `videos` — all four, all six containers still `Up`.
5. **Nothing broke** — `uv run ruff check` clean on every hand-written file
   touched (`models.py`, `env.py`, the four new enum files, `__init__.py`);
   the autogenerated migration keeps the same `Union`/import style as the
   pre-existing users migration, left as alembic generated it rather than
   hand-edited to a different style. `uv run pytest` — **17 passed**, same as
   before this ticket.

### Result

- `cameras` and `videos` exist with the exact shape the plan specified, built
  from the same four shared enums both services import.
- One migration produces both tables from nothing, verified twice — once
  from the host against a fresh volume, once from inside the actual `query`
  container against a fresh full-stack `up -d`.
- All checklist items and the acceptance criterion for OMNI-202 are
  satisfied.

---

## OMNI-203 · Camera CRUD, admin-only writes

### Why this ticket exists

FR-1a needs a way to register a camera before OMNI-204 can test it or
OMNI-208 can list it. NFR-7 needs every write gated by role — this is the
first resource in the app where that gate actually has teeth, since
`/admin/ping` from OMNI-107 was a placeholder built to make the gate
testable, not a real resource.

### What was built

**`services/query/app/cameras.py`** — a new router, `POST`, `GET`, `PATCH`,
`DELETE` on `/cameras`, mounted in `main.py` next to `auth` and `admin`.

**Role enforcement reuses OMNI-107's existing dependency, unchanged:**

```python
@router.post("", response_model=CameraCreateResponse, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> CameraCreateResponse:
```

`GET /cameras` uses `get_current_user` instead — any authenticated role,
including operator, can view. `POST`, `PATCH` and `DELETE` all use
`require_role(Role.ADMIN)`. No new role-checking code was written; this is
exactly the dependency `/admin/ping` already proved works.

**New cameras always start `registered`** — the create route ignores
whatever `status` a client might try to send (there's no `status` field on
`CameraCreate`, only on `CameraUpdate`) and hardcodes
`CameraStatus.REGISTERED`. `connected` only ever comes from OMNI-204's test.

**Soft delete, reusing the status enum instead of a new column.** The ticket
asks for delete to be soft when a video already references the camera. Rather
than add a `deleted_at` column that OMNI-202 didn't define, `DELETE`
checks for a referencing `Video` row first:

```python
has_recordings = db.query(Video.id).filter_by(camera_id=camera_id).first() is not None
if has_recordings:
    camera.status = CameraStatus.DISABLED
    db.commit()
    return {"id": camera.id, "deleted": False, "status": camera.status}

db.delete(camera)
db.commit()
return {"id": camera_id, "deleted": True}
```

`CameraStatus.DISABLED` already existed for exactly this kind of "off but
still on record" state, so reusing it avoids a schema change this ticket
didn't ask for. The response tells the caller which branch happened
(`deleted: false` vs `true`), which OMNI-208 will need to show the right
message instead of a generic success toast.

**The `group` field crosses the API/DB boundary explicitly.** `CameraCreate`
and `CameraOut` both use `group` (matching the ticket's literal JSON shape),
but the ORM attribute is `group_name` (OMNI-202's reserved-word decision).
The router does the mapping by hand at both edges — `group_name=payload.group`
on create, `group=camera.group_name` building the response on the way out —
rather than teaching Pydantic an alias, since it's two lines and doesn't need
a general mechanism.

**Tests:** `tests/test_camera_crud.py`, following the existing
`SessionLocal`-fixture pattern from `test_tc10_auth.py` — admin and operator
users created per module, cameras and videos cleaned up per test. Covers
both halves of the acceptance criterion directly: admin create/list/patch,
hard delete with no recordings, soft delete when a video references the
camera, and three operator 403s (create, patch, delete) plus an operator 200
on list.

`/cameras` was also added to `test_tc10_auth.py`'s `PROTECTED_GET_ROUTES` —
that file's whole job is "every protected endpoint rejects bad auth," so a
new protected endpoint belongs on its list, not just in the new ticket's own
test file.

### Verification performed

1. **`uv run pytest`** — **30 passed** (17 from before this ticket, 9 new in
   `test_camera_crud.py`, 4 new parametrized cases in `test_tc10_auth.py`
   from adding `/cameras`). All run against the real Postgres container, not
   a mock.
2. **Operator gets 403 on create, patch, delete; 200 on list** — proven by
   `test_operator_create_returns_403`, `test_operator_patch_returns_403`,
   `test_operator_delete_returns_403`, `test_operator_list_returns_200`, all
   passing.
3. **Admin can register and remove a camera** —
   `test_admin_create_camera_starts_registered` confirms the created row's
   `status` is `registered` and its DB column is `group_name`, not `group`;
   `test_admin_hard_deletes_camera_with_no_recordings` confirms the row is
   actually gone from the database afterward, not just hidden.
4. **Soft delete confirmed at the database, not just the response** —
   `test_admin_delete_soft_deletes_camera_referenced_by_a_video` creates a
   `Video` row against the camera first, calls `DELETE`, then re-queries the
   camera directly through `SessionLocal` and asserts it still exists with
   `status == CameraStatus.DISABLED`.
5. **Nothing broke** — `uv run ruff check` clean on every hand-written file
   this ticket touched; the `Depends(...)` in-argument-default findings
   (`B008`) it reports on `cameras.py` are the same pattern already present
   in `auth.py` and `admin.py` — FastAPI's own idiom, not something this
   ticket introduced, left alone for the same reason OMNI-200 left
   pre-existing findings alone.

### Result

- `/cameras` supports create, list, edit and delete, with writes gated to
  admin by the same dependency `/admin/ping` already used.
- New cameras start `registered`; a camera with a recording attached is
  disabled instead of deleted, so no video is ever left pointing at a
  vanished camera.
- The 403 for an operator is proven by four passing tests, not by clicking
  through the (nonexistent) UI.
- All checklist items and the acceptance criterion for OMNI-203 are
  satisfied.
