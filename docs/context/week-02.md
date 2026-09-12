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

---

## OMNI-204 · Connection test, end to end

### Why this ticket exists

The plan calls this the single most valuable thing in the slice: a camera
that silently fails costs a day in slice 4, once continuous capture depends
on it. Everything downstream — OMNI-208's Test Connection button, slice 4's
capture loop — assumes this endpoint already tells the truth about whether a
stream is actually there.

### What was built

**`services/ingestion/app/streaming.py`** — `probe_stream(rtsp_url)`, the
actual OpenCV work: open the stream, read one frame, report resolution and
fps, always release the capture. Three problems had to be solved for real,
not glossed over:

**1. The request must never hang**, no matter what the remote end does.
`cv2.VideoCapture` is a blocking C call with no reliable way to interrupt it
from Python mid-call, so the open-and-read step runs in a worker thread and
the caller waits on it with a hard deadline:

```python
future = _executor.submit(_open_and_read, rtsp_url)
try:
    resolution, fps = future.result(timeout=STREAM_OPEN_TIMEOUT_S)
except concurrent.futures.TimeoutError as exc:
    raise ProbeError("timeout", "stream did not open in time") from exc
```

If the deadline fires, the request returns immediately; the worker thread is
left running and releases its own capture whenever the remote end finally
answers or errors. That's a real trade-off (a timed-out probe leaks a thread
until it resolves) accepted deliberately — a connection test is a rare,
human-triggered action, not a hot path, and it's bounded by the executor's
`max_workers=4`.

**2. Three distinguishable reasons, not "something went wrong."** A cheap
TCP preflight (`socket.create_connection` with its own short timeout) runs
*before* touching cv2 at all, so a dead host or a closed port is reported as
`unreachable` in milliseconds instead of waiting out the full stream-open
deadline. Anything that hangs past that — DNS resolves, TCP would connect,
but nothing ever completes the RTSP handshake — becomes `timeout`.

**3. `authentication failed` needed a real signal, and OpenCV's Python API
doesn't expose one.** `cv2.VideoCapture` gives back nothing on failure but
`False` — no status code, no message. The one place a real "401
Unauthorized" actually shows up is ffmpeg's own log lines, written straight
to the process's stderr file descriptor, not to anything Python can catch.
So the open-and-read call temporarily redirects fd 2 to a tempfile and reads
it back afterward:

```python
with _capture_stderr() as captured:
    capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    ...
captured.seek(0)
log_text = captured.read().decode(errors="replace")
```

Redirecting an OS file descriptor is process-wide, not per-thread — two
probes running at once would stomp on each other's capture — so
`_stderr_capture_lock` (a plain `threading.Lock`) serializes just that
narrow window. `classify_open_failure()` then looks for `"401"` /
`"unauthorized"` in the captured text and falls back to `unreachable`
otherwise; it's a pure function, independent of the capture mechanics, so it
can be tested directly with a fabricated log line.

**`services/query/app/ingestion_client.py`** — a small httpx wrapper query
uses to call ingestion's `/probe/stream`, raising `IngestionUnavailableError`
on any transport failure. `httpx` moved from a dev-only test dependency to a
real one (`uv add httpx --package omnisight-query`) — this is the first
ticket where query makes an outbound HTTP call in production code, not just
in a test client.

**`services/query/app/cameras.py`** gained `POST /cameras/{id}/test`, open
to any authenticated role (`get_current_user`, not `require_role(ADMIN)`) —
testing a connection isn't a write to the camera's configuration the way
create/edit/delete are, and an operator wanting to know if a camera is still
up is exactly the "operators may view" case NFR-7 describes:

```python
if result["reachable"]:
    camera.status = CameraStatus.CONNECTED
    camera.last_seen_at = datetime.now(UTC)
else:
    camera.status = CameraStatus.UNREACHABLE
```

`last_seen_at` only moves on an actual successful probe — it means "last
time this camera was confirmed alive," not "last time someone tried."

### Verification performed

1. **All three failure reasons proven live, for real, against the actual
   running `ingestion` container** — a one-off script run with
   `docker compose exec ingestion uv run --package omnisight-ingestion
   python ...` (never committed) called `probe_stream` directly against:
   - the real simulator (`rtsp://mediamtx:8554/cam01`) →
     `{'resolution': '640x360', 'fps': 15.0}`
   - a guaranteed-unresolvable host (`no-such-host.invalid`) →
     `unreachable | [Errno -2] Name or service not known`
   - a genuine blackhole: a raw socket in the same script that accepts a TCP
     connection and then never sends a byte → `timeout | stream did not
     open in time | elapsed=5.00s` — confirming the request returns at
     exactly the configured deadline, not "eventually."
   - `classify_open_failure()` fed a fabricated `"401 Unauthorized"` log
     line → `authentication failed`; a generic connection-refused line →
     `unreachable`. (Genuinely triggering a live 401 would mean adding
     authentication to the shared OMNI-201 simulator, which this ticket
     doesn't ask for and which risks the ten already-proven feeds — the
     classifier itself is what's under test here, and it doesn't care where
     the log text came from.)
