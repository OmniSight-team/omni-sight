# Sprint 5 — The camera wall

**Slice 5 · 30 Sep – 6 Oct 2026 · 7 days · branch `slice-05-camera-wall`**
Board: OmniSight Phase B · Assignee: Ahmad

> **By the end of this sprint:** watch every camera at once on one wall, enlarge any of
> them, rewind a few minutes, and see immediately which feeds are healthy — with ten
> cameras running and the number the machine actually sustains written down.

**Covers:** FR-9 (live monitoring part) · NFR-4 · NFR-1 · TC-1 (complete)
**Settles:** D-9 (live sampling before the gate) · K-1 (live latency behind a recording) ·
K-5 (workers not resumed, status wrong)
**Ships in:** `services/ingestion/` · `services/query/` · `frontend/` · `infra/` · `docker-compose.yml`

---

## What carries over from slices 3–4, and why it is in this sprint

Three open items in `docs/known-issues.md` and `docs/decisions.md` land here, because the
wall and NFR-4 cannot be honest without them:

| Item | Problem | Fixed by |
|---|---|---|
| D-9 | Live capture samples every 0.2 s **before** the gate; Algorithm 1 gates every frame | OMNI-501 |
| K-1 | A long recording being extracted pushes live latency to 6.14 s (NFR-1 fails) | OMNI-502 |
| K-5 | After an ingestion restart nothing captures, but the camera still reads `connected` | OMNI-504 |

K-2 (10 feeds not sustained) is what OMNI-509 measures again after these changes, with
OMNI-510 as the fallback if it still fails.

---

## Ticket order

**Part A — back end (days 1–3)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-500 | Branch and baseline | 0.5 h | 1 |
| OMNI-501 | Live capture gates every frame (Algorithm 1) | 3 h | 1 |
| OMNI-502 | Live frames never wait behind a recording | 2.5 h | 2 |
| OMNI-503 | Preview endpoint: the current frame, cheap to poll | 2.5 h | 2 |
| OMNI-504 | Camera liveness and honest status | 3 h | 3 |
| OMNI-505 | Rewind buffer | 1.5 h | 3 |

**Part B — the wall (days 4–5)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-506 | Live Monitoring screen: a fixed 3x3 wall, grouped | 4 h | 4 |
| OMNI-507 | Tile states: live, frozen, offline | 2 h | 4 |
| OMNI-508 | Enlarge a tile, and rewind it | 3 h | 5 |

**Part C — measure (days 6–7)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-509 | NFR-4: ten feeds, measured properly | 2.5 h | 6 |
| OMNI-510a | **Added 2026-10-03, after OMNI-509:** ingestion gates every frame of ten feeds | 4 h | 6 |
| OMNI-510 | **Only if OMNI-510a's rerun shows the live queue growing:** batch the consumer's commits | 3 h | 6 |
| OMNI-511 | TC-1 complete | 1 h | 6 |
| — | **cut line — the slice is defensible from here** | | |
| OMNI-512 | Layouts (2x2, 3x3, 4x4) and pinning | 2 h | 7 |
| OMNI-513 | Diagram, docs, merge | 2 h | 7 |

Fallback from the plan: *a fixed 3x3 grid is enough; layouts and pinning are refinements.
The NFR-4 measurement is not optional — it is a graded requirement.*

---

# Part A — back end

## OMNI-500 · Branch and baseline

- [x] `master` is clean and has slices 3–4 (`git log` shows `d6d5943` or later)
- [x] **You** create and switch to **`slice-05-camera-wall`** from `master`
      (`git switch -c slice-05-camera-wall`). All work this sprint is committed there
- [x] `docker compose up -d` and `uv run pytest` green before touching anything (304 at the
      end of slices 3–4)

**Acceptance:** on the new branch, the stack runs and the suite is green.

---

## OMNI-501 · Live capture gates every frame (Algorithm 1)

**Why:** **FR-1b**, and Phase A §3.5.1 / Appendix B.1. The live worker reads every frame but
only gates one per 0.2 s. That is the same sampling step removed from files in OMNI-303's
rework, and it is recorded as an open deviation (D-9). OMNI-317 showed why it was there: at
0.2 s the stack stored ~4.2 rows per camera per second and choked at 10 cameras. Sampling
was the wrong lever. The load came from **storing a row for every sampled frame**, not from
gating.

