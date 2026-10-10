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
