# scripts

Small helpers we run occasionally — preparing test data, fetching model weights, one-off
maintenance.

Not part of the running system.

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
