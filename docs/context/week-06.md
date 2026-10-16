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

---

## OMNI-605 · Fix the train / validation / held-out split

### Why this ticket exists

Every measurement from now on compares on the same clips. A split that moves invalidates
every comparison, so it is fixed once, before any window is derived.

### What was done

2026-10-08.

- **Fractions.** Phase A asks for held-out clips and a held-out validation split but gives
  no fractions. 15% everywhere, the share UCF-Crime's official test set already has (290 of
  1,900). Written as **D-22**
- **`omnisight_common.datasets.split`**: UCF-Crime held-out = the official test list;
  validation 15% of the official training list per class, and within a class per timed /
  untimed (the ticket said class; this keeps validation's share of windowed videos equal to
  train's). CCD: crash clips by whole `youtube_id` group in shuffled order (held-out to 15%,
  then validation, then train), normals per clip. VIRAT all `evaluation`. Seed 605, inputs
  sorted before each shuffle, so nothing depends on dict or set order
- **`scripts/build_dataset_split.py`** writes `datasets/splits/{ucf_crime,ccd,virat}.csv` and
  `dataset_manifest.split`. If a committed CSV exists and the rebuild differs, it stops and
  writes nothing: the split never moves
- **`.gitattributes`** (new): `datasets/** -text`. `core.autocrlf` is on here; without it,
  git would rewrite the CSVs' line endings on checkout and the recorded hashes would not
  match the files a clone gets
- **6 tests** in `services/common/tests/test_dataset_split.py` (8 cases): rebuild
  byte-identical to the committed file per dataset, held-out exactly the official test list,
  every UCF-Crime class in all three parts, no CCD source video on two sides, crash and
  normal in every part, VIRAT evaluation only. Skipped when the local mirror is missing
- D-22 in `decisions.md`; counts, seed and hashes in `results.md` with a scoreboard row

### Verification performed

- Ran the script twice: same files, same hashes; 0 manifest rows without a split
- Guard: changed one line of `ccd.csv` by hand and ran the script: it refused and wrote
  nothing; file restored, hash back to the recorded one
- `git check-attr text datasets/splits/ccd.csv`: unset (no conversion)
- Counts in Postgres agree with the CSVs: UCF-Crime held-out 140 official + 150 normal;
  CCD 20 / 23 / 90 source videos in held-out / validation / train
- `uv run pytest services/common/tests`: 26 passed; ruff clean

### Not verified

- Balance beyond class: scene, camera, time of day are not stratified
- CCD normals may share source footage; CCD gives no field to group them by
- The CSVs were not yet read on Colab

### Result

The split is fixed: UCF-Crime 1,368 / 242 / 290, CCD 3,132 / 675 / 693, VIRAT 275
evaluation, seed 605, hashes in `results.md`. CCD's crash held-out is 243, not 225, because
source videos are never split.

---

## OMNI-606 · CCD pre-event footage, and the SM-3 target

### Why this ticket exists

D-2 replaced Phase A's 15 s (unreachable on DoTA) with mTTA on CCD, the target to be set from
CCD's own pre-event footage before any model exists, by a rule written before the numbers.

### What was done

2026-10-08.

- **Rule first.** D-23 written into `decisions.md` before the script existed: the ticket's
  recommended rule, unchanged (target = half the median pre-event footage of the held-out
  crash clips). Disclosed in D-23: OMNI-604's sanity check had already printed the median
  over all crash clips (3.6 s); the rule predates that, in the ticket file
- **`scripts/ccd_pre_event.py`**: reads the labels through the CCD loader and the split from
  the committed CSV; mean, median, p10-p90, min, max, under 1 s and a 0.5 s histogram, for
  all crash clips and per split; then applies D-23
- **Result:** held-out median 3.60 s, **target mTTA ≥ 1.80 s**, written into the SM-3
  scoreboard row and appended to D-23

### Verification performed

- Totals agree with OMNI-604's manifest check (min 3.0, median 3.6, max 4.9 over 1,500)
- Split sizes 1,032 / 225 / 243 equal `results.md` OMNI-605
- Histogram rows sum to each group's n

### Not verified

- Videos not read: 10 fps and 50 frames per clip rest on the clips sampled in OMNI-300;
  OMNI-607 probes fps

### Result

SM-3 has a target, mTTA ≥ 1.80 s, from a rule written before the data was looked at.
Every crash clip has 3.0-4.9 s before the accident; nothing to shorten or drop for OMNI-607.

---

## OMNI-607 · Derive the lead-up windows

### Why this ticket exists

