# Sprint 6 — Real footage, and the dashboard comes alive

**Slice 6 · Wed 7 – Tue 13 Oct 2026 · 7 days · branch `slice-06-dashboard-datasets`**
Board: OmniSight Phase B · Assignee: Ahmad

> **By the end of this sprint:** open the product and see the state of the whole system at a
> glance, with real footage volumes behind it; and the lead-up windows the forecasting model
> trains on are derived, split, hand-checked and exported.

**Covers:** FR-9 (operations dashboard part) · SM-3 target (D-2) · data for SM-1, SM-2, SM-4
**Dependency milestone:** lead-up windows derived. Slices 9 to 12 train on them and cannot
start without them. **If anything slips this week, it is the dashboard, never the windows.**
**Carries over from slice 5:** K-11 (NFR-5 not rechecked for live), K-12 (OMNI-506 wording),
two stale docs, the NFR-4 grid speed-up, K-4 (camera motion, due this slice)
**Ships in:** `services/ingestion/` · `services/query/` · `frontend/` · `scripts/` · `docs/`

---

## Rules for this sprint

- **You run every git command.** Claude Code suggests a short commit message after each
  ticket, without the ticket number, and never commits, branches or merges.
- **Every lead-up window comes from an annotation, never from a guess.** Where a dataset has
  no event time, there is no window, and the count of those is recorded.
- **The split is fixed once, before any window is used, and never moves.**
- **Dataset footage goes through the normal upload path.** The load endpoint calls the same
  code as `POST /videos/upload`; it is a loop, not a back door.

---

## Ticket order

**Part A — carry-over from slice 5 (day 1)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-600 | Branch and baseline | 0.5 h | 1 |
| OMNI-601 | NFR-5 rechecked for live cameras (K-11) | 2 h | 1 |
| OMNI-602 | Three doc fixes from the slice 5 review | 0.5 h | 1 |

**Part B — data and labels: the milestone (days 1–4, must not slip)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-603 | UCF-Crime training videos: check that event timestamps can be obtained | 1 h | 1 |
| OMNI-604 | Dataset manifest and the three loaders | 4 h | 2 |
| OMNI-605 | Fix the train / validation / held-out split | 2 h | 2 |
| OMNI-606 | CCD pre-event footage, and the SM-3 target | 1.5 h | 2 |
| OMNI-607 | Derive the lead-up windows | 4 h | 3 |
| OMNI-608 | Load the datasets into the product | 4 h + background | 3–4 |
| OMNI-609 | Window inspection view, and the hand check | 4 h | 4 |

**Part C — the dashboard (days 5–6)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-610 | Aggregates that stay fast | 3 h | 5 |
| OMNI-611 | Operations Dashboard | 4 h | 5 |
| OMNI-612 | Datasets screen | 2.5 h | 6 |
| — | **cut line — the slice is defensible from here** | | |

**Part D — strengthen and close (day 7)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-613 | The motion grid in one array operation, and NFR-4 again | 3 h | 7 |
| OMNI-614 | Diagram, docs, merge | 2 h | 7 |

Fallback from the plan: *static counts before live-updating ones. The lead-up window
derivation is the part that must not slip.*

---

# Part A — carry-over from slice 5

## OMNI-600 · Branch and baseline

- [x] `master` has slice 5 merged (`git log` shows `24882ba` or later)
- [x] **You** create and switch to the branch: `git switch -c slice-06-dashboard-datasets`
- [x] `docker compose up -d` and `uv run pytest` green before touching anything (387 passed,
      1 skipped at the end of slice 5)

**Acceptance:** on the new branch, the stack runs and the suite is green.

---

## OMNI-601 · NFR-5 rechecked for live cameras (K-11)

**Why:** **NFR-5** — *data lost on failure = 0.* The restart checks in
`scripts/verify_definition_of_done.py` were written for slices 3–4 and never updated. Since
OMNI-501 a live camera stores admitted frames only, so gaps in a session's frame indexes are
normal, and the script reads them as losses; since OMNI-502 live frames are on
`omnisight.segments.live`, and the script waits for the other queue. The NFR-5 scoreboard row
still rests on OMNI-319, which tested the old pipeline.

- [x] For live sessions, drop the index-gap check. Loss is: a row without a file, or stored
      rows short of the worker's `admitted` counter for that session
