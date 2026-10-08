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
| NFR-5 | Data lost on failure or crash = 0 | 0 lost in 9 failure cases: restart, down/up, query killed mid-upload, consumer killed, broker recreated, ingestion restarted and killed, consumer stopped and killed mid-capture. Rechecked for live on the slice 5 pipeline (admitted frames only, own queue): ingestion restarted and killed, `consumer-live` stopped and killed, 0 lost, 2 runs, 32 of 32 checks each | **Pass** in the cases tested | 2026-09-12 to 10-07 | NFR-5, OMNI-311, OMNI-319, OMNI-601 |
| FR-1a | Accept live camera feeds and uploaded files | Files: one clip per dataset `ready`, metadata equal to `ffprobe`. Live: every frame gated (15.0/s), admitted frames stored, 3.05-3.30/s on `cam05` (OMNI-501); recovers by itself after the source is killed | **Pass** | 2026-09-21, 09-26, 09-30 | OMNI-300, OMNI-312, OMNI-313, OMNI-501 |
| FR-1b | Keep the most informative frames by detecting movement | Fixed cameras keep 4.7-19.8%; daylight dash-cam keeps 57%. Live: every frame gated (15.0/s), 20-22% kept on `cam05`, counters balance | **Pass** on fixed cameras, **weak** on moving cameras | 2026-09-26, 09-30 | OMNI-304, OMNI-305, OMNI-318, OMNI-501 |
| FR-3 | Store each segment with time, source and image | Files: a row for every decoded frame. Live: a row for every admitted frame. Image files equal admitted rows in every run | **Pass** | 2026-09-23 to 09-30 | OMNI-304, OMNI-316, OMNI-501 |
| NFR-1, first half | Capture to stored under 5 s (the searchable half comes in slice 7) | Every frame gated, live on its own queue: live alone max 106-472 ms; with a 1,930-frame file extracting max **147-373 ms** (was 6.14 s on one shared queue) | **Pass**, alone and with a long file extracting (preliminary: one camera, two runs) | 2026-10-01 | OMNI-316, OMNI-502 |
| FR-9, the wall's preview (no Phase A target) | 16 tiles polling one camera once a second, cheap; unchanged frames cost a 304 | Live feed: 960 of 960 polls 200, 387 KiB/s, query +15-17% of a core. Frozen feed: 432 of 480 polls 304, 45 KiB/s. Stopped: 404 at once | **Measured**; 304s only on a frozen feed (K-12) | 2026-10-01 | OMNI-503 |
| FR-9, feed health (no Phase A target) | See at once which feeds are healthy; capture resumes after a restart with nobody pressing Start | Simulator paused: `frozen` 3.1-3.2 s after the last frame, `offline` at 30.6-30.8 s (not ~10 s: late frames at each read timeout, K-13), `live` again 15.6 s after unpausing. Ingestion restarted or killed: never `live` without a worker, capture back in 12.3-13.6 s | **Pass**, with K-13 open | 2026-10-02 | OMNI-504 |
| FR-9, rewind (no Phase A target) | Rewind a feed a few minutes | After 5 min of capture on `cam05`: 957 frames in the 5-minute buffer, oldest first, none outside the window, full frames token-checked | **Pass** (one run) | 2026-10-02 | OMNI-505 |
| FR-9, the wall (no Phase A target) | Ten cameras, nine at once, each updating; 304s when a feed is frozen or lost, a new frame on every poll of a live feed by design (D-14; reworded, K-12) | Chrome: 9 tiles in the window, each changing 27-30 times in 30 s; 498 of 499 preview requests 200, ~100 KiB/s; frozen feed 432 of 480 polls 304 (OMNI-503); paging, group filter, no polling while hidden (simulated) | **Pass** | 2026-10-02 | OMNI-503, OMNI-506 |
| FR-9, tile states (no Phase A target) | Frozen, offline, stopped each labelled, the last frame dimmed with its age, never black; a frozen picture never looks live | Simulator paused: all nine tiles Frozen then Offline, no Live in between, Live again after unpausing; a stopped camera Stopped in 2.7 s | **Pass**; offline late and ages too young (K-13) | 2026-10-02 | OMNI-507 |
| FR-9, enlarge and rewind (no Phase A target) | Open a camera, rewind, step through what led up to motion | `cam05` in full screen, polled every 0.5 s; Rewind: 331 frames, motion and heartbeat told apart; stepped back through heartbeat frames to the motion | **Pass** (one run) | 2026-10-02 | OMNI-508 |
| FR-9, layouts and pins (no Phase A target) | Choose 4x4, pin a camera top-left, reload: both kept | Kept after a reload; the pin held when a camera was added and removed; blocked or broken storage falls back to 3x3 with no pins | **Pass** (one pass) | 2026-10-04 | OMNI-512 |
| TC-1 | Live camera and uploaded file together: both decode, only motion (or heartbeat) forwarded, the camera live on the wall throughout | 2 runs, 15 of 15 checks each: file 1,930 of 1,930, 356 admitted, 0 violations; live counters exact, every stored row admitted; camera live at every sample | **Pass, complete** | 2026-09-26, 2026-10-03 | OMNI-316, OMNI-511 |
| NFR-4 (revised, D-19) | 3 live feeds per machine of this class, sustained over 10 min (Phase A: 10) | 3 realistic feeds, wall open, 10 min: 0 dropped, worst 0.17 s, always live. 4: not over 10 min. 10: not (OMNI-509, OMNI-510a) | **Pass** against the revised target (preliminary, one machine) | 2026-10-03 | OMNI-509, OMNI-510a, NFR-4 revision |
| SM-3 | **mTTA ≥ 1.80 s** on CCD's held-out crash clips (D-2, rule D-23: half the held-out median pre-event footage, 3.60 s) | - | **Not measured yet** (no model before slice 10) | 2026-10-08 (target) | OMNI-606 |
| UCF-Crime training event times (data for SM-2, SM-4; no Phase A target) | Every event time from an annotation, none guessed | 594 of 810 training anomalies timed from UCA by a written rule (6 not in UCA, 210 no match); against the official start on 110 test anomalies: median 3.0 s, mean 11.3 s apart, 34% within 1 s | **Measured** (D-21) | 2026-10-07 | OMNI-603 |
| Train / validation / held-out split (data for SM-2, SM-3, SM-4; no Phase A target) | Fixed once, before any window; rebuilds byte-identical | UCF-Crime 1,368 / 242 / 290 (held-out = official test); CCD 3,132 / 675 / 693, no source video on two sides; VIRAT 275 evaluation; seed 605, SHA-256 recorded | **Fixed** (D-22) | 2026-10-08 | OMNI-605 |
| Slice 2 definition of done | The plan's demo on a wiped stack | 5 of 5 steps, 62 tests | **Pass** | 2026-09-12 | Slice 2 DoD |
| Slices 3-4 definition of done | The plan's demo, plus a worker restart mid-capture | 44 of 44 checks, 304 tests | **Pass** | 2026-09-26 | OMNI-319 |
| Slice 5 definition of done | The plan's demo on a fresh stack: ten cameras on the wall, enlarge and rewind, pause and come back, resume after an ingestion restart, TC-1 | 39 of 39 script checks, 387 tests; ten cameras back in 19.5-22.3 s after a restart or kill, 0 failed resumes; ten tiles live, frozen then offline then live around a pause | **Pass** (ten run; 3 sustained, D-19) | 2026-10-04 | Slice 5 DoD |
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