2. **The real end-to-end chain, query → ingestion → mediamtx, run live** — a
   second one-off script, run inside the actual `query` container, created a
   real admin user and a real camera, then called the real
   `POST /cameras/{id}/test` route over the real FastAPI app:
   - good address: `{'reachable': True, 'resolution': '640x360', 'fps':
     15.0, 'error': None}`, and the camera's row in the database afterward
     showed `status=connected`, `last_seen_at` populated with a real
     timestamp.
   - bad address: `{'reachable': False, ..., 'error': 'unreachable'}`,
     row's `status` became `unreachable`.
3. **`uv run pytest`** — **37 passed** (30 from before this ticket, 7 new in
   `test_camera_connection_test.py`). These mock `ingestion_client
   .probe_stream` rather than hitting live RTSP infrastructure — they prove
   the route's own status-transition logic (reachable → connected +
   `last_seen_at` set; unreachable → `unreachable` + `last_seen_at`
   untouched; each of the three reason strings passed through verbatim;
   missing camera → 404; ingestion down → 502), which is exactly what a
   fast, deterministic, CI-safe test can responsibly cover. The real network
   behavior each reason depends on was proven live in steps 1 and 2 above,
   not faked here — this file's own docstring says so, so the boundary
   between "real infra verified live" and "logic verified by test" stays
   visible to whoever reads it next.
4. **Nothing broke** — `uv run ruff check` clean on every hand-written file
   this ticket touched, aside from the same pre-existing `B008`
   (`Depends(...)` in argument defaults) pattern already present everywhere
   else in `services/query/app`.

### Result

- `ingestion`'s `/probe/stream` opens a stream, reads one frame, and always
  releases the capture — proven against a real feed, a real DNS failure, and
  a real hang past its own deadline, not just against happy-path input.
- The endpoint never hangs: a dead address returns in milliseconds, a
  stream that never responds returns at exactly its configured deadline.
- `query`'s `/cameras/{id}/test` calls ingestion for real, over a real HTTP
  call, and updates the camera's `status` and `last_seen_at` from the actual
  result — verified against the real database, not mocked.
- All checklist items and the acceptance criterion for OMNI-204 are
  satisfied.

---

## OMNI-205 · Video storage volume and upload endpoint

### Why this ticket exists

FR-1a's other half — uploaded files, not just live cameras — and the storage
half of NFR-5: zero video or stored data lost on any failure or crash.
OMNI-206 (probe the upload) and OMNI-209 (the archive screen) both assume
this endpoint already writes real files to a real shared path and creates
one truthful row per file.

### What was built

**A named volume, `video_storage`, mounted at `/data/videos` in both `query`
and `ingestion`** — the exact path the plan's own architecture diagram uses.
`ingestion` doesn't read from it yet (that's OMNI-206), but the mount is
provisioned now, the same "wire the topology before the ticket that uses it"
pattern OMNI-200 used for `ingestion_base_url`.

**`services/query/app/videos.py`**, `POST /videos/upload`. Three things the
ticket called out by name had to be real, not just claimed:

