# Extra — The demo set: footage worth searching

**Not a slice · two to three days · branch `demo-set`** (after OMNI-X03 is merged)
Board: OmniSight Phase B · Assignee: Ahmad

> **When it is done:** the archive holds traffic accidents seen by street cameras (WTS), crimes
> in long surveillance videos (UCF-Crime), football matches (SoccerNet), the 60 hand-check clips
> and the 9 VIRAT videos, **all searchable by scene and by action**, with about 10 demo searches
> that were checked against each dataset's own labels.

**Why:** VIRAT's car parks do not show what the system is for. Search has to find a short,
important moment inside long footage.

**Rules for this ticket:**

- **Only `ai_workers` and Colab touch a model;** encoding is done on Colab (D-26, D-31, D-32), as
  in OMNI-708 and 710, with the same pinned checkpoints (D-30, D-33)
- **Every video goes in through the normal path** (upload, gate, segments), never expiring, like
  the VIRAT sample (D-25, D-26)
- **The terms of use:** WTS and SoccerNet are academic only and may not be shared with anyone who
  has not signed for them. Nothing from either goes into a backup for someone else (OMNI-X01) or
  into the repo. Recorded in `decisions.md`

---

## OMNI-X04 · Choose and fetch the footage (on Colab)

Everything lands under Drive `omnisight/data/`; a list of what was chosen, with a fixed seed where
a choice is random, is committed as `datasets/demo/demo_set.csv` (dataset, clip, source file,
start and end if cut, why it was chosen).

- [ ] **WTS** (`data/wts`, a shortcut to the organisers' folder): read `annotations/` and choose
      **10–20 scenarios whose captions describe a collision or a near collision**. From
      `videos.zip` (41.8 GB) **extract only those scenarios' `overhead_view` videos**, by reading
      the zip from Drive (no full download), into `data/wts/selected/`
- [ ] **UCF-Crime** (already on Drive): **20–30 long videos** (at least 1 minute) with a clear
      event: robbery, fighting, explosion, shooting, arson, road accident, arrest. Prefer
      **held-out** videos: they have official event times
- [ ] **SoccerNet:** `pip install SoccerNet`; the password is in Ahmad's NDA email (never
      committed; typed in the notebook at run time). **2 games, 720p**, plus each game's
      `Labels-v2.json`, into `data/soccernet/`. Then **cut three 5-minute excerpts per game, each
      holding a labelled goal, card or corner**, so the gate does not have to keep a whole
      broadcast (a moving camera keeps far more frames, K-4)
- [ ] The **60 hand-check clips** are already in the product (D-26): nothing to fetch

**Acceptance:** `demo_set.csv` committed; the chosen files on Drive; total minutes and size
recorded.

---

## OMNI-X05 · Load, encode, import

- [ ] **Load** every chosen file into the product through the upload path, as `source =
      dataset`, never expiring (the VIRAT sample's way, OMNI-702), with its dataset name and
      clip name. Record per dataset: videos, minutes, frames gated, frames kept, load time,
      storage
- [ ] **Encode on Colab** the product's admitted segments of these videos **and of the 60
      hand-check clips**, both vectors, from the originals on Drive (the OMNI-708 notebook and
      `export_segments_for_colab.py`), cached and resumable
- [ ] **Import** with `import_frame_vectors.py` and `import_clip_vectors.py`, each point carrying
      its `dataset` name in the payload (OMNI-X03);
      `GET /embeddings/status`: `frames_embedded = clips_embedded = frames_total` for every video
- [ ] Record the encode time and frames per second on the GPU

**Acceptance:** every video of the demo set and the 60 hand-check clips is fully searchable by
scene and by action.

---

## OMNI-X06 · The demo searches, checked against the labels

- [ ] **Write first, before searching:** about 10 searches in `datasets/demo/demo_queries.csv`,
      2–3 per kind of footage (*"a car hits a pedestrian at a crossing"*, *"a man robs a shop
      at gunpoint"*, *"a player scores a goal"*, *"a fire breaks out"*), each with how to tell a
      right answer from the dataset's own labels: WTS captions and their times, UCF-Crime's
      official or UCA times, SoccerNet's event times
- [ ] Run each from the Search page (OMNI-X03): how many of the top 5 are right by the labels,
      and is the first right one in the top 1; screenshots
- [ ] `results.md`: the table, labelled **a demo, hand-picked footage and queries, not SM-1**
- [ ] `docs/demo.md` rewritten around the searches that work, with the boxes and Compare

**Acceptance:** the 10 searches, their checked top 5s and the screenshots are recorded, and
`docs/demo.md` runs on them.

---

## Working with Claude Code

One ticket per session, in order X04 → X05 → X06. Paste the ticket, then:

> Here is ticket OMNI-X0n from our sprint board. Implement exactly what it asks and nothing
> more. Before starting, read the context sections for OMNI-702, 708, 710 and OMNI-X03. When you
> are done, show me the diff, tell me which acceptance criteria you verified and how, and
> suggest a short commit message without the ticket number. Do not run any git command that
> changes the repository; I commit myself.

**You create the branch first:** `git switch -c demo-set`.
