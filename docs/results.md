# Results

Every measurement, dated, with the conditions it was taken under and what it does not
cover. Why something was built the way it was is in `decisions.md`; problems still open
are in `known-issues.md`; how the work went is in `context/`.

## Scoreboard

| Requirement | Target | Measured | Status | Date | Entry |
|---|---|---|---|---|---|
| TC-10 | Every protected route: 200 with the right role, 403 with the wrong role, 401 with no, expired or tampered token | 15 of 15 cases on 4 routes | **Pass** | 2026-09-05 | TC-10 |
| NFR-9 | Token expires after 15 min idle; account locks after 5 failed logins | 2 of 2 | **Pass** | 2026-09-05 | NFR-9 |
| NFR-7 | 100% of endpoints reject a request without a valid token | API routes: 100% (TC-10). `/thumbs/` and `/media/`: 0% | **Fail** on the two static routes | 2026-09-24 | OMNI-307/308 |
| NFR-5 | Data lost on failure or crash = 0 | 0 lost in 9 failure cases: restart, down/up, query killed mid-upload, consumer killed, broker recreated, ingestion restarted and killed, consumer stopped and killed mid-capture | **Pass** in the cases tested | 2026-09-12 to 09-26 | NFR-5, OMNI-311, OMNI-319 |
| FR-1a | Accept live camera feeds and uploaded files | Files: one clip per dataset `ready`, metadata equal to `ffprobe`. Live: ~4.1 frames/s stored, recovers by itself after the source is killed | **Pass** | 2026-09-21, 09-26 | OMNI-300, OMNI-312, OMNI-313 |
| FR-1b | Keep the most informative frames by detecting movement | Fixed cameras keep 4.7-19.8%; daylight dash-cam keeps 57%. Live: every frame gated (15.0/s), 20-22% kept on `cam05`, counters balance | **Pass** on fixed cameras, **weak** on moving cameras | 2026-09-26, 09-30 | OMNI-304, OMNI-305, OMNI-318, OMNI-501 |
| FR-3 | Store each segment with time, source and image | Files: a row for every decoded frame. Live: a row for every admitted frame. Image files equal admitted rows in every run | **Pass** | 2026-09-23 to 09-30 | OMNI-304, OMNI-316, OMNI-501 |
| NFR-1, first half | Capture to stored under 5 s (the searchable half comes in slice 7) | Every frame gated, live on its own queue: live alone max 106-472 ms; with a 1,930-frame file extracting max **147-373 ms** (was 6.14 s on one shared queue) | **Pass**, alone and with a long file extracting (preliminary: one camera, two runs) | 2026-10-01 | OMNI-316, OMNI-502 |
| FR-9, the wall's preview (no Phase A target) | 16 tiles polling one camera once a second, cheap; unchanged frames cost a 304 | Live feed: 960 of 960 polls 200, 387 KiB/s, query +15-17% of a core. Frozen feed: 432 of 480 polls 304, 45 KiB/s. Stopped: 404 at once | **Measured**; 304s only on a frozen feed (K-12) | 2026-10-01 | OMNI-503 |
| TC-1, first half | Live camera and uploaded file together for 30 s: both decode, only motion forwarded | 0 decode errors, 0 gate-rule violations | **Pass** | 2026-09-26 | OMNI-316 |
| NFR-4 (preliminary) | 10 concurrent feeds (graded in slice 5) | 8 sustained, 10 not, at 0.2 s sampling; 10 sustained at 0.5 s sampling | **Not met** as configured | 2026-09-26 | OMNI-317 |
| SM-3 | Revised to mean time-to-accident on CCD; target set in slice 6 | - | **Not measured yet** | - | `decisions.md` |
| Slice 2 definition of done | The plan's demo on a wiped stack | 5 of 5 steps, 62 tests | **Pass** | 2026-09-12 | Slice 2 DoD |
| Slices 3-4 definition of done | The plan's demo, plus a worker restart mid-capture | 44 of 44 checks, 304 tests | **Pass** | 2026-09-26 | OMNI-319 |
| Ticket target (OMNI-310) | Re-gate "in about a second" | 1.4-2.0 s on a 10 s, 30 fps clip | **Not met** | 2026-09-25 | OMNI-310 |

**The machine** (stated from OMNI-316 on; earlier entries ran on the same one): Windows 11
Home, Intel Core i7-1165G7 (4 cores, 8 threads), 15.7 GB RAM, Docker Desktop with 8 CPUs
and 7.6 GiB for all containers. Every service, the RTSP simulator and the measuring script
share it.

---

## TC-10 · Authentication and roles on every endpoint · 2026-09-05

**Suite:** `services/query/tests/test_tc10_auth.py`, 15 passed. Real Postgres; two
throwaway accounts (`tc10-admin@`, `tc10-operator@`) created and removed.

**Scope:** every protected route in `query`. `/auth/login` and `/health` are public by
design and out of scope.

| Endpoint | Right role -> 200 | Wrong role -> 403 | No / expired / tampered token -> 401 |
|---|:--:|:--:|:--:|
| `GET /auth/me` | pass | n/a (any authenticated user) | pass |
| `GET /nav` | pass | n/a | pass |
| `POST /auth/logout` | pass | n/a | pass |
| `GET /admin/ping` | pass | pass | pass |

The 401 column is three cases per route: no header; a token with `exp` in the past signed
with the real secret; a valid token with its last character flipped. `/admin/ping` is the
only admin-only route, so the only 403 case.

**Not covered:** the static file routes `/thumbs/` and `/media/`, added later (OMNI-307/308).

## NFR-9 · Idle expiry and lockout · 2026-09-05

**Suite:** `services/query/tests/test_nfr9_lockout_expiry.py`, 2 passed. One throwaway
account, removed afterwards.

