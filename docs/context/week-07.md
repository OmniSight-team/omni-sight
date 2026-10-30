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

## OMNI-704 · `ai_workers`: SigLIP 2 frame and text encoder

### Why this ticket exists

FR-2: produce a searchable representation of each accepted segment's visual content.
Algorithm 2 line 1: `e_f ← SigLIP2_image(f_t); e_f ← e_f / ||e_f||`, 1152-D. Search (OMNI-706)
also needs the same model's text tower to turn a query into a vector.

### What was done

2026-10-19, on `slice-07-search`.

- **The checkpoint:** `google/siglip2-so400m-patch14-384` at revision `e8e48729…` (from the
  Hugging Face API), downloaded to `models/pretrained/siglip2-so400m-patch14-384/` (4.54 GB,
  9.6 min, git-ignored). It is a plain `siglip` checkpoint (fixed 384x384) with a Gemma
  tokenizer. Pinned in `services/ai_workers/app/settings.py`; **D-30**
- **Dependencies, `ai_workers` only:** torch 2.14.1+cpu (from PyTorch's CPU index, declared
  in the root `pyproject.toml`), transformers 5.20.1, pillow, fastapi, uvicorn, sentencepiece,
  protobuf. Image `phase-b-ai-workers` 1.59 GB
- **`app/encoder.py`:** `ensure_checkpoint` (download at the pinned revision if the folder's
  `REVISION` file says otherwise), `text_inputs` (lowercase, pad to 64, truncate),
  `FrameTextEncoder.encode_images` / `encode_texts` (float32, `pooler_output`, L2-normalised,
  1152-D and unit length asserted). No `app.` imports, so Colab and tests load it by path
- **transformers 5 differs from what the ticket assumed:** `get_*_features` return an
  output object, not a tensor (the embedding is `.pooler_output`), and `SiglipProcessor`
  has no padding defaults at all. Checked in the installed source, then pinned by tests
- **`app/main.py`:** `GET /health`, `POST /encode/text {q}` → `{vector (1152), model,
  model_revision}`; empty or over-1,000-character `q` → 422. The model is loaded in the
  lifespan and **warmed up** (one blank image, one text): the weights are memory-mapped,
  and before the warm-up the first query took 31.5 s
- **`ai-workers` in `docker-compose.yml`:** no port, no nginx route; `frame_storage`
  read-only and `./models/pretrained` mounted; healthcheck on `/health` with a 600 s start
  period; no `--reload` (it would reload 4.5 GB on any file change)
- **Tests opt-in for the model** (Ahmad agreed): a `[tool.pytest.ini_options]` section in
  the root `pyproject.toml` registers a `model` marker and adds `-m 'not model'`. The 4 tests
  that load the model run with `uv run pytest services/ai_workers/tests -m model`