**1. Streaming without blocking the event loop.** The obvious FastAPI
pattern — `async def` with `await file.read(chunk)` — turned out to be
wrong here: writing each chunk to disk is a *blocking* call, and doing
blocking I/O inside `async def` stalls every other request on that worker
while a large upload is in flight (`ruff`'s `ASYNC230` caught this). The fix
is a plain `def` route instead, reading straight from `UploadFile.file` (the
underlying spooled file object) — FastAPI runs a sync route in its
threadpool automatically, so neither the reads nor the writes block the
event loop:

```python
def upload_video(request: Request, file: UploadFile = File(...), ...):
    source = file.file
    with open(staging_path, "wb") as out:
        out.write(header)
        while chunk := source.read(CHUNK_SIZE):
            ...
            out.write(chunk)
```

**2. "Not a video" has to mean the bytes, not the filename.** The
acceptance criterion is explicit: a `.txt` renamed to `.mp4` must still be
rejected. Trusting the client's extension can't catch that, so
`_detect_video_extension()` sniffs the first 64 bytes for real container
magic (`ftyp` for mp4/mov, the EBML header for webm/mkv, `RIFF...AVI ` for
avi) and the *detected* format — never the client's claimed one — decides
the stored extension too.

**3. The stored filename is fully generated — `uuid4().hex` plus the
*detected* extension — closing the path-traversal hole the ticket calls
"the one genuine security bug available in this slice."** A filename like
`../../../../etc/passwd.mp4` never touches the filesystem; only
`f"{uuid.uuid4().hex}{extension}"` does, and the client's original name is
kept solely in the `filename` column for display.

**Crash-safety, for NFR-5.** The file is written under a `.part` name first
and only `Path.replace()`d into its final name once the write completes
successfully; a database row is only created *after* that rename succeeds.
A crash mid-upload leaves at worst an orphaned `.part` file — never a row
pointing at a partial or missing one. Any exception during the write (an
over-size abort included) deletes the `.part` file before re-raising, so a
rejected upload leaves nothing behind either.

**Two distinct rejections, both with the reason named**, matching the
ticket's "a message saying which of the two it was": `400` +
`"file is not a recognized video format"` for content that doesn't match a
known container, `413` + `"file exceeds the N MB upload limit"` for size —
checked twice, once cheaply from the `Content-Length` header before any
bytes are read, and again from the running total as chunks arrive (in case
`Content-Length` is absent or understates the truth).

Row fields: `source=upload`, `status=uploaded`, `camera_id=NULL` (the model
already allows this from OMNI-202). `duration_s`, `fps`, `width`, `height`
stay `NULL` — this ticket only stores the file, OMNI-206 is what probes it.

### Verification performed

1. **`uv run pytest`** — **43 passed** (37 from before this ticket, 6 new in
   `test_video_upload.py`). These monkeypatch `settings.video_storage_path`
   to a pytest `tmp_path` rather than the real `/data/videos` — that Linux
   volume only exists inside the containers, not on the Windows host this
   suite runs on directly, and this file is proving the endpoint's own logic
   (sniffing, generated names, atomic rename, size limits, path-traversal
   safety), not the volume wiring. Covers: a valid upload creates an
   `uploaded` row with the real bytes on disk; the stored filename is a
   36-character generated name, never the client's; a `../../etc/passwd.mp4`
   filename cannot leave the storage directory; plain text renamed to
   `.mp4` is rejected by content, not extension; an oversized file is
   rejected with the MB limit named, and leaves no `.part` file behind;
   no token returns 401.
2. **The real volume, live** — from both containers at once:
   `docker compose exec query sh -c "touch /data/videos/probe.txt"`, then
   `docker compose exec ingestion sh -c "ls /data/videos"` — the file showed
   up instantly in the other container. Confirms the same named volume,
   not two separate ones that happen to share a path string.
3. **The 200 MB / no-memory-spike acceptance criterion, live, twice —
   and the second time is the one that actually counts.** The first attempt
   used FastAPI's `TestClient` (the same in-process tool every other test in
   this suite uses) and showed the query container's memory climbing by
   ~350 MB during a 200 MB upload — which looked like a real problem, but
   turned out to be an artifact of `TestClient`'s own ASGI transport
   buffering the whole request body in memory before the app ever sees it,
   not this endpoint's behavior. Re-tested with a genuine end-to-end
   request — `httpx` streaming a real ~191 MB file over a real TCP
   connection to the actually-running `uvicorn` server on the published
   `localhost:8000` — while sampling `docker stats` for the `query`
   container every 0.5s: memory went from a **180.9 MiB** baseline to a
   **190.3 MiB** peak, a ~10 MB rise for a ~191 MB file, and settled back to
   ~180 MiB immediately after. That's what "streamed to disk, not held in
   memory" actually looks like; the first measurement is recorded here too,
   as a reminder that an in-process test client is not a substitute for a
   real socket when the thing under test *is* the streaming behavior.
4. **The `.txt`-renamed-to-`.mp4` acceptance criterion, live** — the same
   real request, with a plain-text body named `notes.mp4`: `400`,
   `{"detail": "file is not a recognized video format"}`.
5. **Nothing broke** — `uv run ruff check` clean on every hand-written file
   this ticket touched, once the `ASYNC230` finding above was fixed at the
   root cause rather than suppressed; remaining findings are the same
   pre-existing `B008` (`Depends`/`File` in argument defaults) pattern used
   everywhere else in `services/query/app`.

### Result

- `POST /videos/upload` streams a multipart file straight to the shared
  `/data/videos` volume in fixed-size chunks, on a route that FastAPI runs
  off the event loop — proven with a real socket and real memory sampling,
  not assumed from reading the code.
- The stored filename is always generated from the file's own detected
  content type, never the client's name or its claimed extension — closing
  the path-traversal hole the ticket flags as this slice's one real security
  bug, with a test that tries exactly that attack.
- A crash mid-write leaves an orphaned `.part` file at worst, never a
  database row pointing at a partial or missing one.
- All checklist items and the acceptance criterion for OMNI-205 are
  satisfied.

---

## OMNI-206 · Probe an uploaded file with OpenCV

### Why this ticket exists

FR-3 needs each stored recording's real details — duration, fps, resolution
— not just the size and filename OMNI-205 already captures. This is also
the first time a video's `status` actually moves past `uploaded`, so it's
what makes OMNI-207's listing and OMNI-209's archive screen show something
meaningful instead of every row stuck the same.

### What was built

**`services/ingestion/app/file_probe.py`**, `probe_file(path)` — opens a
local file (not a network stream, so none of `/probe/stream`'s
timeout/thread machinery from OMNI-204 is needed here), reads one frame,
and computes duration from `frame_count / fps`:

```python
ok, frame = capture.read()
if not ok or frame is None:
    raise FileProbeError("could not read a frame from file")

fps = float(capture.get(cv2.CAP_PROP_FPS))
frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
if fps <= 0 or frame_count <= 0:
    raise FileProbeError("could not determine video duration")

height, width = frame.shape[:2]
duration_s = frame_count / fps
```

