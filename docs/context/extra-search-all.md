# Extra — Search across all footage

## OMNI-X03 · A Search page over everything

### Why this ticket exists

The point of the system is that the user does not know *where* or *when* something happened. D-39 put search only inside
one video or one camera, so no screen searched the archive and FR-4 was Partial. Phase A's own Search screen comes back.

### What was done

- **Before building,** three problems in the first draft of the ticket were raised and fixed in the ticket: `source=dataset`
  could not be filtered in Qdrant (dataset clips are stored as uploads; only `dataset_manifest.video_id` links them), the
  unscoped `GET /search` already existed (D-39 "Kept"), and `measure_nfr2.py` cannot run without `--camera` and `--video`.
  Then one more: `upload` must match a point with no `dataset` key as well as a null one (`IsEmpty`)
- **D-43** in `decisions.md` (revises D-39, closes its "Open" note on Compare); D-39's row says so
- **Payload:** `FramePayload.dataset` (the dataset's name or None) and `EmbedJob.dataset` (default None, so a job queued
  before stays readable). `app/embed_jobs.py` reads it from the same `dataset_manifest` row as the domain. The embed worker
  and both import scripts build their points from these jobs, so all three write it. Payload indexes on `source_type` and
  `dataset` (keyword), in both collections through the shared `PAYLOAD_INDEXES`
- **`scripts/backfill_dataset_payload.py`** (renamed `backfill_search_payload.py` for D-44, below): `set_payload` of `dataset` only, by video id from the manifest, in both
  collections; a point already right is left alone; reports read and changed per collection. Runs inside `query`
- **`GET /search`:** `source` (one or several of `camera`, `upload`, `dataset`), one `should` condition inside both Qdrant
  searches: `camera` = `source_type` camera; `upload` = `source_type` upload and `dataset` empty; `dataset` = `dataset` not
  empty. Each result has `dataset` from the payload. `/search/boxes` unchanged
- **Menu:** `/search`, "Search", for operator, analyst and admin, in `omnisight_common/nav.py`; the sidebar marks it built
- **The page** (`frontend/src/app/(app)/search/page.tsx`) reuses the player's panel (`moment-search.tsx`) with new props:
  `withFilters` (source buttons, none = all; a camera select), `showSource` (camera name, or the video's file name with a
  dataset badge), `k` (16 a mode: Compare asks the boxes of three columns in one request of at most 50). Scene / Action /
  Combined (Combined by default), dates, count and time, the same empty, no-result, error and model-unavailable states, and
  Compare, all from the panel. The no-result message names the filters when any is set
- **A click:** a video result goes to `/videos/{id}?t={second}`; the boxes go through `sessionStorage`
  (`lib/search-pick.ts`), read once by the player. The player, on `?t=`, pauses, seeks and shows the boxes. A camera result
  opens its stored frame on the page, with the boxes, and "Back to results" keeps the results (K-29)

### Verification performed