The sprint's dependency milestone. Phase A derives lead-up windows by working backward from
each known event and feeds the predictor 30 s and 60 s windows; no dataset ships them, and
slices 9 to 12 train on them.

### What was done

2026-10-09.

- **Probe first.** The ticket wants each video's fps from its own probe, and negative
  windows need each normal video's length, but only 38 videos are local.
  `scripts/probe_dataset_videos.py` (standard library plus `ffprobe`, header only) ran in
  Colab against Drive, like `list_dataset_videos.py`, and wrote `video_probe.csv` for
  UCF-Crime and CCD: 6,450 files, 0 errors. Unzipped into `data/`
- **`omnisight_common.datasets.windows`**: pure functions over the loaders' entries, the
  committed split and the probes. Positive `[start - L, start)`, L = 30 / 60 s on UCF-Crime;
  CCD one window `[0, accident)`; shortened to 0 and flagged; second interval, event at 0 s,
  event past the video's end and untimed anomalies skipped with a reason; negatives at a
  seeded random position (seed 607), CCD negatives with a length drawn from the same split's
  crash windows. A missing or failed probe stops the derivation
- **Rules written as D-24** for the cases the ticket left open (negative lengths on CCD, a
  normal video shorter than L, events at 0 s, keeping shortened windows)
- **Migration `5c0e2f7a9b13`**, `event_windows`: the ticket's columns plus `kind`,
  `nominal_length_s` (NULL on CCD) and `shortened`; unique `(manifest_id, kind,
  nominal_length_s)` with NULLs not distinct; a check that every window has positive length
- **`scripts/build_event_windows.py`** writes `datasets/windows/{dataset}.csv` and
  `{dataset}_skipped.csv`, refuses to change an existing file (like the split), inserts rows
  with `ON CONFLICT DO NOTHING` so OMNI-609's verdicts survive a rerun, and prints the counts,
  the off-rate videos and the hashes. `.gitattributes` already keeps `datasets/**` byte-exact
- **15 tests** in `services/common/tests/test_event_windows.py`: window ends at the event,
  shortening, second interval per L, the three skip reasons, negatives inside the video and
  in their split, a short normal video, determinism and input order, CCD's single window,
  CCD negative lengths per split, off-rate report, missing / failed probe, and the committed
  files rebuilt byte for byte
