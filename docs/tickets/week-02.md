# Sprint 2 — Cameras and uploads

**Slice 2 · Stage A (Foundation) · 06 – 12 Sep 2026 · 7 days**
Board: OmniSight Phase B · Assignee: Ahmad · Reviewer: Cyrine

> **By the end of this sprint:** register a camera and prove it connects; upload a
> video file and see it listed with correct duration and size. Both appear in one
> archive.

**Covers:** FR-1a · FR-3 · NFR-5 · NFR-7
**Ships in:** `services/ingestion/` · `services/common/` · `services/query/` ·
`frontend/`

---

## What changes architecturally this week

Week 1 was one service. This week introduces the **second**, and the way they talk
to each other is the decision that matters — get it wrong now and slices 3, 4 and 6
inherit it.

The split:

- **`services/query`** owns the HTTP API the dashboard calls. Camera and video
  records, listing, filtering, authorisation. It never opens a video stream itself.
- **`services/ingestion`** owns everything that touches video. Opening an RTSP
  stream, reading a frame, probing a file for duration and frame rate. It has no
  public routes — nginx does not expose it.

They talk over the Docker network: query calls ingestion's internal endpoints.
RabbitMQ arrives in slice 4 for continuous capture; this week a direct call is
correct and simpler.

**Uploads do not pass through ingestion.** Query receives the multipart upload and
writes the file to a shared named volume, then asks ingestion to probe it *by path*.
Sending the bytes twice over HTTP would be wrong.

```
browser ──upload──> query ──writes──> /data/videos (named volume)
                      │                      ▲
                      └──probe(path)──> ingestion ┘

browser ──test──> query ──probe(rtsp_url)──> ingestion ──> MediaMTX simulator
```

---

## Ticket order

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-200 | Ingestion service skeleton | 1.5 h | 1 |
| OMNI-201 | RTSP simulator with ten looping feeds | 2 h | 1 |
| OMNI-202 | Cameras and videos tables, shared enums | 2 h | 2 |
| OMNI-203 | Camera CRUD, admin-only writes | 3 h | 2 |
| OMNI-204 | Connection test, end to end | 3 h | 3 |
| OMNI-205 | Video storage volume and upload endpoint | 3 h | 4 |
| OMNI-206 | Probe an uploaded file with OpenCV | 2.5 h | 4 |
| OMNI-207 | Video listing with server-side filters | 2 h | 5 |
| OMNI-208 | Cameras screen | 3.5 h | 5 |
| OMNI-209 | Video Archive screen | 3.5 h | 6 |
| — | **cut line — the slice is defensible from here** | | |
| OMNI-210 | Prove nothing is lost on restart (NFR-5) | 1.5 h | 6 |
| OMNI-211 | Dataset folder layout for slice 6 | 1.5 h | 7 |
| OMNI-212 | Retention field, docs, pull request | 1.5 h | 7 |

The plan's own fallback, if the week goes badly: *upload and listing first, camera
registration second — but do not skip the connection test.* A camera that silently
fails costs a day in slice 4.

---

## OMNI-200 · Ingestion service skeleton

**Why:** the second service. Everything that touches video lives here from now on.

- [x] Branch: `git checkout -b slice-02-cameras-uploads`
- [x] Dependencies on the workspace member, not the root:

```bash
uv add fastapi "uvicorn[standard]" opencv-python-headless pydantic-settings \
       --package omnisight-ingestion
```

`opencv-python-headless`, not `opencv-python` — the container has no display and
the headless build is far smaller.

- [x] App entry point in `services/ingestion/`, mirroring the query service's shape:
      settings through pydantic-settings, JSON logging, clean JSON errors
- [x] `/health` returning `{"status": "ok"}`
- [x] `ingestion` service in `docker-compose.yml`, on the internal network only —
      **no port published to the host, no nginx route**
- [x] Query reaches it at `http://ingestion:8000` from inside the network; the base
      URL comes from settings, never a literal
- [x] `docker compose up -d` and confirm query can call ingestion's `/health`

**Acceptance:** both services run; query can reach ingestion; ingestion is not
reachable from your browser.

---

## OMNI-201 · RTSP simulator with ten looping feeds

