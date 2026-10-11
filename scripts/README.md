# scripts

Small helpers we run occasionally — preparing test data, fetching model weights, one-off
maintenance.

Not part of the running system.

- `list_dataset_videos.py` — run in Colab against Drive: writes each dataset's `video_files.txt` (every
  video's relative path) and packs those plus VIRAT's full `annotations/`, empty directories kept, into
  `omni604_mirror.zip` for the local mirror (OMNI-604). Standard library only.
- `probe_dataset_videos.py` — run in Colab against Drive: `ffprobe` on every UCF-Crime and CCD video,
  writes each dataset's `video_probe.csv` (fps, frames, duration) and packs both into `omni607_probe.zip`
  for the local mirror (OMNI-607). Standard library plus `ffprobe`.
- `build_event_windows.py` — derives the lead-up windows (D-24) from the manifest entries, the committed
  split and the probes; exports `datasets/windows/*.csv` (refuses to change existing files) and fills
  `event_windows` (OMNI-607). Prints counts per class, split and length, shortened and skipped counts,
  videos off their labels' frame rate, and each file's SHA-256.
- `plan_dataset_load.py` — lists the footage OMNI-608 first planned to load (CCD all, VIRAT the 275 with
  events, UCF-Crime the 290 held-out; dropped by D-26, kept as the record of the estimate) from the loaders and the committed split into `data/omni608_subsets.txt`.
- `estimate_dataset_load.py` — run in Colab against Drive with that list: size, fps, frames and duration
  of every clip to load, into `omni608_estimate.csv` (OMNI-608's estimate). Standard library plus `ffprobe`.
- `build_hand_check_sample.py` — draws the 60-clip hand-check sample once (seed 609, D-26) into
  `datasets/hand_check/sample.csv`; refuses to write a different one. These are the only dataset clips
  loaded into the product.
- `copy_dataset_subsets.py` — copies the sampled clips from Drive (mounted by Google Drive for desktop)
  into `data/`, native paths kept, size checked against Drive; rerunnable.
- `run_dataset_load.py` — loads the sample through `POST /datasets/{name}/load` as a throwaway admin,
  dataset by dataset, and prints the time and counts (OMNI-608).
- `hand_check_report.py` — the hand check's result from the verdicts given on `/windows` (D-27):
  correct out of checked per dataset and source, with a 95% Wilson interval, and every Wrong with its
  reason (OMNI-609).
- `ccd_pre_event.py` — CCD's footage before the first accident frame, all crash clips and per split,
  and the SM-3 target from rule D-23 (OMNI-606). Reads label files only.
- `build_dataset_split.py` — fixes the train / validation / held-out split (D-22), writes
  `datasets/splits/*.csv` and `dataset_manifest.split`; refuses to write a split that differs from the
  committed files (OMNI-605). Prints counts per split per class and the SHA-256 of each file.
- `build_dataset_manifest.py` — fills `dataset_manifest` from the three loaders in
  `omnisight_common.datasets` and checks the counts against `docs/dataset-layout.md`; exits non-zero on
  a mismatch (OMNI-604). Upserts; never touches `split` or `video_id`.
- `backfill_dashboard_rollup.py` — fills `segments.file_bytes` on rows written before OMNI-610 from the
  files on disk, rebuilds `segment_hourly` and checks it against a direct count (D-28). Runs inside `query`;
  see its docstring. Rerunnable.
- `measure_dashboard.py` — the dashboard endpoints on the running stack: their counts against a direct
  count before and after an upload, extraction, re-gate and delete of one CCD clip, then p50 / p95 over
  100 calls each (OMNI-610).
- `measure_capture_latency.py` — capture-to-stored latency of a live camera, alone and with a
  file being extracted at the same time, plus the TC-1 checks (OMNI-316). Needs the stack up;
  see its docstring. Its results are recorded in `docs/results.md`.
- `measure_concurrent_feeds.py` — how many simultaneous simulator feeds the machine sustains: a ladder
  of camera counts, each watched for a window, reporting drops, latency, queue depth and CPU; also
  `--consumer-capacity` for the consumer's own ceiling (OMNI-317). Run long windows in the background:
  a foreground shell command that outlives its time limit is killed before the script can clean up.
- `measure_gate_retention.py` — what fraction of frames the motion gate keeps on real dataset footage:
  uploads and extracts every clip under `data/` through the real pipeline at the default parameters,
  reports retention per dataset group and per clip, and with `--sensitivity 50:3,100:3` also re-gates
  at other parameters to show what would change (OMNI-318). Measures; does not tune.
- `verify_definition_of_done.py` — the slice 3 and 4 definition of done against the live stack: still-then-moving
  recording, threshold counts, a camera against the simulator, the simulator killed and restored, and the worker
  restarted mid-capture (ingestion graceful and `kill -9`, the consumer stopped and killed) with a loss check
  (OMNI-319). Run in the background; it stops and starts services on purpose and puts them back.