| Test | Result |
|---|:--:|
| Five wrong passwords lock the account: `failed_attempts = 5`, `locked_until` in the future (read from the database); a sixth attempt with the **correct** password is still 401 | pass |
| A token signed with the real key but `exp` one minute in the past is 401 on a protected route | pass |

**Not covered:** the 15-minute window in real time; the test uses an already-expired token.

## NFR-5 · Uploads survive restarts and a crash mid-upload · 2026-09-12

Live checks against the running stack, real video, not a pytest suite.

| Check | Result |
|---|:--:|
| `docker compose restart`: row and file survive | pass |
| `docker compose down` + `up -d`: row and file survive | pass |
| `query` killed mid-upload: no orphan row, no partial file | pass |

**Restart and down/up:** a 5 s, 21,086-byte MP4; file checksum and `GET /videos/{id}`
identical before and after (same id, `size_bytes`, `duration_s`). Between `down` and `up`,
`docker compose ps -a` showed zero containers; `postgres_data` and `video_storage` survived.

**Kill mid-upload:** a 480 MB upload (503,316,480 bytes) sent straight to `query`'s port,
killed with `docker kill` at 40% (201,326,632 bytes), triggered by the client's own byte
count; the client got `ConnectionAbortedError`. After restart: zero rows for the file, no
`.part` file. Sent to `query` directly because nginx buffers the whole body before
forwarding it (`proxy_request_buffering on`), so a kill during an upload through nginx
never reaches `query` mid-transfer.

**Not covered:** anything after the upload (frames, queue); see OMNI-311 and OMNI-319.

## Slice 2 definition of done · 2026-09-12

`docker compose down -v` (empty database and storage), `up -d`, `alembic upgrade head`, one
admin and one operator seeded, then the plan's demo.

| Demo step | Result |
|---|:--:|
| Register a camera on the simulator; Test Connection reports resolution and fps | pass: `640x360 @ 15.0 fps`, `connected` |
| An invalid address reports a specific reason | pass: `error: "unreachable"` |
| Upload an MP4: correct duration and size | pass: 7.000 s source, `duration_s: 7.0`; `size_mb: 0.03` matching the file |
| The upload survives a container restart | pass: checksum and record identical |
| An operator cannot delete a camera | pass: `403 {"detail":"insufficient role"}`, camera still present |

`uv run pytest` afterwards: 62 passed.

## OMNI-300 · Dataset clips through the upload path · 2026-09-21

One clip per dataset from the local subset, uploaded through the Video Archive screen; the
stored row compared with `ffprobe` on the source.

| Dataset | Clip | Status | Duration (stored / source) | fps | Resolution | Bytes (stored = source) | Codec |
|---|---|:--:|---|---|---|---|---|
| CCD | `Crash-1500/000413.mp4` | ready | 5.000 / 5.000 s | 10 | 640x360 | 232,123 | MPEG-4 Part 2 |
| UCF-Crime | `Anomaly-Videos-Part-1/Arson/Arson049_x264.mp4` | ready | 12.867 / 12.867 s | 30 | 320x240 | 3,142,046 | H.264 Baseline + AAC + PNG stream |
| VIRAT | `videos_original/VIRAT_S_010208_07_000768_000791.mp4` | ready | 19.232 / 19.232 s | 23.97 | 1280x720 | 1,362,385 | H.264 Main |

**Result:** all three `ready`; duration, fps, size and bytes equal the source. No probe
failures.

**What later slices need:** CCD is MPEG-4 Part 2, which browsers do not play (handled in
OMNI-308 with an H.264 playback copy). VIRAT is 23.97 fps, so frame and window arithmetic
must use the stored `fps`. The local clips are short (5-19 s), not minutes.

**Not covered:** long files, variable-frame-rate files (`duration = frame_count / fps` is
exact here, an estimate for some containers), bulk loading.

## OMNI-303/304 · Algorithm 1 on dataset footage · 2026-09-23

Two dataset clips extracted through the running stack at the defaults: grid 8, cell
threshold 25, 3 active cells, stride Δ 0.5 s, blur kernel 21.

| Clip | Rows (= decoded frames) | Scored (after the 2Δ warm-up) | Admitted | Files on disk |
|---|---|---|---|---|
| CCD `000413.mp4` (5 s, 10 fps) | **50** | 40 | 24 | 24 frames + 24 thumbnails |
| UCF-Crime `Arson049` (12.9 s, 30 fps) | 386 | 356 | 52 | 52 frames + 52 thumbnails |

**Result:** a row for every decoded frame; image files only for admitted frames, equal in
number. A 5 s CCD clip yields 50 gated frames, which the acceptance asked for.

**Superseded first run, same day** (1 s sampling and a 5-sample buffer, removed because
Algorithm 1 has no sampling step): CCD 5 rows, **0 scored**; UCF 13 rows, 8 scored, 5
admitted (scores 31-36 of 64 cells at t = 5-9 s, then 0 at t = 10-12 s).

**Not covered:** VIRAT (not re-run after the rework); a 2-minute clip; a threshold sweep
at dataset scale (see OMNI-318).

## OMNI-305 · Heartbeat admissions · 2026-09-23

Defaults as above, heartbeat 1.0 s.

| Clip | Rows | Admitted | By reason |
|---|---|---|---|
| Static, freshly encoded, 8 s at 10 fps | 80 | 7 | 7 heartbeat, 0 motion |
| CCD `000413.mp4` (5 s, 10 fps) | 50 | **26** | 24 motion, **2 heartbeat** |

**Result:** a clip with no motion still gets one frame a second (t = 1 s to 7 s); CCD gains
2 frames it had no motion admission for.

**Not covered:** a 5-minute static clip (a 300 s scheduling trace in
`services/ingestion/tests/test_heartbeat.py` covers the same property). The 1.0 s default
is untuned.

## OMNI-306 · Re-gating moves the admitted set both ways · 2026-09-23

