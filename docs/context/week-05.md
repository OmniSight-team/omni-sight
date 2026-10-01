# Context notes — Sprint 5

Slice 5, the camera wall, 30 Sep – 6 Oct 2026. Tickets in `docs/tickets/week-05.md`.
Entries are added as each ticket closes.

---

## OMNI-500 · Branch and baseline

### Why this ticket exists

Slice 5 changes the live worker, the queue layout and the schema. A known-good starting
point is needed first, so that anything that breaks later is known to come from this
sprint and not from slices 3–4.

### What was done

2026-09-30, on `master` at `d6d5943`.

- **`master` is not clean.** `git log` shows `d6d5943` on top, so slices 3–4 are there, but
  the working tree has the 2026-09-28 documentation reorganisation uncommitted:
  - modified: `README.md`, `docs/README.md`, `docs/context/week-03-04.md`,
    `docs/dataset-layout.md`, `docs/results.md`, `services/ingestion/app/pipeline.py`,
    `services/ingestion/app/settings.py`
  - untracked: `CLAUDE.md`, `docs/decisions.md`, `docs/known-issues.md`,
    `docs/tickets/week-05.md`

  The two code files differ only in comments (the pointers moved from `docs/results.md` to
  `docs/decisions.md` D-4 and D-9); no behaviour changed. Committing is Ahmad's, so it is
  left for him, before the branch is created
- **Stack:** `docker compose up -d` from stopped. All eight services running, `postgres`
  and `rabbitmq` healthy, `https://localhost` answers 200
- **Suite:** `uv run pytest` against a scratch database (`omni500_scratch`, created,
  migrated from empty to `08b81a0fd8d1` with `alembic upgrade head`, dropped afterwards),
  because five query test files empty the `videos` table of whatever database they run on

### Verification performed