Width and height come from the actually-decoded `frame.shape`, not the
container's metadata properties — the same choice `probe_stream` made in
OMNI-204, for the same reason: it reflects what really decoded, not just
what the header claims. `FileProbeError` is caught by the route and turned
into `{"ok": false, "error": ...}`, never a 500 — matching the ticket's "it
does not vanish and it does not 500" line exactly.

**`services/query/app/videos.py`** calls `/probe/file` with the video's own
stored path — the same path both containers already share from OMNI-205's
volume — right after the row is created, inside the same upload request.
The status-transition logic makes one distinction the ticket doesn't spell
out but the acceptance criteria imply: a **file** ingestion genuinely
couldn't decode is a real, permanent problem (`status -> failed`), but
ingestion itself being unreachable is an infrastructure hiccup, not a claim
about the file — so that case leaves the video at `uploaded` instead,
mirroring the same "don't mislabel an infra problem as a content problem"
choice `/cameras/{id}/test` made in OMNI-204:

```python
def _probe_and_finalize(video: Video, db: Session) -> str | None:
    try:
        result = ingestion_probe_file(video.path)
    except IngestionUnavailableError as exc:
        ...
        return "ingestion service unavailable"   # status left untouched

    if result["ok"]:
        video.duration_s = result["duration_s"]
        ...
        video.status = VideoStatus.READY
        return None

    video.status = VideoStatus.FAILED             # a real, permanent failure
    return result.get("error") or "probe failed"
```

The failure reason isn't persisted as a new column — `VideoStatus` has no
slot for free text, and OMNI-202 didn't add one. It's logged (structured
JSON, same as every other service log) and returned in that upload
response's new `error` field, the same shape `CameraTestResponse` already
used in OMNI-204. "The reason recorded" is satisfied the same way it was
there: returned to the caller and logged at the moment it happened, not
retained forever on the row.

