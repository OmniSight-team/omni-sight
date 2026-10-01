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
