# Sprint 7 — Search

**Slice 7 · Sun 18 – Sat 24 Oct 2026 · 7 days · branch `slice-07-search`**
Board: OmniSight Phase B · Assignee: Ahmad

> **By the end of this sprint:** type a description of something and get the matching moments
> back in under three seconds, then jump straight to that second in the video.

**Covers:** FR-2 · FR-3 · FR-4 · NFR-1 (complete) · NFR-2 · TC-2 and TC-3 (frame half)
**Algorithm:** Algorithm 2 (Phase A §3.5.2, Appendix B.2), **the frame stream** (SigLIP 2).
The clip stream (InternVideo2), Algorithm 3's fusion, SM-1 and TC-4 are slice 8.
**Carries over from slice 6:** K-14 (flaky test on `master`), a VIRAT sample to search, K-4
(Colab), K-20 and the 30 / 60 s windows (both due before slice 9)
**Ships in:** `services/ai_workers/` · `services/query/` · `services/ingestion/` · `infra/` ·
`frontend/` · `notebooks/`

--- 

## Why the frame half only, and what that means

Phase A's TC-2 asks for a frame **and** a clip embedding per admitted segment, and TC-3 for
both Qdrant collections. This slice builds the frame stream end to end (encode, store,
search, screen); slice 8 adds the clip stream and fuses the two. So TC-2 and TC-3 are done
here for `frame_vectors` and recorded as **first half**, the same way TC-1 was split across
slices 4 and 5. Phase A's own Semantic Search screen is described as *"retrieved using the
SigLIP 2 frame embeddings"*, so this slice's search is what Phase A drew.

## Where things run (D-26 applied)

| Work | Where | Why |
|---|---|---|
| Encoding new admitted frames (live and uploads), query text | **Local**, `ai_workers` on CPU | The product must work end to end; NFR-1 and NFR-2 are system measurements (D-26) |
| Encoding the datasets (VIRAT now; CCD, UCF-Crime later) | **Colab**, A100, cached to Drive | Model measurements need a GPU; SM-1 in slice 8 runs there |
| Qdrant, search, the screen | **Local** | |

Same model, same weights, same code (`services/common` + `ai_workers`) in both places.

---

## Rules for this sprint

- **You run every git command.** Claude Code suggests a short commit message after each
  ticket, without the ticket number.
- **Algorithm 2 as written:** every admitted frame is encoded, L2-normalised, stored with its
  metadata. No skipping frames to keep up; grouping frames into batches is allowed (Phase A
  §3.6 names it).
- **One model, pinned:** the exact SigLIP 2 checkpoint and revision are recorded, and the
  same one runs locally and on Colab.
- **Only `ai_workers` loads a model.** `query` never imports PyTorch; it asks `ai_workers`
  to encode the query text.

---

## Ticket order

**Part A — carry-over (day 1)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-700 | Branch and baseline | 0.5 h | 1 |
| OMNI-701 | K-14: the flaky live capture test | 1 h | 1 |
| OMNI-702 | A VIRAT sample in the product, to search | 1.5 h + background | 1 |

**Part B — the frame stream and search (days 1–4)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-703 | Qdrant in the stack, and `frame_vectors` (TC-3, frame half) | 2 h | 2 |
| OMNI-704 | `ai_workers`: SigLIP 2 frame and text encoder (TC-2, frame half) | 4 h | 2 |
| OMNI-705 | Every admitted frame reaches the encoder, durably | 3 h | 3 |
| OMNI-706 | `GET /search` | 3 h | 3 |
| OMNI-707 | Search screen | 4 h | 4 |

**Part C — measure (days 5–6)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-708 | NFR-2: search latency | 1.5 h | 5 |
| OMNI-709 | NFR-1 complete: capture to searchable | 2.5 h | 5 |
| OMNI-710 | Colab: encode VIRAT, cached and resumable; K-4 on all of CCD | 3 h + background | 6 |
| OMNI-711 | Proof: relevant queries beat unrelated ones | 1.5 h | 6 |
| — | **cut line — the slice is defensible from here** | | |