- **The speed question:** the first measurement (32 + 64 frames) was killed by Claude Code
  when Windows ran low on memory (2.6 GB free; Docker's VM held 4 GB). Ahmad asked why speed
  is measured on a laptop when the target has a GPU; Phase A §3.3.2 puts the AI Workers on a
  GPU. **D-31 (Ahmad's decision):** the laptop checks correctness; speed is measured on
  Colab's GPU (with OMNI-710); NFR-1 and NFR-2 are judged as local stack times plus GPU
  encode time. A short laptop run (8 + 16 frames) was kept as information
- **`scripts/measure_encoder.py`**, **`scripts/verify_tc2_frames.py`**: both stop the
  service and use a one-off container, so only one copy of the model is in memory. TC-2's
  first run left its uploaded video behind (the token expired during the 25-minute encode);
  deleted through the API, and the script now logs in again before cleaning up. Its stderr is
  now read as UTF-8 (Windows' cp1255 could not decode it; the run itself was unaffected)

### Verification performed

- `services/ai_workers/tests/test_encoder.py`: 6 always-on tests (padding to 64, the
  processor alone not padding, lowercasing, truncation, the `REVISION` check both ways) and 4
  model tests (unit 1152-D frames, batch equals one-at-a-time, unit 1152-D text, red and green
  images matched to their texts). All 10 passed on the host with the checkpoint
- Endpoint from inside `query`: 1152 floats, norm 1.0, revision `e8e48729`; `"A PERSON
  WALKING"` gives the same vector as `"a person walking"`; empty `q` → 422. From the host:
  no port (`ps` shows none); `https://localhost/encode/text` and `/api/encode/text` → 404
- TC-2: 8 of 8 (`results.md`, OMNI-704). Laptop CPU cost recorded as information
- Full suite: **490 passed, 1 skipped, 4 deselected** (6 min 58 s)

### Not verified

- The encoder's speed on a GPU (OMNI-710, D-31)
- The 4 model tests through `-m model` (they were run before the marker existed)
- Two copies of the model at once (the service plus a script) do not fit beside the stack on
  this laptop; the scripts avoid it by stopping the service
- The transformers warning that the config's bos/eos token ids are outside the vocabulary:
  the checkpoint's own config, harmless for embeddings (not generation), not investigated

### Result

`ai-workers` serves SigLIP 2 at a pinned revision, only service with PyTorch; TC-2's frame half
passes for an upload and a live camera. On this CPU a frame takes about 9 s, so its speed is
measured on Colab's GPU instead (D-31).

---

---

## OMNI-705 · Every admitted frame reaches the encoder, durably

### Why this ticket exists

NFR-5 applies to vectors too: an admitted frame that never gets a vector is a frame search
can never find. OMNI-704 gave ai_workers an encoder but nothing fed it.

### What was done

2026-10-28, on `slice-07-search`.

- **The embed queue** (`omnisight_common/embed_queue.py`): `EmbedJob` (segment id, frame
  path, and every payload field but the model) and `omnisight.embed`, durable with a
  dead-letter queue, declared the same way as the segment queue
- **The consumer** (`app/consumer.py`, both roles): after a segment's row commits and
  **before** the message is acked, an admitted frame's job is published (confirmed,
  persistent). Also on a DUPLICATE: a consumer that died between the commit and the
  publish gets the message back, finds the row, and publishes then. Jobs are built from
  Postgres by `app/embed_jobs.py` (shared with the backfill)
- **ai_workers** (`app/embed_worker.py`, a thread beside the HTTP API, so one copy of the
  model serves both): batches of up to 8 (a batch closes when full or after 0.5 s with
  nothing new), encode, upsert with `wait=True`, **then** ack. The encode runs on a helper
  thread while the connection keeps being serviced, so a 70-130 s batch does not miss the
  broker's heartbeat. An unparseable job or an unreadable frame is dead-lettered (the batch
  falls back to one frame at a time so the rest are stored); anything else drops the
  connection and the jobs come back
- **`GET /embeddings/status`** (`app/embeddings.py`, any logged-in role): per video and per
  live camera, admitted frames against frames whose segment id has a point of the pinned
  model. Ids are scrolled from Qdrant (ids only) rather than counted per video, so points
  left by a deleted or re-gated video are not counted (K-24). 503 if Qdrant is down
- **`scripts/backfill_embeddings.py`** `queue` / `check`, run inside `query`; groups queued
  in order VIRAT, CCD, other, live, UCF-Crime; `--only`, `--video`
- The model pin moved to `CommonSettings`; a frame's domain is taken from its camera, its
  video's camera, its dataset, else surveillance (**D-34**). Compose: ai-workers gets
  `RABBITMQ_HOST`, `QDRANT_HOST` and waits for both

**The detour:** before starting the backfill the counts showed **34,769** admitted frames,
not about 1,000: UCF-Crime's hand-check clips alone hold 30,701 (about 77 h at 9 s a frame).
I first proposed running VIRAT and CCD overnight and moving UCF-Crime to Colab. Ahmad
pointed out the ticket's goal is the durable path, not encoding the archive, and SM-1 is
measured on VIRAT only. So the proof ran on **one video** (**D-35**); K-25 records the
numbers.

### Verification performed

- `services/query/tests/test_embeddings.py`, 13 tests (real Postgres and RabbitMQ, scratch
  queues, Qdrant in-process): the job's payload and absolute time; no job for a frame not
  admitted or stale; the four domain cases; the backfill picks only frames without a point;
  three admitted of six messages give three jobs; a consumer killed after the commit still
  gets the job out on redelivery; status counts (another model's point and an orphan point
  not counted), 401 without a login, 503 with Qdrant down
- `services/ai_workers/tests/test_embed_worker.py`, 6 tests (real RabbitMQ, a stand-in
  encoder): one point per job with its payload; batches up to the batch size; a job
  delivered twice is one point; an unreadable frame and a malformed job dead-lettered, the
  rest stored; an upsert failure acks nothing and the next run stores all; a 6 s batch with
  a 2 s heartbeat keeps its connection. The first test failed once in the first run, while
  the stack was still starting, on its 20 s limit; passed 9 times after, limit raised to 60 s
- Full suite: **509 passed, 1 skipped, 4 deselected** (8 min 25 s)
- On the real stack, VIRAT video 3226 (44 frames): `docker compose kill ai-workers` 14 s
  into the third batch with 16 stored; after restart 44 of 44, 44 points, none missing,
  none extra, no dead letters; `GET /embeddings/status` 44 / 44 (`results.md`, OMNI-705)

### Not verified

- A new upload or a running camera producing jobs on the real stack (the consumer path is
  covered by tests on the real broker and database, not by the running consumer containers)
- A kill of the consumer between commit and publish on the real stack (test only)
- The other 34,725 admitted frames: not queued (D-35). Search (OMNI-707) needs the other 8
  VIRAT videos: `backfill_embeddings.py queue --only virat`, about 2.5 h
- K-24 is open: search must drop hits whose segment no longer exists
- Note: the tickets moved to `docs/tickets/week-07-08.md`; these notes stay in this file

### Result

Every admitted frame now gets an embed job after its row commits, and ai_workers acks only
after its point is stored. A kill mid-batch lost nothing and duplicated nothing on a real
VIRAT video. Encoding the stored archive is left until something needs it (D-35).

## OMNI-706 · InternVideo2 pinned, and both encoders timed on the GPU

### Why this ticket exists

FR-2's temporal half: Algorithm 2 lines 2-3 encode an 8-frame clip with InternVideo2, so
search can tell actions apart (opening against closing a trunk), which a single frame
cannot. The forecasting model later trains on these clip vectors, so the checkpoint is
chosen and pinned once, here. It also carries D-31's GPU timings for both encoders.

### What was done

- **Getting the code to Colab:** the repo had no remote. Ahmad pushed it to the existing
  public repo `OmniSight-team/omni-sight` as two new branches, `phase-b` (from `master`)
  and `slice-07-search`, leaving Phase A's `main` alone. Before the push, all 81 commits
  were checked for secrets: only `changeme` placeholders in `.env.example`. Colab clones
  the branch with no token (public)
- **The checkpoint, by the ticket's three checks** (D-33): OpenGVLab's InternVideo2 repos
  on Hugging Face were listed and their files and configs read. `Stage2_1B` takes 4 frames;
  `CLIP-1B-224p-f8` is gated and holds only a 14 MB head file; the 6B ones are too large;
  the distillation repo has no text side. `InternVideo2_CLIP_S` passes: 8 frames at 224,
  512-D (run), a 63M-parameter text side. Phase A says 768; the 768-D features exist
  inside the model, but the searchable video-text space is 512-D, so `clip_vectors` will
  be 512-D (recorded as a deviation in D-33)
- **Detour: the model code.** The checkpoint ships its model as `.py` files next to the
  weights. The first version imported them from the download folder (with a stub for
  `flash_attn`, which they import but the config turns off); Claude Code's permission check
  refused to run downloaded code. Ahmad chose to copy the code into the repo instead:
  `services/ai_workers/app/internvideo2/` (`vision.py`, `text.py`), inference only, read
  line by line, names unchanged, sources and licences in the header. Only `config.json`
  and `model.safetensors` are downloaded now. With the copy, `timm` and `einops` were no
  longer needed; `open-clip-torch` (the tokenizer) and `torchvision` (CPU wheels, the
  resize) stayed
- **`clip_encoder.py`** beside `encoder.py`, the same style: `ClipTextEncoder(model_dir,
  device, video=True|False)`, `encode_clips` (8 RGB frames per clip, the checkpoint's own
  resize and normalisation), `encode_texts`, float32, 512-D unit vectors checked on every
  call; `uniform_indices` (Algorithm 2's `uniform_subsample`, the checkpoint's "middle"
  sampling) and `read_clip` (OpenCV, imported only where clips are read from files)
- **The pin** in `CommonSettings` (`clip_model_id`, `clip_model_revision`), next to
  SigLIP 2's; `ensure_checkpoint` takes the checkpoint's own download patterns
- **ai_workers on the laptop** (D-32) loads `ClipTextEncoder(video=False)` after SigLIP 2,
  warms it up, reports both models on `/health`, and answers `POST /encode/clip-text`
- **VIRAT events:** `virat.read_events` and `EVENT_TYPES` in `omnisight_common`, the 12
  type names checked against the Release 2.0 description (PDF, section 3.2), so the
  notebook names its clips from the repo, not from memory
- **`notebooks/encoders_gpu.ipynb`:** clones the branch, installs the locked versions,
  mounts Drive, loads both encoders on the GPU from `MyDrive/omnisight/models/pretrained/`,
  then the one-clip check, the motion check and the timings; writes everything to
  `MyDrive/omnisight/results/omni706_encoders_gpu.json`
- **`scripts/measure_text_encoders.py`:** ms per query for both text encoders and the
  container's memory
- Fixed a wrong reference in OMNI-705's `embed_jobs.py` (the domain rule is D-34, not
  D-33); added the missing D-34 and D-35 rows to the index table of `decisions.md`

