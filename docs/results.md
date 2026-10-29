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
| NFR-4 (revised, D-19) | 3 live feeds per machine of this class, sustained over 10 min (Phase A: 10) | 3 realistic feeds, wall open, 10 min: 0 dropped, worst 0.17 s, always live. 4: not over 10 min, before and after the one-operation grid (after: 0 dropped, one feed 2 s not live). 10: not (OMNI-509, OMNI-510a) | **Pass** against the revised target (preliminary, one machine) | 2026-10-03, 2026-10-16 | OMNI-509, OMNI-510a, NFR-4 revision, OMNI-613 |
| SM-3 | **mTTA ≥ 1.80 s** on CCD's held-out crash clips (D-2, rule D-23: half the held-out median pre-event footage, 3.60 s) | - | **Not measured yet** (no model before slice 10) | 2026-10-08 (target) | OMNI-606 |
| UCF-Crime training event times (data for SM-2, SM-4; no Phase A target) | Every event time from an annotation, none guessed | 594 of 810 training anomalies timed from UCA by a written rule (6 not in UCA, 210 no match); against the official start on 110 test anomalies: median 3.0 s, mean 11.3 s apart, 34% within 1 s | **Measured** (D-21) | 2026-10-07 | OMNI-603 |
| Train / validation / held-out split (data for SM-2, SM-3, SM-4; no Phase A target) | Fixed once, before any window; rebuilds byte-identical | UCF-Crime 1,368 / 242 / 290 (held-out = official test); CCD 3,132 / 675 / 693, no source video on two sides; VIRAT 275 evaluation; seed 605, SHA-256 recorded | **Fixed** (D-22) | 2026-10-08 | OMNI-605 |
| Lead-up windows (data for SM-2, SM-3, SM-4; no Phase A target) | Every timed event has its windows or a recorded reason; exported and hashed | UCF-Crime 680 positive per L (30 s, 60 s), 950 negative per L; 67% / 84% shortened; 54 events at 0 s, 216 untimed, 16 second intervals skipped. CCD 1,500 positive (3.0-4.9 s), 3,000 negative. SHA-256 recorded | **Derived** (D-24); hand check pending (OMNI-609) | 2026-10-09 | OMNI-607 |
| Lead-up windows, hand check (Phase A: "check a sample by hand"; no target) | 60 windows checked by eye against a criterion written first (D-27) | UCF-Crime 23 of 30 correct (official 13 of 15, UCA 10 of 15); CCD 30 of 30. 5 of 7 Wrongs end too late | **Measured** (preliminary: one checker, small sample); UCA weakness recorded as K-20 | 2026-10-10 | OMNI-609 |
| Dataset footage in the product (no Phase A target) | Through the upload path, never expiring; D-26: only the 60-clip hand-check sample | 60 of 60 `ready`, 0 failed: CCD 30 in 2 min 4 s, UCF-Crime 30 in 33 min 46 s; 2.06 GB of storage, ~31 KB per kept frame. Full load estimated at 50 GB, 20-34 h, not run | **Pass** (D-25, D-26) | 2026-10-09 | OMNI-608 |
| VIRAT demo sample in the product (no Phase A target) | One VIRAT video per scene, through the upload path, never expiring (D-26 amended) | 9 of 9 `ready`, 0 failed, 9 scenes (0000, 0001 have no video under 500 MB), 13 min 37 s; 23,057 frames gated, 1,039 kept (4.5%: 248 motion, 791 heartbeat) [corrected 2026-10-29: was 949 / 701, a mis-added total]; 1.49 GB of storage | **Pass** with 9, not 11, scenes (D-26) | 2026-10-18 | OMNI-702 |
| TC-3, frame half | 1,000 vectors with payloads into Qdrant; retrieved by id and by filtered search, every field equal; again after a Qdrant restart | 2 runs: 1,000 of 1,000 by id (payloads equal as JSON bytes, vectors bit-identical) and by filtered search, filter counts equal, a redelivery of 100 left 1,000 points; the same after each restart (healthy again in 4.7-4.8 s). First run failed: 66 `timestamp_s` values one unit in the last place off, fixed (D-29) | **Pass, first half** (`clip_vectors` in slice 8) | 2026-10-19 | OMNI-703 |
| TC-2, frame half | Each admitted frame of a 30 s uploaded MP4 and of 30 s from a live camera encodes to one 1152-D, unit-length vector, no error | Upload: 136 of 136 (VIRAT 0102, first 30 s, 720 frames gated). Camera `cam05`: 41 of 41. All 1152-D, finite, norms 0.9999998-1.0000001, 0 errors. One run, CPU | **Pass, first half** (clip embedding in slice 8) | 2026-10-19 | OMNI-704 |
| SigLIP 2 cost on this laptop's CPU (information, D-31) | No target: the speed is judged on a GPU (Colab, OMNI-710) | 8.7 s per frame at batch 1, 9.3 s at batch 8; 1.2 s per text query; 4.2 GiB RSS; 80 s start to ready | Information only | 2026-10-19 | OMNI-704 |
| NFR-5 for vectors (OMNI-705) | Every admitted frame ends with exactly one point; a kill of `ai_workers` mid-batch loses nothing and duplicates nothing | VIRAT video 3226, 44 admitted frames: killed 14 s into the 3rd batch with 16 stored and 8 in flight; after restart 44 of 44 frames with a point, 44 points, 0 missing, 0 extra, 0 dead letters. `GET /embeddings/status`: 44 / 44 | **Pass** (one video, one kill, D-35) | 2026-10-28 | OMNI-705 |
| InternVideo2's text side on this laptop, beside SigLIP 2 (D-32) | Fits Docker's 7.6 GiB; ms per query recorded | ai_workers process 3.84 GiB after 400 queries, 4.17 GiB peak; InternVideo2 text median 131 ms (p95 300), SigLIP 2 text median 1,097 ms (p95 1,885); 200 queries each, one run | **Pass** (fits; preliminary) | 2026-10-28 | OMNI-706 |
| InternVideo2 checkpoint (D-33): one 8-frame clip and one text | 512-D (Phase A: 768, D-33), finite, unit length | VIRAT 040103_00 event 29 (opening a trunk), 8 frames: clip and text 512-D, finite, norm 1.0; every checkpoint weight loaded with all keys matched. Laptop CPU and L4 GPU: the same similarity (0.0967) | **Pass** | 2026-10-28 | OMNI-706 |
| InternVideo2 motion check (OMNI-706; a sanity check, not SM-1) | Record the 10 x 10 matrix and how many clips rank their own caption first (no pass mark) | 2 of 10 own caption first; 4 of 10 a caption of their own type (chance 2 of 10). Opening and closing a trunk not told apart: all 4 trunk clips rank a vehicle caption first and score *shutting a car's trunk* above both opening captions | Recorded (weak) | 2026-10-28 | OMNI-706 |
| Encoder cost on a GPU (D-31) | No target here: NFR-1 and NFR-2 use it (OMNI-714) | NVIDIA L4, float32, from the stored input: SigLIP 2 108 / 106 / 112 ms per frame at batch 1 / 8 / 32, text 13 ms; InternVideo2 297 / 319 / 316 ms per clip, text 7 ms; peak GPU memory up to 6.9 GiB (SigLIP 2 b32) and 8.6 GiB (InternVideo2 b32), both models loaded | Information (L4, not the A100 named: none free) | 2026-10-28 | OMNI-706 |
| FR-4, frame search (`GET /search`, OMNI-707) | Ranked moments with every field; a camera filter returns only that camera's frames even when its best match ranks below other cameras' | Running stack, video 3226 (44 frames with vectors): 3 queries, 5 ranked hits each, every field set, 0 dropped; a date filter around the top hit returns it alone. Camera filter: tested on real Postgres with in-process Qdrant (the stack has no two cameras with vectors). 27 tests | **Pass** (frame mode; clip and fused in OMNI-710, 711) | 2026-10-28 | OMNI-707 |
| The VIRAT archive on Colab, both streams (data for SM-1, TC-4; no Phase A target, D-37) | Every admitted frame of the 275 evaluation videos cached with both vectors; the product's segments matched to it; laptop and Colab agree (cosine ≥ 0.999) | 275 of 275 videos, 0 failed; 793,686 frames gated, 35,704 admitted (8,255 motion, 27,449 heartbeat), each with both vectors; 2.52 h on one A100, 87 frames/s gated, 3.93 admitted frames/s encoded. Product: 1,039 of 1,039 segments matched. Agreement: 44 of 44 at least 0.999 (min 0.999979) | **Pass**; the kill-and-resume test not run on Colab | 2026-10-29 | OMNI-708 |
| FR-9, dashboard aggregates (no Phase A target) | The summary's counts equal a direct count; both endpoints measured with the archive at full size | Equal to a direct count before and after an upload, a re-gate and a delete on the real pipeline. 146,807 rows (D-26's archive): summary p50 41 ms, p95 72 ms; activity p50 15 ms, p95 36 ms, 100 calls each | **Pass** (preliminary: two runs, one machine; storage misses 1.05 GB of orphan files, K-21) | 2026-10-11 | OMNI-610 |
| FR-9, Operations Dashboard (no Phase A target) | Each number matches the API and leads somewhere; refresh every 30 s, paused while hidden | 5 figures equal to the API, before and after a clip was added and removed, without a reload; each links (analysts: cameras unlinked, no access to the wall); requests 30 s apart, none while hidden, one on return | **Pass** (one pass, admin; `/datasets` arrives in OMNI-612) | 2026-10-11 | OMNI-611 |
| FR-9, Datasets screen (no Phase A target) | Load 10 more CCD clips from the screen and watch the count and the dashboard move (read under D-26: the 30 sampled CCD clips were all loaded, so 10 were deleted and loaded again) | CCD 20 / 30 → 30 / 30 in 28 s (10 clips, ~2.8 s each), polled every 2 s; dashboard 50 → 60 videos, 146,307 → 146,807 segments, 500 in the current hour; 30 verdicts kept; windows and verdict counts equal to the database (4,500 / 30 / 30 CCD, 3,260 / 30 / 23 UCF-Crime) | **Pass** (one pass, admin) | 2026-10-15 | OMNI-612 |
| Slice 2 definition of done | The plan's demo on a wiped stack | 5 of 5 steps, 62 tests | **Pass** | 2026-09-12 | Slice 2 DoD |
| Slices 3-4 definition of done | The plan's demo, plus a worker restart mid-capture | 44 of 44 checks, 304 tests | **Pass** | 2026-09-26 | OMNI-319 |
| Slice 5 definition of done | The plan's demo on a fresh stack: ten cameras on the wall, enlarge and rewind, pause and come back, resume after an ingestion restart, TC-1 | 39 of 39 script checks, 387 tests; ten cameras back in 19.5-22.3 s after a restart or kill, 0 failed resumes; ten tiles live, frozen then offline then live around a pause | **Pass** (ten run; 3 sustained, D-19) | 2026-10-04 | Slice 5 DoD |
| Slice 6 definition of done | The plan's proof on a fresh stack: the dashboard's counts accurate and live, every figure leads somewhere; a dataset loads through the normal pipeline, appears in the archive, its windows spot-checked on screen | 20 of 20 script checks (dashboard and `GET /datasets` equal to the database on the fresh stack, after the delete and after the load; 3 UCF-Crime clips deleted and reloaded through the load endpoint in 148 s, rows and admitted frames identical, windows re-linked, verdicts kept); on screen: load progress, the dashboard moving without a reload, every link followed, a reloaded clip played on its window | **Pass** (one pass) | 2026-10-16 | Slice 6 DoD |
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

