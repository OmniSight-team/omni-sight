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

---

## OMNI-602 · Three doc fixes from the slice 5 review

### Why this ticket exists

Three places still described slice 4 as current or held a slice 5 item open: OMNI-506's
acceptance asked for "mostly 304s on still scenes", which the preview design (D-14) cannot
give on a live feed (K-12); the FR-1a row quoted the sampling era's ~4.1 frames/s; and the
slice 4 diagram shows the 0.2 s sampling with no note that it is gone.

### What was done

2026-10-07, docs only.

- **K-12.** `docs/tickets/week-05.md`, OMNI-506's acceptance reworded to the ticket's text,
  with a note of what it read before. `results.md`, the wall row: target reworded the same
  way, the frozen-feed 304s from OMNI-503 (432 of 480) added to the measured column, status
  **Pass**. K-12 moved to *Fixed (reworded)* in `known-issues.md` with what it was and why no
  code changed
- **FR-1a row.** "Live: ~4.1 frames/s stored" replaced with OMNI-501's figure: every frame
  gated (15.0/s), admitted frames stored, 3.05-3.30/s on `cam05`. OMNI-501 and its date added
  to the row
- **Slice 4 diagram.** One line at the top: the 0.2 s sampling was removed in slice 5 (D-9),
  pointing to `slice-05-camera-wall.md`. The diagram is unchanged

### Verification performed

- Searched `README.md`, `docs/README.md`, `docs/architecture/`, `docs/results.md` and the
  dataset docs for "sampl", "0.2 s" and "4.1 frames". What is left is the conditions of dated
  slice 3-4 measurements (correct as history) and `slice-05-camera-wall.md`, which already
  says the sampling was removed. No doc describes it as current
- CRLF kept on every edited file

### Not verified

- `docs/context/` files from earlier sprints were not searched: they are the build story and
  describe the sampling as it was at the time

### Result

No doc describes the live sampling as current; K-12 closed by rewording, the wall row reads
Pass.

---

## OMNI-603 · UCF-Crime training videos: event timestamps

### Why this ticket exists

Lead-up windows are derived by working backward from a known event (Phase A §3.4, §3.6).
UCF-Crime times its anomalies for the 290 test videos only; the 1,610 training videos (810 of
them anomalies) have a class and no time. Without times the surveillance head has almost
nothing to train on. UCA was the candidate, not yet checked for availability.

### What was done

2026-10-07.

- **Obtained.** The GitHub API lists the repository's tree (commit `e478cb5b`, 2024-04-30):
  `UCF Annotation/{txt,json,txt_mask}`. The six txt and json files plus the 0-byte
  `revised_en_UCFCrime_Train.json` were downloaded from raw URLs pinned to that commit into
  `data/ucf_crime/annotations/uca/{txt,json}/`, the commit written to `SOURCE_COMMIT`. Every
  size equals the tree's. README: Apache-2.0, academic and research use. Recorded in
  `dataset-layout.md`
- **Matched.** All 1,854 UCA names are in the official lists (none in two UCA splits); 804 of
  810 training anomalies and all 140 test anomalies are covered. UCA's own Train / Val / Test
  is not the official split (86 official test anomalies are in UCA's Train): recorded as a
  trap, not used. Matching was against the official lists, not the disk: the lists were
  checked against the full set on Drive on 2026-09-21, and only 38 clips are local
- **The picking rule.** UCA's sentences describe everything that happens. A frequency
  comparison of each class's words against normal videos' words (training videos only) gave
  each class's vocabulary; from it, word patterns per class were written into
  `scripts/uca_event_times.py`: the earliest-starting segment whose sentence matches; no
  match, no time. Written down before running the agreement
- **Ran it once.** 594 of 810 training anomalies timed; agreement on 110 test anomalies:
  median 3.0 s, mean 11.3 s. Then looked at six untimed training videos to rule out a bug:
  none, they use other words ("a burst of flames") or never describe the act. The rule was
  not widened, because the agreement would then be measured on data already seen
- **D-21** in `decisions.md`: where every UCF-Crime event time comes from, the rule, the match
  count and the agreement; `results.md` entry and a scoreboard row

### Verification performed

- File sizes against the GitHub tree: all equal
- Counts cross-checked: UCA anomaly names 944 = 950 - 6 missing; normals 764 + 146 = 910;
  944 + 910 = 1,854
- The official temporal file parsed for all 290 test videos; the comparison uses the first
  interval's start, frame / 30

### Not verified

- Video frame rates: the official frames are converted at 30 fps as its readme says; OMNI-607
  probes every video
- Whether any time is right by eye: OMNI-609's hand check
- The rule's agreement on the training class mix: the test set has few videos of some classes
  (Robbery 5, Stealing 2)

### Result

UCA is obtainable and covers 804 of 810 training anomalies; the written rule times 594. Its
starts sit a median 3.0 s from the official ones (34% within 1 s), so UCA-derived windows are
less exact than official ones; OMNI-609 compares the two by eye. Decision D-21.

---

## OMNI-604 · Dataset manifest and the three loaders

### Why this ticket exists

Each dataset keeps its native layout, so each needs its own loader, and all three must emit
one shared manifest. The manifest has to cover every clip from the annotation files, not
only the 38 in the local mirror, because training runs on Colab from Drive.

### What was done

2026-10-08.

- **Loaders** in `services/common/omnisight_common/datasets/` (`ucf_crime.py`, `ccd.py`,
  `virat.py`), pure file readers with no database, so Colab can import them. The D-21 rule
  moved unchanged from `scripts/uca_event_times.py` into `datasets/uca.py`; the script now
  imports it
- **The whole dataset without the whole dataset.** The mirror holds 38 videos. A loader
  needs the list of every video file (CCD normals have no label file; UCF-Crime's class is
  the folder on disk). `scripts/list_dataset_videos.py`, run in Colab, wrote
  `<dataset>/video_files.txt` on Drive (UCF-Crime 1,950, CCD 4,500, VIRAT 329) and packed
  those with VIRAT's full `annotations/` into a 31.7 MB zip, empty directories kept (865
  files, 122 empty directories). Unzipped into `data/`