### Verification performed

- One VIRAT trunk-opening clip (040103_00, event 29) and four texts, on this CPU: every
  checkpoint weight loaded with all keys matched; 512-D, finite, norm 1.0 (`results.md`)
- `test_clip_encoder.py`: 12 tests (sampling, text side, the video side marked `model`:
  unit 512-D, batch equals one at a time, frame order changes the vector, 8 frames
  required); with `test_encoder.py`, 22 passed including the model tests
- The rebuilt ai_workers: healthy with both encoders; 200 queries each: InternVideo2 text
  131 ms median, SigLIP 2 1,097 ms; 3.84 GiB RSS, 4.17 GiB peak (`results.md`)
- Colab, three runs: the first stopped on `No module named 'omnisight_common'` (an
  editable install is only seen after a runtime restart; the setup cell now adds the path
  itself); the second ran out of GPU memory (below); the third completed on an L4
  (`results.md`)
- The second Colab run: the batch-32 clip timing ran out of GPU memory on a 22 GiB GPU (not the
  A100 the ticket names). The video encoder's attention built the full attention matrix,
  8 GiB at batch 32; it now uses PyTorch's fused `scaled_dot_product_attention`, the same
  result to 5e-8 (checked against the original computation on a 2049-token input); the
  clip tests pass again
