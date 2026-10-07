# Context notes — Sprint 6

Slice 6, real footage and the dashboard, 7 – 13 Oct 2026. Tickets in `docs/tickets/week-06.md`.
Entries are added as each ticket closes.

---

## OMNI-600 · Branch and baseline

### Why this ticket exists

Slice 6 adds the dataset manifest, the windows, a rollup table and the dashboard. A
known-good starting point is needed first, so that anything that breaks later is known to
come from this sprint and not from slice 5.

### What was done

2026-10-07, on `master` at `24882ba`.

- **`master` has slice 5:** `git log` shows `24882ba docs: tick the slice 5 merge` on top of
  `661029b Merge branch 'slice-05-camera-wall'`. The only untracked file is
  `docs/tickets/week-06.md` (this sprint's ticket file)
- **Stack:** Docker Desktop was not running; started it, then `docker compose up -d`. All
  nine services up (`postgres`, `rabbitmq` healthy; `consumer`, `consumer-live`,
  `ingestion`, `query`, `frontend`, `mediamtx`, `nginx` running). `https://localhost`
  answers 200
- **Branch:** `slice-06-dashboard-datasets` is created by Ahmad
  (`git switch -c slice-06-dashboard-datasets`). It starts at `24882ba`, the same commit the
  suite ran on

### Verification performed

- `uv run pytest`: **387 passed, 1 skipped**, 1 warning (Starlette's `httpx` deprecation),
  148 s. Same count as the end of slice 5

### Not verified

- Nothing in the browser beyond the 200 from nginx; the slice 5 definition of done was
  already checked on a fresh stack in OMNI-513

### Result

Baseline green: slice 5 on `master`, stack running, 387 passed / 1 skipped.

---

## OMNI-601 · NFR-5 rechecked for live cameras (K-11)

### Why this ticket exists

NFR-5's scoreboard row rested on OMNI-319, which tested the slice 3-4 pipeline. Since then a
live camera stores admitted frames only (OMNI-501), so its frame indexes have gaps that the
OMNI-319 check reads as losses, and live frames go to their own queue (OMNI-502), which the
check never waited for. K-11 was found by reading the code; the check had not been run on
slice 5.

### What was done

2026-10-07, on `slice-06-dashboard-datasets`. Only `scripts/verify_definition_of_done.py`
changed, check F and what it uses; checks A-E are untouched.

- **The rule.** The index-gap check is gone. Loss is: a row whose file is missing, or fewer
  stored rows than the worker reported admitted. Read from the worker's code: `_handle`
  writes the frame (inside `process_frame`), counts it admitted, then publishes it with a
  broker confirm, and `_report` runs between frames on the same thread. So every
  `camera_stats` report counts only frames the broker had confirmed, and is a floor for the
  stored rows. A killed worker sends no final report, so its last report can be below what
  was stored (seen once: 14 rows, 13 reported); that is not a loss
- **Per session and per camera.** `camera_stats` keeps only the current session's totals,
  and after a restart the new session replaces the old within seconds (OMNI-504 resumes
  it). So a `StatsWatch` thread reads the row every 0.5 s during each case and keeps the
  highest count per session; the camera's lifetime `admitted_motion + admitted_heartbeat`
  is checked too. Rows are split into sessions as before (the index going back down)
- **Queues.** `wait_drained` now waits for the file queue, `omnisight.segments.live` and the
  camera queue. The ticket names two; the third carries the stats reports, and the
  comparison is only fair once they are applied
- **The cases.** The two consumer cases now stop and kill `consumer-live`, the consumer that
  stores live frames (`consumer` only carries files and the camera queue now)
- **Stale part removed.** After an ingestion restart or kill the old check asserted that the
  worker did *not* resume (K-5, then known) and started it by hand. Since OMNI-504 it resumes
  by itself, so the check now waits up to 60 s for the new session and asserts it appeared.
  Every case also checks capture keeps producing after the failure, then stops the camera
  and drains before comparing
- **Self-test** (runs before anything else): a live capture with gaps and two sessions is not
  flagged; a killed worker's low last report is not flagged; a missing row, a missing file and
  a short count each are

### Verification performed

- Self-test passes at the start of both runs
- `--only F --camera cam02`: **32 of 32**. `--only F --camera cam05`: **32 of 32**. Zero lost by
  the new rule in all eight case-runs; numbers in `results.md`, OMNI-601
- Both ingestion cases: a second session appeared by itself; the consumer cases: the live
  queue held 14-26 messages while `consumer-live` was down, all stored afterwards
- `ruff check` on the script: clean (the `json` import was only used by the removed part)

### Not verified

- Few frames per case: on these feeds the gate kept about 3-4% during the runs (22-55
  admitted per case), although `cam05` was chosen as the busier feed
- One camera per case; a failure longer than 15 s; the broker recreated with live capture
  running
- The `StatsWatch` floor can miss a session's very last report if the next session replaces
  it within 0.5 s; the lifetime counter still includes it, and it is checked too

### Result

NFR-5 rechecked for live on the slice 5 pipeline: 0 frames lost in all four cases, two runs.
Scoreboard row updated; K-11 moved to *Fixed*.