A CCD clip, extracted, then re-gated twice through `POST /videos/{id}/gate`.

| Step | `min_active_cells` | Admitted | Rows | Same row ids? | Time |
|---|---|---|---|---|---|
| Extraction | 3 (default) | 26 | 50 | - | - |
| Re-gate 1 | 60 | 4 | 50 | yes | 0.3 s |
| Re-gate 2 | 1 | 32 | 50 | yes | - |

**Result:** re-gating admits frames that were discarded before (32 against 26), with no
new rows: ids and `created_at` identical in all three states. Files on disk after the last
run: 32, equal to admitted.

**Not covered:** long recordings (see OMNI-310 for a 30 fps clip).

## OMNI-307/308 · Static routes serve footage without a token · 2026-09-23 and 09-24

Requested with no `Authorization` header, through nginx:

```
GET https://127.0.0.1/thumbs/1479/000030.jpg                                   -> 200 image/jpeg, 8,489 bytes
GET https://127.0.0.1/media/ff810750e6cf4593a973ef7e0a727907_playback.mp4      -> 200 video/mp4
```

**Result:** 0% of requests to `/thumbs/` or `/media/` need a token, against 100% of API
routes (TC-10). Thumbnail paths are predictable (`/thumbs/{video_id}/{frame_index:06d}.jpg`).
NFR-7 fails on these two routes; open in `known-issues.md`.

**Also measured:** the H.264 playback copy for a CCD clip (MPEG-4 Part 2 in, H.264 out,
both confirmed with `ffprobe`) added **0.66 s** to the upload, probe and transcode together,
on a 5 s clip. The transcode runs inside the upload request with a 150 s timeout that has
not been measured against long recordings.

## OMNI-310 · Threshold sweep and re-gate latency · 2026-09-25

One 10 s, 30 fps, 320x240 upload (UCF `Abuse029`, 300 frames), re-gated through the API at
each cell threshold, then a full frames fetch; restored to 25 afterwards.

| Threshold | Admitted | Motion / heartbeat | Gate + frames fetch |
|---|---|---|---|
| 1 | 257 | 257 / 0 | 1.97 s |
| 10 | 165 | 162 / 3 | 2.02 s |
| 25 (default) | 48 | 42 / 6 | 1.59 s |
| 40 | 13 | 4 / 9 | 1.47 s |
| 50, 75, 100 | 9 | 0 / 9 | 1.36-1.63 s |

**Result:** the count falls monotonically as the threshold rises and discarded frames come
back as it falls. From 50 up only the nine heartbeat frames remain, so slider travel above
about 60 changes nothing. On every step the frames endpoint agreed with the gate response.

**Against the ticket's "about a second":** not met, **1.4-2.0 s** (0.3 s on the 5 s,
10 fps CCD clip in OMNI-306). Profiled in the container: decode 0.22 s, motion scoring
0.83 s (0.57 s of it the 21x21 blur), JPEG writes negligible, the rest HTTP and updating
300 rows. In the browser a burst of drags settled in about a second at high thresholds.

**Not covered:** longer or higher-resolution recordings; the cost grows with frame count.

## OMNI-311 · NFR-5 across a consumer kill and a broker recreate, and the queue's cost · 2026-09-25

A synthetic 60 s, 30 fps, 320x240 clip (1,800 frames), every stored frame read back through
`GET /videos/{id}/frames`.

| Scenario | What was done | Outcome |
|---|---|---|
| Consumer killed mid-run | `docker kill` with 402 segments stored | 419 stored when it died, **629 waiting in the queue**, video `extracting`, not `failed`. After restart: **1,800 of 1,800**, frame indexes 0-1799 each once |
| Uninterrupted | same clip | 1,800 stored, **1,360 admitted, identical to the killed run** |
| Broker recreated | consumer stopped, 1,800 queued, `rm -sf` then `up -d` on the broker | **1,800 still queued**; after starting the consumer, **1,800 of 1,800**, none duplicated |

**Result:** no accepted segment lost or stored twice. One clip and three runs, not a soak
test.

**What the durable path costs:** persistent messages, each publish waiting for the broker's
confirm (a disk sync). `/extract/publish` took **3.5-4.4 s for 300 frames** and
**21.8-27.0 s for 1,800**, about 12-15 ms per frame, of which decode and gate are about
3 ms. The 300-frame extraction went from about 2 s to 4.6-5.6 s end to end. A 10-minute
30 fps recording (18,000 frames) would take about 4 minutes to publish (extrapolated, not
measured).

**Not covered:** ingestion crashing part-way through publishing; query crashing while an
extraction waits.

## OMNI-312 · Live capture: rate, start, stop, storage · 2026-09-26

The simulator's `cam01` (15 fps, 320x240 H.264), started and stopped through the API; rows
counted in the database; open streams counted as established TCP connections from
ingestion to port 8554 (`/proc/net/tcp`). Sampling every 0.2 s (default).

| Measurement | Result |
|---|---|
| Rows arriving | growing at every 2.5 s check for 20 s; **about 4.1 rows/s** (88 rows, 75 admitted, after 20 s) |
| Why not 5/s | 0.2 s samples on a 15 fps stream land every third or fourth frame (0.20-0.27 s apart) |
| Newest row's age when read | 0.2 s (one reading, includes polling; the NFR-1 measurement is OMNI-316) |
| Every row | `source_type = camera`, `camera_id` set, `video_id` null, `timestamp_s` = Unix time |
| Stop | **0.0-0.1 s**; rows frozen for the 6 s checked afterwards |
| Streams left open after a stop | **0, in 14 of 14 start/stop cycles** (1 while running) |
| Restart without restarting the service | resumed (89 to 114 rows), into a new folder per start |
| Start time | **about 7 s** (3.8-7.1 s over 6 starts), the simulator's wait for its next keyframe |

