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