- `uv run pytest`: **304 passed**, 1 warning (Starlette's `httpx` deprecation), 106 s. Same
  count as the end of slices 3–4. Run on the working tree as it is, uncommitted changes
  included
- The dev database after the run: 3 videos, 0 cameras, 300 segments — untouched
- All eleven migrations applied cleanly from empty on the scratch database

### Not verified

- The suite was not run again after the branch was created. `slice-05-camera-wall` points
  at `c32ad10`, which is the tree the suite ran on plus these notes and the ticket file, so
  the 304 carries over
- No live capture was started; this ticket only asks that the stack runs and the suite is
  green

### Result

Stack up and suite green (304). Ahmad committed the pending documentation changes on
`master` as `c32ad10` and created `slice-05-camera-wall` from it; `master` and the branch
are at the same commit and the working tree was clean. All three boxes ticked.

---

## OMNI-501 · Live capture gates every frame (Algorithm 1)

Done 2026-09-30, on `slice-05-camera-wall`. Numbers and conditions are in
`docs/results.md` (OMNI-501).

### Why this ticket exists

FR-1b, and Phase A §3.5.1 / Appendix B.1. The live worker read every frame of a stream but
gated only one per 0.2 s, the sampling step OMNI-303's rework had already removed from
files. It was recorded as an open deviation (D-9). OMNI-317 showed the stack choking at ten
cameras, and the conclusion there was that the load came from storing a row for every
sampled frame, not from the gate. So: gate every frame as the pseudocode says, and publish
only what the gate admits.

### What was done

- **Sampling removed from the worker** (`services/ingestion/app/live_capture.py`). The
  capture thread now decodes every frame the stream delivers (`grab` then `retrieve`, no
  interval check) and puts it on the bounded queue. `sample_interval_s` is gone from
  `LiveWorker`, and `LIVE_SAMPLE_INTERVAL_S` from `settings.py`, `.env.example` and
  `docs/rtsp-simulator.md`. The gate a live frame goes through was already the file's
  (`_gate_for` in `main.py`: `MotionGate` inside `HeartbeatGate`, the same settings), so
  nothing changed there
- **Only admitted frames are published.** In `_handle`, the frame goes through
  `process_frame()` as before (which writes the JPEG and thumbnail only when admitted); the
  record is published only if `record.admitted`. A discarded frame gets no message, so no
  row, and it never had a file. This is the one live-specific part, and it is in the worker;
  `process_frame()` is untouched and still has two producers
- **The clip window** needed no code: the gate already sets `clip_start_s` / `clip_end_s`
  to `[t - 2Δ, t]` on every admission, heartbeat included, and the record carries them. Now
  tested and checked on the stack for live rows
- **Counters.** The worker counts `gated`, `admitted_motion`, `admitted_heartbeat` and
  `discarded` at the gate's decision, under one lock, so they balance in every report. They
  travel in `CameraStatsReport` (defaults of 0, so a report queued before the change still
  parses), are folded into `camera_stats` by the consumer the same way `captured` and
  `dropped` are (running totals, a `session_` twin per counter; the six are now one loop
  over `STATS_COUNTERS`), and `GET /cameras/{id}/stats` returns them with `admitted` as the
  sum of the two reasons. Migration `1108fdad7cf9` adds the eight columns
- **What the existing counters mean now.** `captured` is every decoded frame (it was every
  sampled frame). `fps_effective` is frames gated per second (it was frames published per
  second), so on a healthy camera it reads the feed's frame rate. `published` in the
  worker's snapshot is the admitted frames handed to the broker
- **Where a drop is counted.** Both kinds of drop (the in-process queue full, the broker
  backlog too deep) still happen before the gate, so a dropped frame is never gated and
  never half-admitted with a file but no message. That is what keeps
  `captured = gated + dropped` true
- **Frame indexes.** Every frame handed to the pipeline takes an index, admitted or not, as
  a file's frames do. Stored live rows therefore have gaps in `frame_index` where frames
  were discarded. File names still come from the index and stay unique
- **Docs.** `decisions.md`: D-9 is Done (the history of the deviation kept, the evidence
  added); D-5 has the line about live cameras storing admitted frames only. `known-issues.md`:
  notes on K-2 and K-8, three small items in K-10, and a new K-11 (below)
- **Frontend, wording only:** the camera screen said "frames sampled" and "sampled frames";
  it now says "frames decoded", "captured frames" and "frames gated". The new fields were
  added to the `CameraStats` type. The new counters are not displayed (not asked for)
- **Tests.** Three tests that described sampling were rewritten; four were added in
  ingestion and four in query. The ticket's test is
  `test_a_still_then_moving_stream_publishes_only_the_frames_the_gate_admits` with
  `test_the_gate_counters_balance_exactly`: a scripted capture of 100 still frames then 100
  with a block crossing the picture, through the real `MotionGate`, `HeartbeatGate` and
  `process_frame()` at the default settings
- **`scripts/verify_live_gate.py`**, new: the acceptance check on the running stack

### A mistake in my own check

The first run of the script printed 9 of 10. The failing check was mine: it required the
frames read in the window to equal the frames gated exactly, from two snapshots of a
running worker. A snapshot is not atomic, and one frame was between the queue and the
counter (909 read, 910 gated). I changed the check to allow a frame at each end of the
window and ran again: 10 of 10. The result was not changed, and the exact balances were
never in doubt: they are read from the session totals after the stop, and held in both
runs.

### Found on the way, not fixed

- **K-11:** `scripts/verify_definition_of_done.py` treats a gap in a live session's frame
  indexes as a lost frame. Gaps are now normal, so its restart checks will report loss that
  did not happen. Read from the code, not run. It has to be dealt with before the slice 5
  definition of done
- The two measuring scripts still talk about sampled frames and discarded live rows; they
  are rerun in OMNI-502 and OMNI-509 (K-10)
- `LIVE_QUEUE_SIZE` = 10 was sized for 5 frames/s and is now about 0.7 s of a 15 fps feed.
  Left at 10: no drops on one camera, and changing a default without a measurement under
  load is not this ticket's business (K-10)
- `camera_stats` rows written before this migration would not balance (their `captured`
  counted sampled frames and `gated` starts at 0). The dev database has no cameras, so no
  such row exists; nothing was backfilled
- `.env` (not committed, not mine to edit) still has `LIVE_SAMPLE_INTERVAL_S=0.2` on line
  33. It is ignored; the line can be deleted

### Verification performed

- **`uv run pytest`: 312 passed** (304 before), against a scratch database
  (`omni501_scratch`, dropped afterwards). The live capture file alone, three more times:
  53 passed each time
- **Migration `1108fdad7cf9`:** up, down, up on the scratch database, `alembic check` clean,
  then applied to dev
- **`ruff`:** nothing new in the files touched (the known `B008` pattern, and the new
  migration has the same findings as the generated ones before it)
- **`tsc --noEmit`** in the frontend container: clean
- **Acceptance, real stack, `cam05`, two 60 s runs** (`scripts/verify_live_gate.py`):
  - gated **15.02/s and 15.00/s** (910 frames in 60.6 and 60.7 s); 0 dropped, 0 decode errors
  - **every stored row is admitted with a reason**: 205 rows (163 motion, 42 heartbeat) and
    190 rows (148, 42), equal to the `admitted` counter and to the files on disk
  - **heartbeat:** the largest gap between two stored frames was 1.068 s and 1.073 s, the
    1.0 s interval plus one 67 ms frame
  - **counters balance exactly**, read after the stop: 996 = 996 + 0 and 996 = 205 + 791;
    996 = 996 + 0 and 996 = 190 + 806
  - every row carries `[t - 2Δ, t]`, error 0
- Dev database afterwards: 3 videos, 0 cameras, 300 segments, the throwaway user gone

### Not verified

- More than one camera. Whether ten feeds fit is OMNI-509; this ticket only shows one camera
  gating 15 frames/s at 36-39% of a core in ingestion (of which 8-14% is there when idle)
- Anything longer than a minute, a feed faster than 15 fps, or frames larger than 320x240
- Drops on the real stack: the counters under drops are covered by unit tests only
  (`test_the_counters_still_balance_when_frames_are_dropped` and the OMNI-314 ones)
- The camera screen in a browser. Three strings changed; it type-checks, it was not opened
- The "heartbeat admits at least one frame a second" reading depends on how it is counted:
  the gap is up to the interval plus one frame (1.07 s), so a given clock second can hold
  no stored frame. That is how `HeartbeatGate` has always worked for files too

### Result

Live capture follows Algorithm 1 as written: every frame gated, admitted frames forwarded
with their clip, the rest counted. D-9 is closed. All acceptance points hold on `cam05`.

---

## OMNI-502 · Live frames never wait behind a recording

Done 2026-10-01, on `slice-05-camera-wall`. Numbers and conditions are in
`docs/results.md` (OMNI-502); the design is D-13 in `docs/decisions.md`.

### Why this ticket exists

NFR-1: a captured frame stored in under 5 s. OMNI-316 measured 49 ms for live alone but
6.14 s while a 1,930-frame file was extracted, because both shared one queue and one
consumer, first in first out (K-1).

### What was done

- **A second durable queue.** `live_segment_queue` = `omnisight.segments.live` in the
  shared settings (`services/common/omnisight_common/settings.py`). The live worker's
  publisher now uses it (`_live_worker_for` in ingestion's `main.py`); file extraction keeps
  `omnisight.segments`. Declared with the same `declare_segment_queue`, so it is durable and
  has its own dead-letter queue
- **A second consumer service**, `consumer-live` in `docker-compose.yml`: same image, same
  command, same code, with `CONSUMER_ROLE=live`. The role is a new query setting
  (`consumer_role`, `files` by default; `consumer` sets `files` explicitly). `queues_for()`
  in `consumer.py` maps the role to its queues: `files` reads the file queue and the camera
  queue (status and stats), `live` reads the live queue only. I kept the camera queue off
  the live consumer so nothing at all is handled in front of a live frame in that process;
  status and stats messages are a few per camera every 5 s and stay where they were
- **Same guarantees on both:** nothing about publishing or acknowledging changed, only the
  queue name. Persistent messages and a confirm per publish come from the same
  `SegmentPublisher`; the live consumer runs the same `_on_message`, which acknowledges after
  `store_segment` has committed. A new test publishes a live frame, makes the commit fail,
  and finds the message still on the live queue, then stored once on a second try
- **`LIVE_MAX_BACKLOG`** now measures the live queue, because the worker's publisher reads
  the depth of the queue it publishes to. So a large upload no longer makes live capture drop
  frames. Comment in `settings.py` updated
- **`scripts/measure_capture_latency.py`:** samples both queues' depth, reports
  `consumer-live`'s CPU, and no longer prints a "discarded frames" latency line (no such live
  rows since OMNI-501)
- **Tests:** four in `test_segment_consumer.py`: each role reads its own queue; the live
  consumer stores live frames and leaves five waiting file messages untouched; the file
  consumer does not take live frames; ack after commit on the live queue. `start()` takes a
  `queue` argument for these
- **Docs:** D-13 in `decisions.md`; K-1 moved to *Fixed* in `known-issues.md` with the
  numbers; K-11 notes that `verify_definition_of_done.py` now also waits on the wrong queue;
  the K-10 item about the measuring scripts narrowed to `measure_concurrent_feeds.py`; NFR-1
  scoreboard row updated

### A detour

The first test run hung for five minutes and I stopped it: the whole stack had been stopped
since the day before (every container exited), so the tests were waiting on a database that
was not there. `docker compose up -d` started everything, including the new
`consumer-live`, and the suite then passed. No data was involved; the scratch database had
not been created.

### Verification performed

- **Stack:** both consumers log their role on start: `files` on `omnisight.segments` with
  camera events, `live` on `omnisight.segments.live` without. `rabbitmqctl list_queues`: both
  queues durable, one consumer each, plus their dead-letter queues
- **`uv run pytest`: 316 passed** (312 before), against a scratch database
  (`omni502_scratch`, dropped afterwards). `ruff` clean on the files touched (apart from the
  known `B008`)
- **`measure_capture_latency.py --camera cam01 --loops 5 --runs AB`, two runs:**
  - live + the 1,930-frame file: worst live frame **147 ms and 373 ms** (was 6.14 s); file
    queue peak 330 and 306, live queue peak 0 at every 200 ms sample; the file extracted in
    full both times (1,930 of 1,930, 47.5 and 50.5 s)
  - live alone: worst 472 ms and 106 ms
  - TC-1 first-half checks: 0 violations, files equal rows, for the file and for live
- Everything the script created was removed (it deletes the video through the API and the
  camera rows directly)

### Not verified

- More than one camera with the file (OMNI-509 measures ten feeds)
- `cam05` against the file; only `cam01` was run, as in OMNI-316's 1,930-frame row
- A kill of `consumer-live` or a broker restart during live capture on the real stack;
  ack-after-commit on the live queue is tested against the real broker, not killed live
- Why live alone in run 1 had a p95 of 298 ms when run 2 had 31 ms. Live alone is also
  slower than OMNI-316's 28-49 ms, which fits storing about 12 frames a second instead of
  about 4, but that was not isolated

### Result

K-1 is fixed: with the longest file OMNI-316 used extracting, live frames are stored in
under 0.4 s, and NFR-1's first half passes with a recording extracting. Preliminary: one
machine, one camera, two runs.

---

## OMNI-503 · Preview endpoint: the current frame, cheap to poll

Done 2026-10-01, on `slice-05-camera-wall`. Numbers in `docs/results.md` (OMNI-503); the
design is D-14 in `docs/decisions.md`.

### Why this ticket exists

FR-9: a wall of sixteen tiles must not be sixteen video streams. A tile needs the current
frame about once a second, as one small JPEG, and an unchanged frame should cost almost
nothing.

### What was done

- **`services/ingestion/app/preview.py`, new:** `PreviewWriter` scales a frame so its longest
  side is at most 640 px (never up), encodes it as JPEG, writes it to `camera-{id}.jpg.tmp`
  and renames it over `camera-{id}.jpg` (`os.replace`); `clear()` removes both.
  `preview_path()` is the one place the file name is decided
- **The worker** (`live_capture.py`) takes an optional `preview` and `preview_interval_s`. On
  the capture thread, right after a frame is decoded and before it is queued or gated, it
  writes the preview if one is due (at most every 0.5 s). Admitted or not, dropped or not:
  the preview is the stream's picture. A failed write is counted (`preview_errors`), logged
  once per stretch of failures, and capture carries on. The preview is cleared in the capture
  thread's `finally`, so a stopped or failed worker leaves no file. The snapshot gained
  `previews_written`, `preview_errors`, `last_preview_at`
- **Settings:** `previews_path` (`/data/previews`) in the shared settings, since ingestion
  writes and query reads it; `LIVE_PREVIEW_INTERVAL_S` (0.5), `LIVE_PREVIEW_MAX_SIDE_PX`
  (640) and `LIVE_PREVIEW_JPEG_QUALITY` (70) in ingestion. The quality is my choice; the
  ticket did not give one
- **Volume `preview_storage`:** read-write in ingestion, read-only in query, not mounted in
  nginx
- **`GET /cameras/{id}/preview`** in `cameras.py`, operator or admin like the camera's frames
  and stats. Opens the file, takes the ETag from the open file's write time (nanoseconds),
  answers 304 with no body when `If-None-Match` carries it, otherwise the JPEG with `ETag`,
  `Cache-Control: no-cache` and `Last-Modified`. 404 with the reason when the camera does not
  exist, is not being captured, or has no preview yet. "Being captured" is the same rule
  the stats endpoint already used (a session that has not said it stopped, and a report
  within `CAMERA_STATS_STALE_S`); I moved it into `_is_capturing()` so both share it. The
  check matters for a worker that was killed: its file is never cleared, and without the
  check the last frame would be served as current until the next start
- **Tests:** nine in query (200 with the headers; 401 without a token and with a bad one, 403
  for an analyst; 304 with no body on the same ETag; a new frame gives a new ETag and a 200;
  404 for no preview, for a stopped camera with a file left behind, for a worker gone quiet,
  for a camera never captured, and for a missing camera), thirteen in ingestion
  (`test_preview.py`: the size cap both ways, no upscaling, one file and no leftovers, a
  reader never sees half a file, clear; the worker writes at most every 0.5 s and as often as
  that allows, keeps its pace when half the frames are discarded, clears on stop and on a
  failed start, survives a failing write, works without a preview)
- **`scripts/measure_preview_polling.py`, new:** the acceptance measurement

### Things that went wrong on the way

- **I emptied `test_camera_capture.py` for a minute.** The helper script I used to append the
  new tests opened the file for writing with Windows' default encoding (cp1255), which
  truncated it and then failed to encode. I restored it from the last commit with `git show`
  (read-only), checked `git diff` showed only additions afterwards, and redid the edit with
  UTF-8. A second slip in the same helper turned the `\xff` escapes in the test JPEG bytes
  into literal characters; ruff caught it as a syntax error and I put the escapes back. I
  also checked the files earlier helpers had edited: all still valid UTF-8, unchanged
  apart from the intended edits
- **The "reader never sees half a file" test fails on Windows**, because Windows refuses to
  rename over a file another handle has open. The service runs on Linux, so the test is
  skipped on Windows with that reason, and I ran the same check in the ingestion container:
  2,000 reads during 552 rewrites, 0 torn

### Something the ticket did not anticipate (K-12)

With the ETag taken from the write time and the preview rewritten every 0.5 s, a tile
polling once a second on a live feed always gets a new JPEG: 960 of 960 polls were 200. 304s
come only when no new frame is written (the simulator paused: 432 of 480). The ticket's
"unchanged frames cost a 304" holds, but OMNI-506's acceptance, "mostly 304s on still
scenes", cannot: a still scene is still rewritten. OMNI-504 (`last_frame_at` is the preview's
write time) and OMNI-507 (the live indicator follows the ETag) both need the file rewritten
with every new frame, so I built it as written and recorded the conflict as K-12, with the
recommendation to reword OMNI-506's acceptance to 304s on frozen or lost feeds.