The simulator's `cam01` (15 fps, 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15] H.264), started and stopped through the API; rows
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

**Storage:** **24.2 KB per admitted frame** (16 KB frame + 8 KB thumbnail at 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15]; 98
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
(15 fps, 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15] H.264, constant motion); `cam05` for TC-1 (motion and still stretches).
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

**Conditions:** the simulator's ten looping feeds (15 fps, 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15] H.264; beyond ten the
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
**Not covered:** more than 6 minutes; separate machines; frames larger than 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15] (so
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
simulator's synthetic clip with motion and still stretches, 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15], 15 fps); default gate
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
feed faster than 15 fps or larger than 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15]; the worker's counters while frames are being
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
320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15], constant motion, so most frames are admitted and stored: about 12 a second).
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

**Conditions:** the machine above, the full stack, one camera capturing (`cam05`, 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15],
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

## OMNI-504 · Camera states from evidence, and capture that resumes by itself (preliminary) · 2026-10-02

**Conditions:** the machine above, the full stack, one camera (`cam05`); defaults: a camera is
`live` while its newest frame is at most 3 s old (`LIVE_STALE_AFTER_S`), the worker's read
timeout is 10 s, the resume check runs every 5 s. `GET https://localhost/api/cameras/live`
(through nginx, as the wall will) polled every 0.25 s for the whole run; the frame's age is
the poll's time minus `last_frame_at`. Script: `scripts/verify_camera_states.py --camera
cam05`, two runs, **12 of 12 checks passed in both**.

| Step | Run 1 | Run 2 |
|---|---|---|
| Before any start | `stopped` | `stopped` |
| Start (the API call) | 5.7 s | 7.3 s |
| Running: `live` on every poll for 8 s | 29 of 29 | 28 of 28 |
| Newest frame's age while running, p50 / max | 0.26 / 0.51 s | 0.21 / 0.47 s |
| Simulator paused: `frozen` | 3.3 s after the command, frame 3.2 s old | 3.2 s, frame 3.1 s old |
| ... then back to `live` for about 3 s | at 10.5 s and 20.5 s | at 10.6 s and 20.6 s |
| ... `offline` | **30.6 s** after the pause | **30.8 s** |
| Unpaused: `live` again by itself | 15.6 s | 15.6 s |
| `docker compose restart ingestion`: states from the command returning to `live` | `offline` only (35 polls) | `offline` only (35 polls) |
| ... `live` again, worker `running` | 13.5 s after the command returned | 13.6 s |
| `docker compose kill ingestion`, then `start`: states in between | `offline` only (35 polls) | `offline` only (35 polls) |
| ... `live` again, worker `running` | 12.3 s | 12.5 s |
| Stop: `stopped` | at once (0.2 s) | at once (0.0 s) |
| ... and not resumed, 8 s later | stays `stopped` | stays `stopped` |

**The acceptance, point by point:** frozen within 3 s, **yes** (3.1-3.2 s after the last
frame). Then offline after the read timeout, **yes, but at 30.6-30.8 s, not about 10 s**: at
each 10 s read timeout the worker received a late burst of frames from before the pause, the
camera read `live` for about 3 s, and the timeout started again (K-13; a separate probe saw 1
frame then 9 arrive while paused). Unpaused, live again by itself, **yes**, 15.6 s, which is
mostly the reconnect backoff. After a restart or a kill of ingestion, capture resumed by
itself, **yes**, in 12.3-13.6 s (the 5 s check plus a start, about 6-7 s), and no camera
read `live` without a worker, **yes**.

**Not covered:** more than one camera at once (ten resumed together are started in parallel,
not measured); a real network stall rather than `docker compose pause`; a camera whose
stream is down when it is due to resume (the retry backoff is tested, not run live); a query
restart (the same check runs at query's start; not run live).

`uv run pytest`: **361 passed, 1 skipped**, against a scratch database; one earlier full run
had one unrelated failure, K-14.

## OMNI-505 · The rewind buffer after five minutes of capture (preliminary) · 2026-10-02

**Conditions:** the machine above, the full stack, one camera (`cam05`, 320x240 [corrected 2026-10-03: the simulator's clips are 640x360, K-15], 15 fps,
motion and still stretches), gate defaults, captured for 300 s; then
`GET https://localhost/api/cameras/{id}/buffer` (through nginx) for 1, 5 and 10 minutes.
Script: `scripts/verify_rewind_buffer.py --camera cam05`, one run, **12 of 12 checks passed**.

| Window | Frames | Motion / heartbeat | Oldest / newest | Largest gap | Response | Time |
|---|---|---|---|---|---|---|
| 1 min | 190 | 154 / 36 | 59.5 s / 0.5 s ago | 1.07 s | 33 KiB | 78 ms |
| **5 min** | **957** | 772 / 185 | **300.0 s** / 0.6 s ago | 1.07 s | 166 KiB | 36 ms |
| 10 min | 958 | 772 / 186 | 301.3 s / 0.9 s ago | 1.07 s | 166 KiB | 57 ms |

(The 10-minute window holds the same frames: capture had run only about 5 minutes.)

**Acceptance:** after 5 minutes of capture the buffer returned **957 frames** (at least 300
required), **oldest first, none outside the window** (the oldest 300.0 s before the request,
in every window). Every frame has a reason. No two consecutive frames are more than 1.07 s
apart: the heartbeat (1 s) plus one frame. `frame_url` served the full JPEG with the token for
20 of 20 sampled frames, and 401 without it. `thumb_url` is served by nginx without a token,
as every thumbnail is (K-3).

