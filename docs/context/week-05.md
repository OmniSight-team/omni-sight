# Context notes — Sprint 5

Slice 5, the camera wall, 30 Sep – 6 Oct 2026. Tickets in `docs/tickets/week-05.md`.
Entries are added as each ticket closes.

---

## OMNI-500 · Branch and baseline

### Why this ticket exists

Slice 5 changes the live worker, the queue layout and the schema. A known-good starting
point is needed first, so that anything that breaks later is known to come from this
sprint and not from slices 3–4.

### What was done

2026-09-30, on `master` at `d6d5943`.

- **`master` is not clean.** `git log` shows `d6d5943` on top, so slices 3–4 are there, but
  the working tree has the 2026-09-28 documentation reorganisation uncommitted:
  - modified: `README.md`, `docs/README.md`, `docs/context/week-03-04.md`,
    `docs/dataset-layout.md`, `docs/results.md`, `services/ingestion/app/pipeline.py`,
    `services/ingestion/app/settings.py`
  - untracked: `CLAUDE.md`, `docs/decisions.md`, `docs/known-issues.md`,
    `docs/tickets/week-05.md`

  The two code files differ only in comments (the pointers moved from `docs/results.md` to
  `docs/decisions.md` D-4 and D-9); no behaviour changed. Committing is Ahmad's, so it is
  left for him, before the branch is created
- **Stack:** `docker compose up -d` from stopped. All eight services running, `postgres`
  and `rabbitmq` healthy, `https://localhost` answers 200
- **Suite:** `uv run pytest` against a scratch database (`omni500_scratch`, created,
  migrated from empty to `08b81a0fd8d1` with `alembic upgrade head`, dropped afterwards),
  because five query test files empty the `videos` table of whatever database they run on

### Verification performed

- `uv run pytest`: **304 passed**, 1 warning (Starlette's `httpx` deprecation), 106 s. Same
  count as the end of slices 3–4. Run on the working tree as it is, uncommitted changes
  included
- The dev database after the run: 3 videos, 0 cameras, 300 segments — untouched
- All eleven migrations applied cleanly from empty on the scratch database

### Not verified

- Nothing was run on the branch itself, because it does not exist yet. The branch is
  created from the same tree, so the result carries over only if nothing else changes
  between the commit and the branch
- No live capture was started; this ticket only asks that the stack runs and the suite is
  green

### Result

Stack up and suite green (304). Two items are Ahmad's and still open: commit the pending
documentation changes on `master`, then create `slice-05-camera-wall`.
