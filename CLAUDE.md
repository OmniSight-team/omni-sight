# CLAUDE.md — OmniSight Phase B

Capstone project 26-2-D-17 (Braude College), Ahmad Tawil. Phase A (the design book) is
finished and graded; this repo is Phase B, the implementation. Teammate Cyrine Fahoum is
not active right now, so Ahmad works alone.

## How to talk to Ahmad

- Short, clear, direct. No long explanations unless he asks.
- Give **one recommendation**, not a menu of options.
- Do not repeat what he already knows or re-explain the project to him.
- If something he asked for conflicts with Phase A or a requirement, say so in one or two
  sentences **before** building it.
- **One branch per slice** (e.g. `slice-05-camera-wall`), created at the start of the
  sprint and merged into `master` at the end. No PRs or reviews while Cyrine is inactive;
  he will say when she rejoins.

## Git: Ahmad runs every git command

- **Never run a git command that changes the repository**: no `commit`, `add`, `branch`,
  `switch`/`checkout`, `merge`, `push`, `pull`, `rebase`, `reset`, `stash`, `tag`. Ahmad does
  all of them himself. Read-only commands (`status`, `diff`, `log`) are fine.
- When a ticket is done, **suggest one short commit message** for him to use, in the repo's
  style: a `feat:`, `fix:` or `docs:` prefix and a plain sentence saying what changed.
  **No ticket number** in the message. Example:
  `feat: gate every live frame and publish only admitted frames`
- When a ticket says to create a branch, commit or merge, tell him the exact command to
  run; do not run it.

## Phase A is the spec

- The Phase A book is `../../OmniSight_Capstone_Project_Phase A_26-2-D-17 (1).pdf` (outside
  the repo). Requirements are referenced by ID: `FR-*`, `NFR-*`, `SM-*` (success metrics),
  `TC-*` (test cases).
- **Algorithms are implemented as Phase A writes them.** Algorithm 1 (§3.5.1, pseudocode in
  Appendix B.1) is followed line by line. Do not add steps the pseudocode does not have
  (sampling, skipping frames, shortcuts for speed) and do not drop steps it has.
- Any departure from Phase A, however small, is written in `docs/decisions.md` as a
  **Deviation** with its reason and evidence, and Ahmad is told. Never silently.
- Never invent a target number. If a Phase A target is unreachable, measure why and record
  the revision in `docs/decisions.md` (example: D-1/D-2, DoTA replaced by CCD and SM-3 revised).

## Before starting any work

Catch up on what was already done instead of asking Ahmad to repeat it:

1. `docs/tickets/` — the current sprint's file (the newest `week-NN.md`): which tickets are ticked, which is next.
2. `docs/context/` — the sections for the tickets you are about to touch, and the ones they build on.
   These files are long (the week 3-4 one is about 200 KB): search them by ticket number
   (`OMNI-312`) or topic and read those sections, do not read them end to end.
3. `docs/results.md` scoreboard, `docs/decisions.md` and `docs/known-issues.md` — what is
   measured, what was decided and why, and what is still open.

Do not redo, contradict or re-decide something recorded there without saying so first.

## How the work is organised

The plan is 18 vertical slices. Each sprint is a ticket file Ahmad works through in order.

| File | What goes in it |
|---|---|
| `docs/tickets/week-NN.md` | The sprint's tickets (`OMNI-N00`...). Checkboxes `- [x]` tagged with the requirement they serve, e.g. `**[FR-1b]**`. Ticked when done |
| `docs/context/week-NN.md` | One section per ticket: *Why this ticket exists · What was done · Verification performed · Not verified · Result*. The build story, including detours and mistakes |
| `docs/results.md` | **Measurements only.** Scoreboard table at the top (requirement, target, measured, pass/fail, date, entry), then one short entry per measurement: conditions, numbers, what was not covered. No process narrative |
| `docs/decisions.md` | Why things were built the way they were; every deviation from Phase A |
| `docs/known-issues.md` | Found and not fixed: evidence, requirement affected, which slice must deal with it |
| `docs/architecture/` | One pipeline diagram per slice |

Rules:
- Work one ticket at a time, in the order of the ticket file. Do not start the next one unless asked.
- Do only what the ticket asks. A problem outside the ticket goes into `known-issues.md`, not
  into a fix.
- A result goes into `results.md` the day it is measured, never reconstructed later. Update
  the scoreboard row too.
- The vertical-slice tracker site (with `plan-data.js`) is a separate project, not in this
  repo. Do not edit it unless asked.

## Measuring

- Measure on the **real running stack** (`docker compose up -d`), real footage, real API.
  Not mocks. This is for **system** measurements (latency, throughput, data loss, storage,
  the dashboard). **Model** measurements (SM-1 to SM-4: embeddings, search, forecasting) run
  on **Colab's GPU** from Drive, with the same `services/common` code and the committed
  split / windows / sample files (D-26). The product holds only the 60-clip hand-check
  sample of dataset footage, never the full datasets.
- State the conditions: machine, settings, clip, how many runs. Say what was *not* covered.
- Report the number you got, including failures. Do not change defaults to make a
  requirement pass; label exploration as exploration.
- Label one-machine or small-sample results **preliminary**. Short windows can hide trends
  (a 30 s window made 10 feeds look fine; 3 minutes showed the queue climbing).
- Measuring scripts live in `scripts/` with a docstring saying how to reproduce. Long runs
  go in the background.
- The machine: Windows 11 Home, i7-1165G7 (4 cores, 8 threads), 15.7 GB RAM, Docker Desktop
  with 8 CPUs and 7.6 GiB; everything runs on it together.

## The system

Docker Compose, one machine: `postgres`, `query` (FastAPI API, auth, Alembic migrations),
`ingestion` (the only service that touches video; not exposed), `consumer` (stores segments
from the queue), `rabbitmq` (durable queue, ack after commit), `mediamtx` (RTSP simulator,
ten looping feeds), `frontend` (Next.js; has its own `frontend/CLAUDE.md`), `nginx` (TLS,
serves `/thumbs/` and `/media/` straight from the volumes). Shared code is `services/common`.
Later slices fill `services/ai_workers` and `services/pfm`.

```
docker compose up -d                          # whole stack; open https://localhost
uv sync                                       # Python workspace
uv run pytest                                 # needs Postgres up; uses a scratch database
uv add <pkg> --package omnisight-query        # dependency for one service only
                                              # (omnisight-ingestion for ingestion)
```

Media and playback only work through nginx at `https://localhost`, not the dev server on 3000.

## Datasets

- UCF-Crime and VIRAT (surveillance), CCD (traffic; **replaces DoTA**, which cannot be
  obtained), SoccerNet (slice 10), AI City (slice 13). Full copies are on Ahmad's Google
  Drive; `data/` holds a small local subset (38 clips) and is never committed.
- Each dataset keeps its **native layout**; see `docs/dataset-layout.md` and
  `docs/datasets.md`. Check a claim about a dataset (link, file, count) before stating it.

## Environment gotchas

- The repo is on Windows with CRLF line endings. Keep CRLF when editing. A diff that is only
  line endings is not a change; do not report it.
- `data/`, `models/` and `.env` are never committed.
