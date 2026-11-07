# Extra — Search across all footage

**Not a slice · one day · branch `search-all`**
Board: OmniSight Phase B · Assignee: Ahmad

> **When it is done:** a **Search** page in the menu: type *"a car hits a pedestrian"* once and
> get the best moments from every video, dataset clip and camera, each with where it is from,
> when, its score and its box; click one and that video opens at that second.

**Why:** the point of the system is that you do not know *where* or *when* something happened.
D-39 put search only inside one video or one camera, which is why FR-4 is **Partial**.

---

## OMNI-X03 · A Search page over everything

### Decision first

- [x] **D-43** in `decisions.md`: the Search page comes back (it is Phase A's own Search screen);
      the search inside the player and the camera viewer **stays** as it is. **Revises D-39**,
      and closes D-39's "Open" note (Compare only in the player, on one video): Compare now
      works from the Search page too

### The payload: which dataset a point comes from

Dataset clips are stored as uploads (`SegmentSourceType` has only `upload` and `camera`); they
are linked to their dataset only through `dataset_manifest.video_id` in Postgres. So Qdrant
cannot tell a dataset clip from an upload today.

- [x] A **`dataset`** field in each point's payload, in both `frame_vectors` and `clip_vectors`:
      the dataset's name (`virat`, `ccd`, `ucf_crime`, ...) or null; set wherever points are
      written (the embed worker, `import_frame_vectors.py`, `import_clip_vectors.py`)
- [x] A payload index on `dataset`, and on `source_type` if it has none
- [x] **A backfill** of the points already stored: set `dataset` from `dataset_manifest` by
      video id, without rewriting vectors; idempotent; reports how many points it changed in each
      collection, and a second run changes none

### The API

`GET /search` with no video or camera **already** searches everything, with fusion (D-40) and
`MAX_K = 50` (D-39, "Kept"). That part is a check, not new work.

- [x] **Check:** an unscoped query returns hits from several videos and sources
- [x] New filter **`source`**: `camera`, `upload`, `dataset` (one or several), built from
      `source_type` and the new `dataset` field, added in `_filter` (`services/query/app/search.py`)
      so it is applied **inside** both Qdrant searches, like the camera and date filters, never by
      filtering the top k afterwards:
      - `dataset`: `dataset` is not empty
      - `upload`: `source_type` is `upload` **and** `dataset` is empty, as a Qdrant **`IsEmpty`**
        condition, which matches both a null `dataset` and a point with no `dataset` key at all
        (points written before the backfill have none). A "null" match alone would drop them
      - `camera`: `source_type` is `camera`
      - A test with three points: an upload with no `dataset` key, an upload with `dataset`
        null, and a dataset clip; `upload` returns the first two, `dataset` the third
- [x] Each result says where it is from: camera name, or video title and, for a dataset clip,
      the dataset's name (from the payload)
- [x] Boxes (OMNI-X02) through `GET /search/boxes`, unchanged

### The page

- [x] **Search** in the menu for operator, analyst and admin (D-36)
- [x] One big search box; mode Scene / Action / Combined (Combined by default); filters: source,
      camera, date range
- [x] Results as a grid: thumbnail with its box and label, where it is from, date and time
      (or the second in the video), score, what matched it; count and elapsed time shown
- [x] Click a result: the video opens at that second, paused, with the box; a camera result opens
      its stored frame (K-29)
- [x] The same empty, no-result, error and model-unavailable states as the player's search
- [x] **Compare** (OMNI-716) works from this page too

### Check and measure

- [x] **On the real stack, with two cameras that have vectors** (OMNI-707 could only check this
      in-process: the stack had no two cameras with vectors). Start two simulator cameras long
      enough for some of their frames to be encoded; then a query whose best match is on one
      camera, with a filter to the other camera: the first camera never appears
- [x] The `source` filter: `dataset` returns only dataset clips, `camera` only camera frames,
      `upload` only uploads that are not dataset clips, each against a direct count
- [x] **NFR-2:** rerun `scripts/measure_nfr2.py` as it is (no script change; it needs
      `--camera` and `--video`). Its first and repeat passes already search without a filter:
      report those unfiltered passes now that the archive is bigger, beside the old numbers
      (max 2.02 s) in `results.md`
- [x] FR-4's row in `docs/requirements-tracker.md`: **Pass** if this works, with D-43

**Acceptance:** from the Search page, one query returns moments from several videos and from the
datasets, filters work inside the search, a click opens the right second, NFR-2 still under 3 s.

---

## Working with Claude Code

> Here is ticket OMNI-X03 from our sprint board. Implement exactly what it asks and nothing
> more. Before starting, read the context sections for OMNI-707, 711, 712, 716 and OMNI-X02.
> When you are done, show me the diff, tell me which acceptance criteria you verified and how,
> and suggest a short commit message without the ticket number. Do not run any git command that
> changes the repository; I commit myself.

**You create the branch first:** `git switch -c search-all`.