- **A detour:** before writing D-24, the build was smoke-tested once with stand-in
  durations (UCA's, else 600 s) to see it run end to end; output and rows deleted, the rules
  unchanged after. Disclosed in D-24
- `results.md` entry and scoreboard row; `scripts/README.md`, `dataset-layout.md` updated

### Verification performed

- Real stack, Postgres in Docker. Migration upgraded, downgraded, upgraded; `alembic check`
  clean; `\d event_windows` shows `NULLS NOT DISTINCT` and the check constraint
- Drive probe vs local probe on the 35 mirror clips: identical rows
- Ran the build twice: identical files, still 7,760 rows. Guard: edited line 2 of `ccd.csv`,
  the script refused and wrote nothing (exit 1); file restored, hash back
- Accounting: 680 + 54 + 216 = 950 anomalies per L; 540 = 594 UCA - 54 at 0 s
- SQL: 0 positives ending off their event start, 0 split mismatches with the manifest,
  0 negatives on non-normal clips
- `git check-attr text datasets/windows/ccd.csv`: unset
- `uv run pytest services/common/tests`: 41 passed. Full suite: 425 passed, 1 failed
  (`test_no_frame_is_lost_or_counted_twice_across_a_reconnection`, the intermittent failure
  already in `known-issues.md`; 53 of 53 on rerun of its file). Ruff clean on new files

### Not verified

- No window looked at by eye: OMNI-609
- The 54 UCA events at 0 s: real starts, or the D-21 rule picking a scene-setting sentence?
  Worth a look in OMNI-609
- The CSVs not yet read on Colab; not yet copied to Drive

### Result

7,760 windows derived, exported and hashed: UCF-Crime 680 positive and 950 negative per L,
CCD 1,500 positive and 3,000 negative. Every anomaly has its windows or a recorded reason.
Most UCF-Crime events start early in their video: 67% of 30 s and 84% of 60 s positive
windows are shortened (median 15.8 s of footage), which slice 9 has to live with.

---

## OMNI-608 · Load the datasets into the product

### Why this ticket exists

The plan put CCD (4,500), VIRAT with events (275) and UCF-Crime held-out (290) into the
product so slice 7 could encode them and the dashboard would show real volumes, with the
sprint rule that dataset footage goes through the normal upload path.

### What was done

2026-10-09. The ticket changed scope half-way (D-26); both halves are here.

- **The shared upload function.** `POST /videos/upload`'s body moved into `store_video()`
  (sniff, stream, row, probe), behaviour unchanged (its 15 tests pass). An `on_insert` hook
  writes the manifest link in the video row's own transaction. `claim_extraction()` came
  out of the extract route so the loader claims a video the same way
- **`POST /datasets/{name}/load {limit}`** (admin) and **`GET /datasets`** in
  `services/query/app/datasets.py`: a background thread loads clips one at a time through
  `store_video`, then `run_extraction`; resumable (a clip is done when `ready` with a
  finished extraction; a stored but unextracted clip is extracted, not stored again); a
  `failed` count added to the ticket's response for the acceptance check and OMNI-612.
  The mirror is mounted read-only into `query` at `/datasets`
- **Never expires:** `source = dataset`, `retention_until` NULL; `backfill_retention.py`
  now skips dataset rows (it would have given them a date)
- **Estimate first.** The full videos are on Drive: `plan_dataset_load.py` listed the 5,065
  clips, `estimate_dataset_load.py` (Colab) gave size and frames: 50 GB, 2.13M frames. Two
  limits would be hit (19 files over 500 MB, two hour-long videos past the 900 s timeout);
  Ahmad chose to raise both. Then measured live: 34-55 ms per frame end to end at 720p, not
  the 12-15 ms the estimate assumed, so about 20-23 h with the simulator stopped (27-34 h
  with it). A stray live worker from a test run was found eating CPU (K-19)
- **K-18 found and fixed on the way:** five query test files delete every video; with
  hours of dataset footage in the dev database, one `uv run pytest` would have wiped it.
  The query tests' `conftest.py` now points them at `omnisight_test`, created and migrated
  on the fly
- **The full load started, then stopped (D-26).** Drive for desktop was installed, the copy
  ran (1,354 CCD clips) and the load was waiting for them when Ahmad asked what the
  footage is for: real users never see datasets, and model measurements need a GPU, so they
  run on Colab. Decision D-26: the product holds only OMNI-609's hand-check sample. Copy and
  load stopped before any clip was loaded; the copied clips, three trial videos and the
  throwaway admin were removed; the two raised limits reverted (D-25). `CLAUDE.md`'s
  measuring rule now separates system measurements (the stack) from model measurements
  (Colab)
- **The sample, drawn here for OMNI-609:** `omnisight_common.datasets.hand_check`, seed 609:
  UCF-Crime 15 official + 15 UCA, round-robin over the 13 classes; CCD 30 crash clips.
  `datasets/hand_check/sample.csv`, fixed like the split; mounted into `query` at
  `/hand_check`. Copied (60 clips, sizes checked against Drive) and loaded through the API
- **K-4** moves to slice 7 (Ahmad); 67.6% kept on the 30 sampled CCD clips recorded

### Verification performed

- Real stack: 60 of 60 `ready`, 0 failed; all `source = dataset`, no retention date, linked
  in the manifest; `GET /datasets` both `loaded`; storage +2.06 GB. Before that, a 3-clip
  trial through the live endpoint (deleted after)
- `test_dataset_load.py` (6): admin only (401 / 403 / 404), clips go through `store_video`
  as `dataset` with no retention date and the file copied byte for byte, only the sample
  is loaded, a missing file is counted, a stored but unextracted clip resumes without a
  second copy, a finished dataset re-queues only its failures, the upload route still sets
  a retention date
- `test_hand_check_sample.py` (3): redraw byte-identical, 15 + 15 sources each over 13
  classes, 30 distinct crash clips. The script run twice: same hash
- Query suite on `omnisight_test`: 260 passed, the dev database untouched (3 users, 6,675
  manifest rows)
- Settings in the running `query` container: 500 MB, 900 s, the sample path; nginx 500m
- Full `uv run pytest`: 435 passed, 1 skipped, 2 failed, both in ingestion's
  `test_live_capture.py` (drop-summary log timing); that file then passed 53 of 53 three
  times. No ingestion code changed here; noted under K-14

### Not verified

- A restart in the middle of a real load (the resume logic is tested with a stubbed
  extraction, not by killing `query` mid-load)
- VIRAT through the load path (not loaded, D-26)
- K-19's cause (which test leaves the worker running)

### Result

Dataset footage enters the product only through the upload function and never expires. The
full load was estimated (50 GB, 20-34 h) and then dropped by D-26: model measurements run
on Colab, and the product holds the 60-clip hand-check sample, loaded in 36 min with no
failure. K-4 moved to slice 7; K-18 fixed; K-19 opened.

---

## OMNI-609 · Window inspection view, and the hand check

### Why this ticket exists

Phase A: "check a sample by hand". A derived window is only trusted once someone has looked,
and the slices that train on the windows need to know how far to trust them.

### What was done

2026-10-10.

- **Criterion first: D-27**, the ticket's wording, written before the screen was used.
  During the check it changed twice, both recorded in D-27 with when and why: the tolerance
  went from 1 s to 1.5 s after 2 windows (both Verified, so neither verdict could change),
  because Ahmad found sub-second judgement by eye unreliable; and per-class rules for "where
  the act begins" were added as classes came up (arrest: first restraint, by guards or at
  gunpoint; burglary: breaking in; robbery: the threat; shooting: the first shot, pointing
  the gun being lead-up; stealing and shoplifting: the first act of taking), each written
  before that window was judged