- `test_search.py`: 5 new tests (each source alone and together, with an upload with no `dataset` key, one with null, a
  dataset clip and a camera frame; the source filter inside the search below another source's top 5; inside both searches
  of fused; the dataset's name on a hit, frame and fused; an unknown source 422). `test_backfill_dataset_payload.py` (now `test_backfill_search_payload.py`): 2
- On the stack (`results.md`): the backfill (1,039 set in each collection, a rerun 0); the source filter against a direct
  count in both collections, the same id sets; two cameras with vectors (a temporary camera 2452 on `cam05`), the filter
  to one never returning the other; NFR-2 again, unscoped, on the bigger archive
- Chrome through nginx, as admin: *Search* in the menu; *a person walking next to a parked car* 16 results from 2 VIRAT
  videos with dataset badges and boxes; Cameras alone: only camera 2446, with times; a camera hit opened its stored frame
  with 2 boxes, back kept the results; Datasets: only VIRAT clips; a video hit opened video 3231 paused at 16.03 s with its 3
  car boxes; Compare: three columns of 16; Datasets plus camera 2446: *No results* in each column
- `tsc` clean in `src`; ESLint clean on the changed files

### Not verified

- An analyst or operator on the page; admin only
- The model-unavailable and error states on this page (same component and code path as the player's, not triggered here)
- A plain upload's hit on the page (the 20 upload points did not rank for the queries tried); `source=upload` checked
  against the direct count only

### Detours

- **The first backfill's second run changed 41 points again:** qdrant-client drops `None` values from a payload, so setting
  `dataset` to null stores nothing. "No dataset" is a missing key; the backfill now counts a missing key as null, and the
  filter's `IsEmpty` already did. The same is true of every null field in the payload (a camera point has no `video_id` key)
- **A fast click gave no boxes in the player:** the click came before the page's boxes (about 0.4 s a frame on this CPU)
  had arrived. The pick now carries the query and segment id, and the player asks for that one frame's boxes when the pick
  has none. Seen working: clicked with 0 boxes on the card, 3 boxes in the player
- **Back from the player empties the Search page** (the query and results are not kept): K-33
- The dev server needed `frontend` and `nginx` restarted to serve the new files (OMNI-712's detour)

### Result

A Search page over every video, dataset clip and camera, with source, camera and date filters inside the search; a click
opens the video at that second, paused, with the box, or the camera's stored frame. FR-4 Pass with D-43. NFR-2 unscoped on
13 times the frame points: 0 of 1,800 over 3 s on the combined figure; on the CPU alone 1 request at 3.31 s (the text
encode).

### Follow-up: different videos in the results (D-44, 2026-11-06)

Ahmad searched *a person holding an umbrella*: all 16 results came from one VIRAT video, and the result he expected from
another video did not show. The top 50 held 2 videos. Also found: only 12 of 74 videos and cameras have scene vectors, so
the other 62 cannot appear whatever the ranking.

- **`footage`** on `FramePayload`, a computed field (`video:{id}` or `camera:{id}`), stored on every point, indexed
- **`GET /search?per_footage=N`:** Qdrant's `query_points_groups` on `footage` in each stream; fused merges the grouped
  lists and keeps N of each footage; then the first `k`. Without it, unchanged
- **The backfill** renamed `scripts/backfill_search_payload.py`; it now sets `dataset` and `footage`, and deletes a key
  whose right value is null (a null sent is dropped, so a stale `dataset` could never be cleared). Run: 1,110 frame and
  1,039 clip points changed; a rerun 0
- **The page** asks for `per_footage=2`; the panel takes `perFootage`
- **D-44** (Deviation) in `decisions.md`; the numbers in `results.md`

**Verification:** `test_search.py` 6 new tests (one video fills the list without it; with 1 and 2 another video and a camera
come up, in order; the same in fused; still stops at `k`; 0 and 51 refused); `test_backfill_search_payload.py` 2 (the
wrong `dataset` deleted, a second run nothing). The payload tests in `services/common` now count the computed field.
151 passed in those files. On the stack: the umbrella query, 8 sources in Scene and 9 in Combined; the cost above.
In Chrome: Combined, 16 results from 9 sources, at most 2 each.

### Follow-up: back to the results (K-33, 2026-11-06)

Ahmad: after opening a result there was no way back to the results. The Search page now keeps its search in its URL
(`/search?q=...&mode=...&source=...&camera=...&from=...&to=...&compare=1`, written with `history.replaceState` on each
search) and runs it again when opened; a repeated query's text vector is cached. The player shows *← Search results*
(browser back) instead of *← Video Archive* when opened with `?t=`. Both pages read the URL with `useSearchParams` inside a
`Suspense` boundary, as this Next version's docs ask; the panel starts the saved search from a timer, not inside the
effect, for the `set-state-in-effect` lint rule.

**Verification:** Chrome, *a person holding an umbrella*, Combined, Datasets: open the first result (video 3231 at 16.0 s,
*← Search results* shown), click it: the same query in the box, Datasets still on, the same 16 results. `tsc` and ESLint
clean. Not tried: a direct link to a search opened in a new tab, the dates and camera in the URL (written and read the same
way, not exercised).
