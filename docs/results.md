# Results

Every measurement, written the week it's taken.

## TC-10 · Protect every endpoint with authentication and role-based authorization — 2026-09-05

**Suite:** `services/query/tests/test_tc10_auth.py`
**Run:** `uv run pytest` — 15 passed, 0 failed.

Endpoints covered (every protected route in `services/query`; `/auth/login`
is the public entry point and `/health` is deliberately public, so neither is
in scope for TC-10):

| Endpoint | Valid token, correct role → 200 | Valid token, insufficient role → 403 | No / expired / tampered token → 401 |
|---|:--:|:--:|:--:|
| `GET /auth/me` | pass | n/a — no role restriction beyond "authenticated" | pass |
| `GET /nav` | pass | n/a — no role restriction beyond "authenticated" | pass |
| `POST /auth/logout` | pass | n/a — no role restriction beyond "authenticated" | pass |
| `GET /admin/ping` | pass | pass | pass |

`/admin/ping` is the only route gated to a specific role (admin) rather than
"any authenticated user," so it's the only one where the 403 condition
applies — that's exactly why it was added in OMNI-107, to make the 403 path
real and testable. "No / expired / tampered" is tested as three separate
cases per endpoint in the suite (no `Authorization` header; a token with
`exp` in the past, signed with the real secret; a valid token with its last
character flipped) — all three return 401 everywhere.

**Test users:** two accounts created at the start of the run
(`tc10-admin@omnisight.local`, `tc10-operator@omnisight.local`) and deleted
at the end — confirmed no `tc10-*` rows remain in `users` after the suite
finishes.

**Requires:** Postgres running (`docker compose up -d`) — the suite hits the
real database, same as everything else verified this sprint.

## NFR-9 · Tokens expire after 15 minutes of inactivity; accounts lock after 5 failed logins — 2026-09-05

**Suite:** `services/query/tests/test_nfr9_lockout_expiry.py`
**Run:** `uv run pytest` — 2 passed, 0 failed.

| Test | Result |
|---|:--:|
| Five failed logins lock the account | pass |
| A token past its inactivity window is rejected | pass |

**Five failed logins:** a throwaway account attempts login with a wrong
password five times in a row. After the fifth, `failed_attempts = 5` and
`locked_until` is set in the future (`account_lockout_minutes` ahead of
`now()`) — confirmed directly against the database. A sixth attempt with the
**correct** password is still refused (`401`), proving the lock is enforced
before password verification, not after.

**Idle token rejected:** a JWT signed with the real `jwt_secret_key` but with
`exp` one minute in the past (simulating a session idle past its 15-minute
window) is rejected with `401` on a protected route. This exercises the same
expiry check that OMNI-108's sliding renewal (`X-Access-Token` header) relies
on — a token that's never renewed because no request was made with it
eventually expires exactly this way.

**Test user:** one throwaway account (`nfr9-lockout-test@omnisight.local`)
created before the test and deleted after — confirmed no `nfr9-*` rows
remain in `users` afterward.

**Requires:** Postgres running (`docker compose up -d`).

## NFR-5 · On any failure or crash, video or stored data lost = 0 — 2026-09-12

**Method:** live checks against the running stack (`docker compose up -d`),
not a `pytest` suite — this is proving real container/volume behavior, not
application logic. All three checks used a real uploaded video, not a
fixture.

| Check | Result |
|---|:--:|
| `docker compose restart` — row and file survive | pass |
| `docker compose down` + `up -d` — row and file survive | pass |
| Kill `query` mid-upload — no orphan row | pass |

**`docker compose restart`:** uploaded a real 5-second, 21,086-byte MP4
(`sha256: 36afef16…b895f`), confirmed via `GET /videos/{id}` and a checksum
of the file on disk. Restarted every container in place. Checksum after
restart: identical. `GET /videos/{id}` after restart: identical record,
same id, same `size_bytes`, same `duration_s`.

**`docker compose down` + `up -d`:** same video, same checks, this time
after fully removing and recreating every container (not just restarting
them) — `docker compose ps -a` showed zero containers between the two
commands, confirming this genuinely tore down and rebuilt the stack, not a
no-op. `docker volume ls` confirmed `phase-b_postgres_data` and
`phase-b_video_storage` — the two volumes this check cares about — survived
the teardown untouched, which is the entire reason OMNI-205 used named
volumes rather than a bind mount to a temp directory. Checksum after:
identical. Login with an existing account and `GET /videos/{id}` both
succeeded with the same record, confirming both volumes (`postgres_data`
for the user row surviving login, `video_storage` for the file) came back
correctly, not just one of the two.