- **The sample** was drawn in OMNI-608 (D-26), 60 clips; the check takes one window per clip
  (UCF-Crime's 30 s one: the 60 s one ends at the same event start)
- **API** (`services/query/app/windows.py`): `GET /windows` (the 60), `GET /windows/{id}`
  (window, event and the clip's video), `POST /windows/{id}/verdict` (analyst or admin;
  Wrong needs a reason; checking again replaces). Migration `7d1a3c5e9f20` adds
  `event_windows.verify_reason`
- **Screens** (`frontend/src/app/(app)/windows/`): the list with the tally per source and
  "Check next"; the check page with the player, a timeline shading the window and marking the
  event, "Play window" (to 4 s past the event start) and "Play the boundary", and the verdict
  panel (reason list from D-27 plus free text). Not in the sidebar: the Datasets screen
  (OMNI-612) links to it
- **`scripts/hand_check_report.py`** counts the verdicts with Wilson intervals and lists every
  Wrong
- **The check:** Ahmad, one pass over all 60. I helped apply the criterion when he asked
  (which moment counts as the start), without seeing the video myself
- Docker Desktop was not running at the start (the laptop had restarted); started it. The
  frontend dev server did not see the new route folder until restarted

### Verification performed

- `alembic upgrade / downgrade / upgrade`, `alembic check`: clean
- `test_windows.py` (5): only the checked window of each sampled clip listed; detail carries
  window, event and video; unsampled and 60 s windows 404; verdict stores who and when and can
  be replaced; Wrong without a reason 422, operator 403, no token 401
- On the live database: 60 windows (30 CCD, 15 official, 15 UCA), all with a video
- Screens seen in Chrome (port 3000, a throwaway admin, deleted after, no verdict recorded);
  `tsc` and `eslint` clean on the new files
- The report: 60 of 60 checked; numbers in `results.md`
- Full `uv run pytest`: first 440 passed, 2 failed, the same two ingestion log tests as in
  OMNI-608. Not timing, as I had said there: OMNI-608's test `conftest.py` ran alembic with its
  ini file, whose `fileConfig` disables loggers already created. Ran alembic without the ini
  file: **442 passed, 1 skipped**. K-14's note corrected

### Not verified

- A second checker: one person's judgement, one pass
- The 60 s windows and the negative windows (not checked by eye)
- The screen's video playback through nginx in my own browser session (the automation could
  not open the self-signed `https://localhost`); Ahmad used it there for all 60

### Result

UCF-Crime windows: 23 of 30 correct (official 13 of 15, UCA 10 of 15); CCD 30 of 30. UCA-timed
windows are wrong twice as often, mostly by containing the event: K-20, to be dealt with
before slice 9 trains on them.

---

## OMNI-610 · Aggregates that stay fast

### Why this ticket exists

FR-9's dashboard shows the state of the whole system, and `segments` holds a row per decoded
frame of every file (D-5). Counting it on every page load would get slower as the archive
grows, so the figures come from an hourly rollup kept exact in the same transaction as the
rows.

### What was done

2026-10-11.

- **Read first:** the consumer (`app/consumer.py`) is not the only writer of `segments`. A
  failed or replaced extraction deletes a video's rows, a re-gate updates `admitted` and the
  files in place, a deleted video cascades. A counter kept only in the consumer's code
  would drift the first time any of those ran. So the rollup is kept by **statement-level
  triggers on `segments`** (insert, update, delete, truncate), which run inside the
  statement's own transaction: the consumer's insert updates the rollup in the same commit,
  and so does every other change. Recorded as **D-28**
