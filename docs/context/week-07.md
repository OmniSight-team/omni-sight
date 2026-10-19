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

## OMNI-702 · A VIRAT sample in the product, to search

### Why this ticket exists

D-26 kept the product to the 60 hand-check clips, none of them VIRAT. Search needs real
surveillance footage with people and vehicles to be demonstrated at all, and VIRAT is
Phase A's search dataset.

### What was done

2026-10-18, on `slice-07-search`.

- **The draw** (`omnisight_common.datasets.demo`, `scripts/build_virat_demo_sample.py`):
  one video per scene from the 275 VIRAT videos with events, seed 702, inputs sorted, into
  `datasets/demo/virat_sample.csv` (the hand-check sample's columns, so the same code reads
  both). The VIRAT loader runs on the local listing and annotations; no database
- **The conflict, raised before loading:** the first draw (not committed) picked 1,456 MB
  and 1,111 MB videos for scenes 0000 and 0001. Every video in those two scenes is over the
  500 MB upload limit (642-1,608 MB, 9,075-29,580 frames), and would also run far past the
  900 s extraction timeout. "11 from 11 scenes" could not pass without raising the product's
  limits, which D-25 tried and reverted. **Ahmad chose 9 scenes:** only videos under the
  limit are eligible (sizes from OMNI-608's probe of Drive, `data/omni608_estimate.csv`), and
  the sample was redrawn. The rule changes the rng sequence, so the other scenes' picks
  differ from the first draw. 9 videos, 1,120.6 MB, 23,057 frames, the largest 490.6 MB
- **D-26 amended** in `decisions.md`: the VIRAT demo sample, the 9-scene rule and why the
  limits stay; index row updated
- **The load path:** `virat` added to `DOMAINS` (surveillance) in
  `services/query/app/datasets.py`; `sample_keys("virat")` reads the demo sample
  (`demo_sample_path`, new setting), every other dataset the hand-check sample.
  `docker-compose.yml` mounts `./datasets/demo:/demo:ro` into `query`.
  `scripts/copy_dataset_subsets.py` copies both samples' files.
  `scripts/run_dataset_load.py` takes dataset names as arguments (default unchanged)
- **Drive:** Google Drive for desktop was not running (no `GoogleDriveFS` process, no `G:`);
  started it from here once Ahmad had tried, `G:` appeared in 10 s. Copied the 9 files (96 s,
  sizes equal to Drive)
- **The load:** `scripts/run_dataset_load.py virat` through nginx: 9 of 9 `ready`, 0 failed,
  13 min 37 s. Numbers in `results.md` (OMNI-702)
- **Found, not fixed (K-23):** the gate kept 949 of 23,057 frames (4.1%), 701 of them
  heartbeats; 4 of the 9 videos kept no frame for motion and a fifth kept 3, though all have
  annotated events. Search on them sees about a frame a second. Outside the ticket; it
  matters for FR-4 and SM-1, so it goes to slice 8, before SM-1

### Verification performed

- `uv run python scripts/build_virat_demo_sample.py` writes the file; run again it finds the
  same bytes. `test_virat_demo_sample.py` (3 tests): the redraw equals the committed file;
  9 distinct scenes, each pick under the limit, the two left-out scenes have nothing under
  it; a video over the limit or of unknown size is never drawn
- `test_dataset_load.py`: a new test, `sample_keys("virat")` gives 9 keys from 9 scenes, the
  test dataset still reads the hand-check sample, `GET /datasets` lists `virat` as
  surveillance. 9 passed; `test_windows.py` and the common tests also pass
- After the load, in Postgres: all 9 `source = dataset`, `retention_until` NULL, `ready`,
  `gate_stride_s` set, manifest `video_id` set, no `error`; `GET /datasets` shows `virat`
  `loaded` 9 of 9, CCD and UCF-Crime still 30 of 30. No live worker in ingestion afterwards
- Storage measured per video in the volumes (original, playback copy, frame and thumbnail
  directories)

### Not verified

- The full suite was not rerun after these changes (the touched test files were); OMNI-714
  runs it
- Playing the VIRAT videos in the browser; the search ticket (OMNI-707) does that
- No whole-volume before/after storage snapshot (taken per video instead)
- The gate's recall against VIRAT's event annotations (K-23)

### Result

9 VIRAT videos `ready`, never expiring, from 9 scenes, in 13 min 37 s; 949 kept frames to
search. The ticket's 11 became 9 by Ahmad's decision (D-26 amended). K-23 opened.

---

## OMNI-703 · Qdrant in the stack, and `frame_vectors`

### Why this ticket exists

FR-3: store each analysed segment with its details for later retrieval. Phase A puts the
vectors in Qdrant (§3.3, Appendix B.2). Nothing can be encoded (OMNI-704) or searched
(OMNI-706) until the store and the collection exist.

### What was done

2026-10-19, on `slice-07-search`. Docker Desktop was not running; started it from here.

- **`qdrant` service** in `docker-compose.yml`: `qdrant/qdrant:v1.19.1`, the version of the
  `qdrant-client` uv resolved (1.19.1); named volume `qdrant_data`; **no port published**;
  `infra/qdrant/production.yaml` mounted over the image's (storage paths, HTTP 6333,
  telemetry off). The image has no curl or wget, so the healthcheck asks `/readyz` through
  bash's `/dev/tcp`. `query` waits for it to be healthy and gets `QDRANT_HOST: qdrant`.
  The `.gitkeep` in `infra/qdrant/` removed now that the folder has a file