## OMNI-607 · The lead-up windows: counts, shortened and skipped, and hashes · 2026-10-09

**Conditions:** `uv run python scripts/build_event_windows.py`, rules D-24, seed 607, on the
OMNI-604 manifest and the committed split (D-22). Every video's fps and duration from
`ffprobe` on Drive (`scripts/probe_dataset_videos.py`, Colab, 2026-10-09): 1,950 UCF-Crime
and 4,500 CCD files, 0 probe errors; the 35 local mirror clips probed locally gave
identical rows. Run twice: identical files, no new rows. Deterministic; one machine.

**UCF-Crime positive windows** (one per timed event and L; the same per L, 680 each):

| Class | Train | Validation | Held-out |
|---|---|---|---|
| Abuse | 26 | 6 | 2 |
| Arrest | 25 | 4 | 5 |
| Arson | 32 | 6 | 9 |
| Assault | 36 | 6 | 3 |
| Burglary | 37 | 6 | 13 |
| Explosion | 14 | 2 | 21 |
| Fighting | 29 | 6 | 5 |
| RoadAccidents | 74 | 13 | 23 |
| Robbery | 89 | 13 | 5 |
| Shooting | 17 | 2 | 23 |
| Shoplifting | 14 | 3 | 21 |
| Stealing | 45 | 8 | 5 |
| Vandalism | 22 | 5 | 5 |
| **Total, per L** | **485** | **86** | **140** |

Accounting for the 950 anomalies, per L: 680 windows (140 official times, 540 UCA)
+ 54 events at 0 s + 216 untimed = 950. Plus 16 second intervals skipped (held-out).

**UCF-Crime negative windows:** 950 per L (train 680, validation 120, held-out 150), one per
normal video.

**How much footage the windows really have** (length in seconds):

| Windows | n | Shortened | p25 | Median | p75 | Under 5 s | Under 10 s |
|---|---|---|---|---|---|---|---|
| Positive, L = 30 s | 680 | **454** (67%) | 5.8 | 15.8 | 30.0 | 155 | 256 |
| Positive, L = 60 s | 680 | **571** (84%) | 5.8 | 15.8 | 38.8 | 155 | 256 |
| Negative, L = 30 s | 950 | 172 | 30.0 | 30.0 | 30.0 | 0 | 14 |
| Negative, L = 60 s | 950 | 402 | 37.0 | 60.0 | 60.0 | 0 | 14 |

Shortest positive: 0.033 s (one frame). Shortened positives by source, L = 30 s: official
81 of 140 (median length 20.7 s), UCA 373 of 540 (median 15.0 s); L = 60 s: 109 and 462.
**Most UCF-Crime events start less than 30 s into their video**, so a full 30 s lead-up exists
for a third of them and a full 60 s for a sixth.

**Skipped** (`ucf_crime_skipped.csv`, 572 rows):

| Reason | Per L | Note |
|---|---|---|
| Event starts at 0 s | 54 | all UCA times (train 45, validation 9); none official |
| No event time | 216 | D-21: 6 not in UCA, 210 no matching segment |
| Second interval | 16 | held-out test videos |
| Event after the probed end | 0 | |

**CCD:** 1,500 positive windows `[0, accident_start)` (train 1,032, validation 225, held-out
243), 3.0-4.9 s, median 3.6 s, none shortened or skipped; 3,000 negatives (2,100 / 450 / 450),
lengths drawn from the same split's crash windows. All 4,500 clips at 10 fps; 4,498 run
5.000 s, 2 run 4.900 s.

**Frame rates:** 11 UCF-Crime videos are not at 30 fps: `Arrest050` (29.97) and 10 training
normals in `Training-Normal-Videos-Part-2` (25: `Normal_Videos586, 600, 635, 644, 645, 648,
649, 650, 651, 653`). None has an official frame-number time (Arrest050 is timed by UCA in
seconds; normals have no event), so no window is affected by the 30 fps conversion.

**`event_windows`:** 7,760 rows (UCF-Crime 3,260, CCD 4,500), equal to the CSVs. In SQL:
0 positive windows ending anywhere but their event start, 0 windows whose split differs from
the manifest, 0 negatives on a non-normal clip, 0 verified yet.

**Files** (`datasets/windows/`, LF, sorted by clip, kind, length):

| File | Rows | SHA-256 |
|---|---|---|
| `ucf_crime.csv` | 3,260 | `9115e1afc9d68ce4cebdd61d910619bf4a511df333f60795deb4429b7a2fd500` |
| `ucf_crime_skipped.csv` | 572 | `d8c85c4d43a91e5a3b74ed0aa261db9756c6fc4deeabc75ef71bd2361a462a5e` |
| `ccd.csv` | 4,500 | `6e892642198d80e447d91ba30b6dd3c6aa3aaaebf72da4ee7760d57e9adfa044` |
| `ccd_skipped.csv` | 0 | `c0776c437b989dcea1504d875a69a305718ebafc3c6a3064123382ce4c4a8284` |