- **Migration `9b4e6d2a7c31`:** `segment_hourly (hour, source_type, segments, admitted,
  file_bytes)`, the four triggers (one aggregated upsert per hour and source per statement,
  from its transition table; the hour in UTC whatever the session's time zone), and
  `segments.file_bytes`. It also counts the rows already there
- **Bytes written:** the consumer cannot see the frame volumes, so ingestion measures the
  two JPEGs right after writing them (`process_frame`) and the size travels on the message
  (`SegmentMessage.file_bytes`, default 0 so an old queued message still parses) and in
  the re-gate response (`ExtractedSegment.file_bytes`, written by `run_gate`)
- **`GET /dashboard/summary`** and **`GET /dashboard/activity?hours=24`** in
  `services/query/app/dashboard.py`, every role (the dashboard is everyone's, `nav.py`).
  Segments and frame bytes from the rollup; cameras and videos from their own small tables;
  `cameras_online` counts `live` in the same function `GET /cameras/live` now calls
  (`live_cameras`, pulled out of the route); `alerts_today` and each hour's `alerts` are
  `null`; added to the ticket's shape: `retention_days` and `oldest_recording_at` (the
  oldest video retention will delete, so dataset footage is left out). Activity returns
  every hour, oldest first, ending with the current one; an hour with no rollup row is 0
- **`scripts/backfill_dashboard_rollup.py`:** fills `file_bytes` on old rows from the disk,
  rebuilds the rollup with `segments` locked against writes, and compares it with a direct
  count; rerunnable. Runs inside `query` (it needs the volumes)
- **`scripts/measure_dashboard.py`:** the exactness check on the real pipeline (upload,
  extract, re-gate, delete one CCD clip) and the timings
- **Found on the way:** the volumes hold 2.04 GB of frames and thumbnails, the rows account
  for 0.99 GB. Three directories have no row: two deleted test cameras (one is K-19's stray
  worker) and one deleted video. Not fixed here: **K-21**. Playback copies (22.7 MB) are not
  counted either, also K-21
- The first measurement run re-gated at `cell_threshold` 10, which admitted the same 40
  frames, so the update path was not exercised; rerun at 60 (40 → 10), and the rollup's
  admitted count added to the comparison

### Verification performed

- `test_dashboard.py` (11) on the test database: a stored segment is counted in the same
  commit and a redelivery adds nothing; a live frame counted under `camera`; a stale message
  changes nothing; a re-gate-style update moves admitted and bytes; deleting a video
  (cascade) and deleting a failed extraction's rows take them out; after each, the rollup
  per source equals a direct count over the whole table. Summary equals a direct count
  (segments, videos, storage), counts only `live` cameras, `alerts_today` null; oldest
  recording ignores datasets; activity has 24 hourly entries ending now with this hour's
  rows; `hours` 0 and 169 rejected; 401 without a token
- `test_extraction_pipeline.py`: an admitted frame's `file_bytes` equals its two files'
  sizes, a discarded one's is 0
- `alembic downgrade -1 / upgrade head / check` on the test database: clean
- Full `uv run pytest`: 453 passed, 1 skipped
- Real stack: migration applied, backfill equal to a direct count (146,807 rows, 31,715
  admitted, 989,872,990 bytes); `measure_dashboard.py`: equal before, after upload and
  extraction, after the re-gate and after the delete; all 40 admitted rows carried bytes.
  Timings in `results.md`

### Not verified

- Millions of rows: after D-26 the archive is 146,807 rows, where a direct count is still
  18.5 ms. The rollup reads one row per hour and source, so its cost does not grow with
  `segments`, but that was not measured at scale
- The trigger's cost on the consumer's throughput (one more upsert per stored frame) and on
  a re-gate (the ORM updates row by row, so the update trigger runs per changed row; K-6's
  1.4-2.0 s was not remeasured)
- `cameras_online` with real cameras: none were registered (0 of 0); the counting is tested
  with a stubbed state list, the state itself is `GET /cameras/live`'s own function
- Two consumers writing the same hour and source at once (only one consumer writes each
  source today)

### Result

The dashboard's counts come from a rollup kept by triggers in the same transaction as the
rows, and equal a direct count after an insert, a re-gate and a delete on the real
pipeline. Summary p50 41 ms / p95 72 ms, activity 15 / 36 ms, over 100 calls each on
146,807 rows. K-21 opened for 1.05 GB of files with no row.

---

## OMNI-611 · Operations Dashboard

### Why this ticket exists

FR-9: the landing page after sign-in should show the state of the whole system at a glance,
with every figure leading to the screen behind it. OMNI-610 gave it the numbers.

### What was done

2026-10-11.

- **`frontend/src/app/(app)/page.tsx`** replaces the placeholder tiles (sign-in already lands
  on `/`). Five figures, each a card that links:
  - Cameras online `x / y` and how many are not live: the camera wall (`/live`)
  - Footage held (videos): the archive (`/videos`)
  - Segments indexed: the archive
  - Storage in use (GB), days kept (`VIDEO_RETENTION_DAYS`) and the oldest recording due to
    expire: the archive
  - Datasets, clips loaded out of the sample, from `GET /datasets`: the datasets screen
    (`/datasets`, built in OMNI-612; until then the link answers 404)
- **Activity, last 24 hours:** one bar chart, segments stored per hour from
  `GET /dashboard/activity`, local time on the axis (24 h clock), a tooltip per bar on hover
  or keyboard focus (edge bars anchored inward so the tooltip stays in the card), "Nothing
  stored in the last 24 hours" when empty, a screen-reader table of the same numbers, and a
  link to the archive
- **Alerts needing attention:** a panel saying "Alerts arrive in slice 9", nothing counted
- **Refresh:** loaded once, then every 30 s while the tab is visible; hidden, it stops;
  visible again, it refreshes at once. A failed refresh keeps the last figures and says so
  next to the time they are from
- **One conflict with the ticket, told to Ahmad first:** every role sees the dashboard, but
  Live Monitoring is operators' and admins' (`nav.py`). For an analyst the cameras figure
  is shown without a link ("Live Monitoring is for operators") instead of a link to a screen
  that answers 403. Which screens a user may open comes from `GET /nav`, the same map as the
  sidebar
- Types for the three endpoints in `lib/api-client.ts`
- Found on the way: the hour labels wrapped onto two lines and the edge tooltip was cut off
  by the card; both fixed. The frontend container needed a restart after each change
  (K-10). A Next-generated file (`.next/dev/types/validator.ts`) was left with trailing
  bytes by one restart, so `tsc` reports it; `src/` has no errors

### Verification performed

- `tsc` (no errors in `src/`), `eslint` clean on the page (4 older warnings in
  `api-client.ts`, lines not touched)
- Chrome, port 3000, signed in as the admin (by Ahmad): every figure equal to the API
  (0 / 0 cameras, 60 videos, 146,807 segments, 2.04 GB for 2.035, 60 / 60 clips)
- A CCD clip uploaded and extracted through the API while the page was open: without a
  reload the page went to 61 videos, 146,857 segments and a 50-segment bar at 19:00 (16:00
  UTC), the API's numbers; deleted afterwards, the page back to 60 / 146,807
- Links read from the page: `/live`, `/videos` (four), `/datasets`; clicked: cameras → the
  wall, footage → the archive (the new clip at the top)
- Refresh: summary requests at 16:08:32, 16:09:02, 16:09:32 (30 s apart); none in the 70 s
  the tab was hidden (simulated: `visibilityState` overridden and `visibilitychange`
  dispatched, as for the wall in OMNI-506); one at 16:10:58, the moment it was visible again

### Not verified

- The analyst's view in the browser (no analyst signed in); the unlinked cameras figure
  follows from `GET /nav`, which leaves `/live` out for an analyst
- A real hidden tab (the automation's own waits bring the tab forward, so the pause was
  simulated)
- `/datasets` itself (OMNI-612)
- Through nginx at `https://localhost` (the automation cannot open the self-signed site)

### Result

The dashboard is the landing page: cameras, footage, segments, storage with retention,
datasets and 24 hours of activity, each matching the API and each a link; alerts held for
slice 9; refreshed every 30 s, paused while hidden.

---

## OMNI-612 · Datasets screen

### Why this ticket exists

FR-9: the dashboard's datasets figure needs a screen behind it, showing what each dataset
holds in the product and how far its lead-up windows are derived and checked, with a way for
an admin to load clips and watch it happen.

### What was done

2026-10-15.

- **One conflict with the ticket, told to Ahmad first:** the acceptance says "load 10 more
  CCD clips", but D-26 limits the product to the hand-check sample and all 30 sampled CCD
  clips were loaded, so there was nothing more to load. Ahmad chose: delete 10 sampled CCD
  clips and load them again from the screen. Nothing in the product changed for it; the
  verdicts sit on the windows, so they survive
- **`GET /datasets`** (`services/query/app/datasets.py`) gains `windows_derived` (every
  window of the dataset, positive and negative, not only the sample), `windows_checked`
  (a verdict given) and `windows_verified` (verdict correct), and the running load's
  `load_done` / `load_queued` (null when none runs)
- **`frontend/src/app/(app)/datasets/page.tsx`:** a card per dataset: domain, videos loaded
  out of the sample's total (and failed, if any), status, windows derived, hand-checked,
  verified correct. Admins get "Load up to N clips" (default 10); while any load runs the
  button is disabled and the screen polls every 2 s with a progress bar (done of queued).
  "Windows →" opens `/windows?dataset=<name>`
- **`/windows` takes `?dataset=`** and lists only that dataset's sampled windows, with links
  back to Datasets and to all datasets. Each row already opened OMNI-609's view.
  `useSearchParams` sits under a `Suspense` boundary, as Next 16 requires for a production
  build
- Not in the sidebar: the nine screens come from the product document (`NAV_ROUTES`), and
  Datasets is not one of them; the dashboard's figure links to it, as OMNI-611 planned
- Docker Desktop's stack was down at the start; `docker compose up -d`

### Verification performed

- `test_dataset_load.py`: 8 passed (2 new): the window counts (4 derived, 2 checked, 1
  verified, a window of an unsampled clip counted), and the progress (2 queued, 0 done while
  the first clip is held; null again after)
- `tsc` no errors; `eslint` clean on the new and changed files (4 older warnings in
  `api-client.ts`)
- Real stack: `GET /datasets` equal to the database (CCD 4,500 / 30 / 30, UCF-Crime 3,260 /
  30 / 23); 10 sampled CCD clips deleted through `delete_video` (CCD 20 / 30, dashboard 50
  videos, 146,307 segments); Ahmad clicked Load (10) on the screen: 30 / 30 in 28 s, the
  dashboard back to 60 / 146,807 with a 500-segment bar this hour; the 30 CCD verdicts kept.
  Links followed in Chrome. Numbers in `results.md`
- Full `uv run pytest`: 455 passed, 1 skipped. No stray ingestion worker after (K-19)

### Not verified

- The progress bar on screen mid-load: the load finished before I looked; the 2 s polls are
  in the query log
- An operator's or analyst's view (no Load control; `POST` answers 403, tested in OMNI-608)
- Through nginx at `https://localhost`

### Result

The Datasets screen shows each dataset's clips, status, windows derived, checked and verified,
lets an admin load clips with progress, and links to each dataset's windows and from there to
each window's check. Read under D-26, a 10-clip CCD load from the screen moved the screen's
count and the dashboard on the real stack.

---

## OMNI-613 · The motion grid in one array operation, and NFR-4 again

### Why this ticket exists

NFR-4 was revised from 10 feeds to 3 (D-19) with one software candidate from K-2 never tried:
computing the 8x8 grid's cell means in one array operation instead of 64. The same arithmetic,
Algorithm 1 unchanged, less Python per frame. The revision is easier to defend once it is tried.

### What was done

2026-10-16.

- **`_cell_means` in `services/ingestion/app/pipeline.py`:** lines 4-5 of Algorithm 1 now take
  the G x G cell means in one operation: a reshape and an integer sum (`uint32`) when the frame
  divides the grid evenly (every simulator clip does), an integral image (`cv2.integral`) with
  np.array_split's exact cell boundaries otherwise. Exact integer sums over pixel counts, so
  the means are bit-for-bit those of each cell's `.mean()`, not approximately equal
- **Why not `cv2.resize(INTER_AREA)`,** which the ticket offered: it rounds in floating point,
  so "identical" could not be promised. A first `np.add.reduceat` version was exact but slower
  than the loop in HD (2.4 ms against 1.1 ms in a microbenchmark), so it was dropped
- **Tests (`test_motion_gate.py`):** the old loop kept in the test as the reference; random
  frames at five sizes, three uneven, equal cell means; and the first 300 frames of each of the
  ten simulator clips through the gate both ways, the same score and admission on every frame
  (skipped when the clips are not on disk; they are never committed)
- **`frame_cost.py` before and after:** HEAD's `pipeline.py` copied into the ingestion
  container beside the new one, the two alternated, 3 runs each, 900 frames, on `real01`
  (1280x720) and `real04` (320x240). The script itself is unchanged
- **The NFR-4 ladder** with the wall open at 4x4 in Chrome (Ahmad signed in), an in-page
  recorder logging visibility, layout, each tile's badge and every preview request each second.
  3 minutes at 4, 5, 6 feeds; 10 minutes at 5, then at 4
- **D-19 and K-2** got a dated note: tried, the number stays 3

### Things that went wrong on the way

- **The recorder's first version read the layout and badges wrong** (a regex on the page
  text, and badge spans with a child dot). Fixed about 40 s into the first 4-feed window; that
  window's visibility was recorded throughout, the tiles were seen live on a screenshot