### Verification performed

- **`uv run pytest`: 338 passed, 1 skipped** (the Windows-only skip above), against a scratch
  database (`omni503_scratch`, dropped). `ruff`: nothing beyond the known `B008`
- **Stack:** `docker compose up -d` recreated ingestion and query with the new volume;
  `/data/previews` exists in both, read-only in query
- **Acceptance, two runs, `cam05`, 16 clients through nginx once a second:**
  - live feed: 960 requests, all 200, **387 KiB/s** of JPEGs (24.5 KiB each), response p95
    27-28 ms; query **25.6-27.9%** of a core against 10.7-11.1% capturing without polling
  - frozen feed (simulator paused): **432 of 480 were 304** with 0 bytes of body, 45 KiB/s;
    query 22.1-23.5%, so most of query's cost is the request itself (token, three small
    reads), not the image
  - stop: the next poll was **404 "camera is not being captured"** at once
- Everything the script created was removed and the simulator unpaused

### Not verified

- Sixteen different cameras, and a browser as the client: OMNI-506 and OMNI-509
- Frames larger than the simulator's 320x240, whose previews would be larger
- How old the preview is when served on a healthy feed: at most 0.5 s plus one frame by
  construction, not measured (OMNI-504 uses it as `last_frame_at`)
- What the 48 early 200s in the frozen phase were beyond each client's first poll (3 per
  client in both runs)