**Storage:** **24.2 KB per admitted frame** (16 KB frame + 8 KB thumbnail at 320x240; 98
frames took 2.3 MB). At this clip's ~3.7 admitted frames a second, about **7.7 GB per
camera per day**; a static scene (heartbeat only) about **2.1 GB**. Real cameras' frames
are larger.

**Not covered:** several cameras (OMNI-317), long runs, CPU per camera.

## OMNI-313 · Source killed mid-capture: detection, backoff, recovery · 2026-09-26

`cam01`, `docker compose stop mediamtx` mid-capture, status polled through `GET /cameras`
every 0.05-0.2 s, worker state from `GET /workers`, retry waits from ingestion's log, then
`docker compose start mediamtx`. Outages of 76 s and 25 s. Backoff at defaults: first retry
1 s, doubling, cap 30 s, jitter 20%.

| Measurement | Result |
|---|---|
| Status after the stop | `connected` to `unreachable` **0.4 s** after the stop command (the container took 0.8 s to stop) |
| Rows while down | frozen (53 before, 53 after 26 s, 53 after 76 s) |
| `last_seen_at` | frozen while down; advances while healthy (checked 5 s apart) |
| Retry waits, 76 s outage | **0.95, 2.24, 3.74, 9.42, 17.62, 26.74 s**, 5 failed attempts before one worked |
| Retry waits, 25 s outage | 1.03, 2.32, 3.47 s, 3 failed attempts |
| Recovery, 76 s outage | `connected` **20.5 s** after the simulator started; capture resumed by itself |
| Recovery, 25 s outage | **11.4 s** after the simulator started; +14 rows within a few seconds |
| Integrity across the gap (25 s outage) | no duplicate moments, frame indexes unbroken, one session, **54 thumbnails for 54 admitted rows** |
| After a stop | worker registry empty, 0 open connections |

**Result:** detected within a second, retries backed off as designed, capture resumed with
no action. Recovery time is the next retry wait (up to the 30 s cap), plus the simulator
restarting its feed, plus the first keyframe (about 5-7 s).

**Not covered:** a stream that stalls without closing (would take the 10 s read timeout);
several cameras dropping at once; a broker restart during capture.

## OMNI-314 · Throttling downstream during live capture · 2026-09-26

`cam01` (about 4.2 sampled frames/s). Worker counters (`GET /workers`), broker queue depth
(`rabbitmqctl`) and ingestion memory (`docker stats`) read every few seconds. In-process
queue 10 frames; run 2 set `LIVE_MAX_BACKLOG=40` (default 2,000), reverted afterwards.

**Broker frozen 24 s** (`docker compose pause rabbitmq`)

| | healthy | +4 s | +13 s | +22 s | after release |
|---|---|---|---|---|---|
| dropped | 0 | 9 | 44 | 83 | **107**, then no more |
| published | 84 | 101 | 101 | 101 | +38 every 5 s |
| in-process queue | 0/10 | 10/10 | 10/10 | 10/10 | 0/10 |
| ingestion memory | 186 MiB | 194 | 194 | 194 | 187-188 |

**Consumer paused 40 s** (`docker compose pause consumer`, backlog limit 40)

| | healthy | +4 s | +17 s | +29 s | +43 s | after release |
|---|---|---|---|---|---|---|
| dropped | 0 | 0 | 23 | 74 | 131 | **166**, then no more |
| broker queue | 0 | 31 | 52 | 52 | 52 | 0 within 5 s |
| ingestion memory | 129 MiB | 129 | 129 | 129 | 130 | 130 |

**Result:** drops climbed during the throttle and stopped when it lifted; memory moved 8 MiB
at most; the in-process queue held at 10 and the durable queue at 52 (40 ready + 10
unacknowledged + about a second of lag). The books balanced exactly: captured 404 =
published 297 + dropped 107 + queued 0; captured 512 = published 346 + dropped 166 +
queued 0. `GET /cameras/{id}/stats` agreed on dropped. Capture kept running through both.
107 drops logged **5** warnings, 166 logged **8** (one at the start of a run of drops, then
a summary about every 5 s).

**Healthy:** 0 dropped, `fps_effective` 4.1-4.3, queue empty.

**Not covered:** memory at real resolutions; a broker freeze longer than the 30 s
heartbeat; several cameras. Queue sizes are untuned.

## OMNI-316 · NFR-1 first half and TC-1 first half · 2026-09-26

**Conditions:** one consumer, prefetch 10; live sampling 0.2 s, 10-frame in-process queue;
gate defaults (grid 8, threshold 25, 3 cells, stride 0.5 s, heartbeat 1 s). Live: `cam01`
(15 fps, 320x240 H.264, constant motion); `cam05` for TC-1 (motion and still stretches).
File: `Arson049` (30 fps, 320x240) looped to 38.7 s (1,158 frames) or 64.5 s (1,930),
extracted through `POST /videos/{id}/extract`. 30 s windows after a 6 s warm-up. Host,
Docker VM and database clocks agree within 1 ms (database minus host +1.3 ms and +0.3 ms).
Script: `scripts/measure_capture_latency.py`.

**What is measured:** capture = `segments.timestamp_s` (the worker read the frame); stored
= `segments.created_at` (database time at insert; commit follows within 1-2 ms).
API-visible = first seen by a poller on `GET /cameras/{id}/frames` every 100 ms. Excludes
camera-to-decoder time and the searchable half (slice 7). Every frame counted.