- **The first 4-feed 10-minute run was killed by Claude Code at about 300 s,** for low memory on
  the host, before its verdict and its cleanup. Four workers kept capturing. I stopped them
  through ingestion's `POST /workers/stop` and deleted the cameras, their 7,909 segments, stats,
  frame folders and the throwaway user by hand (the first delete hit a frame still in flight
  and rolled back; the retry went through). Rerun after Ahmad agreed
- `docker compose exec` from Git Bash rewrote `/workspace/...` again; PowerShell for those calls

### Verification performed

- `test_motion_gate.py`: 31 passed, including the ten recorded clips
- `frame_cost.py`: gate + files 9.1-9.3 → 7.0-7.5 ms a frame in HD, 3.4-3.6 → 2.0-2.3 ms in SD
  (one outlier "before" run at 17.8 ms)
- NFR-4, wall visible at every sample: 4 and 5 feeds sustained over 3 minutes, 6 not (4
  dropped); over 10 minutes 5 not (no drops, 2-4 s not live on three feeds) and 4 not (no
  drops, worst 0.82 s, `cam01` 2 s not live). Numbers in `results.md`
- After the last run: no `nfr4-` camera, segment or throwaway user. Ingestion still listed the
  killed run's four cameras as `failed` workers: query had resumed them after I stopped them
  (D-15), and they failed writing once their folders were gone. Not capturing; stopped, list empty