**Not covered:** whether any window is right by eye (OMNI-609); whether the 54 UCA events
at 0 s really start at 0 s or the D-21 rule picked a scene-setting segment; whether the
shortened windows carry enough lead-up to learn from (slice 9 and on); the CSVs not yet read
on Colab.

## OMNI-608 · Estimate before loading the datasets into the product · 2026-10-09

**Conditions:** the clips to load listed from the manifest (`scripts/plan_dataset_load.py`:
CCD all, VIRAT the 275 with events, UCF-Crime the 290 held-out), then size and `ffprobe`
(header: fps, `nb_frames`, duration) of each file on Drive (`scripts/estimate_dataset_load.py`,
Colab). 5,065 files, 0 errors, every file reported its frame count. Load time extrapolated
from OMNI-311's publish cost (12-15 ms per frame), not measured.

| Subset | Videos | Size | Frames | Footage | Frame rates | Over 500 MB | Over 60k frames |
|---|---|---|---|---|---|---|---|
| CCD | 4,500 | 7.34 GB | 224,998 | 6.25 h | all 10 | 0 | 0 |
| VIRAT (with events) | 275 | 34.67 GB | 793,686 | 7.82 h | 23.97 (153), 29.97 (89), 30 (31), 2 others | 17 (largest 1,608 MB) | 0 (largest 29,580) |
| UCF-Crime held-out | 290 | 7.99 GB | 1,111,808 | 10.30 h | all 30 | 2 (906, 589 MB) | 2 (107,994 and 107,997) |
| **Total** | **5,065** | **50.0 GB** | **2,130,492** | 24.4 h | | 19 | 2 |

**Load time, first estimate:** publishing 2.13M frames at 12-15 ms = 7.1-8.9 h, plus a
playback copy for every CCD clip (all 4,500 are MPEG-4 Part 2, not H.264), roughly 1-2 h:
about 8-11 h. **Too low**, see the measurement below.

**Disk:** 50 GB in the local mirror plus 50 GB copied into `video_storage` by the upload
path, plus admitted-frame JPEGs, roughly 10-20 GB (extrapolated from 24.2 KB per admitted
frame at 640x360, OMNI-312; not measured on these resolutions). About 120 GB; 428 GB free.

**Measured before the full load** (the real stack, through `POST /videos/upload` and
`/extract`, the Drive copy running at the same time; one or two runs each, preliminary):

| Clip | Resolution | Conditions | Extraction, end to end |
|---|---|---|---|
| 3 CCD clips via `POST /datasets/ccd/load` | 1280x720, 50 frames | simulator on | 6.9 s per clip (playback copy 2.5-3.5 s, publish 2.2-3.1 s) |
| VIRAT_S_010208_07 | 1280x720, 461 frames | simulator on + a stray live worker (K-19) / simulator on / simulator off (x2) | 55.2 / 39.1 / 34.3, 34.2 ms per frame |
| Normal_Videos170 (UCF-Crime) | 320x240, 1,086 frames | same three conditions | 32.4 / 42.3 / 22.9, 19.4 ms per frame |

The 12-15 ms per frame from OMNI-311 was publish only, on 640x360; end to end at these
resolutions it is 2-4 times that. **Revised projection, simulator stopped:** CCD 6.3-8.6 h,
VIRAT about 7.5 h, UCF-Crime 5.9-7.1 h, **about 20-23 h** with `mediamtx` stopped (the ten
simulator feeds cost 40-75% of a core), 27-34 h with it running.

**Outcome: the full load was not run (D-26).** A copy from Drive was started (1,354 CCD
clips copied, then deleted) and stopped before any clip was loaded. Model measurements move
to Colab; the product loads only the 60-clip hand-check sample (next entry).

**Limits the full load would have hit:** 19 files over the 500 MB upload limit; 2 videos
whose publish (22-27 min) exceeds the 900 s extract timeout. Raised, then reverted with
D-26 (D-25).

## OMNI-608 · The hand-check sample loaded into the product · 2026-10-09

**Conditions:** the real stack (`docker compose up -d`, simulator running, no cameras),
the 60 clips of `datasets/hand_check/sample.csv` (D-26) copied from Drive
(`scripts/copy_dataset_subsets.py`, 32 copied and 28 already local, sizes equal to Drive,
2 min 21 s), then loaded through `POST /datasets/{name}/load` via nginx
(`scripts/run_dataset_load.py`), which runs each clip through `store_video` (the upload
path), then extraction. One run.

| Dataset | Clips | Ready | Failed | Load time | Size | Footage | Frames gated | Kept |
|---|---|---|---|---|---|---|---|---|
| CCD | 30 | 30 | 0 | 2 min 4 s | 17.4 MB | 2.5 min | 1,500 | 1,014 (67.6%) |
| UCF-Crime | 30 | 30 | 0 | 33 min 46 s | 1,028 MB | 1.35 h | 145,307 | 30,701 (21.1%) |

All 60: `source = dataset`, `retention_until` NULL, `ready` with a finished extraction,
`dataset_manifest.video_id` set, no `error`. Every CCD clip got a playback copy (MPEG-4
Part 2 originals); no UCF-Crime clip needed one (H.264). `GET /datasets`: both `loaded`,
30 of 30, 0 failed. No stray live worker in ingestion afterwards (K-19).

**Storage** (Docker volumes, after minus before): `video_storage` +1.07 GB (originals plus
CCD playback copies), `frame_storage` +0.59 GB, `thumb_storage` +0.40 GB: 0.99 GB for 31,715
kept frames, **about 31 KB per kept frame** (frame plus thumbnail).

**CCD kept 67.6%** on these 30 crash clips (57% on 10 in OMNI-318): the dash-cam moves, so
most frames look like motion (K-4). Preliminary, 30 clips; the full-set number moves to
slice 7, on Colab (D-26).

**Not covered:** VIRAT (not loaded, D-26); the full datasets (estimate above); a restart
in the middle of a real load (the resume is covered by `test_dataset_load.py` only); load
time with cameras capturing.

## OMNI-609 · The hand check: 60 lead-up windows checked by eye · 2026-10-10