**Not covered:** a camera in constant motion (about 12 stored frames a second on `cam01`,
so ten minutes would be about 7,000 frames and about 1.2 MB of JSON by this run's 177 bytes
a frame, extrapolated, not measured); the buffer while frames are being stored (the window
ends at the request; a frame still in the live queue appears on the next request);
more than one run.

`uv run pytest`: **372 passed, 1 skipped**, against a scratch database.

## OMNI-506 · The camera wall in a browser, ten cameras running (preliminary) · 2026-10-02

**Conditions:** the machine above, the full stack; the simulator's ten feeds registered and
started by `scripts/wall_cameras.py up` (`cam01`-`cam05` in "Building A", `cam06`-`cam10` in
"Building B"; 640x360, 15 fps, K-15); `https://localhost/live` in Chrome on the same machine,
signed in as admin, window 1864x927; counted inside the page with the browser's own
resource timing (`performance.getEntriesByType('resource')`), two 30 s windows.

| | Window 1 | Window 2 |
|---|---|---|
| Tiles on screen / `<video>` elements | 9 / 0 | 9 / 0 |
| Preview requests | 254 (8.5/s) | 245 (8.2/s) |
| 200 / 304 | **253 / 1** | **245 / 0** |
| Transferred | 102.8 KiB/s | 99.5 KiB/s (12.2 KiB a frame) |
| Times each tile's picture changed | 27-28 | 29-30 |
| Response time p50 | 123 ms | 193 ms (p95 371, max 473) |
| Camera list requests (every 5 s) | - | 5 |

Protocol `http/1.1`; time waiting for a connection before a request, p50 8 ms; time in the
server, p50 163 ms (window 2), against about 15 ms for one camera in OMNI-503: ten cameras
are being captured on the same machine.

**Checks:** nine tiles at once, each labelled with name and location, all nine fully inside
the window with no page scroll (after the layout fix below). Ten cameras: "Page 1 of 2", page
2 holds the tenth alone. Group filter "Building B": 5 cameras, no pager. Polling with the page
hidden: **0 requests in 10 s**, against 26 in the 5 s before; resumed 4 ms after it showed
again. The hidden state was simulated in the page (`visibilityState` reported as hidden and a
`visibilitychange` event fired), not a real tab switch: opening a second tab through the
automation left the wall in front.

**Against the acceptance:** ten cameras running, nine on the wall at once, each updating:
**yes**. "The network tab shows mostly 304s on still scenes": **no**, 498 of 499 requests
were 200, as K-12 predicted: the preview is rewritten every 0.5 s on a running feed, so a
once-a-second poll always finds a newer frame. (The simulator's scenes are not still either;
`cam05` has still stretches.)

**Not covered:** the browser's own network tab (the counts are the page's resource timing,
which is what that tab shows); a real hidden tab; a 4x4 wall (OMNI-512); the cost to the
stack of the wall itself under NFR-4 (OMNI-509).

## OMNI-507 · Tile states on the wall, and live only while frames arrive steadily (preliminary) · 2026-10-02

**Conditions:** the machine above, the full stack, the simulator's ten feeds on the wall
(`scripts/wall_cameras.py up`); `https://localhost/live` in Chrome, signed in as admin; a
recorder in the page reading every tile's badge, dimming and age text every 0.5 s; the
simulator paused for 40 s with `docker compose pause mediamtx`, then unpaused; one camera
stopped through the API. Also `scripts/verify_camera_states.py --camera cam05` (OMNI-504's
check, polls every 0.25 s), one run with the new rule (D-17).