**Part D — before slice 9 (day 7; may spill into slice 8, never past it)**

| # | Ticket | Est. | Day |
|---|---|---|---|
| OMNI-712 | K-20: how wrong are UCA-timed windows, and does ending them earlier fix it | 3 h | 7 |
| OMNI-713 | The 30 s and 60 s windows on UCF-Crime: a decision | 1.5 h | 7 |
| OMNI-715 | Experiment: SigLIP 2 so400m against giant, on the same small set | 2.5 h + Colab | 7 |
| OMNI-714 | Diagram, docs, merge | 2 h | 7 |

Fallback from the plan: *index uploaded footage first if camera footage is not yet embedded.
One working search path beats partial coverage of every source.*

---

# Part A — carry-over

## OMNI-700 · Branch and baseline

- [x] `master` has slice 6 (`git log` shows `62225f8` or later)
- [x] **You** create the branch: `git switch -c slice-07-search`
- [x] `docker compose up -d` and `uv run pytest` before touching anything; record the count
      (469 passed, 1 skipped, 1 failed at the slice 6 merge, K-14)

**Acceptance:** on the new branch, the stack runs and the baseline is recorded.

---

## OMNI-701 · K-14: the flaky live capture test

**Why:** it failed again on `master` after the slice 6 merge (`assert 75 == 76`). A suite that
fails now and then stops being believed.

- [x] Count the frame `_open_stream` grabs to prove the stream in `grabbed` where it is
      grabbed (K-14's fix candidate), or show from the code why that is wrong
- [x] A test that reproduces it deterministically: stop the worker right after the stream opens
- [x] Full suite 5 times in a row, all green; K-14 → *Fixed*

**Acceptance:** the reproducing test fails before the fix and passes after; 5 green full runs.

---

## OMNI-702 · A VIRAT sample in the product, to search

**Why:** D-26 keeps the product to the 60 hand-check clips, none of them VIRAT. Search needs
real surveillance footage with people and vehicles to be demonstrated at all, and VIRAT is
Phase A's search dataset.

- [x] Amend D-26 in `decisions.md`: *the product also holds a VIRAT demo sample, one video
      per scene with events (11), drawn once with a fixed seed into
      `datasets/demo/virat_sample.csv`*. SM-1 still runs on Colab
- [x] Load them through `POST /datasets/virat/load` (D-25's path: upload, extract, gate)
- [x] Record load time, frames, admitted frames and storage in `results.md`

**Acceptance:** 11 VIRAT videos `ready`, never expiring, in the archive, from 11 scenes.

---

# Part B — the frame stream and search

## OMNI-703 · Qdrant in the stack, and `frame_vectors`

**Why:** **FR-3** — *store each analysed segment with its details for later retrieval.* Phase A
puts the vectors in Qdrant (§3.3, Appendix B.2).

```
Qdrant collection frame_vectors: size 1152, distance Cosine, HNSW
point id = segments.id
payload {segment_id, video_id, camera_id, source_type, domain, timestamp_s, captured_at,
         frame_path, thumb_path, model, model_revision}
```

- [x] `qdrant` service in `docker-compose.yml`, named volume, **no port published to the
      host**, version pinned; config in `infra/qdrant/`
- [x] The collection is created on startup if missing, never recreated if present
- [x] **Point id = segment id**, so a redelivered message overwrites the same point instead of
      making a duplicate
- [x] **Deviation, record in `decisions.md`:** Appendix B.2 line 4 sets the shared identifier
      to `frame_id = hash(camera_id, timestamp)`. An uploaded file has no camera, so two files
      would collide; the segment id is unique for every source and is the same identifier
      slice 8's `clip_vectors` will use, which is what line 4 is for (matching a frame entry to
      its clip entry)
- [x] `captured_at` is an absolute time for every source: a camera frame's capture time; an
      uploaded file's upload time plus `timestamp_s` (files carry no wall-clock time; recorded
      in `decisions.md`)
- [x] **Payload indexes** on `camera_id`, `video_id` and `captured_at`, so filters run inside
      the vector search