- [x] Wait for **both** queues to drain
- [x] Self-test: the detector flags a missing row, a missing file and a short count, and does
      **not** flag a normal gap
- [x] Rerun the four cases on the real stack: `restart ingestion`, `kill ingestion`, consumer
      stopped 15 s, consumer `kill -9` 15 s (now `consumer-live`)
- [x] `results.md`: a new entry and the NFR-5 scoreboard row updated; K-11 moved to *Fixed*

**Acceptance:** all four cases, zero frames lost by the new rule, recorded with the numbers.

---

## OMNI-602 · Three doc fixes from the slice 5 review

- [x] **K-12:** reword OMNI-506's acceptance in `docs/tickets/week-05.md` to *"304s when a
      feed is frozen or lost; a live feed gets a new frame on every poll by design (D-14)"*;
      the wall scoreboard row in `results.md` → **Pass**; K-12 → *Fixed (reworded)*
- [x] **`results.md` FR-1a row:** replace "Live: ~4.1 frames/s stored" (the sampling era)
      with the current figure from OMNI-501
- [x] **`docs/architecture/slice-04-frames-from-camera.md`:** one line at the top: *the 0.2 s
      sampling shown here was removed in slice 5 (D-9); see slice-05-camera-wall.md*. The
      diagram itself stays as built

**Acceptance:** no doc describes the live sampling as current, and K-12 is closed.

---

# Part B — data and labels

## OMNI-603 · UCF-Crime training videos: check that event timestamps can be obtained

**Why:** Phase A §3.4 and §3.6 say lead-up windows are derived *"by working backward from each
known event"*. UCF-Crime times its events for the **290 test videos only**; the 1,610 training
videos have a class and no time. Working backward needs a time. Without one, the surveillance
head has almost nothing to train on.

**The candidate:** UCA, *UCF-Crime Annotation* (Yuan et al., CVPR 2024): start and end times at
0.1 s for events in 1,854 UCF-Crime videos (1,165 train, 379 validation, 310 test), released
for academic use from the project's GitHub repository (folder `UCF Annotation`, txt and json).
**Not yet verified downloadable from here** — check it the way DoTA was checked (D-1).

- [x] Download the UCA annotation files (Colab or your machine) into
      `data/ucf_crime/annotations/uca/`; record the files, sizes and counts in
      `docs/dataset-layout.md`
- [x] Match UCA's video names to the 1,900 UCF-Crime videos on disk: how many match, how many
      anomaly training videos gain a time
- [x] UCA describes **every** event in a video, not only the crime. Record how the anomaly's
      segment is picked (the first segment whose description matches the class) — this is
      the "semi-automatic" part Phase A names
- [x] **Agreement check:** on the test videos that have both, compare the start UCA gives with
      the official temporal annotation. Record mean and median difference in seconds
- [x] `docs/decisions.md`: a decision either way. **If UCA cannot be obtained, stop and decide
      with Ahmad before OMNI-605** (like D-1); do not invent times

**Acceptance:** `decisions.md` says where every UCF-Crime event time comes from, with the
match count and the agreement number.

---

## OMNI-604 · Dataset manifest and the three loaders

**Why:** each dataset keeps its native layout (`docs/dataset-layout.md`); one small loader per
dataset turns it into one shared manifest. The manifest covers the **whole** dataset from its
annotation files, loaded into the product or not, because training runs on Colab from Drive.

```
dataset_manifest(id, dataset, clip_key, domain, event_class, event_start_s, event_end_s,
                 annotation_source, split, video_id NULL)
```

- [x] Copy every annotation file (small) into the local mirror: VIRAT's full `annotations/`,
      UCF-Crime's `annotations/` plus UCA, CCD's `Crash-1500.txt`
- [x] Alembic migration for `dataset_manifest`; `clip_key` is the dataset's own identity
      (`(subset, id)` for CCD, filename for UCF-Crime, base name for VIRAT); unique per dataset
- [x] **UCF-Crime:** class from the class folder, never `Part-N`; exclude
      `Normal_Videos_for_Event_Recognition/`; the real training list is the top-level
      `Anomaly_Train.txt` (the one in the splits folder is 0 bytes); up to two intervals per
      test video, frame numbers at 30 fps; training times from OMNI-603
- [x] **CCD:** pull the bracketed `binlabels` block out with a regex before splitting; event
      start = first `1` / 10 fps; normal clips have no event