**Why:** NFR-4 in slice 5 needs ten concurrent feeds and you will not have ten
cameras. Building the simulator now means slices 3, 4 and 5 all have something real
to point at.

- [x] MediaMTX service in `docker-compose.yml`, config in `infra/` alongside the
      other supporting tools
- [x] Collect a handful of short MP4 clips — anything will do, they are scaffolding,
      not data. Put them somewhere gitignored; they are not project data
- [x] Configure at least **ten distinct looping feeds**, each on its own path:
      `rtsp://mediamtx:8554/cam01` … `cam10`
- [x] Confirm with `ffprobe` or VLC that a feed plays and loops
- [x] Write the ten addresses into `docs/` so Cyrine can find them without asking
- [ ] The address a developer types into the Add Camera form is documented in the
      empty state (OMNI-208)

**Acceptance:** ten distinct RTSP URLs each serve a looping stream, reachable from
inside the Docker network.

> Ten feeds is not premature. It is the difference between discovering a
> concurrency problem in week 2 and discovering it in week 5, the week it is graded.

---

## OMNI-202 · Cameras and videos tables, shared enums

**Why:** FR-1a and FR-3 need somewhere to put both kinds of footage source.

From the plan:

```
cameras(id, name, rtsp_url, location, group, domain, status, last_seen_at, created_at)
status in {registered, connected, unreachable, disabled}
domain in {surveillance, sports, traffic}

videos(id, filename, path, camera_id NULL, source, duration_s, fps, width, height,
       size_bytes, status, retention_until, created_at)
source in {upload, camera, dataset}
status in {uploaded, extracting, ready, failed}
```

- [x] Four enums in `services/common`, beside the Role enum from last week —
      `CameraStatus`, `Domain`, `VideoSource`, `VideoStatus`. Both services import
      them, so neither can invent a fifth value
- [x] SQLAlchemy models in the query service
- [x] One alembic migration for both tables
- [x] `group` is a reserved word in SQL — quote it or name the column `group_name`
      and map it. Decide now, not when the migration fails
- [x] Index on `camera_id` and on `created_at`; the archive filters on both
- [x] `alembic upgrade head` applies cleanly on a fresh database

**Acceptance:** both tables exist; a fresh `docker compose down -v && up -d` plus
migration produces them from nothing.

**Note:** `domain` decides which prediction head applies in slice 11, and
`retention_until` is enforced in slice 16. Both are recorded now and unused until
then — that is deliberate, not dead weight.

---

## OMNI-203 · Camera CRUD, admin-only writes

**Why:** **FR-1a** — *Accept video input from live camera feeds and from uploaded
video files.* And **NFR-7** — *100% of API endpoints reject requests lacking a valid
token or sufficient role.*

```http
POST   /cameras {name, rtsp_url, location, group, domain} -> {id, status}
GET    /cameras -> [{id, name, location, group, domain, status, last_seen_at}]
PATCH  /cameras/{id}
DELETE /cameras/{id}
```

- [x] Stream address stored as configuration on the record — never hardcoded
      anywhere **[FR-1a]**
- [x] Camera grouping by site or zone, the field the camera wall uses in slice 5
- [x] **Only administrators may create, edit or delete. Operators may view** —
      enforced by the role dependency from OMNI-107, not by a new check **[NFR-7]**
- [x] New cameras start at `registered`, not `connected` — nothing is connected
      until the test in OMNI-204 says so
- [x] Delete is soft where a video already references the camera; hard delete would
      orphan recordings
- [x] Tests: an operator token gets 403 on create and delete, 200 on list

**Acceptance:** an admin can register and remove a camera; an operator can see them
and nothing else. The 403 is proven by a test, not by clicking.

---

## OMNI-204 · Connection test, end to end

**Why:** the single most valuable thing in this slice. A camera that silently fails
costs a day in slice 4.

```http
POST /cameras/{id}/test -> {reachable, resolution, fps, error?}
```

- [ ] Ingestion endpoint `POST /probe/stream {rtsp_url}`: open the stream, read one
      frame, report resolution and frame rate, close it. It must always close, even
      on failure
- [ ] A timeout — an unreachable address must not hang the request
- [ ] **Specific failure reasons: unreachable, authentication failed, timeout.**
      "Something went wrong" is not acceptable here