| Scenario | Frames | p50 | p95 | p99 | max | API-visible max | Queue peak |
|---|---|---|---|---|---|---|---|
| Live alone, `cam01`, run 1 | 126 | 9 ms | 18 ms | 41 ms | **49 ms** | 180 ms | not sampled |
| Live alone, `cam01`, run 2 | 125 | 9 ms | 23 ms | 28 ms | **28 ms** | 184 ms | 0 |
| Live + 1,158-frame file, `cam01`, run 1 | 125 | 1,225 ms | 4,646 ms | 4,833 ms | **4,910 ms** | 4,979 ms | not sampled |
| Live + 1,158-frame file, `cam01`, run 2 | 125 | 607 ms | 4,341 ms | 4,640 ms | **4,673 ms** | 4,797 ms | 336 |
| Live + 1,158-frame file, `cam05` | 128 | 258 ms | 3,512 ms | 3,799 ms | **3,977 ms** | 3,869 ms | 323 |
| Live + **1,930-frame file**, `cam01` | 127 | 1,368 ms | 5,956 ms | 6,138 ms | **6,139 ms** | 6,266 ms | 544 |

No drops and no decode errors in any run.

**NFR-1 result:** live alone passes by about a hundred times (worst 49 ms, API-visible
within 0.2 s). With a 1,158-frame file extracting it passes by 0.1-0.3 s; with a
1,930-frame file it **fails at 6.14 s**. Cause: live frames and the file's segments share
one queue and one consumer, first in first out; extraction publishes its frames in one
burst (queue peak 323-544, above 100 for 19-22 s) and live frames wait behind it. 544
messages in about 6 s is roughly 90/s, the same order as OMNI-311's ~10 ms per publish
(arithmetic; the consumer's own rate was not measured here).

**Load, run 1 (100% = one core, average):** ingestion 23% alone, 123% with the file (peak
361%); consumer 3% to 47%; RabbitMQ 47% to 76%; PostgreSQL 3% to 19%. The 1,158-frame
extraction took 24-33 s alongside live capture, against 20.9 s for 1,200 frames on an idle
stack (OMNI-311).

**TC-1, first half:**

| | Decoded without error | Gated | Forwarded | Motion / heartbeat | Discarded |
|---|---|---|---|---|---|
| File, 1,158 frames | yes, `ready`, 1,158 of 1,158 | 1,158 | **209 (18%)** | 182 / 27 | 949 |
| File, 1,930 frames | yes, 1,930 of 1,930 | 1,930 | **357 (18%)** | 312 / 45 | 1,573 |
| Live `cam05` | yes, `running`, 0 decode errors | 227 | **64 (28%)** | 32 / 32 | 163 |
| Live `cam01` | yes | 235-326 | 213-296 (91%) | all motion | 22-30 |

**TC-1 result:** checked from the stored rows, **zero violations** in every run: every
forwarded frame has a reason and a file; every motion admission scored at or above 3 active
cells; no heartbeat admission had motion; no discarded frame has a file or scored at or
above the threshold; JPEG files equal forwarded frames exactly (209, 357, 64, 213, 296).

**Not covered:** whether the rule picks the right frames (OMNI-318); the camera wall
(TC-1's second half, slice 5). `cam01` never stops moving, so it barely exercises the gate.

## OMNI-317 · Several feeds at once (NFR-4, preliminary) · 2026-09-26

**Conditions:** the simulator's ten looping feeds (15 fps, 320x240 H.264; beyond ten the
same feeds are read twice), each sampled every 0.2 s (about 4.2 stored frames/s per
camera), 10-frame in-process queue, backlog limit 2,000, one consumer. Cameras started
four at a time, 8 s to settle before the window. Latency as in OMNI-316. Script:
`scripts/measure_concurrent_feeds.py`. One machine, one scene set, a handful of runs.

| Feeds | Held for | Dropped | Stored per camera | Worst capture to stored | Queue peak | Verdict |
|---|---|---|---|---|---|---|
| 8 | **6 min** | 0 of 12,684 | 4.19/s | p99 1.4 s, **max 1.8 s** | 48 | **sustained** |
| 8 | 3 min | 0 of 6,597 | 4.18/s | p99 0.8 s, max 1.2 s | 23 | sustained |
| 9 | 3 min | 0 of 7,726 | 4.19/s | first 90 s: p99 up to 7.7 s (max 7.9 s); last 90 s: p99 0.6-1.0 s | 282 | **unreliable** |
| 10 | 3 min, three runs | 0 (598 in a run with a heavier CPU sampler) | 4.19/s | max 12.0 s and 12.6 s (68 s with the heavier sampler) | 473-507 | **not sustained** |
| 11 | 3 min | 53 of 9,360 | 3.54/s | p99 45 s | 2,012 | fails |
| 15 | 30 s | 44 of 4,023 (1.1%) | 3.75/s | p99 30.6 s | 1,559 | drops begin |
| 20 | 30 s | 1,264 of 6,219 (20%) | 1.93/s | p99 42.9 s | 2,028 | overloaded |

Every worker stayed `running`, no reconnects, no decode errors.

**Result: 8 feeds sustained, 10 not.** At 8 the queue stays near zero for 6 minutes. At 10
it is fine for 30 s (mean depth 16, p99 1.5 s), then climbs without recovering: mean depth
63, 230, 307, 350, 403 over the next five 30 s slices, p99 12 s by minute three. A 30 s
window hides this (30 s windows gave 10 feeds p99 1.0-1.4 s).

**Where the ceiling comes from:** the consumer alone stores **76-83 frames/s** (3,000
queued frames drained in 36-39 s, one transaction each; 83 cold, 76 after twenty minutes of
load). In the full stack the stored rate stops at **50-56/s** (12 feeds at 4.2, 15 at 3.75).
With 10 feeds the machine's CPU read **92-99%**, processor performance 82-87% of nominal.
Ten feeds offer about 42 frames/s, eight about 34. The limit is total CPU on one machine,
not one service.

**Cost per feed (100% = one core, averages):** ingestion 22% for one feed, 143% for ten,
256% for twenty; memory 203, 388 and 722 MiB (about 20-27 MiB per camera). At ten feeds:
consumer 44%, RabbitMQ 80%, PostgreSQL 12%, query 17%, simulator 22%. RabbitMQ spikes to
230-330% even idle, so its peaks mean nothing. Starting feeds takes about 3.9 s per camera
(27-29 s for 8, 37-42 s for 10, 77 s for 20).

**0.5 s sampling instead of 0.2 s** (1.88 stored frames/s per camera): **10 feeds sustained
for 3 minutes**, 0 dropped of 3,893, queue peak 18, p99 0.1-0.4 s in five of six slices
(1.6 s in one), worst frame 1.7 s. A setting (`LIVE_SAMPLE_INTERVAL_S`), reverted
afterwards.

**How much to trust it:** measuring changes the result at the edge (a PowerShell CPU
sampler turned 10 feeds from 12 s max and 0 drops into 68 s and 598 drops); the headline
numbers for 8-11 feeds and for 0.5 s come from runs without it. Runs at the edge vary.
**Not covered:** more than 6 minutes; separate machines; frames larger than 320x240 (so
this is optimistic); two consumers.

## OMNI-318 · Motion gate retention on dataset footage (preliminary) · 2026-09-26

**Conditions:** the 38 local clips through the real pipeline at the **default parameters,
untouched**: grid 8, threshold 25, 3 cells, stride 0.5 s (first 1 s of each clip is
warm-up), blur 21, heartbeat 1.0 s. Retention = admitted frames / all frames. Clips are
3.5-37 s (CCD 5 s): a small sample, not the datasets' statistics. Script:
`scripts/measure_gate_retention.py`.

| Group (clips) | Camera | Frames | Forwarded | **Retention** | Per clip min / median / max | Motion / heartbeat |
|---|---|---|---|---|---|---|
| CCD crash (10) | dash-cam, daylight, 640x360, 10 fps | 500 | 285 | **57.0%** | 28 / 52 / 80% | 55.0 / 2.0% |
| CCD normal (10) | dash-cam, almost all night, 1280x720, 10 fps | 500 | 52 | **10.4%** | 8 / 8 / 32% | 3.2 / 7.2% |
| UCF-Crime anomaly (10) | fixed CCTV, 320x240, 30 fps | 4,698 | 932 | **19.8%** | 3 / 16 / 88% | 17.6 / 2.3% |
| UCF-Crime normal (5) | fixed CCTV, 320x240, 30 fps | 2,077 | 274 | **13.2%** | 3 / 3 / 60% | 10.4 / 2.8% |
| VIRAT (3) | fixed ground camera, 1280x720, 24 fps | 1,435 | 67 | **4.7%** | 4 / 4 / 6% | 0.8 / 3.9% |

**Result:** on fixed cameras the gate behaves sensibly: quiet scenes fall to the heartbeat
floor (**3% at 30 fps**, 4% at 24, 8% at 10), busy ones keep more (UCF Robbery089 88%,
RoadAccidents027 70%, a busy normal clip 60%). Six of 15 UCF clips and two of three VIRAT
clips never triggered on motion. On daylight dash-cam footage it mostly does not: 6 of 10
crash clips keep half or more, and four (000288, 000289, 000290, 000418) keep 40 of 50,
**every scoreable frame** (median 6-16 active cells of 64), because camera motion looks like
scene motion. The CCD normal clips are night footage, near black; 9 of 10 never trigger on
motion, which says the gate is quiet in the dark, not that it handles a moving camera.

**Exploration, not tuning** (other thresholds, 3 cells, rest default):

| Group | 25 (default) | 50 | 100 |
|---|---|---|---|
| CCD crash | 57.0% | 29.8% | 14.8% |
| CCD normal | 10.4% | 8.0% | 8.0% |
| UCF-Crime anomaly | 19.8% | 9.4% | 4.6% |
| UCF-Crime normal | 13.2% | 9.9% | 6.2% |
| VIRAT | 4.7% | 4.0% | 4.0% |

A higher threshold lowers dash-cam retention but also cuts fixed-camera clips with real
activity, so it does not separate camera motion from subject motion. No setting adopted.

**How much to trust it:** 38 clips chosen by what is on disk, most dash-cam ones 5 s; a
group is dominated by its longest clips (UCF Fighting023 and Arrest013 are nearly half the
anomaly frames); CCD normal is night only; the same 21 px blur is a larger share of a
320x240 frame (effect not measured). **Not covered:** whether the admitted frames contain
the event. No clip is an empty corridor; the nearest are VIRAT and the quiet UCF normal
clips, at the heartbeat floor.

## OMNI-319 · Definition of done for slices 3-4, and a worker restart mid-capture · 2026-09-26

**Conditions:** `docker compose down` (volumes kept), `up -d`, then
`scripts/verify_definition_of_done.py` against the real stack; `cam02` at default sampling
(0.2 s) and gate parameters. **44 of 44 checks passed**, and again on one run against the
stack as it was. Throwaway admin, cameras and videos removed afterwards.

| Definition of done | Result |
|---|---|
| Still then moving: early frames discarded, moving ones admitted | 12 s clip (6 s still, 6 s moving, 15 fps): still part **0 of 90 admitted for motion**, 5 by heartbeat; moving part **90 of 90** |
| Moving the threshold changes the counts | admitted at threshold 5 / 25 / 100 / 200: **95 / 95 / 11 / 11** |
| Clicking a thumbnail seeks the player | by script: thumbnail is `image/jpeg`, its moment is inside the recording, the playback stream answers a range request with 206. In the browser on the fresh stack: clicking the 0:07.4 tile put the player at 7.366666 s, that frame's timestamp (through nginx at `https://localhost`) |
| Start a camera: frames arrive, counters climb | `captured` 30, 51, 73, 94 at 6 s intervals; 113 rows; `connected` |
| Kill the simulator: unreachable, then recovers | `unreachable` by the time the stop returned; **`connected` about 11 s after the simulator restarted**, no action on the camera |
| Restart the worker mid-capture, nothing accepted is lost | four ways, below: **no frame lost** |

**Restart mid-capture.** Ground truth is the disk: a worker writes each admitted frame's JPEG
before publishing it, and frame indexes count every frame of a session. A row without a
file, or a gap in a session's indexes, is a loss; a file without a row is a frame the broker
never confirmed.

| Action, 14 s into a capture | Rows before -> after | Gaps | Rows without a file | Files without a row |
|---|---|---|---|---|
| `docker compose restart ingestion` | 60 -> 62 | none | 0 | 0 |
| `docker compose kill ingestion` (SIGKILL) | 58 -> 61 | none | 0 | 0 |
| consumer stopped 15 s (queue held 64-66) | 60 -> 198 | none | 0 | 0 |
| consumer `kill -9` for 15 s (queue held 64) | 60 -> 193 | none | 0 | 0 |

After either ingestion restart, capture restarts as a new session with the old rows intact
(62 -> 96 and similar). The queue drained to zero after every action. The loss detector was
self-tested (a missing row, a missing file and a restarted session are each flagged).

**Not covered:** the moment between writing a JPEG and the broker's confirm (three random
kills never hit it; a frame there is not "accepted" by construction, not by test); frames in
the worker's in-process queue (up to 10) are lost on a kill the same way; a broker restart
during capture. After an ingestion restart nothing resumes the worker and the camera still
reads `connected` (open in `known-issues.md`).