- **`omnisight_common/frame_vectors.py`** (shared, because ai_workers writes and query
  searches): `FRAME_VECTOR_SIZE` 1152, `FramePayload` (the ticket's 11 fields),
  `frame_point` (point id = `segment_id`, refuses a vector that is not 1152-D),
  `captured_at` (D-29), `qdrant_client`, `ensure_frame_collection` (create if missing,
  Cosine, Qdrant's default HNSW; never recreate; payload indexes `camera_id` and `video_id`
  integer, `captured_at` datetime, asked for on every start so a half-finished first start
  is repaired). `qdrant-client` added to `omnisight-common`. Settings: `qdrant_host`,
  `qdrant_port`, `qdrant_timeout_s`, `frame_collection`
- **Created on startup:** query's lifespan calls `ensure_frame_collection`; a failure is
  logged, not fatal (everything but search works without Qdrant), like the extraction sweep
- **D-29** in `decisions.md`: the point-id deviation from B.2 line 4, `captured_at` for
  uploads (upload time plus offset), and the microsecond rounding below
- **TC-3's first run failed:** 66 of 1,000 payloads differed, all upload `timestamp_s`
  values needing 17 significant digits, one unit in the last place off. The raw HTTP
  response had the changed value, so Qdrant changes it, not the client. A diagnostic run
  showed every filtered search did find its point; the 66 "misses" were the same payload
  inequality. **Fix:** `FramePayload` rounds `timestamp_s` to the microsecond (as
  `captured_at` already is); TC-3's live timestamps then got full-precision fractions too.
  Recorded as a failed run in `results.md`, not hidden
- **`scripts/verify_tc3_frame_vectors.py`:** Qdrant is not reachable from the host, so the
  script pipes itself into `query` for the `write` and `check` stages and does the restart
  from the host between them. Scratch collection `frame_vectors_tc3`, dropped at the end;
  the real collection is only checked to exist

### Verification performed

- `services/common/tests/test_frame_vectors.py`, 9 tests on qdrant-client's in-process
  mode: the collection's shape; an existing collection with a point is not recreated; the
  same segment written twice is one point holding the second payload; a 768-D vector is
  refused; the payload is plain JSON with exactly the model's fields; the microsecond
  rounding; `captured_at` for a live and an uploaded frame; an upload without its time is
  refused
- TC-3 on the real stack, twice, each passing before and after `docker compose restart
  qdrant` (numbers in `results.md`, OMNI-703)
- `query`'s log: on the first start a create request for `frame_vectors`; after `docker
  compose restart query` only the existence check and the three index requests
- `docker compose ps`: `6333-6334/tcp`, nothing mapped; `curl http://localhost:6333` from the
  host: exit 7
- Full suite: **484 passed, 1 skipped** (4 min 50 s)

### Not verified

- Real SigLIP 2 vectors and real segments (OMNI-704, OMNI-705)
- A kill or `down`/`up` of Qdrant (only `restart`); NFR-5 for vectors comes with OMNI-705
- Qdrant also listens on gRPC 6334 inside the network (the image default); unused, not
  turned off

### Result

Qdrant runs in the stack with no host port; `frame_vectors` is created by query once and
never recreated. TC-3's frame half passes, including after a restart, after a first run
that failed on 17-digit floats and was fixed by D-29's microsecond rounding.

---