- [ ] Query's `/cameras/{id}/test` calls ingestion and updates `status` and
      `last_seen_at` from the result
- [ ] Test against a real simulator feed: reports resolution and frame rate
- [ ] Test against a wrong address, and against a wrong port: two different reasons

**Acceptance:** a good address returns resolution and fps and flips the camera to
`connected`; three distinct bad addresses return three distinct reasons.

---

## OMNI-205 · Video storage volume and upload endpoint

**Why:** **FR-1a**, the other half — uploaded files. And the storage half of
**NFR-5** — *On any failure or crash, video or stored data lost = 0.*

```http
POST /videos/upload (multipart) -> {id, filename, duration_s, size_mb, fps, status}
```

- [ ] Named Docker volume for video storage, mounted into query and ingestion at
      the same path **[NFR-5]**
- [ ] Multipart upload written to that volume; **only the path goes in the
      database, never the bytes** **[FR-1a]**
- [ ] Stored filename is generated, not taken from the client. A user-supplied name
      reaching the filesystem is a path-traversal bug; keep the original in
      `filename` for display
- [ ] Reject anything that is not a video, and anything over a size limit from
      settings — with a message saying which of the two it was
- [ ] Stream the upload to disk rather than reading it into memory; these are large
      files
- [ ] Row created with status `uploaded` before probing starts

**Acceptance:** a 200 MB MP4 uploads without the container's memory spiking; a
`.txt` renamed to `.mp4` is rejected with a clear reason.

---

## OMNI-206 · Probe an uploaded file with OpenCV

**Why:** **FR-3** — *Store each analyzed segment with its details (time, source
camera, representative image) for later retrieval.* The details start here.

- [ ] Ingestion endpoint `POST /probe/file {path}` returning duration, fps, width,
      height **[FR-3]**
- [ ] Query calls it after the upload lands and fills the row
- [ ] Status moves `uploaded` → `ready`, or → `failed` with the reason recorded
- [ ] A corrupt or truncated file fails cleanly and stays visible as `failed` —
      it does not vanish and it does not 500
- [ ] `GET /videos/{id}` returns the full record plus `segments_count` (zero this
      week; slice 3 fills it)

**Acceptance:** upload an MP4 of known length and the stored duration matches within
a second; a deliberately truncated file lands as `failed` with a reason.

---

## OMNI-207 · Video listing with server-side filters

```http
GET /videos?source=&camera_id=&from=&to= -> [ ... ]
DELETE /videos/{id}
```

- [ ] **Filters applied in the query, not in the browser.** By slice 6 this table
      holds thousands of dataset rows; a client-side filter dies there
- [ ] Pagination, for the same reason
- [ ] Both uploads and camera recordings come back from one endpoint — the archive
      is one list, not two
- [ ] Delete removes the row and the file together, or neither

**Acceptance:** filtering by camera and by date range returns correct results with
the filtering visible in the SQL, not the response size.

---

## OMNI-208 · Cameras screen

- [ ] List: name, location, group, status badge, last-seen time
- [ ] Add-camera form with a **Test Connection button that reports what it found
      before saving** — resolution and frame rate, or the specific failure
- [ ] Status as a coloured badge so an unreachable camera is obvious at a glance
- [ ] Edit, disable and delete, with delete confirmed
- [ ] Empty state explaining how to register the first camera, **including the
      simulator address** so Cyrine can start without reading a ticket
- [ ] Create and delete are not rendered for an operator — and the API refuses them
      anyway (OMNI-203)

**Acceptance:** register a camera against the simulator from the browser, see it
turn connected, and get a specific error for a bad address.

---

## OMNI-209 · Video Archive screen

- [ ] Recordings with filename, camera, duration, size, status and upload time
- [ ] Upload control with progress and a clear success or failure message
- [ ] Status badges so `ready` and `failed` are distinguishable at a glance
- [ ] Filters for source, camera and date range, driving the API query parameters
- [ ] Empty state prompting the first upload
- [ ] Both uploads and camera recordings appear in the same list

**Acceptance:** upload a file from the browser, watch progress, and see it land with
correct duration and size.