**The change:** gate every decoded frame, exactly as files do; publish **only admitted
frames** (Algorithm 1 forwards only admitted frames); count the rest.

- [x] Remove sampling from the live worker: **every decoded frame** goes through the same
      `MotionGate` and `process_frame()` as a file, with the same settings (stride Δ, grid,
      threshold, active cells, blur, heartbeat) **[FR-1b]**
- [x] Remove `LIVE_SAMPLE_INTERVAL_S` from settings, `.env.example` and docs
- [x] For a live camera, publish a segment **only when the frame is admitted** (motion or
      heartbeat). Discarded live frames get no row and no file
- [x] Each admitted live frame carries its causal clip `[t - 2Δ, t]` (`clip_start_s`,
      `clip_end_s`), exactly like a file: pseudocode lines 7-8, `forward(f_t, W)`
- [x] Per-camera counters in `camera_stats`: `gated`, `admitted` (motion / heartbeat) and
      `discarded`, beside `captured` and `dropped`; exposed by `GET /cameras/{id}/stats`
- [x] Still one `process_frame()`, two producers. The only live-specific part is what gets
      published
- [x] `docs/decisions.md`: D-9 becomes **Done** (Algorithm 1 as written, no sampling); D-5
      gains one line: *live cameras store admitted frames only — a row per frame at 15 fps
      is about 1.3 million rows per camera per day; the counters keep the gate explainable*
- [x] Tests: a scripted capture of still-then-moving frames publishes only admitted ones,
      and the counters balance: `captured = gated + dropped`, `gated = admitted + discarded`

**Acceptance:** `cam05` for 60 s: `gated` is about 15/s, every stored row is admitted with a
reason, heartbeat admits at least one frame a second on still stretches, and the counters
balance exactly.

---

## OMNI-502 · Live frames never wait behind a recording

**Why:** **NFR-1** — *a captured frame must be ready to search in under 5 seconds.* OMNI-316:
live alone 49 ms worst, but 6.14 s while a 1,930-frame file was extracted, because both
share one queue and one consumer, first in first out (K-1).

- [x] A second durable queue for live segments; file extraction keeps the existing one
- [x] A second consumer service in `docker-compose.yml` (same image, same code, the queue
      name from settings) that consumes only the live queue
- [x] Same guarantees on both: persistent messages, publisher confirms, ack after commit
      **[NFR-5]**
- [x] Rerun `scripts/measure_capture_latency.py`: live alone, and live + the 1,930-frame file

**Acceptance:** with the 1,930-frame file extracting, the worst live frame is **under 5 s**.
Update the NFR-1 scoreboard row in `docs/results.md`, and move K-1 to *Fixed* in
`docs/known-issues.md` with the number.

---

## OMNI-503 · Preview endpoint: the current frame, cheap to poll

**Why:** **FR-9** — sixteen tiles must not mean sixteen video streams. A tile needs the
current frame about once a second, not the stream.

```http
GET /cameras/{id}/preview -> image/jpeg   (ETag; 304 when unchanged)
```

- [x] The live worker writes the **current decoded frame** (admitted or not) as a small JPEG,
      at most once per `LIVE_PREVIEW_INTERVAL_S` (default 0.5 s), longest side capped at
      640 px, to a new `preview_storage` volume, one file per camera, replaced atomically
      (write a temp file, then rename)
- [x] `query` serves it **with the token check** (not an nginx static route, so K-3 does not
      grow) **[NFR-7]**
- [x] `ETag` from the file's write time; `If-None-Match` returns `304` with no body;
      `Cache-Control: no-cache`
- [x] No preview yet, or camera stopped: `404` with a reason, never an old frame pretending
      to be current
- [x] Tests: 200 with a token, 401 without, 304 on a matching ETag

**Acceptance:** 16 clients polling one camera each second: record bytes per second and
query's CPU. Unchanged frames cost a 304, not a JPEG.

---

## OMNI-504 · Camera liveness and honest status