**Kill `query` mid-upload:** the real test, and the one that needed two
attempts to actually exercise. The first attempt sent a request through
nginx with an artificially slow client; killing `query` produced no
database row (correct) but also no partial file at all, because nginx
buffers a client's entire request body before forwarding it upstream by
default (`proxy_request_buffering on`) — the slow client only fooled nginx,
`query` itself had received nothing yet when it died. Second attempt went
directly to `query`'s own published port (bypassing nginx entirely) with a
real, unthrottled 480 MB upload, killing the container from inside the same
Python process that was sending it — timed off the client's own
byte-counter (`docker kill` fired automatically at 40% sent, 201,326,632 of
503,316,480 bytes), removing any dependency on guessing timing across
separate tool calls. The client's request ended with a genuine
`ConnectionAbortedError` (`WinError 10053`), confirming `query` really did
die mid-transfer, not after. After restarting `query`: zero rows for the
interrupted filename, and no orphaned `.part` file either — the row is only
ever created after `services/query/app/videos.py`'s
`staging_path.replace(final_path)` succeeds (OMNI-205), so an interruption
before that point — during either the network receive or query's own
copy-to-volume step — can only ever produce "nothing," never a row pointing
at something incomplete. A first attempt at 450 MB (a smaller multiplier,
sent without instrumented timing) actually completed — write, rename,
insert, probe, response — in well under the ~1–2 seconds it took to react
and issue `docker kill` manually from a separate command, which is itself a
data point: on this stack, a sub-500 MB upload can complete faster than an
operator can interrupt it by hand, which is exactly why the second attempt
timed the kill programmatically instead of by reflex.

**Requires:** Postgres, `query` and `ingestion` running
(`docker compose up -d`); Docker CLI access on the host to actually kill and
restart containers.

## Definition of done — the plan's own demo, fresh — 2026-09-12

**Method:** `docker compose down -v` (wiped `postgres_data`, `video_storage`
and `frontend_node_modules` — a genuinely empty state, not a reused dev
database), `docker compose up -d`, `alembic upgrade head`, two freshly
seeded accounts (one admin, one operator), then the plan's own four-part
demo run end to end.

| Demo step | Result |
|---|:--:|
| Register a camera against the simulator, Test Connection reports resolution and fps | pass — `640x360 @ 15.0 fps`, status `connected` |
| An invalid address reports a specific reason | pass — `error: "unreachable"` |
| Upload an MP4: correct duration and size | pass — 7.000s source, `duration_s: 7.0` exact; `size_mb: 0.03` matching the real file |
| Same upload survives a container restart | pass — file checksum and full record identical before/after `docker compose restart` |
| An operator account cannot delete a camera | pass — `403 {"detail":"insufficient role"}`, camera still present afterward |

All four ran against real containers, real ffmpeg-generated video, and a
real RTSP address served by the OMNI-201 simulator — not mocked, and not
reusing state left over from earlier tickets' verification.

`uv run pytest` afterward — **62 passed** — confirms the wipe and reseed
didn't leave the application itself in a state the rest of the suite
disagrees with.

**Not covered by this entry:** "Merged and pushed" — a git action, out of
scope for a results entry and not done as part of this check.

---

## 2026-09-20 — SM-3 dataset change and target revision

**Decision: DoTA is replaced by CCD (Car Crash Dataset), and SM-3's target is
re-derived from the data rather than fixed at 15 seconds.**

### DoTA is unobtainable

All three Google Drive links in the DoTA repository return 404 — the 55 GB frame
archive, the split archives, and the extras folder. GitHub issue #43 shows several
researchers requesting access since, with no reply from the authors.

The repository still carries `DoTA_urls.txt`, the 184 source YouTube videos the
4,677 clips were cut from. Probed every one with `yt-dlp --simulate` on
2026-09-20:

```
0 alive / 184 dead  (0%)
```

Control URL on the same machine and yt-dlp version resolved normally, so this is
the dataset, not the tooling. DoTA cannot be rebuilt.

### SM-3's 15-second target was never reachable on DoTA

The DoTA annotations survive in the repository, so the clip timings can still be
analysed even though the video cannot. Across all 4,677 clips, at the dataset's
10 fps:

| Measure | Value |
|---|---|
| Median clip length | 9.9 s |
| Mean footage before the anomaly | 3.8 s |
| **Median footage before the anomaly** | **3.6 s** |
| 90th percentile | 5.8 s |
| Maximum | 23.0 s |
| Clips with ≥ 5 s before the anomaly | 903 / 4,677 (19.3%) |
| Clips with ≥ 10 s before the anomaly | 41 / 4,677 (0.9%) |
| **Clips with ≥ 15 s before the anomaly** | **8 / 4,677 (0.2%)** |

Phase A §4.1 sets SM-3 at "warnings fire at least 15 seconds before the event
begins". The dataset Phase A assigned to that metric contains 15 seconds of
pre-event footage in 0.2% of its clips. The target could not have been met on
DoTA under any model.

This is not specific to DoTA. Dash-cam accident datasets are trimmed tight around
the crash: CCD's clips are 5 seconds end to end, DADA-2000's around 10. Published
work in accident anticipation reports time-to-accident in the low single digits.

### The revision

SM-3 keeps its intent — warn early enough to be actionable — and loses the
specific number.

- **Dataset:** CCD (Car Crash Dataset). 1,500 crash clips plus 3,000 normal clips,
  distributed as video files, with per-frame accident labels. Purpose-built for
  accident anticipation.