> **This is the cut line.** With OMNI-200 to 209 done, the slice is defensible:
> FR-1a is complete in both halves, FR-3 has begun, and NFR-7 is enforced on the new
> endpoints. The three below matter, but they can slip a few days without blocking
> slice 3.

---

## OMNI-210 · Prove nothing is lost on restart

**Why:** **NFR-5** — *On any failure or crash, video or stored data lost = 0.* This
is the storage half; fault injection comes in slice 17.

- [ ] `docker compose restart`, then confirm every uploaded file and row is still
      there
- [ ] `docker compose down` then `up -d` — same check. Named volumes, not bind
      mounts to a temp directory
- [ ] Kill the query container mid-upload. The result must be either a complete
      file with a row, or no file and no row — never a row pointing at a partial file
- [ ] Record the result in `docs/results.md` under NFR-5, dated

**Acceptance:** both restart checks pass; the interrupted upload leaves no orphan
row.

---

## OMNI-211 · Dataset folder layout for slice 6

**Why:** slice 6's loaders expect a layout. Agreeing it now costs an hour; agreeing
it in week 6 costs a day.

- [ ] Organise the downloaded datasets in Drive into the folder layout the loaders
      will expect in slice 6 — one folder per dataset, annotations beside the video
- [ ] Write the layout into `docs/` so the loader can be written against a
      specification rather than against whatever is on your disk
- [ ] Confirm the same ingestion path will accept dataset footage: upload one clip
      taken **from a dataset** and check it lands as `ready` like any other file
- [ ] Mirror the layout under `data/` locally, so `data/dota/` and the rest match
      Drive

**Acceptance:** a dataset clip uploads through the normal endpoint and appears in
the archive indistinguishable from a hand-uploaded file. This is what slice 6
depends on.

---

## OMNI-212 · Retention field, docs, pull request

- [ ] `retention_until` populated per recording from a default in settings —
      recorded now, enforced in slice 16
- [ ] Update `docs/context/` with what changed this week, as you did for week 1
- [ ] `uv run pytest` green
- [ ] Open the pull request using the `.github` template; Cyrine reviews before merge
- [ ] Tick slice 2 on the tracker

---

## Definition of done

From the plan's "Proof it works" — this is the demo:

> Register a camera against the simulator: Test Connection reports resolution and
> frame rate and it shows as connected; an invalid address reports a specific
> reason. Upload an MP4: it appears with correct duration and size, and survives a
> container restart. An operator account cannot delete a camera.

- [ ] All four of those are true on a fresh `docker compose up -d`
- [ ] `docs/results.md` has this week's NFR-5 entry
- [ ] Merged and pushed

---

## What to learn this week

- [RTSP, and how a stream differs from a file](https://ffmpeg.org/ffmpeg-protocols.html#rtsp)
  — a stream has no end, it drops, and it must be reconnected.
- [Simulating cameras with MediaMTX](https://github.com/bluenviron/mediamtx)
  — how you reach ten feeds without ten cameras.
- [Multipart upload in FastAPI](https://fastapi.tiangolo.com/tutorial/request-files/)
  — how a browser actually sends a file to an API.

---

## Working with Claude Code

One ticket per session, as last week. Paste the ticket, then:

> Here is ticket OMNI-2xx from our sprint board. Implement exactly what it asks and
> nothing more. This is a uv workspace — add Python dependencies with
> `uv add <pkg> --package omnisight-ingestion` or `--package omnisight-query`, never
> to the root project and never with pip. Shared enums live in `services/common` and
> are imported by both services. Role checks reuse the existing dependency from
> slice 1; do not write a new one. Settings come from `.env` through
> pydantic-settings. When you are done, show me the diff and tell me which
> acceptance criteria you verified and how.

Three things to insist on this week:

- **Query never opens a video stream.** If Claude Code offers to call OpenCV from
  the query service because it is quicker, say no — that collapses the two services
  into one and slice 15's NFR-6a claim stops being true.
- **The upload filename on disk is generated, not the client's.** This is the one
  genuine security bug available in this slice.
- **Filters run in SQL.** A client-side filter looks fine on ten rows and dies on
  the fifty thousand that arrive in slice 6.