**Why:** **FR-9** — *see immediately which feeds are healthy.* Today a camera can read
`connected` with no worker behind it (K-5), and a stream that stalls without closing is only
noticed after the 10 s read timeout.

```http
GET /cameras/live -> [{camera_id, name, location, group_name, state, last_frame_at}]
                     state: live | frozen | offline | stopped
```

- [x] `state` is derived from evidence, not from a stored flag: **live** = a frame arrived in
      the last `LIVE_STALE_AFTER_S` (default 3 s); **frozen** = capture running but no new
      frame for longer; **offline** = unreachable or reconnecting; **stopped** = not
      capturing
- [x] `last_frame_at` is the preview's write time (OMNI-503), so it is at most 0.5 s old on a
      healthy feed
- [x] New column `cameras.capture_enabled` (Alembic migration), set by start and cleared by
      stop. **On startup, ingestion resumes capture for every camera with it set** — no
      one has to press Start after a restart
- [x] Tests for each state, and for resume after restart

**Acceptance:** `docker compose pause mediamtx` → the camera reads **frozen** within 3 s,
then **offline** after the read timeout; `unpause` → **live** again. `docker compose restart
ingestion` → capture resumes by itself, and no camera reads live without a worker. Move K-5
to *Fixed*.

---

## OMNI-505 · Rewind buffer

**Why:** *rewind a feed a few minutes to see what led up to something.* Admitted frames are
already stored, and the heartbeat guarantees at least one a second, more when something
moves. That **is** the short-term buffer; no second copy.

```http
GET /cameras/{id}/buffer?minutes=5 -> [{segment_id, timestamp_s, reason, thumb_url, frame_url}]
```

- [x] Admitted frames from the last `minutes` (1–10, default 5), oldest first, from
      `segments`
- [x] Data model note in `docs/decisions.md`: the rewind buffer is the stored admitted frames
      (on disk), not a separate buffer; a flip-book of frames, not video
- [x] Tests: window bounds, order, limit on `minutes`

**Acceptance:** after 5 minutes of capture, the buffer returns at least 300 frames, oldest
first, none outside the window.

---

# Part B — the wall

## OMNI-506 · Live Monitoring screen: a fixed 3x3 wall, grouped

**Why:** **FR-9** — the screen an operator actually lives in.

- [x] New page **Live Monitoring**, in the nav for operator and admin
- [x] A 3x3 CSS grid of tiles from `GET /cameras/live`; each tile labelled with **name and
      location**
- [x] Each tile polls its preview about once a second with the token (fetch → blob → object
      URL; revoke the old one), sending `If-None-Match`. **No video element per tile**
- [x] Filter by group (`group_name`), so a wall can show one site or building
- [x] More cameras than tiles: pages, not tiny tiles
- [x] Polling stops when the tab is hidden

**Acceptance:** ten simulator cameras running, the wall shows nine at once, each updating,
and the network tab shows mostly 304s on still scenes.

---

## OMNI-507 · Tile states: live, frozen, offline

