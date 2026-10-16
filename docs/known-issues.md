# Known issues

Problems found and not fixed, with the evidence and when each has to be dealt with. When
one is fixed, move it to the bottom with the date and the result that shows it.

| # | Issue | Affects | Found | Must be dealt with by |
|---|---|---|---|---|
| K-3 | `/thumbs/` and `/media/` served without a token | NFR-7 | OMNI-307/308 | Before the demo |
| K-4 | Gate cannot tell camera motion from scene motion | FR-1b, SM-2/SM-3 on CCD | OMNI-318 | Slice 7 (moved 2026-10-09: when kept frames are encoded) |
| K-6 | Re-gate takes 1.4-2.0 s, grows with length | OMNI-310 target | OMNI-310 | When long recordings are used |
| K-7 | Publishing costs 12-15 ms per frame | Upload throughput, K-1 | OMNI-311 | With K-1 |
| K-8 | Storage grows about 7.7 GB per camera per day, nothing prunes | Disk | OMNI-312 | Slice 16 (retention) |
| K-9 | Failure cases not tested | NFR-5 | OMNI-311/313/319 | Before the final NFR-5 claim |
| K-10 | Small items | - | various | Any time |
| K-13 | A stalled stream still delivers late bursts of old frames: `offline` after about 30 s, not 10, and the frame age shown is too young (the flicker back to `live` is fixed, D-17) | FR-9 (honest tile state) | OMNI-504 | Before the demo (moved 2026-10-04: not dealt with in slice 5) |
| K-14 | A live capture test fails now and then: a frame read on reconnecting is not counted if the worker stops at that instant | Test suite reliability | OMNI-504 | Any time |
| K-16 | Ten camera starts at once: five fail with "timeout" | Resume after a restart (D-15), starting a wall | OMNI-506 | When it is seen again (not reproduced 2026-10-04) |
| K-17 | The wall's layout went back to 3x3 by itself, without a reload | FR-9 (the wall), OMNI-512 | OMNI-509 | When it is seen again (hidden by OMNI-512, cause unknown) |
| K-19 | A test run left a live worker running in ingestion for a camera that no longer exists | CPU for everything else (the dataset load), test isolation | OMNI-608 | Any time |
| K-20 | UCA-timed UCF-Crime windows are wrong twice as often as official ones, mostly by containing the event | SM-2, SM-4 (the surveillance forecaster's training data) | OMNI-609 | Slice 9, before training |
| K-21 | About 1.05 GB of frame and thumbnail files on disk have no segment row, so the dashboard's storage does not count them; playback copies (22.7 MB) are not counted either | FR-9 (storage in use), K-8 | OMNI-610 | Slice 16 (retention) |

---

## K-3 · Static routes without a token (NFR-7)

`GET /thumbs/...jpg` and `GET /media/..._playback.mp4` return 200 with no `Authorization`
header. Thumbnail paths are predictable (`/thumbs/{video_id}/{frame_index:06d}.jpg`);
`/media/` exposes whole recordings. Every API route enforces the token (TC-10).
**Fix candidates:** nginx `auth_request` to `query`, or signed short-lived URLs.

## K-4 · Camera motion looks like scene motion

On daylight dash-cam footage (CCD crash) the gate keeps 57%; four clips keep every scoreable
frame. Raising the threshold cuts fixed-camera activity too, so it is not a fix. A design
question for Algorithm 1 (e.g. compensating for global motion) before CCD is loaded at
scale.
**2026-10-09 (OMNI-608):** 67.6% kept on the 30 CCD clips of the hand-check sample (1,014 of
1,500). CCD is no longer loaded at scale (D-26); the full 4,500-clip number is measured on
Colab with the same gate code, in slice 7, where each kept frame starts costing an
embedding. Algorithm 1 stays as written.

## K-6 · Re-gate latency

1.4-2.0 s on a 10 s, 30 fps clip against "about a second"; decode 0.22 s, scoring 0.83 s
(blur 0.57 s). Every re-gate recomputes the threshold-independent part (blur, diff,
per-cell means). **Fix candidate:** store the per-cell means once at extraction, so a
re-gate is a comparison, not a decode.

## K-7 · Publish cost

One confirm per message: 3.5-4.4 s for 300 frames, 21.8-27.0 s for 1,800; a 10-minute 30 fps
recording would take about 4 minutes (extrapolated). **Fix candidate:** asynchronous or
batched confirms.

## K-8 · Storage growth

24.2 KB per admitted frame at 320x240: about 7.7 GB per camera per day in constant motion,
2.1 GB for a static scene; real cameras are larger. Nothing prunes until slice 16.
**2026-09-30 (OMNI-501):** those figures are from 0.2 s sampling (at most about 4.2 stored
frames/s). Every frame is now gated, so a scene in constant motion can store up to the
feed's own rate (15/s on the simulator), about 3.5 times as much; `cam05` stored 3.1-3.3/s.
Not measured per day.

## K-9 · Failure cases not tested

- A stream that stalls without closing (should take the 10 s read timeout)
- Several cameras dropping at once (what the jitter is for)
- A broker restart during live capture: the worker reconnects to the camera, **not to the
  broker**
- Ingestion crashing part-way through publishing a file; query crashing while an
  extraction waits
- A kill between a JPEG write and the broker's confirm (by construction, not by test)
- A broker freeze longer than the 30 s heartbeat

## K-10 · Small items

- The video archive table wraps Size and Uploaded onto several lines with long names (VIRAT)
  at 1114 px and gets a horizontal scrollbar
- Starting cameras is sequential, about 3.9 s each (37-42 s for ten)
- The playback transcode runs inside the upload request with a 150 s timeout never measured
  against a long recording
- The frontend dev server on port 3000 cannot serve `/media/`; use nginx at
  `https://localhost`
- `scripts/measure_concurrent_feeds.py` still speaks of sampled frames and reads only the
  file queue's depth; to be brought up to date when it is rerun (OMNI-509).
  `measure_capture_latency.py` was updated in OMNI-502, apart from its TC-1 live line, which
  says "frames gated" for what are stored (admitted) rows
- The camera screen does not show the new gate counters (`gated`, `admitted`, `discarded`);
  they are in `GET /cameras/{id}/stats` only
- The frontend dev server in Docker does not see file changes on this Windows machine (a new
  page folder answered 404, an edited component stayed old) until `docker compose restart
  frontend` (OMNI-506)
- A wall in a hidden Chrome window (minimised or covered) stops polling, as designed, so a
  measurement "with the wall open" needs the window visible; the NFR-4 runs now record the
  tab's visibility every second (2026-10-03)
- nginx resolves `query` and `frontend` once, when it starts. Restarting them together can
  swap their container addresses, and nginx then answers 502 for everything until it is
  restarted too (`docker compose restart nginx`; seen 2026-10-02, OMNI-507)

---

## K-13 · A stalled stream delivers late bursts of old frames

With the simulator paused (`docker compose pause mediamtx`) the worker kept receiving frames:
1 about 13 s after the pause command and 9 about 23 s after, then nothing (`GET /workers`,
every 0.5 s; the pause command itself took 3.5 s). They arrive in step with the 10 s read
timeout: in both acceptance runs the camera read `live` again at 10.5-10.6 s and 20.5-20.6 s
after the pause and went `offline` at 30.6-30.8 s, instead of about 10 s. They can only be
frames from before the pause (the source is frozen), released late; why exactly at the
timeouts (OpenCV/FFmpeg flushing buffered data when the read is interrupted is the likely
reading) is not established. The worker stamps a frame when it arrives, so each burst
rewrites the preview and the camera reads `live` for about 3 s. `frozen` itself came on time
(3.1-3.2 s after the last frame). The state follows the rule as the ticket wrote it ("a
frame arrived in the last 3 s"). Seen with `docker compose pause`; a real network stall may
or may not behave the same, not tested.
**Fix candidates:** leave `frozen` only after frames arrive steadily again (for example at
least a second's worth within a second), not on one frame; or stamp a frame with the
stream's own timestamp instead of its arrival time, so late frames read as old.

**2026-10-02 (OMNI-507, D-17), half fixed:** `live` now needs frames arriving steadily, so a
burst no longer reads as live: paused, the camera read `frozen` at 2.4 s and nothing else
until `offline`, and on the wall nine tiles went Live, Frozen, Offline with no Live between.
**Still open:** `offline` still comes about 30 s after the pause, not about 10 s, because
each burst restarts the read timeout; and the age a tile shows ("last frame 11 s ago") counts
from when the late frames *arrived*, not from when they were captured, so it understates how
old the picture is. Both are the second fix candidate above (stamp frames by the stream's own
time, or treat a worker that is not receiving for a read timeout as lost).

## K-14 · A live capture test fails now and then

`test_no_frame_is_lost_or_counted_twice_across_a_reconnection` failed once in a full run
(2026-10-02) and passed 15 times alone and in four full ingestion runs. Likely cause, read
from the code, not reproduced: `_open_stream` grabs a frame to prove the stream works and
leaves it pending; if the worker is stopped before the read loop counts it, `grabbed` ends
one below what the stream delivered, which is what the test compares. The frame is a
fraction of a second's worth at a moment the camera is being stopped anyway.
**Fix candidate:** count the pending frame in `grabbed` where it is grabbed.
**2026-10-09 (OMNI-608):** two other tests in the same file failed once in a full run,
`test_dropping_is_logged_once_per_stretch_and_summarised_not_once_per_frame` and
`test_a_continuing_stretch_of_drops_is_summarised_again_after_the_interval` (the drop
summary log line not seen yet: `assert 0 == 1`); the file passed 53 of 53 on three reruns.
**Corrected 2026-10-10 (OMNI-609): not timing.** They failed in every full run since OMNI-608
and passed alone: OMNI-608's `services/query/tests/conftest.py` ran alembic with the ini file,
and `env.py`'s `fileConfig` disabled every logger already created, `app.live_capture` among
them. Fixed by running alembic without the ini file; full suite 442 passed. Only the first
K-14 test above is the intermittent one.
**2026-10-16 (slice 6 merge):** it failed again in the full run on `master` after the merge,
`assert 75 == 76`, one below as described: 469 passed, 1 failed, 1 skipped. Passed 5 of 5
alone straight after. Second failure in about two weeks of full runs; still not fixed.

## K-21 · Files on disk that no row accounts for

2026-10-11, during OMNI-610. `storage_gb` sums the videos' `size_bytes` and the frame bytes
of the rows in `segments` (D-28). On the dev stack the rows account for 0.99 GB of frames
and thumbnails, the volumes hold 2.04 GB. The difference is three directories with no row:
`camera-2035` (682 MB frames, 52 MB thumbnails, last written 2026-10-08) and `camera-2291`
(294 MB, 22 MB, 2026-10-09: K-19's stray worker), both cameras deleted, and video `2001`
(1.6 MB, 2026-09-24), deleted. Their rows went (hand cleanups of test runs, a stray
worker's camera removed) but their files did not. Separately, the 30 playback copies
(OMNI-308, 22.7 MB) have no size on the video row, so they are not counted either.
**Fix candidates:** delete the three orphan directories now (by hand, once Ahmad agrees);
have slice 16's retention job remove directories that no row points at; record a playback
copy's size on the video row.

## K-20 · UCA-timed lead-up windows often contain the event

The hand check (OMNI-609, `results.md`) found 5 of 15 UCA-timed UCF-Crime windows wrong
against 2 of 15 official ones; 5 of the 7 Wrongs *end too late* (the event is visible
inside the window: Arrest011, Robbery006, Stealing043 among the UCA ones). The D-21 rule
takes the earliest UCA sentence matching the class's words, and UCA's sentences often
describe the end of an act (police cuffing) or its middle, not its start. UCA times 540 of
the 680 positive UCF-Crime windows, so a forecaster trained on them as they are would partly
learn to recognise events rather than foresee them. The sample is small (intervals overlap:
UCA 42-85% correct, official 62-96%), so the size of the gap is not settled.
**Fix candidates, for slice 9:** train on official-timed windows only, or weight them up;
check more UCA windows by eye before trusting them (the sample code redraws with a new
seed); or move UCA-derived window ends earlier by a margin and measure the effect.

## K-19 · A test run left a live worker capturing for a deleted camera

2026-10-09, during OMNI-608: ingestion's `GET /workers` listed a running worker for camera
2291, started at 12:05 (when the query suite had just run against the dev database), with
38,228 frames grabbed; the `cameras` table was empty. It used about 73% of a core in
ingestion and kept the simulator busy, and it slowed the dataset load's extraction (VIRAT
55 ms per frame with it, 39 without). Stopped by hand with `POST /workers/stop`. Likely
source: a query test that reaches the real ingestion (the resume tests in
`test_live_state.py` start workers through `CaptureResumer`); not confirmed. The query tests
now use their own database (K-18), but they still share the one ingestion service.
**Fix candidates:** stop every worker a test started in its teardown; or have the resumer
stop workers whose camera no longer exists.

## K-17 · The wall's layout went back to 3x3 by itself

During the 10-feed NFR-4 run (2026-10-03) the wall had been set to 4x4 with ten tiles; 19 s
into the window it showed 3x3 again, the default, with the page not reloaded (same
navigation, the in-page recorder still running). Nothing in the app shell remounts the page
on a timer. The state is only in the page's memory, so anything that re-creates the page
component resets it; what did here is not known (the Next.js dev server is the first
suspect). OMNI-512's "remember the layout" would hide it without explaining it.
Not seen again in the 10-minute OMNI-510a run (2026-10-03): 4x4 for all 600 samples.
Since OMNI-512 (2026-10-04) the layout is remembered in the browser, so a reset of the page's
state now comes back at the chosen layout: the symptom is hidden, the cause still unknown.

## K-16 · Ten camera starts at once: five fail with "timeout"

Starting the simulator's ten feeds through `POST /cameras/{id}/start` in parallel
(`scripts/wall_cameras.py up`, 2026-10-02): five started (13.6-23.6 s each), five failed after
15.1-15.2 s with "could not start capture: timeout", which is the reachability check before
a start (`LIVE_PROBE_TIMEOUT_S` = 15 s). Run again (the other five already
running), the five started in 7.7-17.7 s. Starting is slow anyway (K-10: about 3.9 s each, sequentially), and ten
streams opened together take longer. This matters for D-15: after an ingestion restart the
resume check starts every camera at once, so with ten cameras some would fail and come back
only on the retry backoff (5 s, then 10 s ...). Measured once; the cause (ingestion's
probes, mediamtx, or the machine) not isolated.
**Fix candidates:** resume a few cameras at a time; or a longer probe timeout when many
starts are in flight.
**2026-10-03 (OMNI-509):** starting two at a time, every one of eleven runs (up to ten
cameras each) started without a single retry. The resume (D-15) still starts them all at once.
**2026-10-04 (OMNI-513, fresh stack):** not seen. Ten starts in parallel all started on the
first try (3.7-16.4 s); ingestion restarted, then killed and started, with ten capturing:
the resume started all ten at once both times, 0 failed attempts, all `live` again in
19.5-22.3 s (`scripts/verify_resume_all.py`). Left open: seen once, cause never isolated.

---

## Fixed

| # | Issue | Affected | Found | Fixed |
|---|---|---|---|---|
| K-1 | Live latency breaks 5 s while a long file is extracted | NFR-1 | OMNI-316 | OMNI-502, 2026-10-01 |
| K-5 | After an ingestion restart, workers do not resume and the camera still reads `connected` | FR-1a | OMNI-312, OMNI-319 | OMNI-504, 2026-10-02 |
| K-15 | The simulator's frame size was written as 320x240; the clips are 640x360 | Stated conditions | 2026-10-02 | OMNI-509, 2026-10-03 |
| K-2 | 10 concurrent feeds not sustained | NFR-4 | OMNI-317 | Resolved by revising NFR-4 to 3 per machine (D-19), 2026-10-03 |
| K-11 | The restart loss check read index gaps as lost frames, and waited for the wrong queue | NFR-5 (the mid-capture check) | OMNI-501 | OMNI-601, 2026-10-07 |
| K-12 | On a live feed every preview poll is a 200: OMNI-506's "mostly 304s on still scenes" could not hold | OMNI-506 acceptance | OMNI-503 | Fixed (reworded): OMNI-602, 2026-10-07 |
| K-18 | `uv run pytest` deleted every video in the dev database | Loaded datasets (OMNI-608) | OMNI-608 | OMNI-608, 2026-10-09 |

### K-18 · The test suite deleted every video in the dev database · fixed 2026-10-09

Five query test files clean up with `session.query(Video).delete()` (or a camera delete
that cascades): `test_video_upload.py`, `test_video_probe.py`, `test_video_retention.py`,
`test_video_playback.py`, `test_camera_crud.py`. They run against the database in `.env`,
the same one the stack uses. Until slice 6 that held only throwaway uploads; once
OMNI-608 loads 5,065 dataset videos (hours of extraction), one `uv run pytest` deletes
their rows and segments (cascade) and unlinks `dataset_manifest.video_id` (SET NULL),
leaving the files orphaned in the volumes. Found reading the tests, not by losing data.
**Fix candidates:** run the suite against its own database (`POSTGRES_DB=omnisight_test`,
created and migrated once); or have each test delete only the rows it created.
**Fixed 2026-10-09 (OMNI-608, D-25):** `services/query/tests/conftest.py` points the tests at
`omnisight_test` before the app is imported, creates it if missing and migrates it to head.
Full query suite: 260 passed; the dev database kept its 3 users and 6,675 manifest rows.

### K-1 · Live latency breaks 5 s while a long file is extracted · fixed 2026-10-01

**Was:** live alone, worst frame 49 ms. With a 1,158-frame file extracting: 4.67-4.91 s.
With a 1,930-frame file: **6.14 s**. Live frames and the file's segments shared one queue
and one consumer; extraction publishes its frames in one burst (queue peak 323-544) and live
frames waited behind it.
**Fix (OMNI-502, D-13):** live frames on their own queue, `omnisight.segments.live`, read by
a consumer of their own, `consumer-live`.
**Result:** with the 1,930-frame file extracting, worst live frame **147 ms and 373 ms** in
two runs; the file queue peaked at 306-330 and the live queue at 0 (`results.md`, OMNI-502).
One camera; ten feeds are OMNI-509.

### K-5 · Workers are not resumed after a restart · fixed 2026-10-02

**Was:** after `docker compose restart ingestion` or a kill, `GET /workers` was empty and the
camera still read `connected` with nobody capturing, until capture was started again. No
data was lost (OMNI-319); the status was wrong.
**Fix (OMNI-504, D-15):** `cameras.capture_enabled`, and a check in query every 5 s that
starts every camera with it set and no worker; the wall's state comes from evidence (the
worker list and the newest frame), so a camera with no worker never reads `live`.
**Result (two runs):** `restart ingestion`: offline from the first poll after the command
returned, `live` again 13.5-13.6 s later, worker running; `kill` then `start`: the same,
12.3-12.5 s; no `live` reading in between (35 polls each time). `cameras.status` itself is still the last observed
reachability and is not corrected by a restart; the wall does not read it.

### K-15 · The simulator's frame size was wrong in the results · fixed 2026-10-03

The simulator's synthetic clips are 640x360, not 320x240 as `results.md` said in ten places
(OMNI-312, 316, 317, 501 to 505) and the context notes in two. Each place now carries
"[corrected 2026-10-03: the simulator's clips are 640x360, K-15]" beside the old figure,
not a silent rewrite. No measured number changes; the stated conditions do. Since OMNI-509 the
default simulator clips are real footage (`mediamtx.real.yml`), stated with their sizes.

### K-2 · 10 concurrent feeds not sustained · resolved 2026-10-03 by revising NFR-4

**Since 2026-10-03 (OMNI-509), gating every frame:** 1 feed sustained, HD or SD; 2 HD feeds
drop about 1% of their frames; 10 realistic feeds drop most of theirs (8,412-12,298 each in
10 minutes) and the worst frame takes 6.65 s. The live queue stays empty in every run: storage
keeps up. Frames are lost before the gate, in the worker's queue: ingestion gates 4.2 of 24
HD frames a second and 7-11 of 30 SD frames with ten feeds, spending 3.6-4.1 cores on about
1.9 cores of measured work (`results.md`, OMNI-509). Ingestion is one Python process with
196 threads at ten feeds.
**Fix candidates, none tried:** cap OpenCV/FFmpeg's decoder threads per stream (one or two
instead of a pool each); run the camera workers in several processes instead of one (Python's
interpreter lock); compute the 8x8 grid's cell means in one array operation instead of 64
(the same arithmetic, less Python per frame); more machines. Not candidates: skipping frames
before the gate (Algorithm 1, D-9); batching the consumer's commits (OMNI-510; the consumer is
idle).

**2026-10-03 (OMNI-510a, D-18):** with a process per camera and one thread per decoder
and per OpenCV call, ten realistic feeds gate 157 frames a second with the wall open (was
80.5) and the worst frame takes 3.87 s (was 6.65), but every feed still drops frames and
the containers use 821% of the 800% Docker has: this 4-core laptop is now the limit. Left:
the vectorised grid (less CPU per frame), and hardware with more cores; neither tried.
OMNI-510 (consumer batching) stays unneeded: the live queue peaked at 8 and did not grow.

**Before (OMNI-317, 2026-09-26, sampling every 0.2 s, superseded):** At 0.2 s sampling: 8 feeds sustained, 9 unreliable, 10 backs up within a minute (max
12-12.6 s), drops start at 15. Ceiling is total CPU on one machine: the full stack stores
50-56 frames/s, ten feeds offer about 42. At 0.5 s sampling ten feeds are sustained (worst
1.7 s). Tied to D-9 (the sampling interval is an open deviation). K-1 makes the margin at
eight smaller.
**2026-09-30 (OMNI-501):** sampling is removed and live cameras store admitted frames only,
so these numbers describe a load that no longer exists. One camera gates 15 frames/s at
36-39% of one core in ingestion; several feeds at once are not measured yet (OMNI-509).
**Fix candidates, most measured first:** a longer sampling interval (measured); batched
consumer commits (unmeasured); a separate live queue (K-1); services off the one machine.

**Resolution (2026-10-03, D-19, D-20):** not fixed, revised. With the buffer back to about 2 s
(D-20), this machine sustains 3 realistic feeds over 10 minutes with the wall open; 4 hold for
3 minutes, not 10. NFR-4 now reads 3 live feeds per machine of this class (D-19). The
vectorised grid was not tried; it could raise the number, and stays a candidate.

**2026-10-16 (OMNI-613):** the vectorised grid tried: identical scores, the gate 1.4-1.8 ms a
frame cheaper, 4 feeds over 10 minutes with no frame dropped, but one feed 2 s not `live`, so
still 3 sustained (`results.md`, OMNI-613). No software candidate is left untried.

### K-11 · The restart loss check no longer fitted live rows · fixed 2026-10-07

**Was:** `scripts/verify_definition_of_done.py` (OMNI-319) counted a gap in a session's frame
indexes as a lost frame. Since OMNI-501 a live camera stores admitted frames only, so gaps are
normal; and it waited for the file queue while live frames are on `omnisight.segments.live`
(OMNI-502).
**Fix (OMNI-601):** for live sessions the gap check is gone. Loss is a row without its file,
or fewer stored rows than the worker reported admitted, per session (the highest
`camera_stats` report seen while it ran) and per camera (the lifetime counters). It waits for
the file, live and camera queues to drain. The consumer cases now stop and kill
`consumer-live`. A self-test feeds the detector a missing row, a missing file and a short
count (each flagged) and a capture with gaps (not flagged).
**Result:** two runs (`cam02`, `cam05`), 32 of 32 checks each, 0 frames lost in all four
cases (`results.md`, OMNI-601).

### K-12 · Preview polls on a live feed are never 304 · fixed (reworded) 2026-10-07

**Was:** the preview's ETag is its write time (OMNI-503 as specified) and a live worker
rewrites it every 0.5 s, so every poll of a live feed was a 200 (960 of 960 on `cam05`,
about 387 KiB/s for 16 tiles); 304s came only while the simulator was paused (432 of 480).
OMNI-506's acceptance asked for "mostly 304s on still scenes".
**Fix (OMNI-602, Ahmad's decision):** no code change. OMNI-506's acceptance reworded to
"304s when a feed is frozen or lost; a live feed gets a new frame on every poll by design
(D-14)". OMNI-504 and OMNI-507 need the ETag to change with every new frame.
**Result:** the wall's scoreboard row reads **Pass**; the bandwidth stays as measured
(24.5 KiB per tile per second on `cam05`).
