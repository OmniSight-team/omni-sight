# Extra — A labelled box on each search result

## OMNI-X02 · Open-vocabulary boxes on the search results

### Why this ticket exists

Search says which frame matches a description, not where in the frame the thing is. An open-vocabulary detector
finds it from the same words. An addition on top of FR-4, not a Phase A requirement (D-42).

### What was done

- **Before building,** two problems in the ticket were raised with Ahmad and fixed his way:
  - the query and its object word are two prompts, and YOLO-World only merges overlapping boxes of the same prompt,
    so one car would get two boxes, the bigger one labelled *a blue car*. Fixed with class-agnostic merging and the
    object word as the label (D-42)
  - ultralytics `pip install`s OpenAI's CLIP from GitHub the first time a prompt is set. Confirmed in its source
    (`ultralytics/nn/text_model.py`), so CLIP is a pinned dependency instead
- **`services/ai_workers/app/detector.py`:** YOLO-World `yolov8s-worldv2.pt` pinned by SHA-256, downloaded to
  `models/pretrained/yolo-world` if missing (a file with another hash is never used). CLIP is loaded once and kept;
  ultralytics' own `set_classes` would load it again on every call. One request at a time (setting prompts changes the
  model). Boxes in fractions of the frame; an unreadable frame gets an empty list. Usage events to Ultralytics off
- **`POST /detect`** in ai_workers; the detector loads after the encoders, and if it fails the rest of the service
  carries on (`/health` gives `detector_loaded` apart from `loaded`). Settings `detect_min_score` 0.25,
  `detect_max_boxes` 3, `detector_enabled`
- **`services/common/omnisight_common/box_prompts.py`:** the prompts from a query (the query as typed, then the
  ticket's object words) and the label rule; in common because query builds the prompts and ai_workers labels with them
- **`GET /search/boxes?q=&segment_ids=`** (up to 50) in query: the frames' `frame_path` from Postgres (admitted only),
  then ai_workers; any failure gives empty lists. Same roles as `/search`. `/search` itself unchanged
- **Packaging:** `ultralytics==8.4.202`; CLIP from an archive URL of ultralytics' fork at commit `7ffa84b` (no git in
  the image); a uv override keeps the full `opencv-python` out (it needs libGL), the headless build gives `cv2`
- **Screen:** `components/box-overlay.tsx`, an SVG the frame's own size laid over the picture with the same fit
  (`cover` for thumbnails, `contain` for the player and the live viewer), so the boxes line up through cropping and
  letterboxing. The search panel asks for the boxes once the results are shown and passes them on with a click. The
  player pauses at the result's second and shows them; playing, or a seek to another second, hides them. The live
  viewer shows them over the opened stored frame. Thumbnails show the label only (with the score they overlapped)
- **Docs:** D-42; K-32; `results.md` entry and two scoreboard rows; evidence in `docs/evidence/search-boxes/` (20
  frames with boxes drawn at 960 px, the report, 3 screenshots; 2.8 MB)

### Verification performed

- `test_box_prompts.py` (12), `test_detector.py` (3, plus 1 `model` test on the real weights): 16 passed
- `test_search.py`: 9 new tests (boxes per result from the query and its object word; gone or not admitted frames get
  none and are not sent; ai_workers down or its detector not loaded give empty lists, not an error; `/search` asks for
  no boxes; 50 at most; token; every role that searches). Whole file 51 passed
- Full suite: **678 passed, 1 skipped, 9 deselected** (the `model` tests), 9 min 50 s
- `tsc` clean; ESLint 0 errors (4 old warnings in `api-client.ts`)
- The image rebuilt; on start the detector loaded in 45.5 s (CLIP's 338 MB downloaded the first time)
- `scripts/measure_search_boxes.py` on the running stack: the check by eye on video 3230 and the CPU cost
  (`results.md`)
- Chrome through nginx: thumbnails, the paused player (video 3231) and its boxes going away on play, the live viewer's
  frame (camera 2446); screenshots kept

### Not verified

- The screen with ai_workers down: the API's empty answer is tested; the screen's fallback (no boxes) only read
- Compare mode's thumbnails with boxes (same component, one request for the three columns): not looked at
- An analyst or operator on the screen; admin only
- Boxes while the embed queue is encoding (both on the CPU)
- Labels overlap when boxes are close (seen on camera 2446's three people); left as is

### Detours

- **Video 3230 does not play in Chrome:** MPEG-4 Part 2 and no playback copy, as 6 other VIRAT videos (K-32). The
  player check moved to 3231, which has a copy
- The measuring script first ran `python` in query, which is not the venv; it now runs `/workspace/.venv/bin/python`
- The first thumbnails had labels with scores at 11% of the frame's height; they overlapped, so the score was dropped
  there and the size cut to 9%

### Result

Search results carry labelled boxes in the thumbnails, the paused player and the live viewer; `/search` is unchanged.
On one VIRAT video the boxes are on the right car and walker every time, and miss a person standing against a truck in
3 of 4 frames. About 0.4 s a frame and 2.6 s for a page of 5 on this CPU; ai_workers at 3.44 GiB after the run.