- [x] **TC-3, frame half:** insert a batch of 1,000 vectors with payloads, retrieve them by id
      and by filtered search, compare every field byte for byte; restart Qdrant and compare
      again

**Acceptance:** TC-3's frame half passes, including after a Qdrant restart; recorded in
`results.md`.

---

## OMNI-704 · `ai_workers`: SigLIP 2 frame and text encoder

**Why:** **FR-2** — *produce a searchable representation of each accepted segment's visual
content.* Algorithm 2, line 1: `e_f ← SigLIP2_image(f_t); e_f ← e_f / ||e_f||`, 1152-D.

- [x] Model: **`google/siglip2-so400m-patch14-384`** (1152-D, Phase A's dimension). Pin the
      revision hash in settings; record it in `decisions.md`
- [x] `ai_workers` is the only service with PyTorch and transformers (`uv add ...
      --package omnisight-ai-workers`); CPU locally, the same code on a GPU
- [x] Encode from the **stored full-frame JPEG** (`frame_path`), in both places, so local and
      Colab see the same input
- [x] `get_image_features` / `get_text_features`, then L2-normalise; assert 1152 dimensions and
      unit length
- [x] **Text trap:** SigLIP 2 was trained on lowercased text padded to `max_length=64`
      (`padding="max_length"`, `truncation=True`). `AutoProcessor` does this by default; the
      bare tokenizer does not, and a wrong padding silently gives poor matches, not an error.
      A test pins it
- [x] Internal HTTP endpoint `POST /encode/text {q}` → 1152 floats, for `query`. Not exposed
      through nginx
- [x] **TC-2, frame half:** encode the admitted frames of a 30 s uploaded MP4 and of 30 s from
      a live camera: one 1152-D vector each, unit length, no error
- [x] Measure on this machine: image encode ms per frame (batch 1 and batch 8), text encode ms,
      model load time, container memory. The checkpoint is about 1B parameters, about 4 GB in
      float32; Docker has 7.6 GiB for everything. If it does not fit, raise Docker's memory
      (the machine has 15.7 GB) and record it

**Acceptance:** TC-2's frame half passes for both sources; CPU cost and memory recorded.

---

## OMNI-705 · Every admitted frame reaches the encoder, durably

**Why:** **NFR-5** applies to vectors too: an admitted frame that never gets a vector is a frame
search can never find.

```http
GET /embeddings/status -> [{video_id, camera_id, frames_total, frames_embedded, model, dim}]
```

- [ ] After a segment's insert commits, the consumer publishes an **embed job** (segment id,
      frame path, payload) to a durable queue `omnisight.embed`, admitted frames only, files
      and cameras alike
- [ ] `ai_workers` consumes it, encodes (in batches when several are waiting), upserts to
      Qdrant, and **acknowledges only after the upsert succeeds**
- [ ] A backfill script queues every admitted segment that has no point in Qdrant (the 60
      hand-check clips, the VIRAT sample, anything uploaded before this ticket)
- [ ] `GET /embeddings/status`: admitted frames from Postgres against points in Qdrant (exact
      count with a filter), per video and per camera
- [ ] Kill `ai_workers` mid-backfill and restart: every admitted frame ends with exactly one
      point, none missing

**Acceptance:** after the backfill, `frames_embedded = frames_total` for every video; the kill
test loses nothing and duplicates nothing.

---

## OMNI-706 · `GET /search`

**Why:** **FR-4** — *natural-language search over stored video, returning a ranked list of the
most relevant moments.*

```http
GET /search?q=&k=5&camera_id=&from=&to= -> {results: [{segment_id, video_id, camera, timestamp_s,
                                             captured_at, score, thumb_url}], elapsed_ms, total}
```

- [ ] `query` asks `ai_workers` for the text vector, searches `frame_vectors` (cosine, top `k`,
      `k` 1–50, default 5), joins the hits back to `segments`, `videos` and `cameras`
- [ ] **Camera and date filters inside the vector search** (Qdrant filter on the indexed
      payload), never by filtering the top `k` afterwards
- [ ] A hit whose segment no longer exists in Postgres is dropped, counted and logged, not
      returned
