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