### Result

The preview works as the ticket asks: token-checked, ETag, 304 with no body when nothing
new was written, 404 rather than a stale frame when the camera is not being captured. The
cost of sixteen tiles on one camera is recorded. One acceptance in a later ticket (OMNI-506)
needs rewording, K-12.

---

## OMNI-504 · Camera liveness and honest status

Done 2026-10-02, on `slice-05-camera-wall`. Numbers in `docs/results.md` (OMNI-504); the
design is D-15 in `docs/decisions.md`; K-5 is in `known-issues.md` under *Fixed*.

### Why this ticket exists

FR-9: *see immediately which feeds are healthy.* A camera could read `connected` with no
worker behind it after an ingestion restart (K-5), and nothing resumed capture until someone
pressed Start. A stream that stalls without closing was only noticed after the 10 s read
timeout.

### What was done

- **`GET /cameras/live`** (operator or admin), every camera with `camera_id`, `name`,
  `location`, `group_name`, `state` and `last_frame_at`, ordered by group then name. The
  state is worked out per request in `app/live_state.py` from ingestion's worker list (a new
  `list_workers()` client call, 3 s timeout) and the preview file's write time, which is
  `last_frame_at`: `live` (worker reading, frame at most 3 s old), `frozen` (worker reading,
  older frame or none), `offline` (worker reconnecting or still connecting; or capture asked
  for and no worker; or ingestion unreachable), `stopped` (no worker and nothing asked for,
  or the camera disabled). A worker that is reading counts whatever the flag says, so a
  camera started before the flag existed still reads honestly. `LIVE_STALE_AFTER_S` (3.0)
  is a query setting