- Full `uv run pytest`: 470 passed, 1 skipped

### Not verified

- 3 feeds over 10 minutes with the change (D-19's 3 was measured with the costlier grid)
- More than one run per configuration; another machine
- Why a feed briefly reads not live with the machine at 229% of 800%
- Why SD decode read slower in every "after" run (the change does not touch decoding)

### Result

The grid is cheaper, the scores are identical, and the machine has more headroom at the same
load: 4 feeds over 10 minutes drop nothing at 90% of a core in ingestion (149% before), and 5
feeds hold for 3 minutes. The sustained number does not move: 4 feeds over 10 minutes fail on
one feed being not live for 2 seconds. NFR-4 stays at 3 per machine (D-19); every software
candidate in K-2 has now been tried.

---

## OMNI-614 · Diagram, docs, merge

### Why this ticket exists

The slice closes with its pipeline drawn, its docs current and the branch merged into
`master` by Ahmad.

### What was done

2026-10-16.

- **`docs/architecture/slice-06-dashboard-datasets.md`:** Drive and the mirror → the three
  loaders → manifest → split → windows → the committed CSVs (and Colab from them), the
  hand-check sample → `POST /datasets/{name}/load` → `store_video()`, the upload's own
  function → extraction; the Datasets, Windows and dashboard screens on their endpoints, the
  dashboard on the rollup. Mermaid checked: it renders
- **`docs/context/week-06.md`:** a section for every ticket, OMNI-600 to OMNI-614
- **`results.md` scoreboard:** checked, nothing missing. NFR-5 rechecked for live (OMNI-601),
  the SM-3 target, the split, the windows, the hand check, the dataset footage, the dashboard
  aggregates, dashboard and Datasets screen rows were all there; NFR-4's row updated in
  OMNI-613
- **`decisions.md`:** the index stopped at D-20; D-21 to D-28 added. D-2's status read
  "target pending (slice 6)" and is now done, with D-23's 1.80 s
- **`known-issues.md`:** current. Nothing due in slice 6 is left open: K-4 was moved to slice 7
  on 2026-10-09, K-11 fixed in OMNI-601; K-2 got OMNI-613's note

### Verification performed

- `uv run pytest`: 470 passed, 1 skipped, at the end of OMNI-613; only docs changed since
- The diagram validated as a Mermaid flowchart

### Not verified

- The definition of done on a fresh `docker compose up -d`: not run in this ticket
- `datasets/splits/` and `datasets/windows/` on Drive for Colab: not copied yet (OMNI-607's
  note); Ahmad's step
- The commit, the merge into `master`, `pytest` on `master` and the tracker: Ahmad's steps

### Result

Slice 6's pipeline is drawn and the docs are current. Commit, merge and tracker are with Ahmad.