- [ ] Empty index, empty query, `ai_workers` down: each a distinct, clear response, never a 500
- [ ] Operator and admin; the token check like every API route (NFR-7)
- [ ] `elapsed_ms` in the response, measured inside `query` from request to response

**Acceptance:** a query returns ranked moments with every field; a camera filter returns only
that camera's frames even when its best match ranks below other cameras' in an unfiltered
search.

---

## OMNI-707 · Search screen

- [ ] One prominent search box with a realistic placeholder (*"a person in a red jacket
      walking to a parked car"*)
- [ ] Results as thumbnails with camera (or recording name), date, time and match score
- [ ] **Result count and elapsed time shown**, so NFR-2 is visible to the user
- [ ] Filters: camera, date range
- [ ] Clicking a result opens **playback at that exact second** (the player from OMNI-308 for
      a recording; the rewind view at that moment for a camera)
- [ ] Distinct states: empty index, no results, error, `ai_workers` unavailable
- [ ] In the nav for operator and admin

**Acceptance:** search, click a result, the player is at that second.

---

# Part C — measure

## OMNI-708 · NFR-2: search latency

**Why:** **NFR-2** — *results must appear in under 3 seconds.*

- [ ] Write the query set first: 30 queries (scenes, objects, actions), committed
- [ ] End-to-end latency from the client (request sent → response received) and `elapsed_ms`
      split into text encode, Qdrant search, Postgres join: p50 / p95 / max over the 30
      queries, 3 rounds, with and without a camera filter
- [ ] At the archive's real size, **and** with `frame_vectors` padded to 100,000 random unit
      vectors (labelled as a scale test; removed afterwards)
- [ ] With 3 live cameras capturing at the same time (NFR-4's revised number)

**Acceptance:** NFR-2's scoreboard row: measured, pass or fail, with the conditions.

---

## OMNI-709 · NFR-1 complete: capture to searchable

**Why:** **NFR-1** — *from capture, ready to search in under 5 seconds.* The first half
(capture to stored) passed in slice 5; this adds the encoder.

- [ ] **Searchable** = the frame's point is in Qdrant (a poller every 100 ms reading by point
      id), measured from the camera frame's capture time; the encoder's own timestamps split
      it into queue wait and encode time
- [ ] One camera and 3 cameras (NFR-4's revised number), 10 minutes each, the realistic
      simulator set; p50 / p95 / max, and whether the embed queue grows
- [ ] **The GPU figure:** the same encoder on Colab's A100, ms per frame at batch 1 and batch 8,
      so the deployment target's encode time is measured, not assumed
- [ ] If the CPU run fails 5 s: record it, show where the time goes, and **stop and decide with
      Ahmad**. No frames skipped to make it pass (Algorithm 2 encodes every admitted frame)

**Acceptance:** NFR-1's scoreboard row says complete, with the CPU result and the GPU encode
time beside it.

---

## OMNI-710 · Colab: encode VIRAT, cached and resumable; K-4 on all of CCD

**Why:** slice 8 measures SM-1 on VIRAT; the full dataset is too big for this laptop (D-26).

- [ ] A notebook in `notebooks/` that imports the repo's gate and encoder code (no copies):
      Algorithm 1 over every VIRAT video with events (275), Algorithm 2's frame stream over every
      admitted frame, from Drive
- [ ] Cache: `embeddings/frames/virat/{clip_key}/{frame_index}.npy` plus a `manifest.json`
      written after each video, so a lost session resumes where it stopped and never redoes a
      finished video. Keys are the dataset's own (`clip_key`, frame index), because Colab has
      no product database (a change from the plan's `{video_id}/{segment_id}`, recorded)
- [ ] Kill the runtime mid-run once and resume: no video encoded twice, none skipped
- [ ] Record: frames decoded, admitted, encoded; frames per second on the A100; hours for the
      full pass; projected hours for CCD and UCF-Crime
- [ ] **Agreement:** 20 VIRAT-sample frames encoded locally (OMNI-702) and on Colab: cosine
      at least 0.999 each, or the difference explained
- [ ] **K-4:** the same notebook gates all 4,500 CCD clips (no encoding) and records retention
      for crash and normal clips; K-4's entry updated with the full-set number

**Acceptance:** all 275 VIRAT videos encoded and cached with a manifest; throughput and the
agreement check recorded; K-4 has its full-set number.

---

## OMNI-711 · Proof: relevant queries beat unrelated ones

**Why:** the plan's proof: *a plain-language query returns visibly relevant footage; an
unrelated query returns visibly worse matches.*

- [ ] **Write the check first:** 10 queries about things visible in the VIRAT sample and 10
      about things absent from it (a boat on the sea, a snowy forest), committed before running
- [ ] For each, the top-5 thumbnails and scores saved; relevant queries' top scores against
      unrelated queries' top scores
- [ ] Look at every top 5 and mark each hit relevant or not; record the counts
- [ ] Not SM-1: no ground truth, one look, the demo sample. SM-1 is slice 8, on Colab

**Acceptance:** the 20 queries, their top 5s and the relevant counts are in `results.md`.

> **This is the cut line.** Footage is searchable by meaning, NFR-1 and NFR-2 are measured, the
> VIRAT embeddings for SM-1 are cached. What follows is data work that must be done before
> slice 9 trains anything.

---

# Part D — before slice 9

## OMNI-712 · K-20: how wrong are UCA-timed windows, and does ending them earlier fix it

**Why:** every UCF-Crime **training and validation** positive window (540) is UCA-timed: the
official times exist only for the held-out test videos. In the hand check, UCA windows were
wrong 5 of 15 times, mostly by containing the event. K-20's first fix candidate (train on
official-timed windows only) is impossible: there are none in training.

- [ ] Write the plan first: the same criterion as D-27, a new seeded sample of **100**
      UCA-timed windows across classes, and the margins to test (0, 2, 5, 10 s earlier)
- [ ] Check the 100 by eye in the window view; record correct and wrong, and for each wrong
      one how many seconds too late it ends
- [ ] From those, the share correct at each margin (computed, not re-checked), and how much
      footage each margin removes
- [ ] `decisions.md`: the margin adopted (or none) with this evidence; regenerate the windows
      **only if** a margin is adopted, as a new versioned export, never overwriting the old one

**Acceptance:** UCA windows' error rate measured on 100, a decision recorded, K-20 updated.

---

## OMNI-713 · The 30 s and 60 s windows on UCF-Crime: a decision

**Why:** Phase A runs the predictor on 30 s and 60 s windows and tests lead-up lengths
(§3.6, TC-5). On UCF-Crime 67% of the 30 s windows and 84% of the 60 s ones are shortened,
because events start early in the videos: the median real length in training is about 15 s
for both, so most 60 s windows are the same footage as the 30 s ones. The comparison Phase A
planned cannot really be run on this data.

- [ ] Measure: per split, how many positive windows reach a full 30 s and a full 60 s, the
      length distribution, and how many 60 s windows are identical to their 30 s ones
- [ ] `decisions.md`, the D-2 way: what the lead-up comparison becomes on UCF-Crime (for
      example the lengths the data supports, or the comparison on full-length windows only),
      decided with Ahmad, before any model is trained

**Acceptance:** the numbers and the decision are recorded before slice 9 starts.

---

## OMNI-715 · Experiment: SigLIP 2 so400m against giant, on the same small set

**Why:** Phase A fixes the frame encoder at 1152-D, which is SigLIP 2 **so400m** (about 1B
parameters in all). SigLIP 2 also comes as **giant** (`google/siglip2-giant-opt-patch16-384`,
about 2B parameters). Before trusting the smaller one, check on our own footage whether the
bigger one is visibly better. An experiment, run on Colab; it changes nothing in the product
unless the rule below says so.

- [ ] **Write the rule before running**, in `decisions.md`: *giant replaces so400m only if it
      finds the right moment in the top 5 for at least 10 more queries in 100 on the labelled
      set below, and its encode time still fits NFR-1 on the target GPU.* Otherwise so400m stays,
      as Phase A specifies, and giant is recorded as tried
- [ ] **The same input for both:** the admitted frames of the 11 VIRAT demo videos (OMNI-702),
      the same stored JPEGs, each model's own processor (text lowercased, padded to 64)
- [ ] **Two query sets, both fixed before running:** OMNI-711's 20 queries (judged by eye,
      **blind**: the two models' top 5s shown without saying which is which); and about 20
      queries written from the 11 videos' VIRAT event annotations (*"a person opening a
      vehicle door"*), where a hit is a top-5 frame inside an annotated event of that type
- [ ] Per model: hits in the top 5 on the labelled queries, relevant counts on the blind ones,
      the embedding dimension (check it, do not assume), ms per frame on the A100 at batch 1
      and 8, GPU memory
- [ ] `results.md`: a table, both models side by side, labelled **experiment, small set**;
      `decisions.md`: the rule applied to the numbers

**Acceptance:** both models measured on the same frames and queries, the rule applied, the
decision recorded either way.

**Not this ticket:** SM-1. A small set shows whether the difference is *obvious*; SM-1 in slice 8
measures the chosen model properly on all of VIRAT.

---

## OMNI-714 · Diagram, docs, merge

- [ ] `docs/architecture/slice-07-search.md`: admitted frame → embed queue → `ai_workers` →
      Qdrant; query text → `ai_workers` → Qdrant → Postgres join; and the Colab path
- [ ] `docs/context/week-07.md`, one section per ticket
- [ ] `results.md` scoreboard: NFR-1 complete, NFR-2, TC-2 and TC-3 (frame half), the
      proof queries; `decisions.md` and `known-issues.md` current
- [ ] `uv run pytest` green
- [ ] Everything committed on `slice-07-search` (by you)
- [ ] **You merge into `master`** (`git switch master`, `git merge --no-ff slice-07-search`),
      then `uv run pytest` green on `master`
- [ ] Slice 7 ticked on the tracker, and the schedule moved (slice 7 is 18–24 Oct)

---

## Definition of done

The plan's proof, on a fresh `docker compose up -d`:

> A plain-language query returns visibly relevant footage in under 3 seconds; an unrelated
> query returns visibly worse matches. Embeddings retrieved from Qdrant carry every metadata
> field intact. NFR-1 and NFR-2 are measured and recorded.

- [ ] All of the above true on a fresh stack
- [ ] Click a result: playback at that second
- [ ] `results.md` has NFR-1 (complete), NFR-2, TC-2 and TC-3 (frame half), OMNI-711's queries
- [ ] VIRAT's frame embeddings cached on Drive with their manifest
- [ ] Merged into `master`

---

## What to learn this sprint

- [SigLIP 2 model card and usage](https://huggingface.co/docs/transformers/model_doc/siglip2)
  — image and text features, and the text preprocessing it was trained with.
- [Qdrant: collections, payload indexes and filtering](https://qdrant.tech/documentation/concepts/filtering/)
  — why a filter inside the search beats filtering the top k afterwards.
- [Cosine similarity and L2 normalisation](https://qdrant.tech/documentation/concepts/search/)
  — why every vector is normalised before it is stored.
- [Checkpointing long Colab jobs to Drive](https://colab.research.google.com/notebooks/io.ipynb)
  — sessions die; cached work must not.

---

## Working with Claude Code

`CLAUDE.md` is read automatically. One ticket per session. Paste the ticket, then:

> Here is ticket OMNI-7xx from our sprint board. Implement exactly what it asks and nothing
> more. Before starting, read the context sections for the tickets this builds on. When you
> are done, show me the diff, tell me which acceptance criteria you verified and how, and
> suggest a short commit message without the ticket number. Do not run any git command that
> changes the repository; I commit myself.

Four things to insist on this sprint:

- **Every admitted frame gets a vector.** If the encoder cannot keep up, measure it and stop;
  never skip frames.
- **Only `ai_workers` touches a model.** `query` calls it; it does not load SigLIP 2 itself.
- **Filters inside the search.** Filtering the top 5 afterwards returns fewer than 5 results
  and wrong rankings.
- **One pinned model everywhere.** Local and Colab vectors must be comparable, and the check
  proves it.