- **`cameras.capture_enabled`**, migration `d4865a17f560` (false for every existing camera).
  Set by a start that worked (and by a start answered "already running"), cleared by stop,
  disable and delete, always committed *before* ingestion is asked to stop
- **Resume, in query, not ingestion.** The ticket says ingestion resumes capture on startup.
  Ingestion has no database, so it cannot know which cameras were captured. I put the
  resume in query instead (`app/capture_resume.py`, started in query's lifespan): every 5 s
  it reads ingestion's worker list, then the `capture_enabled` cameras, and starts each one
  without a worker through the same start call as the button, each on its own thread. A
  failed start is retried after 5, 10, 20, 40 s, then every 60 s, and marks the camera
  `unreachable`; a successful one marks it `connected`. Workers are read before cameras so a
  stop that has just happened is never undone (the stop clears the flag first). The outcome
  the ticket asks for is the same; how is different, and I recorded it in D-15 with the two
  alternatives I did not take. **This changes how the ticket said it, so Ahmad should know**
- **`cameras.status` is left alone.** It is still the last observed reachability; it is not
  corrected when ingestion restarts. The wall does not read it
- **Tests:** `test_live_state.py`, 23: the rule (each state, the 3 s limit itself, no
  preview, ingestion down, a running worker with the flag off); the endpoint (all four
  states at once with the fields and `last_frame_at`, nothing live while ingestion is down
  even with a fresh preview, disabled reads stopped, order, roles); the flag (set by a start
  that worked, not by one that failed, cleared by stop and by disabling); the resume
  (cameras that were capturing are started again after a "restart", busy ones left alone, a
  failed worker restarted, disabled and not-enabled cameras never, nothing while ingestion is
  down, the retry wait doubles 5, 10, 20, 40 up to 60, a resumed camera reads connected, no
  double start while one is in flight)
- **`scripts/verify_camera_states.py`, new:** the acceptance on the real stack

### What the real stack showed that the tests could not (K-13)

Pausing the simulator gave `frozen` on time, 3.1-3.2 s after the last frame. But the camera
then read `live` again, briefly, at 10.5 s and 20.5 s, and went `offline` only at 30.6 s. A
probe of the worker's counters every 0.5 s showed why: while mediamtx was paused, frames
still arrived, 1 then 9, in step with the 10 s read timeout. They can only be frames from
before the pause, released late; each one rewrote the preview (so `live` for 3 s) and
restarted the read timeout (so `offline` 20 s late). The second run repeated it to a tenth
of a second. The rule is the one the ticket wrote ("a frame arrived in the last 3 s"), and
changing it belongs with OMNI-507 (a frozen picture must not look live), so I recorded it
as K-13 with two fix candidates instead of changing it here.

### Other things on the way

- **Query logged "capture resume check failed" every 5 s** for a few minutes. That was
  between `--reload` picking up the new code and me applying the migration: the column did
  not exist yet. After the migration and a restart of query, no more errors. The log line has
  no traceback in the JSON format, which made it slower to see; not changed
- **The stack was down again** at the start (all containers exited); `docker compose up -d`
- **One full suite run had one failure** in `test_live_capture.py`
  (`test_no_frame_is_lost_or_counted_twice_across_a_reconnection`), a test from OMNI-501
  untouched here. 15 runs alone and four full ingestion runs passed, and the next full run
  passed. Reading the code, the likely cause is a frame grabbed on reconnecting that is not
  counted if the worker stops at that instant. Outside this ticket, so it is K-14, not a fix

### Verification performed

- **`uv run pytest`: 361 passed, 1 skipped** (338 before), against a scratch database
  (`omni504_scratch`, dropped). One earlier full run: 1 failed (K-14), 360 passed
- **Migration `d4865a17f560`:** up, down, up on the scratch database, `alembic check` clean,
  then applied to dev
- **`ruff`:** nothing beyond the known `B008` in the files touched
- **Acceptance, two runs, 12 of 12 checks each** (`verify_camera_states.py`, polls every
  0.25 s through nginx):
  - running: `live` on every poll, newest frame 0.21-0.26 s old at the median, 0.47-0.51 s at
    most
  - paused: `frozen` 3.1-3.2 s after the last frame; `offline` at 30.6-30.8 s (K-13)
  - unpaused: `live` again by itself after 15.6 s
  - `restart ingestion`: only `offline` from the command returning until `live` again
    13.5-13.6 s later, worker `running`; `kill` then `start`: the same, 12.3-12.5 s
  - stop: `stopped` at once, and not resumed 8 s later
- Dev database afterwards: the throwaway users, cameras and frames removed

### Not verified

- Several cameras resuming at once (they start in parallel; not measured)
- A camera whose stream is down when it is due to resume: the backoff is unit-tested only
- A restart of query itself (the same check runs at its start; not run live)
- A real network stall instead of `docker compose pause` (K-13 may or may not apply)
- The camera wall itself (OMNI-506, OMNI-507)

### Result

The wall can ask what every camera is doing and get an answer from evidence: `live`,
`frozen`, `offline`, `stopped`. Capture resumes by itself after ingestion restarts or is
killed, and no camera reads `live` without a worker. K-5 is fixed. Two things for Ahmad:
the resume lives in query, not ingestion (D-15), and a paused stream comes back as `live`
for a moment at each read timeout (K-13).

---

## OMNI-505 · Rewind buffer

Done 2026-10-02, on `slice-05-camera-wall`. Numbers in `docs/results.md` (OMNI-505); the data
model note is D-16 in `docs/decisions.md`.

### Why this ticket exists

*Rewind a feed a few minutes to see what led up to something.* The ticket's point is that
nothing new needs storing: a live camera already keeps every admitted frame (OMNI-501), and
the heartbeat guarantees at least one a second, so the last few minutes are already on
disk.

### What was done

- **`GET /cameras/{id}/buffer?minutes=N`** (operator or admin; N 1-10, default 5; anything
  else is a 422): the camera's live frames (`video_id` null) that are admitted and have a
  frame and a thumbnail, captured between now minus N minutes and now, oldest first. Each
  has `segment_id`, `timestamp_s`, `reason` (motion or heartbeat), `thumb_url` and
  `frame_url`. A recording made from the camera is not in it. The query runs on the existing
  index on `(camera_id, timestamp_s)` for live rows. No paging: ten minutes is the most, and
  the ticket did not ask for it
- **`frame_url` needed a route.** Full frames are deliberately not served by nginx (only
  thumbnails are, OMNI-307), and the ticket asks for a `frame_url`. Rather than add a static
  route without a token (K-3 would grow), I added
  `GET /cameras/{id}/frames/{segment_id}/image`, token-checked, which serves the frame file
  only if the row is this camera's, live, admitted, and its path is inside the frames
  folder; otherwise 404. Frames never change, so it sends `Cache-Control: private,
  max-age=86400`. This route is my addition to make `frame_url` usable; the ticket only
  named the field
- **D-16** in `decisions.md`: the rewind buffer is the stored admitted frames, on disk, not a
  separate buffer; a flip-book of stills at the gate's pace, not video
- **Tests:** `test_rewind_buffer.py`, 11: the 5-minute window and its order (frames just
  inside kept, 310 s and 900 s old left out), `minutes` setting the window, `minutes` limited
  to 1-10, only this camera's admitted live frames (not another camera's, not a discarded
  row, not a recording's), the fields and URLs, empty, missing camera, roles; and for the
  image route: the full frame with the token, 401/403 without, 404 for another camera's frame
  or a missing file, and a path outside the frames folder never served
- **`scripts/verify_rewind_buffer.py`, new:** the acceptance

### Verification performed

- **`uv run pytest`: 372 passed, 1 skipped** (361 before), against a scratch database
  (`omni505_scratch`, dropped). No migration in this ticket. `ruff` clean apart from the
  known `B008`
- **Acceptance, real stack, `cam05`, 300 s of capture, 12 of 12 checks:** the 5-minute buffer
  returned **957 frames** (772 motion, 185 heartbeat), oldest first, the oldest 300.0 s before
  the request, none outside the window, every frame with a reason, at most 1.07 s between two
  frames; 166 KiB in 36 ms. One minute: 190 frames. `frame_url`: 20 of 20 sampled served the
  full JPEG with the token, 401 without
- Everything the script created was removed

### Not verified

- A camera in constant motion over the full ten minutes (about 7,000 frames, about 1.2 MB
  of JSON, extrapolated)
- More than one run
- The scrubber that will use it (OMNI-508)

### Result

The rewind buffer works from what is already stored: after five minutes of capture it held
957 frames, oldest first, none outside the window, each with its reason and a token-checked
full frame. One addition beyond the ticket's words: the image route behind `frame_url`.