- **Metric:** mean Time-to-Accident (mTTA), the standard in this literature, so
  the result is comparable to published work rather than to an internal target.
- **Target:** set in slice 6 from the measured distribution of pre-event footage
  in CCD, **before any model is trained**, so it cannot be chosen to flatter the
  result. The full distribution is reported alongside the mean.

Phase A's original 15-second target, this analysis, and the revised target all
belong in the Phase B book. The measurement above was taken in week 4, before any
forecasting code was written.

### Knock-on changes

- CCD replaces DoTA as the traffic domain for SM-2, SM-5 and TC-5
- `data/dota/` renamed to `data/ccd/`
- `docs/datasets.md`, `docs/dataset-layout.md` and the slice plan updated
- Slice 6 gains a task: measure CCD's pre-event distribution and record it here

---

## 2026-09-21 — Dataset footage through the normal upload path (OMNI-300)

**Claim under test:** slice 6 loads three datasets through the normal pipeline, so
a dataset clip must pass through the same upload → probe → `ready` path as a
hand-uploaded one, with correct metadata.

**Method:** one clip from each dataset, from the local subset in `data/`, uploaded
through the Video Archive screen on the running stack. Each clip's source values
were taken first with `ffprobe`; the stored row was then read back from the
`videos` table and compared.

| Dataset | Clip | Status | Duration (stored / source) | fps | Resolution | Bytes (stored = source) | Codec |
|---|---|:--:|---|---|---|---|---|
| CCD | `Crash-1500/000413.mp4` | ready | 5.000 s / 5.000 s | 10 | 640×360 | 232,123 | MPEG-4 Part 2 |
| UCF-Crime | `Anomaly-Videos-Part-1/Arson/Arson049_x264.mp4` | ready | 12.867 s / 12.867 s | 30 | 320×240 | 3,142,046 | H.264 Baseline, + AAC + PNG stream |
| VIRAT | `videos_original/VIRAT_S_010208_07_000768_000791.mp4` | ready | 19.232 s / 19.232 s | 23.97 | 1280×720 | 1,362,385 | H.264 Main |

All three landed `ready`; duration, fps, width, height and byte count equal the
`ffprobe` values on the source. No probe failures.

**Differences from a hand-uploaded clip that slice 6 needs to know:**

- **CCD is MPEG-4 Part 2, not H.264.** It probes and decodes fine in the ingestion
  container. Browsers generally do not play it, and playback was not tested (the
  archive screen has no player), so any playback feature needs a transcode step.
- **VIRAT is 23.97 fps, not 30.** Frame and window arithmetic must use the stored
  `fps`.
- **The local clips are shorter than expected** — VIRAT 19 s, UCF-Crime 12.9 s,
  against "minutes". The local subset was built from the smallest files; the full
  Drive copy was not checked.
- **The archive table handles long filenames badly.** With the VIRAT name, the
  Size and Uploaded cells wrap onto several lines at a 1114 px window and the page
  gets a horizontal scrollbar.

**Not covered:** one clip per dataset only, all short. Nothing was measured on
long files, on variable-frame-rate files (duration is `frame_count / fps`, exact
here but an estimate for some containers), or at bulk-load scale. Full write-up in
`docs/context/week-03-04.md`.

---

## 2026-09-23 — Algorithm 1 motion gating on real dataset footage (OMNI-304)

**Superseded the same day** — see "Algorithm 1 rework" below. This entry measured
the first implementation, a frame-count buffer fed by 1-second sampling. That
sampling step is not part of the algorithm and is exactly what made the CCD
finding below true; the rework replaces both. Left in place as the record of
what was actually measured at the time, not rewritten.

**Claim under test:** FR-1b's motion gate — compare each sampled frame to one
`motion_buffer_frames` samples earlier, score it by counting grid cells with
meaningful change, admit above a threshold — produces a real, inspectable
distinction between still and moving footage, on real recordings, with the
defaults the running service actually uses (`motion_grid_size=8`,
`motion_cell_threshold=25.0`, `motion_min_active_cells=3`,
`motion_buffer_frames=5`, `motion_blur_kernel=21`, `extract_interval_s=1.0`).

**Method:** three clips uploaded and extracted through the real running stack —
two real dataset clips (CCD, UCF-Crime) and the synthetic clip used to verify
extraction in OMNI-303, for comparison. `segments.motion_score` and `.admitted`
read back per frame.

| Clip | Rows | Unscored (warm-up) | Scored | Admitted | Scored score range |
|---|---|---|---|---|---|
| OMNI-303's synthetic 2-minute clip (ffmpeg `testsrc2`) | 120 | 5 | 115 | 115 | 4–6 |
| CCD `Crash-1500/000413.mp4` (5 s, 10 fps) | 5 | **5** | 0 | 0 | — |
| UCF-Crime `Anomaly-Videos-Part-1/Arson/Arson049_x264.mp4` (12.9 s, 30 fps) | 13 | 5 | 8 | 5 | 0–36 |

