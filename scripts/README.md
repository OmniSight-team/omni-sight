# scripts

Small helpers we run occasionally — preparing test data, fetching model weights, one-off
maintenance.

Not part of the running system.

- `measure_capture_latency.py` — capture-to-stored latency of a live camera, alone and with a
  file being extracted at the same time, plus the TC-1 checks (OMNI-316). Needs the stack up;
  see its docstring. Its results are recorded in `docs/results.md`.