- **Migration `48f90770010b`**, `dataset_manifest`, unique `(dataset, clip_key)`. Added to
  the ticket's columns: `video_relpath` (where the file is, for OMNI-608) and `attributes`
  JSONB (UCF-Crime's official list and second interval, CCD's `youtube_id` and conditions
  for OMNI-605's grouping, VIRAT's scene and event counts). `annotation_source` says where
  a time comes from: `ucf_crime_temporal`, `uca`, `ccd_binlabels`, `virat_events`, or why
  there is none: `normal`, `untimed`
- **Choices inside the loaders.** UCF-Crime test anomalies take the official time even when
  UCA has one (86 official test anomalies sit in UCA's Train); the first interval is the
  event, the second goes in `attributes` for OMNI-607 to skip and count. CCD
  `event_end_s` = end of the last labelled frame. VIRAT rows carry no class or time
  (many events per video, SM-1 only). Any inconsistency raises instead of being skipped:
  a filename listed twice, a listed video not on disk, a list class that disagrees with the
  disk folder, a crash clip with no label line, a mapping naming an object not in the
  objects file
- **`scripts/build_dataset_manifest.py`** upserts every entry (labels refreshed, `split` and
  `video_id` never touched) and checks the counts; exits non-zero on a mismatch
- **18 trap tests** in `services/common/tests/test_dataset_loaders.py`, each building a tiny
  dataset with the trap in it: UCF-Crime event-recognition namesakes, a duplicate filename,
  the 0-byte split-folder training list, class from the folder not `Part-N`, frames at 30
  fps with a second interval, UCA's split not used, earliest matching UCA segment, normals'
  lists; CCD commas inside the brackets, first `1` / 10 fps, `(subset, id)` identity, an
  unlabelled crash clip; VIRAT empty directories, objects only, the three files together,
  a mapping to a missing object, events without mapping, scene from the filename
- Not loader traps, so no test here: UCF-Crime length and 30 fps (OMNI-607 probes), the
  normal footage split three ways (OMNI-605), CCD's 5 s clips (OMNI-606), CCD normals from
  BDD100K (slice 10), VIRAT's unbalanced scenes (SM-1's query draw)

### Verification performed

- Real stack (`docker compose up -d`), Postgres in Docker. Migration upgraded, downgraded,
  upgraded; `alembic check`: no difference between model and migration
- `build_dataset_manifest.py`: UCF-Crime 1,900, CCD 1,500 crash + 3,000 normal, VIRAT 275,
  all equal to `dataset-layout.md`. 6,675 rows. Run twice: same rows
- UCF-Crime: 140 official test times, 594 UCA times, 216 untimed (6 not in UCA, 210 no
  segment matches), 950 normal; equal to D-21. 16 test videos have a second interval
- VIRAT per scene equal to `dataset-layout.md`'s "with events" row, all 11 scenes
- CCD crash starts 3.0 to 4.9 s, median 3.6 s; none at 0
- `scripts/uca_event_times.py` output byte-identical before and after the move
- `uv run pytest`: 405 passed, 1 skipped (the 18 new ones included); ruff clean on the new
  and changed files

### Not verified

- The listings are Drive as of 2026-10-08; nothing checks they stay in step with Drive
- No time is checked by eye: OMNI-609
- The loaders were not run on Colab against Drive itself, only against the local mirror,
  which uses the same relative paths

### Result

`dataset_manifest` holds every clip of the three datasets, 6,675 rows, every count equal to
the audited numbers, and every loader trap has a passing test. `split` and `video_id` are
empty until OMNI-605 and OMNI-608.