**On the wall** (times from the recorder's start, the same for all nine tiles on page 1):

| Moment | Every tile |
|---|---|
| Before | **Live** (the live dot ticks as new frames arrive) |
| Simulator paused | **Frozen** at once, picture dimmed, "Last frame 3 s ago" |
| ... | **Offline** 27.5 s later, picture dimmed, "Last frame 11 s ago", "The camera cannot be reached; reconnecting." |
| In between | no tile read Live at any 0.5 s sample (before D-17 the camera read live at 10.5 and 20.5 s) |
| Unpaused | **Live** again by itself, 44.5-54.5 s after going offline (reconnect backoff), no reload |
| `wall-cam01` stopped | **Stopped** 2.7 s after the stop returned, last frame dimmed with its age; the other eight stayed Live |
| Page reloaded, `wall-cam01` still stopped | grey panel, stop icon, "This camera is not being captured." (no image to show) |

No tile was a black rectangle in any state.

**`verify_camera_states.py`, with D-17, 12 of 12 checks:** running `live` on every poll;
paused: `frozen` 2.4 s after the pause command (the newest frame then 2.3 s old), `offline`
at 30.6 s, **no `live` in between**; unpaused: `frozen` at 17.0 s then `live` at 18.1 s;
`restart ingestion`: `offline`, `frozen` for 1.1 s, `live` 12.7 s after the command
returned; `kill` then `start`: the same, 12.4 s; stop: `stopped` at once.

**Against the acceptance:** pause the simulator, tiles go frozen then offline without a
refresh: **yes**. Unpause, live again: **yes**. Stop a camera, stopped: **yes**.

**Still wrong (K-13, second half):** offline comes about 30 s after the pause, not about
10 s; and the age on a frozen or offline tile counts from when the late frames arrived, so
it reads younger than the picture is.

**Not covered:** a real network stall (only `docker compose pause`); more than one run on
the wall; a browser other than Chrome.

`uv run pytest`: **383 passed, 1 skipped**, against a scratch database.

## OMNI-508 · Enlarge a camera and rewind it, in a browser (preliminary) · 2026-10-02

**Conditions:** the machine above, the full stack, the simulator's ten feeds on the wall
(`scripts/wall_cameras.py up`), `cam05` capturing for about 2.3 minutes; `https://localhost/live`
in Chrome, signed in as admin; checks read from the page (resource timing and the DOM). One
run.

| Check | Result |
|---|---|
| Click the `wall-cam05` tile | an enlarged view over the whole window, **browser full screen** |
| Preview while enlarged | `cam05` only: **12 requests in 6 s** (every 0.5 s), 11 of them 200, one 304; the wall's other tiles asked for nothing |
| Rewind | **331 frames** of the last 5 minutes (capture had run 2.3 minutes): 254 motion, 77 heartbeat, from 10:06:51 to 10:09:07; opens at the newest |
| Motion and heartbeat on the scrubber | motion ticks 32 px tall and amber, heartbeat ticks 12 px and grey, each placed by its capture time |
| Stepping back from the newest motion (left arrow, 0.4 s per step) | frames 330-329 **motion** at 10:09:07; 328 back to 323 **heartbeat**, one a second (10:09:06 back to 10:09:01); 322 **motion** at 10:09:00; each step showed its full frame (640x360), time and reason |
| Click the middle of the scrubber track | frame 186 of 331, 10:07:59, motion |
| Back to live | the current picture again, Rewind offered |
| Esc | the view closed and the browser left full screen; the wall polled all nine tiles again (36 requests in 4 s) |

**Against the acceptance:** wait for motion on `cam05`, open it, rewind, step through the
frames that led up to it: **yes**: the quiet second-by-second heartbeat frames and then the
motion frames, each with its time and reason.

**Not covered:** a long rewind on a busy camera (ten minutes at 12 frames a second is about
7,000 ticks and a large buffer response, OMNI-505); stepping faster than the frames load; more
than one run; a browser other than Chrome; something actually waved in front of a camera (the
simulator's motion was used).

## OMNI-509 · NFR-4: live feeds sustained on one machine, gating every frame · 2026-10-03

**"Sustained", decided before any of these runs** (and coded in `scripts/measure_nfr4.py`):
N feeds are sustained when, over the whole window, (1) no frame is dropped on any feed (the
worker's `dropped` counter does not move); (2) every feed's worst capture-to-stored time is
under 5 s (NFR-1); (3) the live queue is not trending up over the second half of the window:
least-squares slope at most 0.1 messages/s, and the last quarter's mean at most 10 messages
above the third quarter's; (4) every feed reads `live` at every 1 s sample of
`GET /cameras/live`, which is what the wall's tiles show.

**Conditions:** the machine above (Windows 11, i7-1165G7, 4 cores / 8 threads; Docker with
8 CPUs and 7.6 GiB), the full stack with every slice 5 change (every frame gated, OMNI-501;
live frames on their own queue and consumer, OMNI-502; the wall's previews, OMNI-503).
**Realistic feeds** (new default simulator config, `mediamtx.real.yml`): ten real
surveillance clips looped from `data/`: `cam01`-`cam03` VIRAT, **1280x720 at 23.97 fps**;
`cam04`-`cam10` UCF-Crime, **320x240 at 30 fps** (four normal, three with an incident).
**Synthetic worst case**: OMNI-201's ten test patterns, 640x360 at 15 fps, moving all the
time. N feeds are `cam01`... in order unless stated; cameras started two at a time (K-16);
the window starts once every feed reads `live` plus 15 s. The wall was open in Chrome on the
same machine for every run, at 4x4 (all feeds on one page) except as noted. CPU from `docker
stats` (100% = one core); no host sampler. One run per row; **preliminary**.

| Feeds | Clips | Window | Dropped (per feed) | Worst latency | Not live | Ingestion CPU avg | All containers avg | Sustained |
|---|---|---|---|---|---|---|---|---|
| **10** | realistic, cam01-10 | **600 s** | **8,412-12,298** | **6.65 s** | 5 feeds, 2-6 samples each | 362% | 620% | **no** |
| 8 | realistic, cam01-08 | 180 s | 2,508-3,179 | 3.77 s | 1 feed, 1 s | 396% | 636% | no |
| 6 | realistic, cam01-06 | 180 s | 1,067-2,308 | 3.08 s | 2 feeds | 413% | 634% | no |
| 4 | realistic, cam01-04 | 180 s | 389-724 | 3.19 s | 2 feeds | 407% | 586% | no |
| 3 | realistic, the three HD | 180 s | 249-327 | 1.14 s | none | 370% | 530% | no |
| 2 | realistic, two HD | 180 s | 27-44 | 0.60 s | 1 feed, 2 s | 227% | 365% | no |
| 7 | realistic, the seven SD (cam04-10) | 180 s | 1,870-2,737 | 2.51 s | 5 feeds, 1-2 s | 312% | 565% | no |
| **1** | realistic HD (cam01) | 180 s | **0** | 0.11 s | none | 98% | 198% | **yes** |
| **1** | realistic SD (cam04) | 180 s | **0** | 0.03 s | none | 56% | 149% | **yes** |
| 10 | **synthetic**, cam01-10 | 180 s | 1,284-1,813 | 5.87 s | none | 362% | 617% | no |

**In every run** the live queue held **0** messages at every 1 s sample (slope 0, nothing
trending), the file queue 0, and `consumer-live` used 1-41% of a core. **Storage keeps up;
the frames are lost before the gate**, in the worker's 10-frame queue, because ingestion does
not gate them as fast as they arrive: in the 10-feed run the HD feeds gated 4.2-4.4 frames/s
of 23.97, the SD feeds 7.2-10.7 of 30. The 10-feed run, per feed: latency p50 1.0-2.7 s, p95
1.7-4.2 s; stored 0.83-3.58 frames/s; gated 4.2-10.7 frames/s. Latency comes from frames
waiting in the worker before the gate; the queue to storage is empty.

**What one frame costs** (`scripts/frame_cost.py`, single-threaded, nothing else capturing):
1280x720: decode 3.6 ms, gate and files 11.2 ms (of which grayscale and the 21 px blur 6.4 ms),
preview 0.4 ms, **15.2 ms in all, 0.36 of a core at 24 fps**; 320x240: 0.8 + 3.3 (blur 1.7) +
0.1 = **4.2 ms, 0.12 of a core at 30 fps**. Ten realistic feeds therefore need about **1.9
cores** of this work; ingestion spent 3.6-4.1 cores and still fell behind, and one HD feed
alone took 98% of a core on the stack against 36% measured on its own. During the 10-feed
synthetic run the ingestion server process had **196 threads** on 8 CPUs. Ingestion is one
Python process; the likely costs are its threads contending for Python's interpreter lock and
OpenCV/FFmpeg starting a decoder thread pool per stream. **Not isolated**: no fix was tried.

**The wall during the 10-feed run** (in-page recorder, one sample a second): 9.4 preview
requests a second, 5,622 of them 200 and 20 304 (K-12), p50 269 ms, p95 551 ms; query at 62%
of a core. The tiles that were not `Live` read **Offline** (workers reconnecting): `cam01` 7 s,
`cam03` 4 s, `cam04` 4 s, `cam06` 2 s. **The wall was at 4x4 for 248 s of the 600 s and at 3x3
for 352 s:** the layout went back to its default 19 s into the window without the page
reloading (K-17) and was set back at 3:33:59 PM.

**NFR-4 result: not met.** Under the definition above this machine sustains **1** live feed
while gating every frame, whether HD or SD; **2** HD feeds dropped about 1% of their frames
(27 and 44 in 3 minutes) and 10 feeds dropped most of theirs. OMNI-317 measured 8 sustained
at 0.2 s sampling (about 4.2 frames gated a second per camera); gating every frame
(OMNI-501, D-9) is roughly 4-7 times as much work per camera, and the realistic set includes
three HD feeds. The loss is in ingestion, not in storage, so OMNI-510 (batching the
consumer's commits) is not the lever this measurement points to.

**Not covered:** the ladder upwards (12, 15, 20 feeds), pointless once 10 failed; more than
one run per row; services on more than one machine; a GPU; any of the fix candidates (K-2).

## OMNI-510a · NFR-4 again after cutting ingestion's overhead (preliminary) · 2026-10-03

**Conditions:** as OMNI-509 (the same machine, the realistic simulator set, the same
definition of sustained, `scripts/measure_nfr4.py`), with D-18: one decoder thread per stream,
one thread per OpenCV call, each camera's worker in its own process. Every frame still gated.
The three steps were explored with 3-minute runs **without** the wall; the result for the
record is the 10-minute run **with** the wall open at 4x4 (all ten tiles on screen for all 600
samples, no layout reset this time).

**Exploration: ten realistic feeds, 180 s, no wall** (one run each):

| Change | Gated, all feeds (of 282 a second) | HD feeds | SD feeds | Dropped per feed | Worst latency | Ingestion | All containers |
|---|---|---|---|---|---|---|---|
| none (OMNI-509's 10-minute run, with the wall) | 80.5/s | 4.2-4.4 | 7.2-10.7 | 8,412-12,298 in 600 s | 6.65 s | 362% | 620% |
| one decoder thread | 107.8/s | 5.8-6.0 | 10.5-13.9 | 2,442-3,564 | 3.54 s | 384% | 588% |
| + one OpenCV thread | 117.8/s | 6.7-7.3 | 10.7-14.9 | 2,693-3,541 | 3.53 s | 309% | 516% |
| **+ a process per camera** | **227.7/s** | 15.8-17.6 | 23.3-26.8 | 618-1,239 | 2.24 s | 456% | 701% |

**For the record: ten realistic feeds, 600 s, wall open at 4x4:**

| Per feed | HD (cam01-03) | SD (cam04-10) |
|---|---|---|
| Gated | 9.1-9.6 of 23.97 a second | 16.7-19.7 of 30 |
| Dropped in 600 s | 6,153-7,826 | 6,139-8,029 |
| Latency p50 / p95 / max | 1.0-1.3 s / 2.2-2.5 s / 3.1-3.9 s | 0.26-0.59 s / 0.8-1.6 s / 1.3-3.7 s |
| Samples not `live` (of 586) | 0-1 | 8-33 |

All feeds: **157 frames gated a second** (OMNI-509: 80.5), stored 13-18 a second; live queue
mean 0.1, peak 8, not trending (slope 0.000/s); file queue 0. CPU average: ingestion 469%
(peak 711%), RabbitMQ 110%, query 87%, mediamtx 77%, `consumer-live` 38%, PostgreSQL 32%;
**all containers 821% against the 800% Docker has**; ingestion memory peak 903 MiB. On the
wall: 9.8 preview requests a second, 5,172 of them 200 and 718 304 (no new frame written
between two polls), p50 338 ms, p95 822 ms; tiles not `Live` read **Frozen**, 207
tile-seconds in all, none Offline.

**Against the definition:** no drops, **no**; worst latency under 5 s, **yes** (3.87 s; it was
6.65 s); live queue not trending up, **yes**; every feed live throughout, **no** (frames
arrive too unevenly under the load to count as steady, D-17). **Not sustained.**

**The 3-minute run without the wall gated 228 frames a second; the 10-minute run with it,
157.** The wall's own load (query, RabbitMQ, the browser on the same machine) is enough to
matter once every logical CPU is in use; the machine is full in both. Whether 10 feeds fit
on hardware with more cores than this 4-core laptop is not measured.

**The other OMNI-501 and OMNI-504 checks with process workers:** `verify_live_gate.py`
(`cam05`, now a real 30 fps clip, 60 s): 10 of 10, 29.95 frames gated a second, counters
exact (2,005 = 2,005 + 0; 2,005 = 91 + 1,914). `verify_camera_states.py`: 12 of 12; capture
resumed by itself 10.5 s after `restart ingestion` and 11.4 s after `kill`, never `live`
without a worker.

**Not covered:** the vectorised grid (K-2's third candidate), more than one run of each,
another machine. `uv run pytest`: **387 passed, 1 skipped**.

## NFR-4 revision: how many feeds this machine sustains (D-19, D-20) · 2026-10-03

**Conditions:** as OMNI-510a (one process per camera, one decoder and one OpenCV thread),
plus D-20 where stated (`LIVE_QUEUE_SIZE` 60 instead of 10). The same definition of sustained
(OMNI-509). A **realistic mix**: the first N of `cam04, cam01, cam05, cam06, cam02, cam07, cam08,
cam03, cam09, cam10` (about one 1280x720 VIRAT feed in three, the rest 320x240 UCF-Crime), not
the first N paths (all HD first). The wall at 4x4 in Chrome. **The wall's visibility was
recorded each second**: Chrome stops a hidden tab's polling, and the first two series below ran
with the window hidden (2 requests in 30 minutes), so they are without the wall's load and are
**exploration only**. One run per row; preliminary.

**Exploration, wall hidden, 180 s:**

| Feeds | Buffer | Dropped (all feeds) | Worst latency | Not live | Containers | Sustained |
|---|---|---|---|---|---|---|
| 2 | 10 | 4 | 0.15 s | none | 150% | no |
| 3 | 10 | 148 | 0.09 s | none | 188% | no |
| 4 | 10 | 406 | 0.50 s | 2 feeds | 271% | no |
| 5 | 10 | 823 | 0.65 s | none | 363% | no |
| 6 | 10 | 1,345 | 0.70 s | 2 feeds | 422% | no |
| 4 | **60** | **0** | 0.77 s | none | 270% | yes |
| 6 | 60 | 0 | 0.56 s | 3 feeds, 1-3 samples | 430% | no |
| 8 | 60 | 147 | 4.29 s | 7 feeds, 1-6 samples | 657% | no |

With the 10-frame buffer, frames dropped while the machine was mostly idle: a third of a
second of buffer does not absorb a moment's hiccup (D-20).

**For the decision, wall visible and polling (checked: visible at every sample), buffer 60:**

| Feeds | Window | Dropped per feed | Worst latency | Not live (per feed, of ~600 or ~180) | Ingestion / all containers | Sustained |
|---|---|---|---|---|---|---|
| 4 | 180 s | 0 | 0.53 s | none | 155% / 344% | yes |
| 5 | 180 s | 0 | 1.15 s | 1-2 samples, every feed | 242% / 446% | no |
| 6 | 180 s | 0-256 | 7.62 s | 0-8 samples | 352% / 618% | no |
| **4** | **600 s** | 0, 0, 8, 0 | 1.85 s | 1-4 samples, every feed | 149% / 331% | **no** |
| **3** | **600 s** | **0** | **0.17 s** | **none** | 93% / 216% | **yes** |

The 3 feeds over 10 minutes: `cam04` 30.0 frames gated a second (p50 11 ms, p95 28 ms, max 79
ms), `cam01` 23.5 (36 / 73 / 166 ms), `cam05` 30.0 (10 / 27 / 142 ms); stored 3.1-3.4 frames a
second in all; live queue 0 throughout; `consumer-live` 3%; on the wall 1,800 preview requests
(1,783 200, 17 304), no tile ever not `Live`, 4x4 for all 600 samples.

**Result:** under the definition, **this machine sustains 3 live feeds** of the realistic mix,
with the wall open. 4 hold for 3 minutes but not for 10: hiccups the short window missed
(OMNI-317's lesson again). NFR-4 is revised to that number (D-19).

**Not covered:** more than one run per row; other machines; more cameras over several machines
(the design's answer, D-19, not measured); the vectorised grid (K-2).

## OMNI-511 · TC-1 complete: a live camera and a recording at once, with the wall open · 2026-10-03

**TC-1:** ingest a live feed and an uploaded file at once, keeping only frames with motion.

**Conditions:** the machine above, the full stack as at the end of OMNI-510a and the NFR-4
revision (every frame gated; a process per camera; buffer 60). Live: `cam05`, which since
OMNI-509 is a real UCF-Crime clip (`Normal_Videos170`, 320x240, 30 fps; OMNI-316 used the
synthetic pattern). File: the archive's `Arson049` (30 fps, 320x240) looped five times to
1,930 frames, as in OMNI-316, uploaded, then extracted through `POST /videos/{id}/extract`
while the camera ran. The camera's state sampled every 0.5 s from `GET /cameras/live`; the wall
open in Chrome, recorded every second (visibility and the tile's badge). Script:
`scripts/verify_tc1.py`. Two runs.

| | Run 1 | Run 2 |
|---|---|---|
| Checks | **15 of 15** | **15 of 15** |
| File: extraction | `ready`, no error, 31.6 s | `ready`, no error, 33.4 s |
| File: stored | 1,930 of 1,930 | 1,930 of 1,930 |
| File: admitted (motion / heartbeat) / discarded | 356 (311 / 45) / 1,574 | 356 (311 / 45) / 1,574 |
| File: admitted with a reason and both files; discarded with none; scores on the right side of 3 cells | yes, 356 frame files | yes |
| Live: decode errors, worker | 0, running | 0, running |
| Live: counters | 1,154 = 1,154 + 0; 1,154 = 50 + 1,104; 50 = 14 + 36 | 1,149 = 1,149 + 0; 1,149 = 47 + 1,102; 47 = 11 + 36 |
| Live: stored rows | 50, all admitted with a reason, 50 frame files | 47, the same |
| Camera `live` (API), 30 s window / whole extraction | 59 of 59 / 63 of 63 samples | every sample |
| The wall | visible all 31 s; the tile **Live** with a picture every second; 31 of 31 previews new frames | hidden about 6 s of 33 (the window was covered); Live with a picture every second it was visible |

The file's figures are those of OMNI-316's 1,930-frame run (357 then, 356 now: this copy was
re-encoded without its audio track; not investigated further). Nothing dropped, nothing
decoded wrongly, on either side.

**TC-1: passes in full.** The first half (OMNI-316) and the second (the wall) together.

**Not covered:** a moving-camera recording at the same time; more than one live camera with the
file (NFR-4's runs had no file); the wall at a layout other than 3x3 for this test.

## OMNI-512 · Layouts and pinning, remembered per browser · 2026-10-04

**Conditions:** the full stack, the simulator's ten feeds on the wall (`wall_cameras.py up`; all
ten started on the first try this time), `https://localhost/live` in Chrome, signed in as
admin. Checked by clicking the controls and reading the page. One pass.

| Check | Result |
|---|---|
| Choose 4x4, then pin `wall-cam07` to position 1 (its pin button, "Pin to position", 1) | `wall-cam07` top left, the other nine after it in their usual order; saved as `{"layout":4,"pins":{"<id>":0}}`; the pin's click did not open the enlarged view |
| **Reload** (a full navigation) | **4x4 and `wall-cam07` top left, both kept**; its pin shown as pinned to position 1 |
| A camera added that sorts before all of them (`wall-aaa`, "Building A") | 11 cameras without a reload: `wall-cam07` still first, `wall-aaa` in the first free slot, the rest after |
| That camera removed | back to the ten, `wall-cam07` still first |
| The wall's stored key refused (its `getItem` and `setItem` made to throw, other keys untouched), then the wall opened again from the sidebar | the wall worked at the defaults (3x3, nothing pinned, page 1 of 2); two reads and two writes refused, no error shown; after storage came back and a reload, 4x4 and the pin returned (nothing was overwritten) |
| A broken value in storage (`{this is not json`), then a reload | the defaults (3x3, nothing pinned), the wall working, and a clean value saved over the broken one |

**Acceptance (choose 4x4, pin a camera to the top-left, reload: both kept): passes.**

**Not covered:** a browser that blocks storage for real (simulated in the page); pins across
groups when a group filter is on (pins are slots in whichever list is shown); more than one
browser.

---

## Slice 5 definition of done · 2026-10-04

**Conditions:** `docker compose down`, then `up -d` (the realistic simulator set), on the
branch's code. The machine as stated at the top. `uv run pytest` on a scratch database; the
check scripts run one after another against the real API; the wall in Chrome, signed in as
admin, window visible (the recorder logged the tab's visibility: visible at every sample).

| Step | How | Result |
|---|---|---|
| Suite | `uv run pytest` | 387 passed, 1 skipped |
| Camera states | `verify_camera_states.py --camera cam05` | 12 of 12: paused simulator frozen then offline; never `live` without a worker; back by itself 10.5 s after `restart ingestion`, 6.9 s after kill and start; a stop stays stopped |
| TC-1 | `verify_tc1.py` | 15 of 15: file and live camera together, live counters exact (1,067 = 1,067 + 0; 1,067 = 46 + 1,021), camera `live` at all 59 samples |
| Rewind | `verify_rewind_buffer.py --camera cam05` | 12 of 12: 395 frames in the 5-minute buffer after 302 s of capture, full frames token-checked |
| Ten cameras started | `wall_cameras.py up` (ten starts in parallel) | all ten started on the first try, 3.7-16.4 s each |
| Ten on the wall | Chrome, 4x4, 30 s | 10 tiles, all Live, each picture changing 25-30 times |
| Enlarge and rewind | `wall-cam03` in full screen, then Rewind | 251 frames (60 motion, 191 heartbeat) over 4.5 min; scrubbed back to 10:25:14, about 4 min |
| Pause the simulator, with ten on the wall | `docker compose pause mediamtx` for 49 s, then unpause; tiles read every 1 s | all ten Frozen in the same second, all ten Offline 28 s later (K-13), all ten Live again within about 15 s of unpausing; no tile Live while paused |
| Restart ingestion with ten capturing | `verify_resume_all.py --action restart` | all ten `live` again 19.5-20.2 s after the command returned; 0 failed resume attempts |
| Kill and start ingestion with ten capturing | `verify_resume_all.py --action kill` | all ten `live` again 21.1-22.3 s after the command returned; 0 failed resume attempts |

**Ten feeds overload this machine, as NFR-4 (revised, D-19) says.** With nothing paused, 15 of
430 tile readings (3.5%) were Frozen for 1-2 s before coming back. The wall stays honest (a
late feed is shown as frozen, not live), but ten is above the 3 feeds this machine sustains.
The definition of done's "ten simulated cameras… with the system keeping up" is met only in
that sense: ten run and are shown truthfully; the sustained figure recorded is 3.

**Result: every step of the definition of done holds on a fresh stack** (preliminary: one
machine, one pass of each browser step).

**Not covered:** sixteen cameras; a real camera; a second browser; NFR-4 itself (measured in
the NFR-4 revision entry, not rerun here).

---

## OMNI-601 · NFR-5 rechecked for live cameras on the slice 5 pipeline · 2026-10-07

**Conditions:** the stack as it stands at the start of slice 6 (`master` at `24882ba`),
already running; the machine as stated at the top. `scripts/verify_definition_of_done.py
--only F`, two runs: `--camera cam02` and `--camera cam05` (simulator feeds). Each case uses a
new camera, captures 14 s, applies the failure, waits for the queues to drain, lets capture
go on 6 s, stops it, waits again, then compares.

**The rule (K-11):** a live camera stores admitted frames only (OMNI-501), so gaps in a
session's frame indexes are normal and are not read. Loss is a row whose file is missing, or
fewer stored rows than the worker reported admitted: per session against the highest
`camera_stats` report seen while it ran, and per camera against the lifetime counters. The
check waits for the file queue, `omnisight.segments.live` and the camera queue (stats). The
self-test flags a missing row, a missing file and a short count, and does not flag gaps.

| Case | Run | Sessions (rows / reported admitted) | Camera total (rows / admitted) | Rows without file | Files without row | Lost |
|---|---|---|---|---|---|---|
| `restart ingestion` | cam02 | 14/14, 8/8 | 22 / 22 | 0 | 0 | 0 |
| | cam05 | 14/14, 9/9 | 23 / 23 | 0 | 0 | 0 |
| `kill ingestion` (SIGKILL), then `up -d` | cam02 | 14/14, 8/8 | 22 / 22 | 0 | 0 | 0 |
| | cam05 | 14/13, 22/22 | 36 / 35 | 0 | 0 | 0 |
| `consumer-live` stopped 15 s | cam02 | 44/44 | 44 / 44 | 0 | 0 | 0 |
| | cam05 | 55/55 | 55 / 55 | 0 | 0 | 0 |
| `consumer-live` killed (SIGKILL) 15 s | cam02 | 44/44 | 44 / 44 | 0 | 0 | 0 |
| | cam05 | 55/55 | 55 / 55 | 0 | 0 | 0 |

- **Both ingestion cases:** capture resumed by itself in a new session (OMNI-504) and went on
  producing; every row stored before the failure was still there
- **The kill on `cam05`:** 14 rows against a last report of 13: one frame admitted, published
  and stored after the worker's last report and before the kill. Expected; a kill sends no
  final report
- **Consumer cases:** the live queue held 14-26 messages while `consumer-live` was down or
  dead; all were stored once it started. 0 frames dropped by the worker (`dropped` 0 in every
  case)
- Both runs: **32 of 32 checks**

**Result: 0 frames lost in all four cases, two runs, by the new rule.** Preliminary: one
machine, two runs, one camera per case.

**Not covered:** many cameras at once during a failure; a failure longer than 15 s (the
backlog limit, `live_max_backlog` 2,000, was not reached); the broker recreated or killed
with live capture running (OMNI-311 covered it for files only); few frames per case: the gate
kept about 3-4% of frames on these feeds during the runs, so 22-55 admitted frames per case.

## OMNI-603 · UCF-Crime event times from UCA, and their agreement with the official ones · 2026-10-07

**Conditions:** `uv run python scripts/uca_event_times.py`, on the local annotation mirror:
UCA at commit `e478cb5b` (json files), the official `Anomaly_Train.txt` (1,610),
`Anomaly_Test.txt` (290) and `Temporal_Anomaly_Annotation_for_Testing_Videos.txt`. Matching is
by video name against the official lists, which were checked against the full set on Drive on
2026-09-21; the videos themselves were not read. The picking rule (D-21) was written before
the agreement was computed and not changed after. One run (deterministic).

**Match:** 1,854 UCA videos, all in the official lists. Training anomalies:

| Class | Videos | In UCA | Timed by the rule |
|---|---|---|---|
| Abuse | 48 | 48 | 38 |
| Arrest | 45 | 45 | 30 |
| Arson | 41 | 41 | 39 |
| Assault | 47 | 45 | 42 |
| Burglary | 87 | 87 | 43 |
| Explosion | 29 | 29 | 19 |
| Fighting | 45 | 45 | 38 |
| RoadAccidents | 127 | 125 | 113 |
| Robbery | 145 | 144 | 109 |
| Shooting | 27 | 27 | 20 |
| Shoplifting | 29 | 29 | 17 |
| Stealing | 95 | 95 | 55 |
| Vandalism | 45 | 44 | 31 |
| **Total** | **810** | **804** | **594 (73%)** |

**Agreement:** the 140 official test anomalies are all in UCA; the rule times 110 (30 no
match). Start picked from UCA against the official first interval's start (frame / 30):

| Measure | Value |
|---|---|
| \|difference\| mean / median | **11.3 s / 3.0 s** |
| p75 / p90 / max | 6.6 s / 25.8 s / 322.4 s |
| Signed (UCA - official) mean / median | -3.4 s / -0.8 s |
| Within 1 s / 2 s / 5 s / 10 s | 37 (34%) / 48 (44%) / 73 (66%) / 94 (85%) of 110 |
| UCA start inside an official interval | 39 of 110 (35%) |

Per class, median |difference|: Abuse 2.8 s (2), Arrest 16.5 s (3), Arson 3.6 s (8), Assault
0.7 s (3), Burglary 6.3 s (7), Explosion 0.7 s (13), Fighting 1.6 s (5), RoadAccidents 1.8 s
(23), Robbery 2.1 s (5), Shooting 3.0 s (16), Shoplifting 6.0 s (19), Stealing 35.6 s (2),
Vandalism 2.2 s (4). Small groups; read as indications.

**Not covered:** the test-set agreement measures the rule on 110 videos whose class mix
differs from training (Robbery 5 here, 109 timed in training); whether 30 fps holds for every
video (OMNI-607 probes each); whether either annotation is right (OMNI-609, by eye); the 30
test anomalies the rule could not time (they keep their official times).

## OMNI-605 · The fixed split: counts per split per class, seed and hashes · 2026-10-08

**Conditions:** `uv run python scripts/build_dataset_split.py`, the rule in D-22, seed 605,
on the manifest from OMNI-604 (loaders on the local mirror with Drive's `video_files.txt`).
Run twice: identical files. Deterministic; one machine.

**UCF-Crime** (1,900):

| Class | Train | Validation | Held-out |
|---|---|---|---|
| Abuse | 40 | 8 | 2 |
| Arrest | 39 | 6 | 5 |
| Arson | 35 | 6 | 9 |
| Assault | 40 | 7 | 3 |
| Burglary | 74 | 13 | 13 |
| Explosion | 24 | 5 | 21 |
| Fighting | 38 | 7 | 5 |
| RoadAccidents | 108 | 19 | 23 |
| Robbery | 124 | 21 | 5 |
| Shooting | 23 | 4 | 23 |
| Shoplifting | 24 | 5 | 21 |
| Stealing | 81 | 14 | 5 |
| Vandalism | 38 | 7 | 5 |
| Normal | 680 | 120 | 150 |
| **Total** | **1,368** | **242** | **290** |

Anomalies with an event time: train 505 (UCA), validation 89 (UCA), held-out 140 (official).
Untimed: train 183, validation 33.

**CCD** (4,500):

| Class | Train | Validation | Held-out |
|---|---|---|---|
| Crash | 1,032 (90 source videos) | 225 (23) | 243 (20) |
| Normal | 2,100 | 450 | 450 |
| **Total** | **3,132** | **675** | **693** |

No source video on two sides (test). **VIRAT:** 275, all `evaluation`.

**Files** (`datasets/splits/`, LF, sorted by `clip_key`, columns `clip_key,event_class,split`):

| File | SHA-256 |
|---|---|
| `ucf_crime.csv` | `9d167d543433756afa846ee5f65f448a069fcf16334581b1575e05029a224a78` |
| `ccd.csv` | `a555c747da58e32a0964278295bc993b4b1d115cb07afa89af9199282c7673c4` |
| `virat.csv` | `a031e637e3e02b0281dd72c6c518af2cd780363684868d2be3546ac29ac5bddd` |

**Not covered:** balance on anything but class (scene, camera, time of day); CCD normals
cannot be grouped by source video (no field for it); held-out classes are as small as the
official test set makes them (Abuse 2, Assault 3).

## OMNI-606 · CCD pre-event footage, and the SM-3 target · 2026-10-08

**Conditions:** `uv run python scripts/ccd_pre_event.py`. All 1,500 crash clips from
`Crash-1500.txt` (pre-event footage = first `1` in `binlabels` / 10 fps), split from the
committed `datasets/splits/ccd.csv` (D-22). Rule D-23 written before running. Labels only:
the videos were not read, so the 10 fps and 50 frames rest on the sampled clips
(`dataset-layout.md`). Deterministic; one run.

**Seconds before the first accident frame:**

| Crash clips | n | Mean | Median | p10 | p25 | p75 | p90 | Min | Max | Under 1 s |
|---|---|---|---|---|---|---|---|---|---|---|
| All | 1,500 | 3.72 | 3.60 | 3.00 | 3.20 | 4.20 | 4.60 | 3.00 | 4.90 | 0 |
| Train | 1,032 | 3.73 | 3.60 | 3.00 | 3.20 | 4.20 | 4.60 | 3.00 | 4.90 | 0 |
| Validation | 225 | 3.71 | 3.60 | 3.00 | 3.20 | 4.10 | 4.60 | 3.00 | 4.90 | 0 |
| **Held-out** | **243** | **3.68** | **3.60** | 3.00 | 3.20 | 4.10 | 4.50 | 3.00 | 4.90 | 0 |

Percentiles: linear interpolation between order statistics.

**Histogram** (0.5 s bins):

| Pre-event footage | All | Train | Validation | Held-out |
|---|---|---|---|---|
| 3.0-3.5 s | 606 | 408 | 95 | 103 |
| 3.5-4.0 s | 376 | 261 | 54 | 61 |
| 4.0-4.5 s | 290 | 199 | 44 | 47 |
| 4.5-5.0 s | 228 | 164 | 32 | 32 |

**SM-3 target (D-23):** half of 3.60 s = **mTTA ≥ 1.80 s**. Ceiling: 3.68 s (held-out mean,
a warning at every clip's first frame).

**Not covered:** the real lead-up before each crash (CCD clips start where the dataset cut
them, so footage is never under 3.0 s or over 4.9 s); frame rates of the 1,490 crash clips
not in the local mirror.