**`GET /videos/{id}`** returns the full record — including `width`,
`height`, `size_bytes`, `retention_until`, `created_at` — plus
`segments_count: 0`, hardcoded exactly as the ticket says ("zero this week;
slice 3 fills it"). The raw filesystem `path` is deliberately left out of
the response; nothing external needs a server-side path, and there's no
reason to expose one.

### Verification performed

1. **A known-length file probes to the exact duration, live, against the
   real `ingestion` container** — a 3-second, 10 fps, 320×240 clip generated
   with `ffmpeg` and copied onto the real shared `/data/videos` volume, then
   probed directly:
   ```python
   probe_file("/data/videos/omni206_good.mp4")
   # {'duration_s': 3.0, 'fps': 10.0, 'width': 320, 'height': 240}
   ```
   Exact match, not just "within a second."
2. **A truncated file fails cleanly, live** — the same clip cut to its first
   5 KB (before ffmpeg's `moov` atom, which it writes at the end for a
   non-faststart file) → `FileProbeError: could not open file`, not a crash,
   not a hang.
3. **The full real chain, end to end, through the actual running `query`
   container** — real `curl` uploads (not `TestClient`, for the same reason
   OMNI-205 learned not to trust it for this) against the live stack:
   - the good clip: `{"duration_s":3.0,"fps":10.0,"status":"ready","error":null}`
   - the truncated one: `{"duration_s":null,"fps":null,"status":"failed","error":"could not open file"}`
   - `GET /videos/{id}` for both afterward returned the full stored record,
     `segments_count: 0` on each, and a missing id returned a real `404`.
4. **`uv run pytest`** — **49 passed** (43 from before this ticket, 6 new in
   `test_video_probe.py`). These monkeypatch `ingestion_client.probe_file`
   rather than hitting the real OpenCV path — proving the route's own
   status-transition logic (`ok` → `ready` with the fields filled;
   not-`ok` → `failed` with the reason returned; `IngestionUnavailableError`
   → left at `uploaded`, not `failed`) and `GET /videos/{id}`'s shape,
   which is exactly what a fast, deterministic test should cover; the real
   OpenCV behavior was proven live in steps 1–3. `test_video_upload.py`'s
   own tests (OMNI-205, storage-layer only) now explicitly stub probing to
   "ingestion unavailable" rather than leaving that as an accidental
   side effect of no ingestion server being reachable from a bare host-side
   test run — a silent coincidence isn't a test.
5. **Nothing broke** — `uv run ruff check` clean on every hand-written file
   this ticket touched; the only findings left are the same pre-existing
   `B008` pattern already present everywhere else in `services/query/app`.

### Result

- `ingestion`'s `/probe/file` reports duration, fps, width and height from a
  file it actually decoded — verified against a clip of known length, not
  just against happy-path assumptions.
- A video's `status` now genuinely reflects reality: `ready` when it probed
  cleanly, `failed` (with a reason, logged and returned, never a 500) when
  the file itself is bad, and left at `uploaded` — not incorrectly
  `failed` — when the reason was ingestion being unreachable rather than
  anything wrong with the file.
- `GET /videos/{id}` returns the full record any future screen needs,
  `segments_count` reserved at zero for slice 3.
- All checklist items and the acceptance criterion for OMNI-206 are
  satisfied.

---

## OMNI-207 · Video listing with server-side filters

### Why this ticket exists

OMNI-209's archive screen and slice 6's dataset loaders both need one place
to list every video — uploads and camera recordings alike — with the
filtering and paging done where it scales. By slice 6 this table holds
thousands of dataset rows; a filter written in the browser or in Python
after the fact would work fine on the ten rows in this sprint's demo and
then fall over exactly when it matters.

### What was built

**`GET /videos`**, added to `services/query/app/videos.py` alongside the
existing `POST /upload` and `GET /{id}` from OMNI-205/206. Every filter is a
`.filter()` clause on the SQLAlchemy query *before* `.all()` runs, so the
WHERE clause does the work, not a Python loop over rows already pulled into
memory:

```python
query = db.query(Video)
if source is not None:
    query = query.filter(Video.source == source)
if camera_id is not None:
    query = query.filter(Video.camera_id == camera_id)
if from_ is not None:
    query = query.filter(Video.created_at >= from_)
if to is not None:
    query = query.filter(Video.created_at <= to)

videos = query.order_by(Video.created_at.desc()).offset(offset).limit(limit).all()
```

`camera_id` and `created_at` are exactly the two columns OMNI-202 already
indexed for this — "the archive filters on both" was written into that
ticket's own note before this one existed. `from` is a query parameter but a
Python keyword, so it's aliased (`Query(None, alias="from")`) to the local
name `from_`. Pagination is `limit`/`offset` query parameters (default 50,
capped at 200) rather than a wrapped response envelope — the ticket's own
line shows the endpoint returning a bare array, and `GET /cameras` already
established that shape for a list endpoint in this service.

No `source` filter is needed to make "one list, not two" true — uploads
(`source=upload`, `camera_id=NULL`) and camera recordings
(`source=camera`, `camera_id` set) are just rows in the same table, so a
plain unfiltered `GET /videos` already returns both. `source` and
`camera_id` are there so the archive screen *can* narrow the view, not
because the two kinds of video are stored or served separately.

**`DELETE /videos/{id}`** — the "row and file together, or neither"
requirement runs into a real limit: a database transaction and a filesystem
unlink can't be made truly atomic across the two without much heavier
machinery (a two-phase commit, a tombstone-and-reconcile job) that nothing
in this sprint asks for. The choice made instead: delete and commit the
database row *first*, then remove the file:

```python
db.delete(video)
db.commit()

try:
    file_path.unlink(missing_ok=True)
except OSError as exc:
    logger.warning(...)  # not re-raised
```

This picks the safer of the two possible partial-failure states on purpose.
If the file removal fails after the row is already gone, the result is an
orphaned file — wasted disk, but harmless, since nothing in the API can
reach it anymore. The alternative ordering (file first, then row) would risk
the opposite: a database row that still claims a video exists while its
file is already gone, which is the kind of inconsistency that breaks a
future `GET` or playback attempt. Every other endpoint in this service reads
from the database, so the database is what has to stay trustworthy.

### Verification performed

1. **The filtering is genuinely in the SQL, live, against a real camera and
   real rows spanning different dates** — this is the acceptance
   criterion's own wording, so it needed the compiled statement, not just a
   correct-looking response:
   ```python
   q = session.query(Video).filter(Video.camera_id == cam_a_id).filter(Video.created_at >= cutoff)
   print(str(q.statement.compile(compile_kwargs={"literal_binds": True})))
   # SELECT videos.id, ... FROM videos
   # WHERE videos.camera_id = 150 AND videos.created_at >= '2026-09-11 15:58:49...'
   ```
   A literal `WHERE`, not a response that merely happened to look filtered.
2. **The same filters, live, through the real running endpoint** — four
   real videos seeded directly into the real database (two uploads at
   different ages, two camera recordings against two different real
   cameras), then `GET /videos?camera_id=...` returned exactly the one
   video for that camera, `?source=camera` returned exactly the two camera
   recordings, and a `?from=...&to=...` covering the last 4 hours excluded
   the 10-day-old upload while including everything newer — proving the
   filters compose correctly together, not just individually.
3. **Delete removes both, live** — a real file confirmed present on the
   real shared volume, `DELETE /videos/{id}` against the running container,
   then both the file (`Path.is_file()`) and the database row confirmed gone
   afterward.
4. **`uv run pytest`** — **62 passed** (49 from before this ticket, 9 new in
   `test_video_listing.py`, 2 new parametrized cases in `test_tc10_auth.py`
   from adding `/videos` to its generic auth sweep). These prove filter and
   pagination *correctness* — right rows, right order, right page size —
   against the real database; the "filtering lives in SQL, not Python"
   claim itself was proven live in steps 1–2 above, since a passing test
   can't distinguish "filtered by the database" from "filtered in Python
   after fetching everything" — only reading the actual SQL can.
5. **Nothing broke** — `uv run ruff check` clean on every hand-written file
   this ticket touched; remaining findings are the same pre-existing `B008`
   pattern already present everywhere else in `services/query/app`, plus
   two pre-existing findings in `test_tc10_auth.py` untouched by this
   ticket's two one-line additions to that file.

### Result

- `GET /videos` filters by source, camera and date range entirely in SQL,
  paginates with `limit`/`offset`, and returns uploads and camera recordings
  from the same query — proven by reading the compiled statement itself,
  not inferred from a correct-looking response.
- `DELETE /videos/{id}` removes the database row first and the file second,
  a deliberate choice that favors the database — the thing every other
  endpoint trusts — never being wrong about what still exists, even in the
  rare case the file removal itself fails.
- All checklist items and the acceptance criterion for OMNI-207 are
  satisfied.

---

## OMNI-208 · Cameras screen

### Why this ticket exists

The first real screen built on top of the camera CRUD and connection-test
endpoints from OMNI-203/204 — proof, for a human, that "register a camera
against the simulator and see it turn connected" is actually true, not just
true in a `pytest` assertion.

### What was built

**`frontend/src/app/(app)/cameras/page.tsx`** — list, add/edit form, status
badges, per-row Test/Edit/Disable/Delete actions, an empty state, and
role-based rendering, all in one client component following this app's
existing pattern (no state library — `useState`/`useEffect`, matching
`sidebar.tsx` and `sign-in/page.tsx`'s style exactly, down to the rounded-2xl
card and zinc/indigo palette).

**OMNI-208 needed zero backend changes.** Every capability the screen
needed (create, list, patch, delete, test) was already built and tested in
OMNI-203/204. This ticket is purely `frontend/` plus the routing fix below.

**"Test Connection … before saving" met the backend's actual shape
head-on.** `POST /cameras/{id}/test` needs an id — there's no way to test an
address that doesn't have a row yet. Rather than invent a new
test-without-persisting endpoint (real scope creep past what OMNI-204
built), the form's "Test Connection" button creates the camera on first use
(or patches the existing draft if the user edited fields since), then tests
it, and shows the result inline — the form stays open either way, so the
user sees the result *before* closing it, which is what "before saving"
means from the browser's side even though the row exists in the database a
moment earlier than that phrase might suggest literally. Documented here so
the reasoning is visible, not just the code:

```ts
async function saveDraft(): Promise<number> {
  if (formCameraId !== null) {
    await updateCamera(formCameraId, patchPayload());
    return formCameraId;
  }
  const created = await createCamera(form);
  setFormCameraId(created.id);
  return created.id;
}
```

**A routing bug found before it ever reached a browser.** Wiring `/cameras`
into nginx and `next.config.ts` rewrites the same way OMNI-111 wired
`/auth`, `/admin` and `/nav` would have been wrong: `/cameras` is *both* the
camera-list API path *and* the Cameras screen's own page path, and neither
`/auth`, `/admin` nor `/nav` have a matching frontend page, so this
collision never existed before. Under the naive copy of the existing
pattern, a real browser navigating to `/cameras` would have hit nginx's API
rule first and gotten raw JSON back instead of the page. Caught by
literally reading what the rule would do to that exact URL before touching
a browser — confirmed for real once fixed (see verification below).

The fix: every API call now goes under `/api/*`
(`infra/nginx/default.conf`, `frontend/next.config.ts`,
`frontend/src/lib/api-client.ts`'s `request()`), with nginx stripping the
prefix before proxying to `query`. `query`'s own routes are completely
unchanged — every already-tested OMNI-203–207 endpoint still lives at
literally `/cameras`, `/videos`, etc.; only this edge layer knows `/api`
exists. This isn't a workaround scoped to `/cameras` alone — it fixes the
same latent collision for `/videos` (OMNI-209 will need a page there too)
and any future screen whose name matches its resource, instead of
special-casing collisions one at a time as they're discovered.

**Role gating matches the API's real boundary, not just the ticket's
literal wording.** The checklist says "create and delete are not rendered
for an operator" — Edit isn't mentioned, but `PATCH /cameras/{id}` is
*also* admin-only per OMNI-203, so showing an Edit or Disable button to an
operator would just be a guaranteed-403 button. All four admin actions
(Add, Edit, Disable, Delete) are gated on `user?.role === "admin"` together,
matching what the API will actually allow, not just the two verbs the
ticket named.

### Verification performed

1. **`npx tsc --noEmit`** — clean.
2. **`npx eslint`** on every file this ticket touched — one real finding,
   `react-hooks/set-state-in-effect` on the initial-load `useEffect`
   (`refresh()` called directly in the effect body). Fixed by matching
   `sidebar.tsx`'s already-working pattern — an inline `.then()`/`.catch()`
   for the initial load — rather than suppressing the rule; the shared
   `refresh()` helper stays for the event handlers, which the rule doesn't
   flag. Zero remaining findings in new code; the one remaining warning
   (`no-location-assign-relative-destination` on `api-client.ts:52`) is on a
   line from OMNI-105/109, untouched by this ticket.
3. **The routing collision, proven for real, live** — `curl` against the
   running stack, before and after the `/api` fix:
   ```
   GET https://localhost/cameras     -> <!DOCTYPE html>...        (the page)
   GET https://localhost/api/health  -> {"status":"ok"}            (the API)
   GET https://localhost/api/cameras (no token) -> 401             (the API, auth-gated)
   ```
4. **The full screen's flow, live, through the exact network path a browser
   would use** (nginx TLS → `/api/*` → `query`) — everything the page's
   buttons do, called directly in the same sequence a click would trigger:
   create → test (reachable, real resolution/fps, status flips to
   `connected`) → list → edit → disable → delete, each one checked against
   the real response. Then a second camera with a bad address, tested the
   same way: `{"reachable": false, "error": "unreachable"}` — the
   acceptance criterion's "specific error for a bad address," proven
   end-to-end.
5. **What was *not* verified: actually looking at the page.** The Claude in
   Chrome browser extension wasn't connected in this environment, so the
   rendered screen — badge colors, the modal, button states, the empty
   state's real appearance — was never visually confirmed, only proven
   correct at the network layer above. The code was written to match this
   app's established Tailwind conventions exactly (same classes, same
   patterns as `sign-in/page.tsx` and `sidebar.tsx`), and `tsc`/`eslint`
   confirm it compiles and follows React's rules, but that is not the same
   claim as "a human looked at it in a browser." **This should be opened in
   a real browser and clicked through before being treated as fully done.**

### Result

- The Cameras screen lists, creates, tests, edits, disables and deletes
  cameras against the real backend, gated to admin for every write action
  the API itself restricts.
- A real routing bug — `/cameras` colliding between the API and the page —
  was caught and fixed before it ever reached a browser, with a general fix
  (`/api/*`) rather than a one-off patch, closing the same latent bug for
  `/videos` ahead of OMNI-209.
- Every checklist item is implemented and verified at the network level;
  visual/interactive confirmation in an actual browser is the one piece
  still outstanding, flagged explicitly rather than assumed.

---

## OMNI-209 · Video Archive screen

### Why this ticket exists

The last ticket before the sprint's own cut line. With this screen done,
FR-1a is demonstrably complete in both halves from a browser — a camera
registered and tested (OMNI-208), a file uploaded and probed (this ticket)
— and the plan's own "Proof it works" demo becomes something that can
actually be shown, not just curled.

### What was built

**`frontend/src/app/(app)/videos/page.tsx`** — recordings table, filters,
and an upload control, following the same conventions OMNI-208 already
established (no state library, `useState`/`useEffect`, the same card and
badge styling). Like OMNI-208, this needed zero backend changes — OMNI-205
through 207 already built upload, probing, listing and delete.

**Upload progress needed a different tool than the rest of the app uses.**
Every other call in `api-client.ts` goes through one shared `request()`
helper built on `fetch()` — but `fetch()` has no cross-browser way to
observe how much of a request body has been sent, so there is no way to
show upload progress through it. `uploadVideo()` is the one function in
this file that uses `XMLHttpRequest` instead, specifically for
`xhr.upload.onprogress`:

```ts
xhr.upload.onprogress = (event) => {
  if (onProgress && event.lengthComputable) {
    onProgress(Math.round((event.loaded / event.total) * 100));
  }
};
```

It duplicates `request()`'s token-attachment, token-renewal and 401-redirect
handling by hand rather than sharing that logic, since `fetch`-based
`request()` and XHR-based upload don't share an underlying transport to
factor the common parts through cleanly — noted here so it doesn't read as
an accidental copy the next person "fixes" by merging back in.

**Camera names, not raw ids.** `GET /videos` (OMNI-207) only ever returns
`camera_id`, matching the plan's own field list — no join, no camera name.
The ticket wants "camera" shown per row, so the page also loads
`listCameras()` once on mount and resolves `camera_id -> name` client-side:

```ts
const cameraNames = new Map(cameras.map((camera) => [camera.id, camera.name]));
...
{video.camera_id != null ? (cameraNames.get(video.camera_id) ?? `#${video.camera_id}`) : "—"}
```

An upload (`camera_id: null`) shows `—`; a camera recording falls back to
`#<id>` only if that camera's own row can't be found (e.g. it was since
deleted) — never a blank cell.