- [x] A **quiet** live indicator per tile that changes only when a new frame arrived (driven
      by the preview's ETag changing), so a frozen picture cannot look live
- [x] **Frozen**, **offline** and **stopped** each have an explicit state: label and icon,
      the last frame dimmed with its age ("last frame 12 s ago"). **Never a black
      rectangle**
- [x] State comes from `GET /cameras/live` (OMNI-504), refreshed every few seconds

**Acceptance:** pause the simulator → tiles go frozen then offline without a refresh;
unpause → live again. Stop a camera → stopped.

---

## OMNI-508 · Enlarge a tile, and rewind it

- [x] Click a tile → full-screen view of that camera, preview polled faster (every 0.5 s),
      Esc to close
- [x] In the enlarged view, **Rewind**: a scrubber over `GET /cameras/{id}/buffer`, stepping
      through the last few minutes of admitted frames with their time and reason; **Back to
      live** returns to the preview
- [x] Motion frames and heartbeat frames are told apart on the scrubber

**Acceptance:** wave something in front of a feed (or wait for motion on `cam05`), open it,
rewind, and step through the frames that led up to it.

---

# Part C — measure

## OMNI-509 · NFR-4: ten feeds, measured properly

**Why:** **NFR-4** — *handle 10 or more live video feeds at once without slowing down.*
Graded here. OMNI-317 said 8 sustained, 10 not — before OMNI-501 and OMNI-502 changed the
load.

**Decide what "sustained" means before measuring**, and write it at the top of the
results entry: 0 dropped frames; every feed's worst capture-to-stored under 5 s (NFR-1);
queue depth not trending up over the second half of the window; every tile on the wall
`live` for the whole window.

- [x] **Realistic feeds:** point the ten simulator paths at ten real surveillance clips
      from `data/` (UCF-Crime and VIRAT, looped), because the synthetic test clips move
      constantly and are not what a camera sees. Keep the synthetic set as the worst case
- [x] Ten feeds for **10 minutes**, with the wall open in a real browser at 4x4 (all ten
      visible) for the whole window — the wall's own load is part of the measurement
- [x] Per feed: capture-to-stored p50 / p95 / max, dropped, admitted rate. Overall: both
      queues' depth, CPU per container (container sampler only, no PowerShell sampler)
- [ ] Then a ladder (12, 15, 20) in 3-minute windows to find the ceiling
- [x] The synthetic worst case at 10 feeds, 3 minutes
- [x] Record the number **sustained**, not attempted, in `docs/results.md`; update the
      NFR-4 scoreboard row and K-2

**Acceptance:** the NFR-4 row in `results.md` says how many feeds this machine sustains
under the stated definition, on realistic feeds, with the wall open.

---

## OMNI-510a · Ingestion gates every frame of ten feeds

*Added 2026-10-03 with Ahmad, after OMNI-509.*

**Why:** **NFR-4.** OMNI-509 found 1 feed sustained, not 10. Storage kept up (the live queue
held nothing); the frames were lost inside ingestion, before the gate. The gate's own work for
ten realistic feeds is about 1.9 cores (`scripts/frame_cost.py`); ingestion spent about 4 and
still fell behind, with 196 threads in one Python process. The overhead is around the work,
not the work (K-2).

**The change:** cut that overhead **without skipping a frame**: every decoded frame is still
gated (Algorithm 1, D-9).

- [x] Limit the threads each stream's decoder and each OpenCV call may start, from settings
- [x] Measure the effect on ten realistic feeds before going further; if ten are still not
      sustained, run the camera workers in more than one process
- [x] Every frame still gated: the OMNI-501 checks still pass (counters balance, stored rows
      admitted)
- [x] Rerun OMNI-509's measurement (ten realistic feeds, wall open at 4x4, the same definition of
      sustained); update the NFR-4 row and K-2

**Acceptance:** the rerun says how many feeds are sustained after the change, with the same
definition and conditions as OMNI-509, and the cost of each step is recorded.

---

## OMNI-510 · Only if OMNI-510a's rerun shows the live queue growing: batch the consumer's commits

*Condition changed 2026-10-03: OMNI-509 failed, but the consumer was idle (live queue 0,
`consumer-live` under half a core), so batching waits for OMNI-510a's rerun.*

**Why:** OMNI-317 measured the consumer at 76–83 frames/s alone, one transaction per
message; it is the obvious bottleneck. Skip this ticket if ten feeds are sustained.

- [ ] The consumer commits up to N messages per transaction (or every T ms, whichever comes
      first), then acknowledges them all — **ack after commit, still** **[NFR-5]**
- [ ] A crash mid-batch redelivers the whole batch with no duplicates (same check as
      OMNI-311)
- [ ] Rerun OMNI-509

**Acceptance:** NFR-5 checks still pass, and the consumer's own rate is measured before and
after.

---

## OMNI-511 · TC-1 complete

**Why:** **TC-1** — *ingest a live feed and an uploaded file at once, keeping only frames
with motion.* The first half ran in OMNI-316; the second half is the same, on the wall.

- [x] `cam05` live and the 1,930-frame recording extracting at the same time, 30 s, with the
      wall open
- [x] Both decode without error; for the file, the OMNI-316 checks (every admitted frame has
      a reason and a file, no discarded frame has a file); for live, every stored row is
      admitted with a reason and the counters balance (OMNI-501)
