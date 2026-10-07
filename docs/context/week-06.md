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