**Conditions:** the 60 windows of `datasets/hand_check/sample.csv` (D-26: 15 UCF-Crime with
official times, 15 with UCA times, every class in each; 30 CCD crash clips), one window per
clip (UCF-Crime's 30 s one), watched on the check screen (`/windows`, the real stack) by
Ahmad, one pass. Criterion D-27, written before checking: correct when the window ends where
the event visibly begins and shows none of it. Tolerance 1.5 s (the ticket's 1 s widened
after 2 windows, both Verified; a wider tolerance cannot turn a Verified into a Wrong).
Per-class rules for "where the act begins" were added to D-27 as classes came up, each
before the window was judged. Counted by `scripts/hand_check_report.py`; 95% Wilson intervals.

| Event time from | Checked | Correct | Rate | 95% interval |
|---|---|---|---|---|
| UCF-Crime, official annotation | 15 | 13 | 87% | 62-96% |
| UCF-Crime, UCA (D-21) | 15 | 10 | **67%** | 42-85% |
| UCF-Crime, both | 30 | 23 | 77% | 59-88% |
| CCD, `binlabels` | 30 | 30 | **100%** | 89-100% |

**Every Wrong:**

| Clip | Source | Window | Verdict and what was seen |
|---|---|---|---|
| Abuse035 | UCA | 0.0-0.3 s | ends too early: abuse starts ~0:02.3 |
| Arrest011 | UCA | 21.9-51.9 s | ends too late: guards take him down and hold him; the window ends at the police cuffing |
| Arrest030 | official | 154.5-184.5 s | ends too late: police hold them at gunpoint ~3:01.8 |
| Burglary032 | official | 13.0-43.0 s | ends too late: thieves inside ~0:22.9 |
| Robbery006 | UCA | 0.0-15.8 s | ends too late: thief threatens customer ~0:13 |
| Shooting039 | UCA | 0.0-9.7 s | ends too early: gun pointed ~0:12.8, first shot ~0:23.9 |
| Stealing043 | UCA | 20.6-50.6 s | ends too late: men take items from ~0:10 to ~1:56; the UCA time is mid-theft |

**What it says:** CCD's frame labels are right on every clip checked. UCF-Crime windows are
right about three times in four; **UCA-timed ones are wrong twice as often as official ones**
(5 of 15 against 2 of 15), and 5 of the 7 Wrongs *end too late*: the event is already on
screen inside the window, which would teach a predictor to recognise the event, not foresee
it. Recorded as K-20 for slice 9.

**Not covered:** one checker, one pass, no second opinion; 15 clips per UCF-Crime source is
too few to tell the two rates apart with confidence (the intervals overlap); only the 30 s
window of each UCF-Crime clip was checked (the 60 s one ends at the same time, so it shares
the verdict); negative windows were not checked.

## OMNI-610 · Dashboard aggregates: equal to a direct count, and their speed · 2026-10-11

**Conditions:** the real stack (`docker compose up -d`) on the machine above, simulator
running, no camera registered, after migration `9b4e6d2a7c31` and
`scripts/backfill_dashboard_rollup.py`. The archive at its full size after D-26: 60 dataset
videos, **146,807 segment rows** (31,715 admitted), 3 rollup rows. `scripts/measure_dashboard.py`, two
runs (the first re-gated at `cell_threshold` 10, which changed no frame, so it was run again
at 60), through nginx (`https://localhost/api`), client-side time per call; the second is shown.

**Backfill:** `file_bytes` filled on 31,715 rows from the disk, 0 files missing; rollup
146,807 / 31,715 / 989,872,990 bytes, a direct count the same. 37 s.

**Exactness on the real pipeline** (summary and rollup against a direct count over
`segments` and `videos`, after each step):

| Step | Segments | Admitted | Videos | Storage (GB) | Equal |
|---|---|---|---|---|---|
| Before | 146,807 | 31,715 | 60 | 2.035 | yes |
| CCD `000026.mp4` uploaded and extracted (ingestion → queue → consumer) | 146,857 | 31,755 | 61 | 2.039 | yes |
| Re-gated at `cell_threshold` 60 (40 → 10 admitted) | 146,857 | 31,725 | 61 | 2.037 | yes |
| Deleted | 146,807 | 31,715 | 60 | 2.035 | yes |

All 40 admitted rows the consumer stored carried their file bytes.

**Timing,** 100 calls each after 5 warm-up calls, one at a time:

| Endpoint | p50 | p95 | max |
|---|---|---|---|
| `GET /dashboard/summary` | 41.4 ms | 71.6 ms | 81.5 ms |
| `GET /dashboard/activity?hours=24` | 15.2 ms | 35.9 ms | 55.0 ms |

For comparison, one direct `count(*)` over the 146,807 rows took 18.5 ms in the database
alone. The summary's time includes asking ingestion for its workers (`cameras_online` is
`GET /cameras/live`'s state). A first run gave 41.0 / 81.9 ms and 16.4 / 42.2 ms.

**What it says:** the counts equal a direct count after an insert, a re-gate and a delete on
the real pipeline. Both endpoints answer in tens of milliseconds and read 3 rollup rows,
whatever the size of `segments`.

**Not covered:** the archive is 146,807 rows, not the millions the ticket expected before
D-26, so a direct count is still fast here; the rollup's advantage at millions of rows is by
construction (it reads one row per hour and source), not measured. Two runs, one machine
(preliminary). No camera registered, so `cameras_online` was 0 of 0. The cost of the trigger
on the consumer's throughput was not measured. `storage_gb` does not count 1.05 GB of files
with no row, nor playback copies (K-21).

## OMNI-611 · The Operations Dashboard against the API · 2026-10-11

**Conditions:** the real stack, Chrome on `http://localhost:3000`, signed in as the admin,
one pass. API values read through nginx by a throwaway admin at the same moments.

| Figure | Page | API |
|---|---|---|
| Cameras online | 0 / 0 | `cameras_online` 0, `cameras_total` 0 |
| Footage held | 60 → 61 → 60 | `videos` 60 → 61 → 60 |
| Segments indexed | 146,807 → 146,857 → 146,807 | same |
| Storage in use | 2.04 GB | `storage_gb` 2.035 → 2.036 → 2.035 |
| Datasets | 60 / 60 | `GET /datasets`: 30 + 30 loaded of 30 + 30 |
| Activity, current hour | 0 → 50 → 0 | `segments` of the last hour 0 → 50 → 0 |

The arrows are one CCD clip uploaded and extracted, then deleted, while the page stayed
open; the page followed within one 30 s refresh, without a reload. Refresh timing: summary
requests 30.0 s apart; none in 70 s with the tab hidden (simulated); one at once on return.

**Not covered:** an analyst's view; a real hidden tab; nginx (`https://localhost`); the
datasets screen behind its link (OMNI-612).

## OMNI-612 · The Datasets screen: a load from the screen moves the counts · 2026-10-15

**Conditions:** the real stack, Chrome on `http://localhost:3000`, signed in as the admin by
Ahmad, one pass. Under D-26 the product holds only the hand-check sample and its 30 CCD
clips were all loaded, so "10 more" was read as: the 10 last sampled CCD clips by key
(`Crash-1500/000982` to `001459`) deleted with the archive's own delete function, then loaded
from the screen (Ahmad clicked Load, limit 10).

| Figure | Before the delete | After the delete | After the load |
|---|---|---|---|
| Datasets screen, CCD videos loaded | 30 / 30, Loaded | 20 / 30, Partly loaded | 30 / 30, Loaded |
| Dashboard, footage held | 60 | 50 | 60 |
| Dashboard, segments indexed | 146,807 | 146,307 | 146,807 |
| Dashboard, storage (`storage_gb`) | 2.035 | 2.003 | 2.035 (page 2.04 GB) |
| Dashboard, current hour's bar | 0 | 0 | 500 |

- The load: `POST /datasets/ccd/load` 202, then 10 clips stored and extracted in 28 s
  (created 08:59:11 to 08:59:36 UTC, about 2.8 s per clip); the screen polled `GET /datasets`
  every 2 s while it ran and stopped after. All 10 back as `source = dataset`, no retention date
- Window counts on the screen equal to the database: CCD 4,500 derived, 30 checked, 30
  verified; UCF-Crime 3,260, 30, 23 (OMNI-609's result). The 30 CCD verdicts survived the
  delete and reload (they sit on the windows, not the videos)
- Links followed: dashboard → Datasets → CCD's windows (`/windows?dataset=ccd`, 30 rows, all
  CCD) → a reloaded clip's window, whose player points at the new video's playback file

**Not covered:** the progress bar seen mid-load (the load ended before my screenshot; the
2 s polls are in the query log); an analyst's or operator's view (no Load control); a load
that fails or is refused, seen on screen; nginx
(`https://localhost`).


## OMNI-613 · The motion grid in one array operation: frame cost and NFR-4 again (preliminary) · 2026-10-16

**The change:** Algorithm 1's lines 4-5 compute the 8x8 grid's 64 cell means in one array
operation (`_cell_means` in `services/ingestion/app/pipeline.py`: a reshape and an integer sum
when the frame divides the grid evenly, an integral image otherwise) instead of 64
`np.array_split` slices and 64 `.mean()` calls. The same cells, the same arithmetic (exact
integer sum over pixel count); every frame still gated, Algorithm 1 unchanged.

**Scores identical:** `test_motion_gate.py`, the first 300 frames of each of the ten simulator
clips (VIRAT 1280x720, UCF-Crime 320x240) through the gate with the defaults (G 8, τ 25, k 3,
Δ 0.5 s, blur 21), once each way: the same score and the same admission on every frame; 100
random frames at five sizes, three of them uneven, with the cell means bit-for-bit equal.

**Frame cost** (`scripts/frame_cost.py`, in the ingestion container, no camera capturing, 900
frames, before and after alternated, 3 runs each; "before" is HEAD's `pipeline.py` copied
into the container beside the new one):

| Clip | Gate + files, before | Gate + files, after | Total a frame, before | Total, after | Of a core, before → after |
|---|---|---|---|---|---|
| `real01` VIRAT, 1280x720, 23.97 fps | 9.32 / 17.78 / 9.13 ms | 7.46 / 6.96 / 7.43 ms | 11.97 / 23.17 / 11.72 ms | 10.59 / 9.80 / 10.46 ms | 0.28-0.29 → 0.24-0.25 |
| `real04` UCF-Crime, 320x240, 30 fps | 3.56 / 3.42 / 3.37 ms | 2.03 / 1.99 / 2.28 ms | 4.51 / 4.36 / 4.25 ms | 3.49 / 3.41 / 3.84 ms | 0.13-0.14 → 0.10-0.12 |

The gate's own step is about 1.8 ms cheaper a frame in HD (20%) and 1.4 ms in SD (40%). Run 2's
HD "before" (17.78 ms) is an outlier: every step was slower in it, decode too. SD decode read
0.79-0.86 ms before and 1.31-1.43 ms after in every pair, though the change does not touch
decoding; not explained. These numbers are lower than OMNI-509's (15.2 / 4.2 ms in all), taken
on another day; only the before/after pairs here are compared.

**NFR-4 ladder** (`scripts/measure_nfr4.py`, the definition of sustained unchanged from
OMNI-509; the realistic mix `--paths 4,1,5,6,2,7,8,3,9,10`; D-18 and D-20 as before; the wall
open at 4x4 in Chrome, visible at every recorded sample, with an in-page recorder of
visibility, layout, tile badges and preview requests; one run per row):

| Feeds | Window | Dropped per feed | Worst latency | Not live (API, per feed) | Ingestion / all containers | Sustained | Before (D-19 ladder) |
|---|---|---|---|---|---|---|---|
| 4 | 180 s | 0 | 1.11 s | none | 98% / 252% | yes | yes, 155% / 344% |
| 5 | 180 s | 0 | 0.47 s | none | 149% / 303% | **yes** | no |
| 6 | 180 s | 0-4 (`cam05`) | 1.15 s | `cam05` 2 samples | 192% / 387% | no | no, 0-256 dropped, 7.62 s |
| 5 | **600 s** | 0 | 0.38 s | `cam01` 2, `cam05` 4, `cam02` 3 of 603 | 145% / 301% | **no** | not run |
| 4 | **600 s** | **0** | 0.82 s | `cam01` 2 of 601 | 90% / 229% | **no** | no, 0/0/8/0 dropped, 1-4 samples every feed, 149% / 331% |

The wall in the same windows: one preview request a second per tile (2,400 in the 4-feed 10-minute
run, 2,379 200 and 21 304, p50 38 ms, p95 85 ms); tiles not `Live` on screen: 5 feeds over 3
minutes `cam02` Frozen 2 s; 6 feeds `cam05` 2 s; 5 feeds over 10 minutes `cam05` 6 s and
`cam01` 2 s; 4 feeds over 10 minutes `cam05` 2 s. The first 4-feed run's first ~40 s of the
window has no tile or layout record (the recorder was being fixed); visibility was recorded
throughout. A first 4-feed 10-minute run was killed by the host at about 300 s for low memory,
before its verdict; its leftovers were removed by hand and it was rerun (the row above).
Live queue 0 (peak 1) and file queue 0 in every run; no run dropped a frame except 6 feeds.

**Result:** the grid costs less, and the machine has more headroom at the same load (4 feeds:
ingestion 90-98% instead of 149-155%; no frame dropped over 10 minutes where 8 were before; 5
feeds now hold for 3 minutes). **The sustained number does not change:** 4 feeds over 10
minutes fail on one criterion, one feed not `live` for 2 seconds. NFR-4 stays at 3 (D-19).

**Not covered:** 3 feeds over 10 minutes rerun with the change (D-19's 3 was measured before
it, with more work a frame); more than one run per row; why a feed briefly reads not live with
the machine at 229% of 800% (the D-17 steadiness rule under hiccups, not measured); another
machine.


## Slice 6 definition of done · 2026-10-16

**Conditions:** on `master` after the slice 6 merge; `docker compose down`, then `up -d`
(volumes kept: the 60-clip hand-check sample stays loaded, D-26). The machine as stated at
the top. The scripted part is `scripts/verify_slice6_dod.py` (new) against the real API
through nginx; the on-screen part in Chrome at `https://localhost`, signed in as admin by
Ahmad. One pass.

| Step | How | Result |
|---|---|---|
| Suite on `master` | `uv run pytest` | 469 passed, 1 failed (K-14, `75 == 76`; 5 of 5 alone after), 1 skipped |
| Dashboard accurate, fresh | script: `GET /dashboard/summary` against a direct count | equal: 60 videos, 146,807 segments, 31,715 admitted, 2.035 GB, 0 cameras |
| Datasets accurate, fresh | script: `GET /datasets` against the database | equal: CCD 30 / 30, 4,500 windows, 30 checked, 30 verified; UCF-Crime 30 / 30, 3,260, 30, 23 |
| Delete through the archive | script: `DELETE /videos/{id}` for the last 3 sampled UCF-Crime clips (`Stealing043`, `Vandalism007`, `Vandalism034`) | 200 each; dashboard equal to a direct count again (57 videos, 139,092 segments, 1.957 GB); UCF-Crime 27 / 30, partial |
| Load through the normal pipeline | script: `POST /datasets/ucf_crime/load` (limit 3), poll `GET /datasets` | 202, 3 queued; done in **148 s**, 30 / 30, 0 failed |
| The clips back as before | script, per clip | new video rows (3223-3225), `ready`, `source = dataset`, no retention date, in `GET /videos?source=dataset`; rows 4,813 / 1,146 / 1,756 and admitted 1,032 / 187 / 588, **identical** to before the delete |
| Their windows | script, per sampled window | each points at the new video, verdict kept (Wrong / Correct / Correct), playback file 206 on a range request |
| Dashboard accurate after | script | equal again: 60, 146,807, 31,715, 2.035 GB; both datasets 30 / 30 |
| Load progress on screen | Datasets screen during the load | UCF-Crime "Loading", 27 / 30, "0 of 3 queued clips done", both Load buttons disabled ("A load is running") |
| Dashboard live | dashboard open during the load, read twice 30 s apart, same document | 2:49:12 PM: 59 videos, 143,975 segments, 58 / 60; 2:49:42 PM: 60, 145,651, 59 / 60; 2:50:42 PM: 60, 146,807, 2.04 GB, 60 / 60 (equal to the database) |
| Every figure leads somewhere | the dashboard's links | cameras → `/live`; footage, segments, storage, activity → `/videos`; datasets → `/datasets`; clicked: dashboard → Datasets → UCF-Crime's Windows (`/windows?dataset=ucf_crime`) → `Vandalism007` |
| Windows spot-checked on screen | `/windows/10961` | the reloaded clip (new playback file, 38.2 s) loads and plays (0 → 2.9 s in 3 s); "shortened" window 0.0-8.0 s of 30 s; verdict Correct by the admin, 2026-10-10, kept |
| In the archive | Video Archive | the three clips listed, Ready, linking to `/videos/3223`-`3225` |

**Result: the definition of done holds on a fresh stack** (preliminary: one machine, one
pass). The load progress bar, not seen on screen in OMNI-612, was seen here.

**Not covered:** a wiped stack (`down -v`; the 36-minute reload of the sample was not
redone); a CCD load (done in OMNI-612); the "Play window" button (the video was played from
the page's own element); a second browser; an analyst's or operator's view.

## OMNI-702 · The VIRAT demo sample loaded into the product · 2026-10-18

**Conditions:** the real stack (`docker compose up -d`, simulator running, no cameras, no
live worker in ingestion before or after, K-19), on this laptop. The 9 videos of
`datasets/demo/virat_sample.csv` (D-26 amended: one per scene among videos under the 500 MB
upload limit, seed 702) copied from Drive (`scripts/copy_dataset_subsets.py`: 9 copied, 60
already local, sizes equal to Drive, 96 s), then loaded through `POST /datasets/virat/load`
via nginx (`scripts/run_dataset_load.py virat`): `store_video` (the upload path), then
extraction, one clip at a time. One run.

| Scene | Clip | Video | Resolution | Length | Size | Frames gated | Kept | Motion | Heartbeat | Extract |
|---|---|---|---|---|---|---|---|---|---|---|
| 0002 | VIRAT_S_000207_00_000000_000045 | 3226 | 1280x720, 30 fps | 45.0 s | 47.5 MB | 1,350 | 44 | 0 | 44 | 39 s |
| 0100 | VIRAT_S_010005_01_000085_000164 | 3227 | 1280x720, 24 fps | 70.2 s | 8.2 MB | 1,682 | 70 | 0 | 70 | 30 s |
| 0101 | VIRAT_S_010115_04_000830_000892 | 3228 | 1280x720, 24 fps | 57.7 s | 11.1 MB | 1,382 | 57 | 0 | 57 | 27 s |
| 0102 | VIRAT_S_010201_03_000270_000359 | 3229 | 1280x720, 24 fps | 87.9 s | 9.5 MB | 2,106 | 198 | 121 | 77 | 38 s |
| 0400 | VIRAT_S_040000_06_000746_000964 | 3230 | 1920x1080, 30 fps | 218.0 s | 490.6 MB | 6,533 | 217 | 0 | 217 | 5 min 0 s |
| 0401 | VIRAT_S_040103_00_000000_000120 | 3231 | 1920x1080, 30 fps | 120.0 s | 271.2 MB | 3,594 | 206 | 90 | 116 | 3 min 2 s |
| 0500 | VIRAT_S_050000_13_001722_001766 | 3232 | 1920x1080, 30 fps | 43.9 s | 57.9 MB | 1,316 | 61 | 18 | 43 | 36 s |
| 0502 | VIRAT_S_050202_00_000000_000105 | 3233 | 1920x1080, 30 fps | 105.0 s | 139.5 MB | 3,147 | 107 | 3 | 104 | 1 min 27 s |
| 0503 | VIRAT_S_050300_04_001057_001122 | 3234 | 1920x1080, 30 fps | 65.0 s | 85.0 MB | 1,947 | 79 | 16 | 63 | 1 min 0 s |
| **All** | | | | **13.5 min** | **1,120.6 MB** | **23,057** | **1,039 (4.5%)** | **248** | **791** | |

"Extract" is from the video row's creation to its last segment row, so it includes storing
and probing. The whole load: **13 min 37 s** (09:05:39 to 09:19:16 UTC). [corrected 2026-10-29: the per-video rows add to 1,039 kept, 791 heartbeat, 4.5%; the total was mis-added. Postgres holds 1,039 admitted segments for these 9 videos (OMNI-708's export)]

All 9: `source = dataset`, `retention_until` NULL, `ready` with a finished extraction,
`dataset_manifest.video_id` set, no `error`. Two got a playback copy (3226, 3231). `GET
/datasets`: `virat` `loaded`, 9 of 9, 0 failed; CCD and UCF-Crime unchanged (30 of 30 each).

**Storage**, measured per video in the volumes (no whole-volume before/after this time):
originals 1,120.6 MB, playback copies 60.6 MB, kept frames 296.9 MB, thumbnails 12.8 MB:
**1.49 GB** in all. **About 298 KB per kept frame** [corrected 2026-10-29: was 326 KB, from the mis-added 949] (frame plus thumbnail), ten times
OMNI-608's 31 KB: these are 720p and 1080p full frames, UCF-Crime's are 320x240.

**The gate kept 4.5%, mostly heartbeats** [corrected 2026-10-29: was 4.1%]**.** 4 of the 9 videos kept **no frame for motion**,
only the heartbeat (about one a second), and a fifth kept 3, although every one has annotated events (people
and vehicles moving). VIRAT's cameras are far and still, and the people are small in a
1080p frame. Search on these videos therefore sees about one frame a second plus the
moments the gate called motion. Recorded as K-23; not changed here (Algorithm 1 as Phase A
writes it).

**Not covered:** scenes 0000 and 0001 (no video under the upload limit, D-26); the gate's
recall against VIRAT's event annotations (K-23); load time with cameras capturing; one run.

## OMNI-703 · TC-3, frame half: `frame_vectors` in Qdrant, across a restart · 2026-10-19

`scripts/verify_tc3_frame_vectors.py` on the real stack (Qdrant `v1.19.1`, `qdrant-client`
1.19.1, no host port; the checks run inside `query`). A scratch collection
`frame_vectors_tc3`, made by the product's `ensure_frame_collection` (1152-D, Cosine, payload
indexes on `camera_id`, `video_id`, `captured_at`), 1,000 points made by `frame_point` from
seed 703: 500 uploads over 5 videos, 500 live frames over 10 cameras, three domains, 143
without a thumbnail, random unit vectors. Written in batches of 100, then the first 100
written again; checked; `docker compose restart qdrant`; checked again; dropped.

| Check | Run 1 before / after restart | Run 2 before / after restart |
|---|---|---|
| Points after a redelivery of 100 | 1,000 / 1,000 | 1,000 / 1,000 |
| By id: payload equal (dict and canonical JSON bytes) | 1,000 / 1,000 | 1,000 / 1,000 |
| By id: vector bit-identical to the float32 written | 1,000 / 1,000 | 1,000 / 1,000 |
| Filtered search (own video or camera, exact `captured_at`): own point top hit, payload equal | 1,000 / 1,000 | 1,000 / 1,000 |
| Point count under each of 5 video and 10 camera filters | 15 / 15 | 15 / 15 |
| Write 1,000 points | 2.93 s | 2.33 s |
| Healthy again after the restart | 4.8 s | 4.7 s |

**The run before these failed.** With `timestamp_s` stored as given, 66 of 1,000 payloads
came back different, all upload frames whose time needs 17 significant digits
(`0.9175842509175843` read back as `0.9175842509175844`); the raw HTTP response showed the
changed value, so it is Qdrant, not the client. Searches found all 1,000; the 66 failed only
on payload equality. Fixed by storing `timestamp_s` to the microsecond (D-29); the live
frames' times then got a full-precision random fraction too, to test the fix on both sources.

Also: `query` created `frame_vectors` on its first start, and on a restart only checked that
it exists (no create request in its log); `curl http://localhost:6333` from the host fails
(exit 7, nothing listening).

**Not covered:** real SigLIP 2 vectors and real segment rows (OMNI-704, OMNI-705); a
collection at archive size (slice 7 holds about 1,000 admitted VIRAT frames plus the
hand-check sample's); `docker compose down` and up, and a kill (only `restart`); search
latency (OMNI-708). One machine, two runs.

## OMNI-704 · SigLIP 2 on this laptop's CPU (no GPU; information, not pass/fail) · 2026-10-19

`scripts/measure_encoder.py --frames 8 --batches 2`: the pinned checkpoint (D-30), float32,
PyTorch 2.14.1+cpu with 4 threads, in a one-off `ai-workers` container (service stopped, the
rest of the stack up and idle). Frames: VIRAT demo video 3233's stored admitted frames,
1920x1080 JPEGs. One run. An earlier run with 32 + 64 frames was killed by Claude Code when
Windows ran low on memory (2.6 GB of 15.7 GB free); nothing from it is reported.

| Measure | Result |
|---|---|
| Model load (weights memory-mapped) | 6.8 s |
| First image (reads the vision weights from disk) | 27.7 s |
| First text (reads the text weights) | 18.8 s |
| Image, batch 1, per frame (8 frames) | median 8,747 ms, p95 9,962 ms, 8,252-10,135 |
| Image, batch 8, per frame (2 batches) | median 9,288 ms, 9,025-9,551 |
| Text, per query (20 queries) | median 1,221 ms, p95 1,919 ms, 797-2,408 |
| Process RSS, peak / service idle / service after 20 queries | 4.23 / 3.83 / 3.84 GiB |
| `docker stats`, same moments | 1.01 / 0.64 / 0.64 GiB (leaves out the mapped weights) |
| Service: start to healthy (load plus warm-up) | 80 s |
| First query to the warmed service (through `docker exec`) | 2.4 s |

**What it means:** about 9 s per frame on this CPU, and batching does not help here. An
admitted frame is about one a second per camera, so this machine's CPU cannot keep up with
one camera, and a frame alone takes longer than NFR-1's 5 s. Phase A puts the AI Workers on
a GPU (§3.3.2); the GPU cost is measured on Colab (D-31: how
NFR-1 and NFR-2 are judged). It fits in memory: about 4.2 GiB of Docker's 7.6 GiB.

**Not covered:** a GPU; more than 8 + 16 frames; text queries timed through query's API
(OMNI-708); preliminary, one run, one machine.

## OMNI-704 · TC-2, frame half: an upload's and a camera's admitted frames encoded · 2026-10-19

`scripts/verify_tc2_frames.py` on the real stack. The first 30 s of VIRAT demo video 3229
(scene 0102, `VIRAT_S_010201_03_000270_000359`, 1280x720, 24 fps) re-encoded to H.264 and
uploaded through nginx, extracted by the product (Algorithm 1): `ready`, 30.04 s, 720 frames
gated. `cam05` from the simulator registered and started, 30 s captured after it read `live`,
stopped. Every admitted frame's `frame_path` read from Postgres and encoded from the stored
JPEG by `FrameTextEncoder.encode_images` (D-30), batches of 8, in a one-off `ai-workers`
container with the service stopped. One run, laptop CPU.

| Source | Admitted frames | Vectors | Errors | 1152-D, finite, unit length | Norms | Encode time (CPU) |
|---|---|---|---|---|---|---|
| Upload | 136 | 136 | 0 | 136 of 136 | 0.9999998-1.0000001 | 1,160.5 s (8.5 s/frame) |
| Camera | 41 | 41 | 0 | 41 of 41 | 0.9999999-1.0000001 | 360.3 s (8.8 s/frame) |

8 of 8 checks. The throwaway user and camera were removed by the script. The uploaded video
was not: the encode outlasted the token's 15 idle minutes (NFR-9) and the delete got no
answer it checked. Deleted afterwards through the API (200; rows and files gone); the script
now logs in again before cleaning up and reports a failed delete.

**Not covered:** the vectors written to Qdrant (OMNI-705); the clip embedding (slice 8);
GPU timing (OMNI-710, D-31); one run.

## OMNI-705 · Every admitted frame reaches the encoder: a kill mid-batch · 2026-10-28

The real stack (`docker compose up -d`), laptop CPU, the pinned SigLIP 2 (D-30), batches of
8. One VIRAT demo video, 3226 (scene 0002, `VIRAT_S_000207_00_000000_000045`), 44 admitted
frames, none with a point before. `scripts/backfill_embeddings.py queue --video 3226`
published 44 jobs to `omnisight.embed` at 14:09:37; ai_workers consumed them.

| Moment | Frames with a point | Points | Ready in the queue | Dead letters |
|---|---|---|---|---|
| Before | 0 of 44 | 0 | 0 | 0 |
| 2 batches stored, `docker compose kill ai-workers` 14 s into the 3rd (14:13:48) | 16 of 44 | 16 | 28 (the 8 in flight came back) | 0 |
| Restarted 14:14:09, healthy 14:15:41, done 14:20:25 | **44 of 44** | **44** | 0 | 0 |

`check --video 3226`: missing 0, the model's points for the video = 44 = frames with a
point (no extra, no duplicate). `GET /embeddings/status` from inside the stack: video 3226
`frames_total` 44, `frames_embedded` 44, `clips_embedded` 0. After the restart the worker
encoded the remaining 28 in 4 batches (8, 8, 8, 4). Batches took 72-134 s for 8 frames
(9-17 s a frame; the first was slower, the stack had just started).

**Not covered:** one video, one kill, at one moment (mid-encode; not between the upsert and
the acks, a window of milliseconds, covered by idempotent upserts and the unit tests); a
kill of the consumer between commit and publish on the real stack (unit test only); a new
upload or a running camera producing jobs on the real stack (unit tests only); the other
34,725 admitted frames (D-35); preliminary.

## OMNI-706 · InternVideo2 on this laptop: the text side beside SigLIP 2, and one clip · 2026-10-28

**Conditions:** this laptop (i7-1165G7, Docker Desktop 8 CPUs, 7.6 GiB), the whole stack up
and idle, the embed queue empty. ai_workers rebuilt with both text encoders (SigLIP 2, D-30;
InternVideo2-CLIP-S text side only, D-32, D-33). `scripts/measure_text_encoders.py --runs 20`:
10 search-style queries, one warm-up round, then 20 rounds per encoder, one at a time, sent
from inside `query` (HTTP round trip in the Docker network). Memory: the uvicorn process's
`VmRSS` / `VmHWM`, as OMNI-704 (`docker stats` leaves out the memory-mapped weights).

| Measure | Result |
|---|---|
| Start to healthy: SigLIP 2 load + warm-up / InternVideo2 text load + warm-up | 14.1 s + 87.0 s / 12.6 s |
| InternVideo2 text, per query (200) | median 131 ms, p95 300 ms, max 517 ms |
| SigLIP 2 text, per query (200) | median 1,097 ms, p95 1,885 ms, max 2,188 ms |
| Process RSS after 400 queries / peak | 3.84 GiB / 4.17 GiB |
| `docker stats` before / after | 988 / 1,004 MiB |

OMNI-704 measured SigLIP 2 alone at 3.84 GiB after its queries, 4.23 GiB at peak: the
63M-parameter text tower (about 0.25 GB in float32) does not show as a separate step at this
resolution, and the total fits in 7.6 GiB with about 3.4 GiB to spare.

**One clip and one text** (outside the service, `uv run`, CPU, float32): VIRAT
`VIRAT_S_040103_00_000000_000120`, event 29 (type 3, opening a trunk, frames 2489-2577),
8 frames at 2494, 2505, ..., 2571. Clip vector 512-D, text vectors 512-D, all finite, norm
1.0. Full model load 36 s, 3.0 GB RSS; the clip took 29.6 s on this CPU, 4 texts 0.4 s.
Similarity of the clip to *opening the trunk* 0.097, *closing the trunk* 0.100, *getting
into a car* 0.121, *a dog running on grass* -0.002: one clip says nothing about motion; that
is the 10-clip check on Colab.

**Not covered:** the GPU timings and the motion check (`notebooks/encoders_gpu.ipynb`, to
run on Colab's A100); the text encoders under load together with frame encoding; one run,
one machine, preliminary.

## OMNI-706 · InternVideo2's motion check and both encoders' cost on a GPU · 2026-10-28

**Conditions:** Colab, **NVIDIA L4** (22 GiB; the ticket names an A100, none was free, Ahmad's
choice, D-31: an L4 is slower, so these are upper bounds for an A100), torch 2.11.0+cu130,
transformers 5.20.1. `notebooks/encoders_gpu.ipynb` at commit `1ff7fd0`, importing the
repo's `encoder.py` and `clip_encoder.py`; both checkpoints at their pinned revisions
(D-30, D-33), float32, both on the GPU together. Raw output:
`MyDrive/omnisight/results/omni706_encoders_gpu.json`. One run.

**One clip and one text** (the laptop's CPU check, repeated on the GPU): 512-D, finite,
norm 1.0; similarity to *a person opening the trunk of a car* 0.0967, the same as on the CPU.

**Does it see motion.** 10 clips, 2 per type, drawn with seed 706 from the 275 VIRAT
evaluation videos (events at least 8 frames long; 42 to 156 candidates per type); each clip
is its event's own span, 8 frames by `uniform_indices`. One caption per clip, two wordings
per type. Rows are clips, columns captions; the highest in each row in bold.

| Clip (type, video, event) | c0 | c1 | c2 | c3 | c4 | c5 | c6 | c7 | c8 | c9 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 open trunk, 050202_07_001126_001301 e1 | 0.091 | 0.096 | 0.098 | 0.117 | 0.123 | **0.132** | 0.128 | 0.110 | 0.110 | 0.089 |
| 1 open trunk, 000202_00_000000_000977 e18 | 0.083 | 0.088 | 0.086 | 0.109 | 0.125 | 0.101 | **0.129** | 0.092 | 0.100 | 0.054 |
| 2 close trunk, 040005_07_001026_001223 e39 | 0.045 | 0.058 | 0.047 | 0.076 | 0.072 | 0.059 | 0.083 | 0.053 | **0.093** | 0.051 |
| 3 close trunk, 040103_02_000199_000279 e12 | 0.126 | 0.130 | 0.130 | 0.148 | 0.154 | 0.127 | **0.161** | 0.123 | 0.132 | 0.096 |
| 4 into vehicle, 040103_00_000000_000120 e27 | 0.098 | 0.101 | 0.103 | 0.126 | 0.127 | 0.114 | **0.133** | 0.104 | 0.103 | 0.079 |
| 5 into vehicle, 040000_06_000746_000964 e13 | 0.054 | 0.069 | 0.055 | 0.083 | 0.078 | 0.066 | 0.089 | 0.058 | **0.091** | 0.049 |
| 6 out of vehicle, 000101 e28 | 0.128 | 0.137 | 0.132 | 0.144 | 0.175 | 0.144 | **0.188** | 0.152 | 0.187 | 0.160 |
| 7 out of vehicle, 040103_03_000284_000425 e40 | 0.112 | 0.121 | 0.115 | 0.135 | 0.153 | 0.125 | **0.161** | 0.132 | 0.140 | 0.104 |
| 8 enter facility, 010205_04_000545_000576 e3 | 0.028 | 0.045 | 0.027 | 0.058 | 0.095 | 0.086 | 0.108 | 0.087 | **0.205** | 0.170 |
| 9 enter facility, 010207_10_001549_001596 e12 | 0.025 | 0.041 | 0.025 | 0.058 | 0.090 | 0.084 | 0.103 | 0.087 | **0.198** | 0.169 |

Captions: c0 *a person opening the trunk of a car*, c1 *someone lifting open a car's trunk*,
c2 *a person closing the trunk of a car*, c3 *someone shutting a car's trunk*, c4 *a person
getting into a car*, c5 *someone climbing into a vehicle*, c6 *a person getting out of a
car*, c7 *someone stepping out of a vehicle*, c8 *a person walking into a building*, c9
*someone entering a building through a door*.

| Measure | Result |
|---|---|
| Clips whose own caption ranks first | **2 of 10** (6, 8) |
| Clips whose first caption is of their own type | **4 of 10** (6, 7, 8, 9); chance is 2 of 10 |
| Per type | entering a facility 2/2, getting out of a vehicle 2/2, getting into 0/2, opening a trunk 0/2, closing a trunk 0/2 |
| Opening against closing a trunk | Not told apart: all 4 trunk clips rank a vehicle or building caption first, and each scores *shutting a car's trunk* (c3) above both opening captions |
| One caption wins most rows | c6 *a person getting out of a car* is first for 6 of 10 clips |

**What it means:** on these 10 clips the model puts a clip near the right *scene* (cars, a
building's door) but does not tell the trunk actions apart and barely separates the vehicle
actions. Similarities are low throughout (0.03-0.21). Why is not tested here: VIRAT's
people are small in 1920 x 1080 frames that the checkpoint squeezes to 224 x 224, but that
is a guess. This is a sanity check on 10 clips, not SM-1: search quality is measured on the
labelled query set (OMNI-709, OMNI-713), with both streams fused.

**GPU cost.** 5 warm-up calls, then the median of 20, `torch.cuda.synchronize()` around
each. Frames from the stored full-frame JPEG (read, resize, encode: what ai_workers does);
clips from 8 decoded 1920 x 1080 frames in memory (resize and encode). Peak GPU memory per
measurement, both models loaded (weights: SigLIP 2 4.23 GiB, InternVideo2 1.43 GiB).

| Encoder | Batch 1 | Batch 8 | Batch 32 | Peak GPU memory (b1 / b8 / b32) |
|---|---:|---:|---:|---:|
| SigLIP 2, ms per frame | 108 | 106 | 112 | 5.71 / 5.97 / 6.87 GiB |
| InternVideo2, ms per clip | 297 | 319 | 316 | 5.76 / 6.40 / 8.57 GiB |
| SigLIP 2 text, ms per query | 13.3 | | | 5.67 GiB |
| InternVideo2 text, ms per query | 7.4 | | | 5.67 GiB |

Batching does not lower the cost per frame or per clip. Each call includes image work on
Colab's CPU (JPEG decode and resize for a frame, a bicubic resize of eight 1080p frames for
a clip); that this part dominates is likely but **not measured**: the split between CPU
preparation and GPU compute was not timed. Against this laptop's CPU (OMNI-704, OMNI-706):
SigLIP 2 8.7 s → 0.11 s a frame; text 1.1 s → 13 ms (SigLIP 2), 131 ms → 7 ms (InternVideo2).

**Not covered:** an A100; the CPU / GPU split of each call; float16 or TF32 (float32 only,
as D-30, D-33); more than one run; the motion check on more than 10 clips.

## OMNI-707 · `GET /search` on the running stack (frame mode) · 2026-10-28

**Conditions:** this laptop, the whole stack up; ai_workers on the CPU (SigLIP 2 text,
D-30); `frame_vectors` holds the 44 points of VIRAT video 3226 (OMNI-705, D-35), no camera
has a point. `scripts/try_search.py`: three queries, each twice, through the real API
inside `query` as the admin; then a date filter and a camera filter, `mode=fused`, an empty
query. One run.

| Query | First: elapsed (encode / search / join), ms | Again (vector cached), ms |
|---|---|---|
| *a person walking across a parking lot* | 503 after 30,135 (encode timed out, K-26); then 9,291 (9,050 / 213 / 29) | — |
| *a white car driving on the road* | 2,037 (1,985 / 38 / 14) | 82 (0 / 78 / 4) |
| *a person carrying a bag* | 1,900 (1,860 / 26 / 13) | 133 (0 / 120 / 13) |

- Each query: 5 hits from video 3226, ranked by cosine (top scores 0.145, 0.059, 0.022), every
  field set (segment, video, time, `captured_at`, score, `matched_by` = frame, thumbnail
  URL), 0 dropped. The same frame (31.0 s) ranks first for all three
- `from` = `to` = the top hit's `captured_at`: that one hit. `from` in 2100: none. `camera_id=1`:
  none (no camera has a point). `mode=fused`: 503 *the clip index is not ready yet*. `q` of
  spaces: 422 *the query is empty*

**What it means:** with a warm encoder, a query costs about 2 s on this CPU, almost all of it
the text encode; a repeated query skips it and takes 80-130 ms. The search and join over 44
points take 20-210 ms. NFR-2 (results within 3 s) is judged in OMNI-714 with the GPU's encode
time (D-31): 13 ms on an L4 (OMNI-706). After a long idle the first encode exceeded 30 s (K-26).

**Not covered:** relevance (44 frames of one video; SM-1 is OMNI-713); a camera filter on the
real stack (tested with real Postgres and in-process Qdrant: a camera's best frame at cosine
0.4 is found under five 0.75-0.95 frames of another camera); search over a large collection
(TC-4, OMNI-715); one run.


## OMNI-708 · The VIRAT archive on Colab, both streams · 2026-10-29

**Conditions:** Colab, one NVIDIA A100-SXM4-40GB, one session (started 09:39:10). The
repo's code at commit `24f140f`: ingestion's Algorithm 1 gate with the settings' defaults
(0.5 s, 8 x 8, 25.0, 3 cells, blur 21, heartbeat 1.0 s, JPEG 85); SigLIP 2 frame vector from
the stored JPEG; InternVideo2 clip vector of `[t - 1 s, t]`, 8 frames; float32 (D-30, D-33).
Videos read from Drive; decode and gate on Colab's CPU, encoding on the GPU overlapped with
it. One run. `notebooks/virat_archive_gpu.ipynb`; summary in Drive
`omnisight/results/omni708_virat_archive.json`.

| | |
|---|---:|
| Videos (VIRAT evaluation, D-22) | 275 of 275, 0 failed |
| Frames decoded and gated | 793,686 |
| Admitted | 35,704 (4.5%): 8,255 motion, 27,449 heartbeat |
| Frame vectors (1152-D) and clip vectors (512-D) | 35,704 each |
| Run time (sum of per-video times) | 9,076 s, 2.52 h |
| Frames gated per second | 87 |
| Admitted frames encoded per second, both streams | 3.93 (0.25 s a frame, decode and gate included) |

`check` on the archive: every video in the manifest, every file present and its rows equal to
the manifest's counts, no file outside the manifest, 0 problems. The count is above D-37's
estimate of about 30,000 (made from 9 videos).

**The product's segments:** the 1,039 admitted segments of the product's 9 VIRAT videos
(exported from Postgres) matched by `clip_key` and `frame_index`, with equal timestamp and
reason: **1,039 of 1,039**, 0 unmatched; every video's segment count equals its archive
frame count (44, 70, 57, 198, 217, 206, 61, 107, 79).

**Agreement, laptop and Colab:** the 44 frames of video 3226 that have a laptop vector
(OMNI-705, CPU) against the A100's: cosine min 0.999979, median 0.999994, max 0.999997;
**44 of 44 at least 0.999**.

**Not covered:** the kill-and-resume test on Colab (one session ran to the end; resuming is
tested only with stand-in encoders, `scripts/tests/test_encode_virat_archive.py`); the clip
vectors' agreement (the laptop has no video side, D-32); the split of time between decode,
gate and encode; more than one run.