**Filters call the real query parameters OMNI-207 already built and
proved run in SQL** — `source`, `camera_id`, `from`, `to` — as controlled
inputs whose `useEffect` dependency array re-fetches on every change. The
date inputs are date-only (`<input type="date">`); `from` is widened to
that day's `00:00:00.000Z` and `to` to `23:59:59.999Z` so picking one day
includes the whole day, not an instant of it.

**The same `set-state-in-effect` lint rule from OMNI-208 applied here
too**, and got the same fix: the initial/filter-driven load is an inline
`listVideos(...).then(...).catch(...)` inside the effect (mirroring
`sidebar.tsx`'s already-working pattern), while a separate `refreshVideos()`
helper — safe to call directly, since it's invoked from event handlers, not
from inside an effect body — is what upload and delete call afterward.

### Verification performed

1. **`npx tsc --noEmit`** — clean.
2. **`npx eslint`** on every file this ticket touched — zero errors. Two
   warnings, both `no-location-assign-relative-destination`: one
   pre-existing (`api-client.ts:56`, from OMNI-105/109, untouched here), one
   new at the same file's `uploadVideo()` 401 handler — same justification
   as the pre-existing one: `uploadVideo` is a plain module function, not a
   component or hook, so `useRouter()` isn't reachable from it, same real
   constraint the existing code already lives with.
3. **No `/videos` routing collision** — the same class of bug OMNI-208 found
   and fixed generally (the `/api/*` prefix) was checked again for this
   ticket's own route, live:
   ```
   GET https://localhost/videos     -> <!DOCTYPE html>...   (the page)
   GET https://localhost/api/videos (no token) -> 401        (the API)
   ```
4. **The full upload flow, live, through the exact network path a browser
   would use** — a real 4-second, 320×240 clip generated with `ffmpeg`,
   uploaded with `curl` (a genuine multipart POST over a real socket, the
   same request shape `XMLHttpRequest` sends) against the running stack
   through `https://localhost/api/videos/upload`:
   ```
   {"id":181,"filename":"omni209_good.mp4","duration_s":4.0,"size_mb":0.02,
    "fps":10.0,"status":"ready","error":null}
   ```
   Exact duration match — this is the acceptance criterion's own "correct
   duration and size," proven against a file of genuinely known length, not
   assumed from a passing status code. Then confirmed the same video shows
   up in `GET /api/videos` (unfiltered) and in `?source=upload`, and that
   `DELETE /api/videos/{id}` removes it.
5. **What was *not* verified, same as OMNI-208: actually watching it
   happen in a browser.** The Claude in Chrome extension was still not
   connected in this environment. The upload's real progress bar — the
   whole reason `uploadVideo()` uses `XMLHttpRequest` instead of `fetch` —
   is inherently something only a real browser's network stack can drive;
   `curl` proves the server side handles a real streamed multipart upload
   correctly (matching OMNI-205's own memory-spike finding: a real socket
   is the only trustworthy way to prove streaming behavior), but nothing
   server-side can prove the *client's* progress callback actually fires
   and updates the bar on screen. **This should be opened in a real
   browser — including an upload of a large-enough file to actually watch
   the bar move — before being treated as fully done.**

### Result

- The Video Archive screen lists uploads and camera recordings in one
  table with resolved camera names, filters that drive the real SQL query
  parameters OMNI-207 already proved, and status badges for all four
  `VideoStatus` values.
- Upload has a real progress bar, backed by `XMLHttpRequest` specifically
  because `fetch` can't report upload progress across browsers — verified
  as a genuine streamed multipart upload against the live stack, though not
  watched happen on screen.
- A known-length file uploaded through the real endpoint probed to its
  exact duration, matching the acceptance criterion precisely rather than
  approximately.
- Every checklist item is implemented and verified at the network level,
  and — after the fix below — confirmed for real in a browser: a real
  20m 8s, 35.9 MB MP4 uploaded, landed `ready` with the correct duration and
  size, showed the correct upload timestamp, and deleted cleanly.

### Addendum: the manual browser check found a real bug

Exactly the outcome that caveat above was flagged for. A real 3.35 MB, one
minute clip uploaded from the browser came back "upload failed" — but
`query`'s own request log had no `POST /videos/upload` line at all for it.
`nginx`'s log did:

```
[error] client intended to send too large body: 3515728 bytes,
request: "POST /api/videos/upload HTTP/1.1"
-> 413
```

`client_max_body_size` was never set in `infra/nginx/default.conf`, so
nginx was silently enforcing its own built-in default — 1 MB — in front of
`query`'s configured 500 MB (`settings.max_upload_size_mb`, OMNI-205). Every
`curl`/`httpx` upload this whole sprint's verification used, including
OMNI-209's own "live" check, happened to stay under 1 MB (a few KB to
~18 KB), so nothing before this ever exercised the path that would have
caught it — a real gap in how this ticket was verified, not just bad luck.

Fixed with one line, `client_max_body_size 500m;` on the server block,
matching `query`'s own limit so the two stay in the same place a future
change to `MAX_UPLOAD_SIZE_MB` would need updating too. Re-ran the exact
failing size (3,515,728 bytes) against the fixed config: `201`, not `413`,
`query`'s log now shows the request. (The reprobed file itself then landed
as `status: failed` — expected, since the repro used synthetic filler
bytes, not a real decodable video; a real clip that size lands `ready`.)

Confirmed fixed for real straight after: a genuine 20m 8s, 35.9 MB MP4
uploaded from the browser, progress bar watched moving, landed `ready` with
the correct duration and size, correct upload timestamp shown, delete
worked. The one gap OMNI-208/209 both flagged — nobody had actually looked
at this in a browser — is closed, and it's exactly what caught this bug.

**Lesson for next time this pattern comes up:** an nginx-level rejection
(body size, but the same is true of timeouts, header limits, buffer sizes)
never reaches the proxied service's own logs — only nginx's. When a request
this app's own service logs know nothing about needs debugging, check the
edge (nginx) first, not just query and ingestion.