`uv run pytest`: **304 passed**, against a scratch database.

## OMNI-501 · Algorithm 1 on a live camera: every frame gated, admitted frames stored (preliminary) · 2026-09-30

**Conditions:** the real stack on the machine above, nothing else capturing;
`scripts/verify_live_gate.py --camera cam05 --seconds 60`; one camera, `cam05` (the
simulator's synthetic clip with motion and still stretches, 320x240, 15 fps); default gate
settings (Δ 0.5 s, grid 8, threshold 25, 3 active cells, blur 21, heartbeat 1.0 s); no
sampling setting exists any more. Two runs. The window starts 5 s after the camera is
started; the session totals cover the whole capture, read after the stop. Throwaway admin,
camera and frames removed afterwards.

| In the 60 s window | Run 1 | Run 2 |
|---|---|---|
| Window | 60.6 s | 60.7 s |
| Frames read from the stream | 909 (15.00/s) | 910 (15.00/s) |
| Frames gated | 910 (15.02/s) | 910 (15.00/s) |
| Admitted and published | 200 (3.30/s): 163 motion, 37 heartbeat | 185 (3.05/s): 148 motion, 37 heartbeat |
| Discarded (counted, not stored) | 710 | 725 |
| Dropped / decode errors | 0 / 0 | 0 / 0 |
| `fps_effective` reported while running | 15.10 | 15.00 |
| Ingestion CPU, average / peak (100% = one core) | 39% / 62% | 36% / 48% |
| Consumer, Postgres CPU, average | 3%, 2% | 2%, 1% |

| Whole session, after the stop | Run 1 | Run 2 |
|---|---|---|
| `captured = gated + dropped` | 996 = 996 + 0 | 996 = 996 + 0 |
| `gated = admitted + discarded` | 996 = 205 + 791 | 996 = 190 + 806 |
| `admitted = motion + heartbeat` | 205 = 163 + 42 | 190 = 148 + 42 |
| Stored rows | 205, all admitted, all with a reason | 190, all admitted, all with a reason |
| Frame files / thumbnails on disk | 205 / 205 | 190 / 190 |
| Clip `[t - 2Δ, t]` on every row, largest error | 0 s | 0 s |
| Largest gap between two stored frames | 1.068 s | 1.073 s |

The largest gap is the heartbeat interval (1.0 s) plus one frame (67 ms): on a still stretch
the heartbeat admits the first frame at or after it falls due.

Run 1 printed 9 of 10 checks: the failing one was the script's own window check, which
required frames read to equal frames gated exactly from two snapshots of a running worker
(909 against 910, one frame in flight). The check now allows a frame at each end of the
window; the result was not changed. Run 2: 10 of 10. The exact balances are the session
totals, read after the stop.

**Not covered:** more than one camera at a time (OMNI-509); a run longer than a minute; a
feed faster than 15 fps or larger than 320x240; the worker's counters while frames are being
dropped (unit tests only). RabbitMQ's CPU averaged 39-42% with peaks of 305-329% in both
runs at about 3 messages/s; three samples taken afterwards with nothing capturing read
140%, 0.7% and 0.3%, so the peaks are RabbitMQ's own and not this load, and are not
explained. In the same three idle samples ingestion read 8-14% (it runs with `--reload`),
so the 36-39% above is not all the camera's.

`uv run pytest`: **312 passed**, against a scratch database.

## OMNI-502 · NFR-1 with live frames on their own queue (preliminary) · 2026-10-01

**Conditions:** the machine above; the full stack with two consumers, `consumer` (file
queue and camera queue) and `consumer-live` (live queue only), prefetch 10 each; every live
frame gated (OMNI-501), admitted frames stored; gate defaults. Live: `cam01` (15 fps,
320x240, constant motion, so most frames are admitted and stored: about 12 a second).
File: `Arson049` looped to 64.5 s, **1,930 frames** at 30 fps, extracted through
`POST /videos/{id}/extract`, started at the start of the window. 30 s windows after a 6 s
warm-up. Clocks: database minus host -1.0 and -0.7 ms. Script:
`scripts/measure_capture_latency.py --camera cam01 --loops 5 --runs AB`, two runs. Measured
as in OMNI-316 (capture = `timestamp_s`, stored = `created_at`, API-visible = first seen by
a poller every 100 ms); every stored live frame in the window counted.

| Scenario | Live frames stored | p50 | p95 | p99 | max | API-visible max | File queue peak | Live queue peak |
|---|---|---|---|---|---|---|---|---|
| Live alone, run 1 | 357 | 18 ms | 298 ms | 451 ms | **472 ms** | 653 ms | 0 | 0 |
| Live alone, run 2 | 348 | 12 ms | 31 ms | 49 ms | **106 ms** | 229 ms | 0 | 0 |
| Live + 1,930-frame file, run 1 | 348 | 30 ms | 82 ms | 130 ms | **147 ms** | 327 ms | 330 | 0 |
| Live + 1,930-frame file, run 2 | 349 | 30 ms | 222 ms | 318 ms | **373 ms** | 569 ms | 306 | 0 |

No drops and no decode errors. The file was extracted completely both times (1,930 of
1,930, `ready`, 47.5 s and 50.5 s); its queue stayed above 100 for 16-18 s while the live
queue never held a message at a 200 ms sample.

**NFR-1 result:** with the 1,930-frame file extracting, the worst live frame is **147 ms and
373 ms**, against 6.14 s on one shared queue (OMNI-316). Passes.

**Compared with OMNI-316, live alone is slower** (max 106-472 ms against 28-49 ms): the
camera now stores about 12 frames a second instead of about 4 (every frame gated, OMNI-501),
and the whole stack is busier (ingestion 57-62% of a core on average alone). Run 1's tail
(p95 298 ms) did not repeat in run 2 and is not explained.

**Load, average (100% = one core), live alone / with the file:** ingestion 57-62% / 158-175%
(peaks 131-141% / 368-380%); `consumer-live` 13-15% / 17-18%; `consumer` 0% / 35-36%;
PostgreSQL 8-9% / 18-20%; RabbitMQ 66-86% / 69-79% (peaks 292-316% in every window, as in
OMNI-501).

**TC-1 first-half checks** (same script): file 1,930 gated, 357 forwarded (312 motion, 45
heartbeat), 0 violations, files equal rows; live 0 violations, files equal rows (1,083 and
1,119 rows over both windows). The script's live line says "frames gated" but counts stored
rows, which since OMNI-501 are the admitted frames only.

**Not covered:** more than one camera (OMNI-509); a file longer than 1,930 frames or two
files at once; `cam05` (the camera with still stretches) against the file; the searchable
half of NFR-1 (slice 7); a broker or consumer restart during this run (acknowledgement after
commit on the live queue is covered by a test against the real broker,
`test_segment_consumer.py`).

`uv run pytest`: **316 passed**, against a scratch database.

## OMNI-503 · The wall's preview: sixteen tiles polling one camera (preliminary) · 2026-10-01

**Conditions:** the machine above, the full stack, one camera capturing (`cam05`, 320x240,
15 fps), preview defaults (written at most every 0.5 s, longest side 640 px, JPEG quality
70). Sixteen clients in one Python process on the host, each with its own keep-alive
connection, asking for `GET https://localhost/api/cameras/{id}/preview` (through nginx, as
the wall will) once a second, starting at a random point in the first second, sending back
the last ETag they received. CPU from `docker stats` about every 2 s. Script:
`scripts/measure_preview_polling.py --camera cam05`, two runs. Bytes are response bodies, and
headers as received (status line and header lines; no TLS or TCP overhead).

| Phase | Requests | 200 / 304 | Body | Headers | Response p50 / p95 / max | Query CPU, average |
|---|---|---|---|---|---|---|
| No camera, no polling | - | - | - | - | - | 10.3% / 10.3% |
| Capturing, no polling | - | - | - | - | - | 11.1% / 10.7% |
| **Live feed, 60 s** | 960 / 960 | **960 / 0** | **386.6 / 386.8 KiB/s** (mean JPEG 24.5 KiB) | 3.8 KiB/s | 15 / 28 / 68 ms; 14 / 27 / 174 ms | **27.9% / 25.6%** (peaks 44.5% / 34.8%) |
| **Frozen feed, 30 s** (simulator paused) | 480 / 480 | **48 / 432** | **45.4 / 45.3 KiB/s**; 304s carried 0 bytes | 3.1 KiB/s | 12 / 25 / 50 ms; 13 / 29 / 64 ms | **22.1% / 23.5%** |

Two runs, separated by "/". nginx averaged 1.0-1.6% throughout. Query runs with `--reload`,
which is most of its 10-11% at rest.

**Stopped:** `POST /cameras/{id}/stop`, then the preview at once: **404, "camera is not being
captured"**, in both runs.

**What it shows:**

- **Unchanged frames cost a 304 and no image:** with the simulator paused, 432 of 480 polls
  were 304, with no body. The 48 200s are 3 per client in both runs: each client's first poll
  (it starts with no ETag) and two more early in the pause; not broken down further
- **On a live feed every poll is a 200.** The worker rewrites the preview every 0.5 s and the
  ETag is the write time, so a once-a-second poll always finds a newer frame. Sixteen tiles
  on `cam05` cost about 387 KiB/s. This contradicts OMNI-506's "mostly 304s on still scenes"
  (K-12)
- **The CPU is per request more than per byte:** query was 15-17 points of a core above its
  rest for 16 requests a second sending JPEGs, and 11-13 points when nearly all were 304s.
  Each request checks the token and reads the user, the camera and its stats from Postgres

**Not covered:** sixteen *different* cameras (ten simulator feeds exist; the wall's real load
is measured with ten feeds in OMNI-509); a browser as the client (OMNI-506); larger frames
(a 640 px preview of a real 1080p camera would be bigger than 24.5 KiB); the time a frame
takes from the stream to the file (at most the 0.5 s interval plus one frame by
construction, not measured).

`uv run pytest`: **338 passed, 1 skipped**, against a scratch database. The skipped test (a
reader never sees half a preview) cannot run on Windows; the same check was run on Linux in
the ingestion container: 2,000 reads during 552 rewrites of a 1280x720 preview, 0 torn.