- The notebook's clip selection, run locally against the full VIRAT annotations: 42 to 156
  candidates per type, 10 clips chosen

### Not verified

- The timings on an A100 (none free; an L4 was used, Ahmad's choice, recorded in D-31)
- Where each call's time goes (CPU image work against GPU compute)
- Why the motion check is weak (small people in squeezed 1080p frames is a guess, not tested)
- The copied code against the original: not run side by side (the original could not be
  run here); the evidence is the strict weight load and sensible vectors

### Result

Done. `OpenGVLab/InternVideo2_CLIP_S` is pinned (D-33): 8 frames at 224, **512-D** (Phase A
says 768; recorded), unit vectors, the same numbers on the laptop's CPU and Colab's GPU. Its
text side runs in ai_workers beside SigLIP 2 at 131 ms a query, 3.84 GiB in all (D-32). On
an L4: SigLIP 2 about 110 ms a frame and 13 ms a query, InternVideo2 about 300 ms a clip
and 7 ms a query; batching no cheaper per item. **The motion check is weak:** 2 of 10 own
caption first, 4 of 10 own type, trunk opening and closing not told apart. Recorded, not
hidden, and left to SM-1 to judge with both streams fused.

## OMNI-707 · `GET /search`

### Why this ticket exists

FR-4: natural-language search over stored video, a ranked list of the most relevant moments.
The frame index exists (OMNI-703 to 705); this puts an API on it, with the `mode` parameter
in place for the clip index and fusion that come next (OMNI-710, 711).

### What was done

- **`services/query/app/search.py`:** `GET /search?q=&mode=&k=&camera_id=&from=&to=`. The
  text goes to ai_workers (`POST /encode/text`), Qdrant searches `frame_vectors` (cosine,
  top `k`, 1-50, default 5) with a filter applied inside the search: the pinned model and
  revision always, plus `camera_id` and a `captured_at` range when given (both indexed since
  OMNI-703). The hits are joined to `segments` and `cameras` in one query
- **`services/query/app/ai_workers_client.py`:** the call to ai_workers, a per-encoder cache
  of query vectors by exact text (the last 1,000, thread-safe), and a check that the vector
  comes from the pinned model (otherwise a clear 503: it would be compared with another
  model's vectors). The clip-text path is there for OMNI-710
- **Answers:** `mode=clip|fused` → 503 *the clip index is not ready yet*, before anything is
  encoded; an empty or blank query → 422 *the query is empty*; ai_workers unreachable → 503;
  Qdrant unreachable → 503; nothing indexed → 200, no results, `message` *nothing is indexed
  yet*; `from` after `to` → 422. A date with no zone is read as UTC. `mode` defaults to
  `frame` (the ticket gives no default; fused is the obvious one once it exists, OMNI-711)
- **K-24:** a hit whose segment is gone or no longer admitted is left out, counted in
  `dropped`, and logged with its ids
- **Timings:** `elapsed_ms` and `timings` (`encode_ms`, `search_ms`, `join_ms`,
  `encode_cached`), measured inside query
- **Roles (D-36):** operators, analysts and admins. The ticket says operator and admin;
  Phase A says operators and analysts search. Phase A wins
- **Settings and compose:** `ai_workers_base_url` (`http://ai-workers:8000` in compose; not in
  `depends_on`, the model takes minutes to load), `ai_workers_timeout_s` 30 s,
  `search_text_cache_size` 1,000
- **`scripts/try_search.py`:** queries through the real API inside `query`

### Verification performed

- `test_search.py`, 27 tests on real Postgres with in-process Qdrant and ai_workers replaced at
  its HTTP call: ranking and every field; `k` (default 5, 0 and 51 refused); other models'
  vectors ignored; **the acceptance**: camera A's best frame (cosine 0.4) is not in the
  unfiltered top 5 (five 0.75-0.95 frames of camera B) but is the one hit with
  `camera_id=A`; a date filter inside the search (k=1 still finds the older, weaker frame);
  zone-less dates; a deleted and a re-gated segment dropped and counted, the log line; a
  repeated query not encoded again, a stripped duplicate too; results not cached; `clip`,
  `fused`, unknown mode, empty query, empty index, a filter matching nothing (not an empty
  index), ai_workers down, a wrong model, Qdrant down; no token 401; all three roles 200
- The running stack (`results.md`): ranked hits from video 3226 with every field, the date
  filter on the real Qdrant index, `fused` and empty query answers; a repeated query 82-133 ms
- Full suite: 545 passed, 1 skipped, 8 deselected (the `model` tests), 7 min 47 s

### Not verified

- The camera filter on the real stack: no camera has vectors (D-35)
- Relevance: 44 frames of one video (SM-1 is OMNI-713)
- A large collection (TC-4, OMNI-715)

### Detour

The first query on the running stack got a 503: ai_workers had been idle about 2 h, and its
first text encode ran past query's 30 s timeout; the next took 9 s, then about 2 s.
Recorded as K-26 (memory-mapped weights read back from disk), to measure in OMNI-714.

### Result

`GET /search` works in frame mode, end to end, with filters inside the vector search and a
clear answer for every failure; clip and fused answer *not ready* until OMNI-710 and 711.

## OMNI-708 · The VIRAT archive on Colab, both streams, cached and resumable

### Why this ticket exists

SM-1 and TC-4 need an archive with ground truth, too big for the laptop (D-26): every admitted
frame of VIRAT's evaluation videos with a SigLIP 2 frame vector and an InternVideo2 clip
vector, cached on Drive. The clip vectors are also what the forecasting model trains on later.

### What was done

- **Replanned before building (29 Oct, Ahmad's decisions):** at OMNI-706's L4 speed (about
  0.4 s a frame for both streams) 100,000 vectors is about 11 GPU hours, most of it
  distractors. TC-4 now runs on the 275 VIRAT evaluation videos only (**D-37**, deviation);
  the ticket's distractor box is dropped. The product's 9 VIRAT videos get no separate
  encoding: their vectors are matched from the archive by `clip_key` and `frame_index`; the
  60 hand-check clips are left out (not searched this sprint, D-35)
- **Step 1, the notebook's setup:** `notebooks/virat_archive_gpu.ipynb`, the setup cell of
  OMNI-706's notebook (clone, pinned installs, Drive, GPU), then the gate and both encoders
  from the clone. Ingestion and ai_workers both name their package `app`, so ingestion's
  `pipeline.py` and `settings.py` are loaded by file path under their own names; the gate is
  built as ingestion's `_gate_for` builds it for a file, from the settings' defaults (the
  values in `.env.example`). `settings.py` needs the broker login to load, so placeholders
  are set (Colab has no broker). A last cell checks the 275 evaluation videos are on Drive
- **Steps 2-5, the runner:** `scripts/encode_virat_archive.py`, imported by the notebook (the
  loading code of step 1 moved into it). Per video it decodes and gates every frame with
  ingestion's own `process_frame`, as `extract_file` does; for each admitted frame the
  SigLIP 2 vector from the JPEG `process_frame` wrote (the stored-frame rule, OMNI-704) and
  the InternVideo2 vector of its window `[t - 2Δ, t]`, 8 frames taken from the frames just
  decoded (no second read of the file). Encoding runs on one background thread while the
  next frames are decoded, so the GPU and the CPU work at once. One `.npz` per video in
  `embeddings/virat/`, written before the manifest entry, so a lost session redoes the
  unfinished video and never counts a missing file as done. The manifest holds the pins and
  gate settings; a rerun with others is refused. A video that fails is recorded under
  `failed` and tried again on the next run. The product's 9 run first
- **`window_span`** in `clip_encoder.py`: the frames inside a stored window, with the gate's
  microsecond margin for `index / fps` rounding. It is shared code because the GPU path of
  ai_workers will need the same answer
- **Step 6, `scripts/export_segments_for_colab.py`:** inside `query`, the admitted segments of
  the product's VIRAT videos with each video's gate settings, and the laptop's own frame
  vector where Qdrant has one; written to Drive as `embeddings/product/segments.json`.
  `match_product` in the runner matches them by `clip_key` and `frame_index` (the timestamp
  and reason must agree) and writes `embeddings/product/{video_id}.npz` keyed by segment id.
  It also reports the cosine for each laptop vector (step 7)
- **Found, corrected:** OMNI-702's total in `results.md` said 949 kept (701 heartbeats); its
  own per-video rows add to 1,039 (791), and Postgres holds 1,039. Corrected with dated notes
  in `results.md` and K-23; D-37's rate is now 1.3 kept frames a second

### Verification performed

- The notebook's loading code, run locally (`uv run`, ai_workers' environment): the gate's
  settings are 0.5 s, 8 x 8, 25.0, 3 cells, blur 21, heartbeat 1.0 s, JPEG 85; `app` resolves
  to ai_workers; gating video 3226 (`VIRAT_S_000207_00_000000_000045`) gives **1,350 frames,
  44 kept, the product's own count** (OMNI-702)
- The 9 product VIRAT videos (`datasets/demo/virat_sample.csv`): all 9 are evaluation videos
  in `datasets/splits/virat.csv`, so the archive run covers them
- Drive, read from the laptop (`G:`): all 275 evaluation videos are in
  `omnisight/data/virat/videos_original/`, 0 missing
- Colab, step 1 run by Ahmad: setup, the gate and both encoders loaded on the GPU, and the
  inputs cell printed *275 evaluation videos, 275 on Drive, 0 missing*
- `scripts/tests/test_encode_virat_archive.py`, 7 tests with stand-in encoders on generated
  videos: the kept frames equal the gate's own; both vectors per kept frame; each clip is 8
  frames of its own window in order (read back from a frame number painted in each frame);
  a rerun skips finished videos and redoes none; a lost file is redone; a failed video is
  recorded and the run goes on; other gate settings refused; the product match, including a
  segment with no archive frame reported. 3 new `window_span` tests. 18 passed
- The runner on video 3226 with stand-in encoders: 1,350 frames, 44 kept, all heartbeat, the
  product's count; 15 s to decode and gate on this laptop
- The export on the running stack: 9 videos, 1,039 admitted segments, 44 with a laptop vector
  (video 3226, OMNI-705); every video extracted with 0.5 s, 8 x 8, 25.0, 3 (the archive's)

- **The archive run on Colab (Ahmad, one A100, one session, 2.52 h):** 275 of 275 videos,
  0 failed; 793,686 frames gated, 35,704 admitted (8,255 motion, 27,449 heartbeat), each with
  both vectors; `check` found every file present and equal to the manifest. The early pace
  (30 videos in 45 min) was the long videos; the short ones followed
- **The match:** 1,039 of 1,039 product segments found in the archive, 0 unmatched
- **Agreement:** the 44 laptop vectors of video 3226 against the A100's, cosine min 0.999979,
  44 of 44 at least 0.999 (44, not the ticket's 20: every frame with a laptop vector)
- Results in `results.md` (scoreboard row and entry)

### Not verified

- **The kill-and-resume test on Colab:** the run finished in one session, so the runtime was
  never killed mid-run. Resuming is tested only with stand-in encoders (the rerun, lost file
  and failed video tests). The ticket's box is left open
- The clip vectors' agreement: the laptop has no video side (D-32)

### Result

The VIRAT archive is on Drive with both vectors, 35,704 frames (above D-37's estimate of
about 30,000), and the product's 9 videos have their vectors in `embeddings/product/`. Open:
the kill-and-resume test.

---

## OMNI-709 · The labelled query set, written before any search

### Why this ticket exists

SM-1 needs at least 50 labelled queries on VIRAT, half scenes, half actions, fixed before
anything is measured so nothing can be tuned on them. The modality classifier (OMNI-711) needs
its own training set. K-23 asked first: how much of VIRAT's events did the gate keep?

### What was done

- **Coverage:** `scripts/virat_event_coverage.py`: the archive's admitted frames against every
  annotated event, by `frame_index`, per type; numbers in `results.md`. Run first, before the
  set was fixed: no type with events is dropped; digging has no event in the 275 videos
- **Added to the ticket's count:** the same script reports the share of frames each answer rule
  accepts and the recall@5 five random frames would get, because that is what SM-1's number has
  to be read against
- **`datasets/eval/sm1_queries.csv`:** 25 action queries over the 11 event types with events,
  2 wordings each and 3 for opening a trunk, closing a trunk and entering a facility, with the
  opening/closing, in/out and loading/unloading pairs; 25 scene queries over the 11 scenes, 3
  each for the three scenes with the most videos (0102, 0100, 0002), 2 for the others.
  `answer_rule` is `event_type=N` or `scene=NNNN`
- **Scene queries written by looking:** a sheet per scene of each video's first frame, one per
  camera sequence, up to 6 (`VIRAT_S_0502xx`); read from the local mirror or Drive. Scene 0500
  has one sequence, so one frame
- **`datasets/eval/modality_train.csv`:** 100 queries, 50 scene and 50 action, about places and
  actions other than the test queries' wherever possible
- Google Drive for desktop was not running; started it to reach the archive
- `scripts/tests/test_sm1_query_set.py`: the counts, every rule names a real type or scene, the
  two sets share no text, the coverage count at an event's ends, a frame in two events of a type
  counted once

### Verification performed

- `uv run pytest scripts/tests`: 14 passed (7 new)
- The coverage run read all 275 files: 35,704 admitted frames, OMNI-708's count
- No search has been run on either set: `sm1_queries.csv` went to no model, and the frames were
  looked at directly

### Not verified

- A second reader: Claude wrote every query and every label; nobody has checked them
- Each scene's other videos: a scene query describes the frames on its sheet, and may fit less
  well in other light or with other cars
- Whether a frame inside an event shows the action (`results.md`)
- Full `uv run pytest`: only new files and docs changed, so `scripts/tests` was run alone

### Result

Both files are ready to commit before any SM-1 run. 99.5% of events hold an admitted frame, so
no type is out of search's reach, but mostly through the heartbeat (21.8% hold a motion frame).
Chance recall@5 over the set is 25.1% (actions 11.7%, scenes 38.5%), which OMNI-713 should
report beside SM-1. K-23 stays open for Ahmad's decision.

---

## OMNI-710 · `clip_vectors`, loaded from the cache; InternVideo2's text side locally

### Why this ticket exists

FR-2 and FR-3's clip half: the product's clip vectors, made on Colab (D-32), have to be in Qdrant
beside the frame vectors, and a query has to reach them through InternVideo2's text side.

### What was done

- **`omnisight_common/clip_vectors.py`:** `CLIP_VECTOR_SIZE` 512 (D-33), `clip_point`,
  `ensure_clip_collection`; the same `FramePayload`, payload indexes and point id as
  `frame_vectors`. `ensure_frame_collection`'s body became `ensure_collection(client, name,
  size)`, shared by both. `query` creates both at startup
- **`scripts/import_clip_vectors.py`:** copies the Drive files into `query`, refuses an archive of
  another clip model or a vector that is not a unit vector of 512 dimensions, upserts by segment id
  with the payload `jobs_for_segments` builds (the embed jobs' own), then compares file rows,
  admitted segments and points per video
- **`GET /embeddings/status`:** `clips_embedded` counts admitted frames with a point of the pinned
  clip model
- **`verify_tc3_frame_vectors.py clip`:** OMNI-703's script, now for either collection
- **`scripts/verify_tc2_clips.py`:** TC-2's clip half from OMNI-708's files, no new Colab run: that
  run already gated each file as an upload is and encoded it with the repo's code
- **Different from the ticket, two text endpoints kept:** the ticket has `POST /encode/text`
  return both vectors. OMNI-706 and OMNI-707 already built `/encode/text` and `/encode/clip-text`,
  with a cache per encoder. One combined call would make `mode=clip` wait for SigLIP 2 (1,097 ms
  against 131 ms a query, OMNI-706) and cache the two together. OMNI-711 asks for both. Not a Phase
  A matter; Ahmad told
- **Different from the ticket, 9 videos, not 69:** its acceptance says 69 product videos, but
  OMNI-708 left the 60 hand-check clips out (D-35: not searched this sprint), and Drive holds
  vectors for the 9 only

### Verification performed

- 1,039 of 1,039, per video, and a rerun leaves 1,039; TC-3's clip half passes across a Qdrant
  restart; TC-2's clip half passes; numbers in `results.md`
- The frame half of TC-3 rerun on the changed script: PASS across a restart
- On the stack: `/embeddings/status` through the API as the admin (1,039 clips, on the 9 videos);
  `/encode/text` gives 1152-D of SigLIP 2's pinned revision, `/encode/clip-text` 512-D of
  InternVideo2's; query's log shows the collection's indexes made at startup
- New tests: `test_clip_vectors.py` (4), `test_import_clip_vectors.py` (9 with the refusals),
  one in `test_embeddings.py`
- **Full `uv run pytest`, as it stands: 25 failed, 551 passed, 1 skipped, 26 errors, twice.** All
  RabbitMQ logins refused, from OMNI-708's test file (K-28), not from this ticket. Without that
  file: **569 passed, 1 skipped**. The file alone passes

### Not verified

- A camera's clip vector (D-32) and a real API upload encoded on Colab
- Searching `clip_vectors`: OMNI-711
- Memory or speed again: both text sides have run together since OMNI-706, unchanged

### Result

`clip_vectors` exists and holds every admitted segment of the product's 9 VIRAT videos. Two issues
found and not fixed: `frame_vectors` holds only 44 of those frames (K-27), and a full pytest run
fails because of OMNI-708's test file (K-28).