- [x] The camera's tile stays **live** the whole time
- [x] Record in `docs/results.md`; TC-1 row → complete

**Acceptance:** TC-1 passes in full and is recorded, dated, with the conditions.

> **This is the cut line.** FR-9's live monitoring part works, NFR-4 is measured, TC-1 is
> complete. What follows is refinement and paperwork.

---

## OMNI-512 · Layouts and pinning

- [x] Layout choice: 2x2, 3x3, 4x4; the grid reflows
- [ ] Pin a camera to a fixed position; pinned cameras stay put when the list changes
- [ ] Layout and pins remembered per browser (localStorage), wrapped so a blocked storage
      falls back to the default layout

**Acceptance:** choose 4x4, pin a camera to the top-left, reload: both kept.

---

## OMNI-513 · Diagram, docs, merge

- [ ] `docs/architecture/slice-05-camera-wall.md`: the wall, preview files, the two queues,
      liveness
- [ ] `docs/context/week-05.md`, one section per ticket
- [ ] `docs/results.md` scoreboard: NFR-4, NFR-1, TC-1 updated; `decisions.md` and
      `known-issues.md` current
- [ ] `docs/rtsp-simulator.md`: the realistic clip set, and no mention of sampling
- [ ] `uv run pytest` green
- [ ] Everything committed on `slice-05-camera-wall` (by you)
- [ ] **You merge into `master`** (`git switch master`, `git merge --no-ff slice-05-camera-wall`),
      then `uv run pytest` green on `master`
- [ ] Slice 5 ticked on the tracker

---

## Definition of done

The plan's proof, in one demo on a fresh `docker compose up -d`:

> Ten simulated cameras run at once on the wall with the system keeping up, and the
> sustained figure is recorded. A live feed and an uploaded file ingest simultaneously with
> only motion frames kept — TC-1 passes.

Plus what the wall promises:

> Enlarge any camera and rewind it a few minutes. Pause the simulator: tiles go frozen,
> then offline, and come back by themselves. Restart ingestion: capture resumes with no
> one pressing Start.

- [ ] All of the above true on a fresh stack
- [ ] `docs/results.md` has NFR-4 (sustained, with its definition), NFR-1 with a recording
      extracting, and TC-1 complete
- [ ] Merged into `master`

---

## What to learn this sprint

- [HTTP conditional requests and ETags](https://developer.mozilla.org/en-US/docs/Web/HTTP/Conditional_requests)
  — why sixteen tiles polling once a second cost almost nothing on a still scene.
- [CSS grid layout](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout)
  — the wall must work at 4 tiles and at 16.
- [The Fullscreen API](https://developer.mozilla.org/en-US/docs/Web/API/Fullscreen_API)
  — enlarging a tile.
- [The Page Visibility API](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API)
  — stop polling when nobody is looking.
- [RabbitMQ work queues and prefetch](https://www.rabbitmq.com/tutorials/tutorial-two-python)
  — why a second queue keeps live frames from waiting.
- Measuring concurrency honestly — report the number sustained, not attempted, and decide
  what "sustained" means before you look at the numbers.

---

## Working with Claude Code

`CLAUDE.md` is read automatically. One ticket per session. Paste the ticket, then:

> Here is ticket OMNI-5xx from our sprint board. Implement exactly what it asks and nothing
> more. Before starting, read the context sections for the tickets this builds on. When you
> are done, show me the diff, tell me which acceptance criteria you verified and how, and
> suggest a short commit message without the ticket number. Do not run any git command
> that changes the repository; I commit myself.

Four things to insist on this sprint:

- **Algorithm 1 gates every frame, live too.** No sampling before the gate. If ten feeds do
  not fit, the fix is on the storage side (OMNI-502, OMNI-510), never by skipping frames.
- **No video stream per tile.** The wall polls one small JPEG per tile, with ETags.
- **A tile says live only when a frame actually arrived.** State is derived from the newest
  frame's age, never from a stored flag.
- **"Sustained" is defined before the NFR-4 run**, and the result is the number sustained,
  with the wall open.
