# Extra — A labelled box on each search result

**Not a slice · one day · branch `search-boxes`**
Board: OmniSight Phase B · Assignee: Ahmad

> **When it is done:** search *"a blue car"*, and each of the 5 results shows a box labelled
> *car* around the car; click a result and the player, stopped at that second, shows the same
> box.

**Not a Phase A requirement.** An addition on top of FR-4; recorded as such in `decisions.md`.
**Not in this ticket:** a box that follows the object while the video plays (tracking).

---

## OMNI-X02 · Open-vocabulary boxes on the search results

**Why:** search says *which* frame matches, not *where* in the frame. An open-vocabulary
detector finds the searched thing inside the frame from the same words.

### The detector, in `ai_workers`

- [x] **YOLO-World** (`ultralytics`, the small `yolov8s-worldv2` weights), added to
      `ai_workers` only (the rule: only `ai_workers` loads a model). Pin the `ultralytics`
      version and the weights file's SHA-256 (**D-42**, with its licence: AGPL-3.0, fine for a
      college project, recorded); weights downloaded at startup if missing, like D-30
- [x] `POST /detect {frame_paths: [...], prompts: [...]}` → per frame
      `[{label, score, box: [x1, y1, x2, y2]}]`, the box **in fractions of the frame's width
      and height** (0–1), so it fits any thumbnail or player size
- [x] Reads the stored full-frame JPEG (`frame_path`), as the encoders do
- [x] **The prompts from the query:** the query text as typed, plus the object words it
      contains from a short fixed list (person, man, woman, people → *person*; car, vehicle,
      truck, van → *car*; bike, bicycle; bag, box, object). The label shown is the prompt that
      matched. Recorded in D-42; the list is a constant, not tuned
- [x] Keep boxes with score at least a setting (start at YOLO-World's default, 0.25), at most
      3 per frame

### The API, in `query`

- [x] `GET /search/boxes?q=&segment_ids=...` (up to 50) → `{segment_id: [boxes]}`; same roles
      and token check as `/search`
- [x] **A separate request**, called by the screen after the results appear, so `GET /search`
      and NFR-2 do not change
- [x] `ai_workers` down, or no box found: an empty list for that frame, never an error

### The screen

- [x] Each result thumbnail draws its boxes and labels over the picture, scaled by the
      fractions; a thumbnail with no box looks exactly as today
- [x] Clicking a result: the player at that second shows the box over the video **while it
      is paused there**; the box disappears when the video plays
- [x] Works the same in the video player and in the live viewer's search (its results are
      stored frames)

### Check and measure

- [x] 4 searches on the VIRAT videos (*a blue car*, *a person walking*, *a white truck*,
      *a person opening a trunk*): for each top 5, by eye, how many boxes are on the right
      thing, wrong, or missing; screenshots kept
- [x] On this laptop's CPU: ms per frame and for 5 frames, `ai_workers` memory before and
      after (it must still fit Docker's memory)
- [x] Both in `results.md` (labelled: one look, one person, no ground truth)
- [x] **If it misses VIRAT's small people on most results: stop, record it, and decide with
      Ahmad** (OWLv2 is the next candidate; that is a second day)

**Acceptance:** search *"a blue car"* in a VIRAT video: the results show labelled boxes, the
player shows the box at that second, `/search` is unchanged, and the check and the CPU cost
are recorded.

---

## Working with Claude Code

`CLAUDE.md` is read automatically. Paste the ticket, then:

> Here is ticket OMNI-X02 from our sprint board. Implement exactly what it asks and nothing
> more. Before starting, read the context sections for OMNI-707, 711 and 712. When you are
> done, show me the diff, tell me which acceptance criteria you verified and how, and suggest a
> short commit message without the ticket number. Do not run any git command that changes the
> repository; I commit myself.

**You create the branch first:** `git switch -c search-boxes`.
