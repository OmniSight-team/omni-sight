# scripts

Small helpers we run occasionally — preparing test data, fetching model weights, one-off
maintenance.

Not part of the running system.

- `list_dataset_videos.py` — run in Colab against Drive: writes each dataset's `video_files.txt` (every
  video's relative path) and packs those plus VIRAT's full `annotations/`, empty directories kept, into
  `omni604_mirror.zip` for the local mirror (OMNI-604). Standard library only.
- `build_dataset_split.py` — fixes the train / validation / held-out split (D-22), writes
  `datasets/splits/*.csv` and `dataset_manifest.split`; refuses to write a split that differs from the
  committed files (OMNI-605). Prints counts per split per class and the SHA-256 of each file.
- `build_dataset_manifest.py` — fills `dataset_manifest` from the three loaders in
  `omnisight_common.datasets` and checks the counts against `docs/dataset-layout.md`; exits non-zero on
  a mismatch (OMNI-604). Upserts; never touches `split` or `video_id`.
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