**Result: the gate discriminates on real footage, with no test data built to
produce it.** UCF-Crime's clip scores 31–36 (of 64 cells) and is admitted from
t=5–9s, then drops to exactly `0` and is not admitted from t=10–12s — a real
scene going from motion to stillness, caught by the numbers alone.

**Finding that affects slice 6: CCD clips currently produce zero gated frames.**
A 5-second CCD clip yields only 5 sampled segments at the default 1-second
extraction interval (recorded in OMNI-300/303). With the default
`motion_buffer_frames` of 5, **all five of those segments fall inside the
warm-up window** — the gate never has an earlier buffered frame to compare
against, so none of CCD's 4,500 clips will ever produce a scored or admitted
frame under today's defaults. Before slice 6 loads CCD, either
`EXTRACT_INTERVAL_S` or `MOTION_BUFFER_FRAMES` needs a CCD-specific value (both
are settings, not literals, so this is a config change, not a code change).

**A clip that is not useful evidence for this metric:** OMNI-303's synthetic
`testsrc2` clip admits 115 of 115 scored frames — it animates continuously, so
it never holds still long enough to demonstrate discrimination. It remains
valid evidence that extraction itself works (its original purpose); it should
not be read as evidence about gating.

**Not covered:** VIRAT was not run through gating live (OMNI-300/303 already
established it decodes and extracts correctly; extrapolated from UCF-Crime's
result rather than measured separately here). No threshold sweep was run across
the dataset — the defaults were chosen to be legible in a test, not tuned
against real footage at scale. Full write-up in `docs/context/week-03-04.md`.

---

## 2026-09-23 — Algorithm 1 rework: stride Δ fixes the CCD finding above (OMNI-303/304)

**What changed:** the rework note in `docs/tickets/week-03-04.md` traced the CCD
finding above to its actual cause — sampling one frame per second before gating,
which is not part of Algorithm 1's own pseudocode (Phase A §3.5.1 / Appendix B.1).
The rework removes sampling (every decoded frame is now gated) and replaces the
5-**sample** warm-up buffer with a 2Δ-**second** one, Δ being a stride measured in
time. A JPEG is now written only for admitted frames — a row is still written for
every decoded frame, so this is not a return to the disk cost sampling existed to
avoid.

**Method:** the same two real clips, re-run through the real running stack after
the rework, extracted with the real defaults (`motion_grid_size=8`,
`motion_cell_threshold=25.0`, `motion_min_active_cells=3`, `motion_stride_s=0.5`,
`motion_blur_kernel=21`).

| Clip | Rows (= decoded frames) | Scored (past 2Δ warm-up) | Admitted | Files on disk |
|---|---|---|---|---|
| CCD `Crash-1500/000413.mp4` (5 s, 10 fps) | **50** | 40 | 24 | 24 frames + 24 thumbs |
| UCF-Crime `Anomaly-Videos-Part-1/Arson/Arson049_x264.mp4` (12.9 s, 30 fps) | 386 | 356 | 52 | 52 frames + 52 thumbs |

**Result: the CCD finding above no longer holds.** CCD went from 0 scored frames
(all 5 of its old sampled rows stuck in an unfillable warm-up) to 40 scored and 24
admitted, out of 50 rows — one row per decoded frame, matching `docs/tickets/
week-03-04.md`'s acceptance ("a 5-second CCD clip at 10 fps yields 50 gated
frames, not 5"). File count on disk equals admitted-row count exactly for both
clips, confirming JPEGs are written only for admitted frames.

**Deviation recorded, per OMNI-304's own checklist:** frames are blurred
(`cv2.GaussianBlur`) before differencing; the pseudocode does not call for this.
Without it, two frames of a perfectly still scene still differ pixel by pixel
from sensor noise alone, which would either force `MOTION_CELL_THRESHOLD` higher
(risking missed real motion) or admit noise as motion. Kept as a deliberate,
documented departure — see `services/ingestion/app/pipeline.py`'s `MotionGate`
docstring.

**A real numerical bug found and fixed during this work, unrelated to the
sampling change:** the initial time-based implementation could spuriously fall
back into "warm-up" for a frame or two after scoring had already started,
because comparing accumulated floating-point timestamps exactly against `2Δ`
flickers by a few ULPs right at the boundary. Caught by a test asserting no
`None` score ever follows a real one; fixed with a small (`1e-6` s) epsilon on
both the warm-up and buffer-pruning comparisons. Recorded in
`docs/context/week-03-04.md`.

**Not covered:** no literal 2-minute/3,600-row clip was run — CCD (50 rows) and
UCF-Crime (386 rows) both confirm rows-equal-decoded-frames exactly, which is
the same proportional claim at smaller scale. VIRAT was not re-run live after the
rework (established separately that it decodes correctly, OMNI-300/303). No
threshold sweep at dataset scale.

---

## 2026-09-23 — Heartbeat frames (OMNI-305): a static clip, and CCD's real coverage gain

**Claim under test:** Algorithm 1 step 5 — a frame is admitted at least once every
`HEARTBEAT_INTERVAL_S` even when the motion gate finds nothing, so a recording
with no detected motion anywhere in it does not contribute zero admitted frames.