- [x] **VIRAT:** `isfile()`, not `exists()`; read events, objects and mapping together; only
      the 275 with events; scene from the filename
- [x] Each trap in `dataset-layout.md` has a test that fails if the loader falls into it
- [x] Counts after loading, against `dataset-layout.md`: UCF-Crime 1,900; CCD 1,500 + 3,000;
      VIRAT 275 with events

**Acceptance:** the manifest holds every clip of the three datasets, the counts match the
audited numbers exactly, and every trap test passes.

---

## OMNI-605 · Fix the train / validation / held-out split

**Why:** every measurement from now on uses the same split. A split that moves invalidates
every comparison.

- [x] **UCF-Crime:** held-out = the official 290 test videos (SM-4's normals stay there);
      validation carved from the official training list, stratified by class; train = the rest
- [x] **CCD:** stratified crash / normal; crash clips **grouped by `youtubeID`** so clips cut
      from the same source video never sit on both sides
- [x] **VIRAT:** evaluation only (SM-1), no training split; recorded as such
- [x] A fixed seed; the split written to `dataset_manifest.split` **and** to committed CSV
      files under `datasets/splits/`, with their SHA-256 in `results.md`
- [x] A test that rebuilding the split gives byte-identical files

**Acceptance:** `results.md` records each dataset's counts per split per class, the seed and
the file hashes.

---

## OMNI-606 · CCD pre-event footage, and the SM-3 target

**Why:** D-2. SM-3's target is set from CCD's measured pre-event footage **before any model is
trained**, so it cannot be chosen to flatter the result.

- [x] **Write the rule before computing anything**, in `decisions.md`. Recommended: *SM-3
      target = mean time-to-accident of at least half the median pre-event footage in CCD's
      held-out crash clips.* Warning at the very first frame is the ceiling; half of it means
      warning in the first half of the lead-up
- [x] Across all 1,500 crash clips and per split: seconds before the first accident frame —
      mean, median, p10, p25, p75, p90, min, max, a histogram, and how many have under 1 s
- [x] Apply the rule; the number goes in the SM-3 scoreboard row as the target

**Acceptance:** SM-3 has a target in `results.md`, derived by a rule written before the data
was looked at.

---

## OMNI-607 · Derive the lead-up windows

**Why:** the dependency milestone. Phase A: the predictor sees *"30s and 60s sliding windows"*
before an event (§4.1), lead-up lengths are tested (§3.6), and windows are derived *"by working
backward from each known event"*. No dataset ships them.

```
event_windows(id, manifest_id, window_start_s, window_end_s, length_s, event_class, domain,
              split, derived, verified, verified_by, verified_at)
```

- [x] **Positive windows:** for every timed event, `window_end = event_start` and
      `window_start = event_start - L`, for **L = 30 s and 60 s** on UCF-Crime. A window never
      contains any part of the event
- [x] **Too little footage before the event:** keep the window shortened to what exists, flag
      it, and count them per L (UCF-Crime events that start in the first seconds)
- [x] **Second interval** (UCF-Crime test): its lead-up overlaps the first event → skipped and
      counted
- [x] **CCD:** one window per crash clip, `[0, accident_start)`, length as it is (under 5 s,
      D-2); no 30 s or 60 s windows exist on CCD and none are invented
- [x] **Negative windows:** from normal videos, the same lengths, seeded random positions,
      in the normal video's own split
- [x] `fps` from each video's own probe, never assumed: UCF-Crime frame numbers are converted
      at 30 fps and any video not at 30 fps is reported
- [x] Export `datasets/windows/{dataset}.csv` (window, class, split, length, flags) for Colab;
      SHA-256 in `results.md`
- [x] `results.md`: windows per dataset, per class, per split, per L; shortened and skipped
      counts

**Acceptance:** every timed event has its windows or a recorded reason it has none; the CSVs
are exported and hashed.

---

## OMNI-608 · Load the datasets into the product

**Why:** VIRAT must be in the archive before slice 7 encodes it (SM-1 in slice 8); the
dashboard should reflect real footage volumes; the window view needs the videos.

```http
GET  /datasets             -> [{name, domain, videos_loaded, total, status}]
POST /datasets/{name}/load {limit} -> {queued}
```

**What goes in the product** (training stays on Colab, from Drive):
**CCD: all 4,500** · **VIRAT: the 275 with events** · **UCF-Crime: the 290 held-out test
videos.**

- [x] **Estimate first:** total size and frames of each subset (`ffprobe`), and load time from
      OMNI-311's measured publish cost (12-15 ms per frame); if the total is over 24 h, stop
      and decide with Ahmad before loading
- [x] Copy the subsets from Drive into `data/` (native paths)
- [x] `POST /datasets/{name}/load` (admin only) loads up to `limit` manifest clips not yet
      loaded, **one at a time through the same function as `POST /videos/upload`**, then
      extraction; sets `dataset_manifest.video_id`; resumable after a restart
- [x] **Dataset videos never expire:** `source = dataset`, `retention_until` null. The slice 16
      retention job must never delete research data
- [x] Update `dataset-layout.md`'s last section: the load endpoint exists and calls the upload
      path
- [ ] **K-4:** with all 4,500 CCD clips gated, record retention on the full set (was 57% on
      10 clips). Algorithm 1 stays as written; K-4's deadline moves to slice 7, where kept
      frames get encoded and cost starts to matter

**Acceptance:** all three subsets `ready`, counts equal the manifest, nothing failed or a
reason recorded per failure; load time and storage recorded in `results.md`.

---

## OMNI-609 · Window inspection view, and the hand check

**Why:** Phase A: *"check a sample by hand."* A derived window is only trusted once someone has
looked.

- [ ] A screen per window: the player over the window and a little past it, the window shaded,
      the annotated event marked, class and split shown; **Verified** and **Wrong** buttons
      (with a short reason) set `verified`, `verified_by`, `verified_at`
- [ ] **Write the criterion before checking:** a window is correct when it ends where the event
      visibly begins (within 1 s) and shows none of the event
- [ ] A seeded random sample, stratified: **30 UCF-Crime** (across classes, both annotation
      sources) and **30 CCD** windows
- [ ] `results.md`: correct out of checked per dataset and per source (official / UCA), with
      every *Wrong* listed and its reason

**Acceptance:** 60 windows checked by eye; the agreement rate recorded. If UCA-derived windows
are wrong noticeably more often than official ones, record it in `known-issues.md` before
slice 9.

---

# Part C — the dashboard

## OMNI-610 · Aggregates that stay fast

**Why:** **FR-9.** With the datasets loaded, `segments` holds millions of rows (a row per
decoded frame of a file, D-5). Counting them on every load will crawl.

```http
GET /dashboard/summary -> {cameras_online, cameras_total, videos, segments, alerts_today, storage_gb}
GET /dashboard/activity?hours=24 -> [{hour, segments, alerts}]
```

- [ ] An hourly rollup table (segments, admitted, bytes written, per source), **updated by the
      consumer in the same transaction as the insert**, so the counts can never drift from the
      rows (NFR-5)
- [ ] `summary` and `activity` read the rollup and indexes, never `count(*)` over `segments`
- [ ] `cameras_online` from `GET /cameras/live` state (live = online)
- [ ] `storage_gb`: video bytes plus frame and thumbnail bytes from the rollup; plus the
      retention horizon (`VIDEO_RETENTION_DAYS`) and the oldest retained recording
- [ ] `alerts_today` and the activity's `alerts`: `null` until slice 9, never a fake `0`
- [ ] A backfill script for rows written before the rollup existed
- [ ] Measure both endpoints with the datasets loaded: p50 / p95 over 100 calls, and the row
      count they stand on

**Acceptance:** the summary's counts equal a direct count, and both endpoints are measured and
recorded with the archive at full size.

---

## OMNI-611 · Operations Dashboard

- [ ] The landing page after sign-in: cameras online and offline, footage held, segments
      indexed, storage in use and days retained, activity over 24 hours (one chart, by hour)
- [ ] A panel reserved for alerts needing attention: *"Alerts arrive in slice 9"*, not empty
      space
- [ ] **Every figure is a link** to the screen behind it (cameras → the wall, footage → the
      archive, datasets → the datasets screen)
- [ ] Static first; then refresh every 30 s, paused while the tab is hidden

**Acceptance:** each number on the page matches the API and leads somewhere.

---

## OMNI-612 · Datasets screen

- [ ] Per dataset: domain, videos loaded out of total, status, windows derived and verified
- [ ] A Load control (admin only) with a limit, and progress while it runs
- [ ] A link from each dataset to its windows, and from each window to OMNI-609's view

**Acceptance:** load 10 more CCD clips from the screen and watch the count and the dashboard
move.

> **This is the cut line.** The windows are derived, split, checked and exported; the datasets
> are in the archive; the dashboard shows the real state. What follows strengthens NFR-4 and
> closes the sprint.

---

# Part D — strengthen and close

## OMNI-613 · The motion grid in one array operation, and NFR-4 again

**Why:** NFR-4 was revised from 10 feeds to 3 (D-19). The one candidate never tried is computing
the 8x8 grid's cell means in one array operation instead of 64 — **the same arithmetic**,
Algorithm 1 unchanged, less Python per frame. The revision is far easier to defend once the
cheap optimisation has been tried.

- [ ] Cell means in one NumPy operation (reshape and mean, or `cv2.resize` with `INTER_AREA`
      to G x G when the frame divides evenly); a test that the scores are **identical** to the
      current implementation on recorded frames
- [ ] `scripts/frame_cost.py` before and after, 1280x720 and 320x240
- [ ] Rerun the NFR-4 ladder with the same definition of sustained (OMNI-509), wall visible,
      10-minute confirmations
- [ ] If more feeds are sustained, update D-19's number and the scoreboard; if not, record that
      it was tried and what it changed

**Acceptance:** the per-frame cost and the sustained number are measured after the change and
recorded, whichever way they go.

---

## OMNI-614 · Diagram, docs, merge

- [ ] `docs/architecture/slice-06-dashboard-datasets.md`: loaders → manifest → split → windows →
      export, and dataset footage through the normal upload path
- [ ] `docs/context/week-06.md`, one section per ticket
- [ ] `results.md` scoreboard: NFR-5 (live), SM-3 target, the split, windows, hand check,
      dashboard; `decisions.md` and `known-issues.md` current
- [ ] `uv run pytest` green
- [ ] Everything committed on `slice-06-dashboard-datasets` (by you)
- [ ] **You merge into `master`** (`git switch master`,
      `git merge --no-ff slice-06-dashboard-datasets`), then `uv run pytest` green on `master`
- [ ] Slice 6 ticked on the tracker

---

## Definition of done

The plan's proof, on a fresh `docker compose up -d`:

> The dashboard shows accurate live counts and every number leads somewhere. A dataset loads
> through the normal pipeline, appears in the archive, and its derived lead-up windows are
> spot-checked on screen.

- [ ] All of the above true on a fresh stack
- [ ] `results.md` has: the split (with hashes), windows per dataset, the hand-check rate, the
      CCD pre-event distribution and the SM-3 target, NFR-5 rechecked for live, the dashboard
      endpoints' timings
- [ ] `datasets/splits/` and `datasets/windows/` committed and copied to Drive for Colab
- [ ] Merged into `master`

---

## What to learn this sprint

- [PostgreSQL: counting rows fast, and why `count(*)` is slow](https://wiki.postgresql.org/wiki/Count_estimate)
  — the reason for the rollup table.
- [Upserts with `ON CONFLICT`](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT)
  — keeping hourly counters in the same transaction as the insert.
- [Group-aware splits (`GroupShuffleSplit`)](https://scikit-learn.org/stable/modules/cross_validation.html#group-k-fold)
  — why CCD clips from one YouTube video must stay on one side.
- [UCA: UCF-Crime Annotation (Yuan et al., CVPR 2024)](https://arxiv.org/abs/2309.13925)
  — where the training videos' event times can come from.
- Deriving labels from event annotations — working backward from an event's start, and
  writing down every window that could not be made.

---

## Working with Claude Code

`CLAUDE.md` is read automatically. One ticket per session. Paste the ticket, then:

> Here is ticket OMNI-6xx from our sprint board. Implement exactly what it asks and nothing
> more. Before starting, read the context sections for the tickets this builds on. When you
> are done, show me the diff, tell me which acceptance criteria you verified and how, and
> suggest a short commit message without the ticket number. Do not run any git command that
> changes the repository; I commit myself.

Four things to insist on this sprint:

- **No event time, no window.** If a time has to be guessed, stop and ask.
- **The split before the windows, and it never moves.** Rebuilding it must give identical files.
- **Rules before results.** The SM-3 rule and the hand-check criterion are written down before
  the numbers are looked at.
- **Dataset footage is ordinary footage.** Same upload function, same gate; only its retention
  differs (never deleted).
