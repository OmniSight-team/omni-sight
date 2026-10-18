# Context notes — Sprint 7

Slice 7, search, 18 – 24 Oct 2026. Tickets in `docs/tickets/week-07.md`.
Entries are added as each ticket closes.

---

## OMNI-700 · Branch and baseline

### Why this ticket exists

Slice 7 adds Qdrant, the SigLIP 2 encoder, the embed queue and search. A known-good starting
point is needed first, so that anything that breaks later is known to come from this sprint
and not from slice 6.

### What was done

2026-10-18, on `master` at `62225f8`.

- **`master` has slice 6:** `git log` shows `62225f8 docs: record the split, windows and
  hand-check sample copied to Drive for Colab` on top of `7ad6d4b` and `8dd4518`, after
  `dbcb4ca Merge branch 'slice-06-dashboard-datasets'`. The only untracked file is
  `docs/tickets/week-07.md` (this sprint's ticket file)
- **Stack:** Docker Desktop was not running; started it, then `docker compose up -d`. All
  nine services up (`postgres`, `rabbitmq` healthy; `consumer`, `consumer-live`,
  `ingestion`, `query`, `frontend`, `mediamtx`, `nginx` running). `https://localhost`
  answers 200
- **Branch:** `slice-07-search` is created by Ahmad (`git switch -c slice-07-search`). It
  starts at `62225f8`, the same commit the suite ran on

### Verification performed

- `uv run pytest`: **470 passed, 1 skipped**, 1 warning (Starlette's `httpx` deprecation),
  228 s. At the slice 6 merge the count was 469 passed, 1 skipped, 1 failed (K-14); this run
  the K-14 test passed, so the total is the same 471 tests with no failure

### Not verified

- K-14 is intermittent; one green run says nothing about it. OMNI-701 deals with it
- Nothing in the browser beyond the 200 from nginx; slice 6's definition of done was already
  checked on a fresh stack (`7ad6d4b`)

### Result

Baseline green: slice 6 on `master`, stack running, 470 passed / 1 skipped.

---

## OMNI-701 · K-14: the flaky live capture test

### Why this ticket exists

`test_no_frame_is_lost_or_counted_twice_across_a_reconnection` failed again on `master` after
the slice 6 merge (`assert 75 == 76`), its second failure in about two weeks of full runs. A
suite that fails now and then stops being believed.

### What was done

2026-10-18, on `slice-07-search`.

- **The race, from the code:** `_open_stream` grabs one frame to prove a (re)opened stream
  delivers, and sets `_pending_grab`. `_read_until_lost` takes that frame on its first pass,
  but its loop was `while not self._stop.is_set()`. A stop between the grab and the loop's
  first check skipped the frame: delivered by the stream, never counted, decoded or gated.
  In the test, the script's last step repeats, so after 50 frames the worker reconnects
  again and grabs a proving frame while the test is stopping it: `grabbed` one below
  `delivered`
- **A test that reproduces it deterministically:**
  `test_a_stop_right_after_a_reconnection_opens_still_counts_the_frame_read_to_prove_it`.
  The second stream sets the worker's stop event inside its first `grab()` (what `stop()`
  does first, at that exact instant). Expects `grabbed == 11` and
  `gated == captured == grabbed`
- **K-14's fix candidate is wrong, shown by running it:** counting the frame in `grabbed`
  inside `_open_stream` (tried, then reverted) makes `grabbed` 11 but `captured` stays 10
  (`assert 10 == 11` on `captured`): the failure moves, the frame is still never decoded or
  gated. The ticket allowed "show why that is wrong"; this is the evidence
- **The fix** (`services/ingestion/app/live_capture.py`, `_read_until_lost`): the loop runs
  `while self._pending_grab or not self._stop.is_set()`, so a pending proving frame is
  always taken like any other frame. After it the loop ends on the stop as before; the
  processing thread already drains the queue on a stop, so the frame is gated
- **A second flaky test, found in the 5 runs (K-22):** run 4 of the first 5 failed the five
  `test_tc10_auth.py::test_tampered_token_returns_401` cases with 200. The test changed the
  token's last character `A`↔`B`; that character carries 2 unused base64 bits, so a token
  ending in `A` stayed valid. Checked with PyJWT: 128 of 2,000 tokens end in `A`, all still
  valid after the swap (about 1 in 16). Outside the ticket, but it blocked the 5 green runs;
  Ahmad agreed to fix it here. The test now changes a character in the middle of the
  signature. A test bug, not an auth hole. Recorded as K-22, found and fixed

### Verification performed

- New test before the fix: **failed 3 of 3**, `assert 10 == 11` on `grabbed` (K-14's shape,
  one below). After: passed 3 of 3, together with the original reconnection test
- `test_live_capture.py` alone: 54 passed. `test_tc10_auth.py` alone after K-22's fix: 23
  passed
- **First 5 full runs (K-14 fixed, K-22 not yet):** 471 passed / 1 skipped in runs 1, 2, 3
  and 5; run 4 failed the 5 tampered-token cases (K-22). K-14's test passed in all 5
- **5 full runs after both fixes, in a row:** 471 passed, 1 skipped each (207, 218, 193, 193,
  193 s). 471 = the baseline's 470 plus the new test

### Not verified

- 5 green runs do not prove a 1-in-many failure is gone; K-14 had failed twice in about two
  weeks. The evidence that it is fixed is the deterministic test, not the runs
- Nothing on the real stack: the change is in the read loop's exit condition only, and
  costs one more frame read at most per stop

### Result

K-14 fixed: the proving frame is no longer lost on a stop, and a test pins it. K-14's own fix
candidate was shown not to fix it. K-22 found and fixed. 5 green full runs in a row.

---