**Method:** two real clips, uploaded and extracted through the real running
stack with the real defaults (`heartbeat_interval_s=1.0`, `motion_stride_s=0.5`,
`motion_grid_size=8`, `motion_cell_threshold=25.0`, `motion_min_active_cells=3`).

| Clip | Rows | Admitted | By reason |
|---|---|---|---|
| Freshly encoded, genuinely static, 8 s / 10 fps | 80 | 7 | 7 heartbeat, 0 motion |
| CCD `Crash-1500/000413.mp4` (5 s, 10 fps) | 50 | **26** | 24 motion, **2 heartbeat** |

**Result: heartbeat does the one thing it exists to do, on real footage in both
directions.** The static clip — which the motion gate alone admits nothing from,
by construction — gets 7 admitted frames, one every second from t=1s to t=7s,
matching the ticket's acceptance shape exactly ("a completely static clip still
produces a handful of admitted frames rather than none"). CCD, which already had
real motion coverage from the OMNI-303/304 rework (24 admitted, recorded above),
gains **2 more admitted frames it did not have before** — two moments where
motion never crossed threshold, now represented anyway. CCD's admitted count
went from 24/50 to 26/50 with no change to the motion gate itself.

**Not covered:** no literal 5-minute static clip was run — the 8-second live clip
and a 300-second scheduling trace (`services/ingestion/tests/test_heartbeat.py`)
both demonstrate the same property at smaller scale. `HEARTBEAT_INTERVAL_S`'s
default (1.0 s) was not tuned for this ticket, only wired to something that reads
it for the first time. Full write-up in `docs/context/week-03-04.md`.

---

## 2026-09-23 — Re-runnable gating re-decodes, in both directions (OMNI-306)

**Claim under test:** `POST /videos/{id}/gate` re-scores a video's frames from a
fresh decode of the source, updating existing segment rows in place — never
deleting or creating rows — and can move the admitted set in either direction,
not just narrow it.

**Method:** a real CCD clip, extracted then re-gated twice through the real
running stack, via a throwaway operator account (deleted afterward).

| Step | `min_active_cells` | Admitted | Rows | Same row IDs as before? | Time |
|---|---|---|---|---|---|
| Initial extraction | 3 (default) | 26 | 50 | — | — |
| Re-gate #1 | 60 (near-impossible) | 4 | 50 | yes | 0.3 s |
| Re-gate #2 | 1 (lenient) | 32 | 50 | yes | — |

**Result: re-gating genuinely re-scores, in both directions, with no new
rows.** The lenient run (32 admitted) admits *more* frames than the original
extraction (26) — not merely returning to it, exceeding it — which is only
possible because the endpoint re-decodes the source rather than re-scoring
whatever happened to already have a JPEG (most rows don't have one; only
admitted frames do, since OMNI-303's rework). Row `id`s and `created_at`
timestamps were identical across all three states, confirmed by direct
comparison, not inferred from a stable row count. File count on disk after the
final run (32) matched the admitted count exactly.

**The decision this measures:** the ticket asked for a deliberate choice
between re-decoding (correct, slower) and re-scoring only the frames already on
disk (fast, but can only ever discard more, never reveal a previously-discarded
frame). Re-decoding was chosen because the alternative cannot satisfy OMNI-310's
own acceptance criterion (dragging a slider must reveal more frames going one
way, not just fewer going the other) in one direction at all — not a
performance trade-off, a correctness one. Full reasoning in
`docs/context/week-03-04.md`.

**Not covered:** 0.3 s is on a 5-second clip; nothing about how re-decoding
scales to a 10-minute recording was measured, which is what will actually
determine whether this endpoint stays fast enough for OMNI-310's "about a
second" feel on realistic clip lengths.

---

## 2026-09-23 — Thumbnail URLs are not covered by NFR-7 (OMNI-307)

**Claim under test:** none directly — this is a gap found while building the
frames API, worth measuring against NFR-7's own standard ("100% of endpoints
must reject requests lacking a valid token") even though a static file route
is not an "endpoint" in the sense TC-10 (`docs/results.md`, 2026-09-05)
already covers.

**Method:** `GET /videos/{id}/frames` returns a `thumb_url` served by Nginx
directly off the `thumb_storage` volume (`location /thumbs/`), bypassing
`query` — the design OMNI-307 explicitly asks for, so thumbnails don't route
through the API on every grid load. Fetched a real thumbnail URL live, with no
`Authorization` header at all:

```
GET https://127.0.0.1/thumbs/1479/000030.jpg   (no token)
200, content-type: image/jpeg, 8,489 bytes
```

**Result: 0% of thumbnail requests require authentication, against 100% for
every route TC-10 covers.** Every other path in this system that touches
recorded footage goes through `query`, which enforces a valid JWT on every
request (OMNI-107, verified by TC-10). Thumbnails are the first exception:
Nginx's static-file route has no concept of the token this app otherwise
requires everywhere. Anyone who has or guesses a thumbnail URL — a short,
predictable `/thumbs/{video_id}/{frame_index:06d}.jpg` — can view it.

**Not fixed:** no signed URLs, no auth-checking proxy in front of the static
route. Not asked for by OMNI-307 or any other ticket in this sprint; recorded
as a real, live-demonstrated gap for whoever scopes access control on frame
data next, not treated as covered by TC-10 just because it wasn't tripped by
it. Full context in `docs/context/week-03-04.md`.

---

## 2026-09-24 — The same auth gap, now over whole recordings (OMNI-308)

**Claim under test:** the same measurement as the entry above, against
`/media/`, the new Nginx route OMNI-308 adds for the player's `<video>`
element.

**Method:** uploaded a real CCD clip through the real running stack; fetched
its playback URL through Nginx with no `Authorization` header.

```
GET https://127.0.0.1/media/ff810750e6cf4593a973ef7e0a727907_playback.mp4   (no token)
200, content-type: video/mp4
```

**Result: the exposure OMNI-307 found is now materially larger.** `/thumbs/`
exposes small preview images; `/media/` exposes complete recordings, the same
way, with the same absent authentication. Still 0% of requests to either
static route require a token, against 100% for every route TC-10 covers.

**Also measured while checking this:** the real transcode a non-H.264 source
needs — CCD's clip, genuine MPEG-4 Part 2 re-confirmed via `ffprobe`, encoded
to genuine H.264 (also re-confirmed, not assumed from ffmpeg's own exit code)
— added negligible time to the upload: **0.66 s** total for probe and
transcode together, on a 5-second clip. Nothing about how this scales to a
real multi-minute recording was measured; the transcode runs synchronously,
inside the same request the probe already runs in, with a 150-second timeout
that is a generous guess, not a measurement.

**Not fixed, same reasoning as OMNI-307's entry:** not asked for by this
sprint. Recorded so the two gaps are visible together, not read as one
smaller issue repeated. Full context in `docs/context/week-03-04.md`.

## 2026-09-25 — Threshold sweep and re-gate latency on a 30 fps clip (OMNI-310)

**Method:** through the real API, a throwaway operator account, one 10 s, 30 fps,
320x240, 300-frame upload (Abuse029). `POST /videos/{id}/gate` with each
`cell_threshold` in turn, then a full frames fetch; restored to the original 25.

| threshold | admitted | of which motion / heartbeat | gate + frames fetch |
|---|---|---|---|
| 1 | 257 | 257 / 0 | 1.97 s |
| 10 | 165 | 162 / 3 | 2.02 s |
| 25 (default) | 48 | 42 / 6 | 1.59 s |
| 40 | 13 | 4 / 9 | 1.47 s |
| 50, 75, 100 | 9 | 0 / 9 | 1.36-1.63 s |

**Result:** the count falls monotonically as the threshold rises, and discarded
frames come back as it is lowered (48 at the default, 257 at 1). From 50 up the
gate admits only the nine heartbeat frames, so a slider wider than about 60
spends the rest of its travel on no change. On every step the frames endpoint's
admitted count equalled the gate response's.

**Against OMNI-310's "in about a second":** not met on this clip. A re-gate
takes **1.4-2.0 s**, against 0.3 s on the 5 s, low-frame-rate CCD clip
measured under OMNI-306. Profiled in-container: decode 0.22 s, motion scoring
0.83 s (0.57 s of it the 21x21 Gaussian blur), JPEG writes negligible, the
rest being HTTP and updating 300 rows. In the browser a burst of drags settled in about one second per run at high thresholds (few frames admitted). Cost scales with frame count, so a
longer or higher-resolution recording will be slower still; that was not
measured.

**Not changed:** the blur and scoring are Algorithm 1 as documented, so they
were left alone. The threshold-independent part (blur, diff, per-cell means) is
recomputed on every re-gate; storing it once would make a re-gate a comparison
instead of a decode. Recorded as an option, not built. Full context in
`docs/context/week-03-04.md`.

## 2026-09-25 — NFR-5 across a consumer kill and a broker recreate, and what the durable path costs (OMNI-311)

**Method:** the real stack, a throwaway operator account, a synthetic 60 s, 30 fps,
320x240 clip (1,800 frames) uploaded through the API and removed afterwards.
Three runs, each checked by reading every stored frame back through
`GET /videos/{id}/frames`.

| Scenario | What was done | Outcome |
|---|---|---|
| Consumer killed mid-run | `docker kill` on the consumer with 402 segments stored | 419 stored by the time it was dead, **629 waiting in the queue**, video still `extracting`, not `failed`. After restarting the consumer: **1,800 of 1,800** stored, frame indexes 0-1799 each exactly once |
| Uninterrupted run | same clip, no failure | 1,800 stored; **1,360 admitted, identical to the killed run** |
| Broker container recreated | consumer stopped, 1,800 messages queued, `rm -sf` then `up -d` on the broker | **1,800 still queued** afterwards; consumer started; **1,800 of 1,800** stored, none duplicated |

**Result:** in these runs no accepted segment was lost or stored twice, across
the death of the consumer and the destruction of the broker container. That
is one clip and three failures, not a soak test; it is evidence for NFR-5's
"lost = 0" on the path between the gate and the database, not proof for every
failure. It does not cover a crash of ingestion part-way through publishing, or
of query while an extraction waits (see the context notes for what those do).

**What the queue costs:** every message is persistent and each publish waits
for the broker's confirmation, which includes a disk sync. Ingestion's
`/extract/publish` took **3.5-4.4 s for 300 frames** and **21.8-27.0 s for
1,800 frames**, roughly 12-15 ms per frame, of which decoding and gating is
about 3 ms. Extracting the 300-frame clip used to take about 2 s end to end
and now takes 4.6-5.6 s. Scaling linearly, a 10-minute 30 fps recording (18,000
frames) would take about 4 minutes to publish. Not measured at that size.

**Not changed:** publishing confirms one message at a time. Confirming in
batches (asynchronous confirms, or several channels) would share the disk sync
and should be much faster; it was not built because no requirement asks for
it yet and the dataset clips are 5-13 s. Recorded as the obvious next step if
long recordings matter. Full context in `docs/context/week-03-04.md`.

## 2026-09-26 — Live capture from the RTSP simulator: rate, start time, release, and what it stores (OMNI-312)

**Method:** the real stack, a throwaway admin account and camera, the simulator's
`cam01` (a 15 fps H.264 stream, 320x240). Started and stopped through the API
(`POST /cameras/{id}/start` and `/stop`); rows counted in the database, open
streams counted as established TCP connections from the ingestion container to
the simulator (port 8554, read from `/proc/net/tcp`). Sampling interval 0.2 s
(the default). Everything created was removed afterwards.

| Measurement | Result |
|---|---|
| Rows arriving | strictly growing at every 2.5 s check for 20 s; **about 4.1 rows/s** (88 rows, 75 admitted, after 20 s) |
| Why not 5/s | 0.2 s samples on a 15 fps stream land on every third or fourth frame (0.20-0.27 s apart) |
| Newest row's age when read | 0.2 s (one observation, includes the polling delay; not the NFR-1 measurement, which is OMNI-316) |
| Every row | `source_type = camera`, `camera_id` set, `video_id` null, `timestamp_s` = Unix time |
| Stop | **0.0-0.1 s**; rows stayed frozen for the 6 s checked afterwards |
| Streams left open after a stop | **0, in 14 of 14 start/stop cycles** (1 open while running, each time) |
| Restart without restarting the service | resumed (89 to 114 rows), into a new folder per start, so no file was overwritten |
| Start time | **about 7 s** (3.8-7.1 s over 6 starts), which is the simulator's wait for its next keyframe |

**Start failures found and fixed on the way:** the first version waited for a
frame twice (once in a reachability check, once in the worker), which took
**about 17 s** per start (16.7-17.8 s over 8 starts); and the check's 5 s
first-frame limit failed healthy starts intermittently (two of the first handful of
attempts, neither counted precisely), because the simulator's first frame takes 3-5 s or more. The check now waits
for the stream to open, not for a frame, and the worker's own first frame is
the confirmation; 6 of 6 starts succeeded afterwards.

**What it costs to store:** **24.2 KB per admitted frame** (a 16 KB frame and an
8 KB thumbnail at 320x240; 98 admitted frames took 2.3 MB). Nothing prunes them
yet. At this clip's rate of about 3.7 admitted frames a second that is roughly
**7.7 GB per camera per day**; for a static scene, where only the once-a-second
heartbeat admits, about **2.1 GB per camera per day**. A real camera's frames
are larger. This is for slice 16's retention job to bound; it is recorded here
so it is not a surprise.

**Not measured:** more than one camera at once (OMNI-317), how long a capture
runs before anything degrades, and CPU per camera. Full context in
`docs/context/week-03-04.md`.

## 2026-09-26 — Killing the simulator mid-capture: detection, backoff and recovery (OMNI-313)

**Method:** the real stack and the simulator's `cam01` (15 fps), a throwaway admin
account and camera, started through the API. `docker compose stop mediamtx`
mid-capture, camera status polled through `GET /cameras` every 0.05-0.2 s, the
worker's own state read from ingestion's `GET /workers`, retry waits read from
ingestion's log; then `docker compose start mediamtx`. Two outages: 76 s and
25 s. Reconnection settings at their defaults (first retry 1 s, doubling, cap
30 s, jitter 20%).

| Measurement | Result |
|---|---|
| Camera status after the stop | flipped `connected` to `unreachable` **0.4 s** after the stop command was issued (the container itself took 0.8 s to stop) |
| Rows while down | frozen (53 before, 53 after 26 s; 53 after 76 s) |
| `last_seen_at` while down | frozen at the last frame, not advancing |
| `last_seen_at` while healthy | advances (checked 5 s apart) |
| Retry waits, 76 s outage | **0.95, 2.24, 3.74, 9.42, 17.62, 26.74 s** (1, 2, 4, 8, 16, 30 with jitter), 5 failed attempts before one worked |
| Retry waits, 25 s outage | 1.03, 2.32, 3.47 s, 3 failed attempts |
| Recovery, 76 s outage | camera `connected` **20.5 s** after the simulator was started; capture resumed by itself |
| Recovery, 25 s outage | **11.4 s** after the simulator was started; +14 rows within a few seconds |
| Integrity across the gap (25 s outage) | no duplicate moments, frame indexes unbroken, one capture session, **54 thumbnail files for 54 admitted rows** |
| After a stop | worker registry empty, 0 open connections to the simulator |

**Result:** the acceptance case held: the simulator was killed mid-capture, the
camera reported `unreachable` within a second, and when the simulator returned
capture resumed with no one touching it. The waits grew as designed instead of
retrying every 100 ms.

**What the recovery time is made of:** the wait before the next attempt (up to
the 30 s cap), the simulator restarting its own feed, and the wait for the first
keyframe (about 5-7 s). So a camera that comes back can go unnoticed for about
the cap plus that; a lower cap trades that against how often a long-dead camera
is retried.

**Two measurements in the first run were wrong and are not used:** the
"time to flip" read 0.0 s because `docker compose stop` blocks until the
container has stopped, so polling began after the flip had already happened;
and thumbnail files were compared with rows while capture was still running (52
against 50), which only measured frames in flight. Both were fixed for the
second run.

**Not measured:** a stream that stalls without closing (the case here closes
its connection, so the drop was seen at once; a silent stall would take the 10 s
read timeout), several cameras dropping together (what the jitter is for), and a
broker restart during capture. Full context in `docs/context/week-03-04.md`.

## 2026-09-26 — Throttling downstream during a live capture: drops climb, memory and queues stay flat (OMNI-314)

**Method:** the real stack and the simulator's `cam01` (about 4.2 sampled frames a
second), a throwaway admin account and camera, started through the API. Two
deliberate throttles, each held while the worker's counters (`GET /workers`),
the broker queue depth (`rabbitmqctl`), and the ingestion container's memory
(`docker stats`) were read every few seconds, then released. Defaults: in-process
queue of 10 frames; the second run set `LIVE_MAX_BACKLOG=40` (default 2000) so a
backlog could be reached in seconds, and was reverted afterwards.

**1. Broker frozen for 24 s** (`docker compose pause rabbitmq`: publishing stalls)

| | healthy | +4 s | +13 s | +22 s | after release |
|---|---|---|---|---|---|
| dropped | 0 | 9 | 44 | 83 | **107**, then no more |
| published | 84 | 101 | 101 | 101 | resumed, +38 every 5 s |
| in-process queue | 0/10 | 10/10 | 10/10 | 10/10 | 0/10 |
| ingestion memory | 186 MiB | 194 | 194 | 194 | 187-188 |

**2. Consumer paused for 40 s** (`docker compose pause consumer`, backlog limit 40)

| | healthy | +4 s | +17 s | +29 s | +43 s | after release |
|---|---|---|---|---|---|---|
| dropped | 0 | 0 | 23 | 74 | 131 | **166**, then no more |
| broker queue (messages) | 0 | 31 | 52 | 52 | 52 | 0 within 5 s |
| ingestion memory | 129 MiB | 129 | 129 | 129 | 130 | 130 |

**Result:** the acceptance held in both. `dropped` climbed steadily while the
throttle lasted and stopped the moment it was lifted; memory moved by 8 MiB at
most and came back; the in-process queue sat at its bound of 10 and the durable
queue at 52 rather than growing. In the second run the queue is 40 ready plus the
10 the consumer was holding unacknowledged plus about a second of lag, which is
the limit doing its job. At this camera's rate an unbounded queue would have added
about 170 messages over the same 43 s (arithmetic from the rate, not a separate
run).

**Nothing went missing without being counted.** After each run the worker's own
books balanced exactly: captured 404 = published 297 + dropped 107 + queued 0, and
captured 512 = published 346 + dropped 166 + queued 0. `GET /cameras/{id}/stats`
agreed with the worker on dropped (107 and 166); its `captured` was 7 and 2 ahead
only because the camera kept running between the two reads. Capture carried on
through both throttles, and the worker was still `running` after a 24 s broker
freeze.

**Visible in the log, without flooding it:** 107 drops produced **5** warnings and
166 produced **8**: one when a stretch of drops began, then a summary about every
5 s giving the count, the reason (`processing` or `backlog`), the running total
and the queue depth.

**Healthy, for comparison:** 0 dropped, `fps_effective` 4.1-4.3, in-process queue
empty. After a stop, `fps_effective` and `uptime_s` read 0 while the totals stay.

**Not measured:** memory at a real resolution (these frames are 320x240, about
230 KB; ten of them at 1080p would be about 60 MB, which is arithmetic, not a
measurement), a broker freeze longer than the 30 s heartbeat, and several cameras
at once. The defaults (queue of 10 frames, backlog limit of 2000) are untuned.
Full context in `docs/context/week-03-04.md`.
