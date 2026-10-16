# Dataset layout

The specification slice 6's loaders are written against. It describes how each
dataset **actually sits** on Drive and in the local mirror under `data/` — not an
idealised layout. Written in OMNI-300, after all three slice-6 datasets were
downloaded and verified.

## The decision: native structure, one loader per dataset

An earlier version of this document specified a flat layout — every clip's
annotation file beside its video, sharing a base name. None of the datasets are
shaped that way:

- CCD keeps **one** label file for all 1,500 crash clips
- VIRAT keeps annotations in a **parallel tree**, three files per video
- UCF-Crime has **one** temporal-annotation file for the entire test set, and no
  timings at all for training

Reshaping ~140 GB to fit the flat spec would be work with no payoff, and would
diverge from every published loader for these datasets. So each dataset keeps its
native structure, and slice 6 writes **one small loader per dataset**, each of
which knows that dataset's shape and emits the same thing: a list of
`(video_path, clip_identity, labels)`.

Paths below are relative to the Drive root `MyDrive/omnisight/data/`. The local
mirror under `phase-b/data/` uses **the same relative paths**, so a loader works
unchanged against either.

**The loaders** (OMNI-604) are `omnisight_common.datasets.{ucf_crime,ccd,virat}`; each
emits one manifest entry per clip, written to the `dataset_manifest` table by
`scripts/build_dataset_manifest.py`. They read the annotation files plus
**`<dataset>/video_files.txt`**, one relative path per video file, made from the full
copy on Drive by `scripts/list_dataset_videos.py` (2026-10-08: UCF-Crime 1,950, CCD
4,500, VIRAT 329). The listing is not part of any download; it is what lets the
manifest cover every clip while the mirror holds 38.

**`<dataset>/video_probe.csv`** (UCF-Crime and CCD, OMNI-607): every listed video's fps,
frame count and duration, read by `ffprobe` from the file on Drive by
`scripts/probe_dataset_videos.py`. Lead-up windows are cut against these, never against an
assumed rate or length.

## At a glance

| Dataset | Domain | Role | Videos | Status |
|---|---|---|---|---|
| **UCF-Crime** | surveillance | trains surveillance head; SM-4 false alarms | 1,950 | on Drive, verified |
| **CCD** | traffic | trains traffic head; SM-3 early warning | 4,500 | on Drive, verified |
| **VIRAT** | surveillance | SM-1 search evaluation only | 329 | on Drive, verified |
| SoccerNet | sport | trains sports head; SM-5 transfer | — | slice 10 |
| AI City | traffic | SM-6 multi-camera reports only | — | slice 13 |

---

## UCF-Crime

### Where the videos are

```
ucf_crime/
├── videos/
│   ├── Anomaly-Videos-Part-1/
│   │   ├── Abuse/            50
│   │   ├── Arrest/           50
│   │   ├── Arson/            50
│   │   └── Assault/          50
│   ├── Anomaly-Videos-Part-2/
│   │   ├── Burglary/        100
│   │   ├── Explosion/        50
│   │   └── Fighting/         50
│   ├── Anomaly-Videos-Part-3/
│   │   ├── RoadAccidents/   150
│   │   ├── Robbery/         150
│   │   └── Shooting/         50
│   ├── Anomaly-Videos-Part-4/
│   │   ├── Shoplifting/      50
│   │   ├── Stealing/        100
│   │   └── Vandalism/        50
│   ├── Testing_Normal_Videos_Anomaly/       150
│   ├── Training-Normal-Videos-Part-1/       430
│   ├── Training-Normal-Videos-Part-2/       370
│   └── Normal_Videos_for_Event_Recognition/  50
└── annotations/
    ├── Anomaly_Detection_splits/
    ├── Action_Regnition_splits/
    ├── Anomaly_Train.txt
    ├── Temporal_Anomaly_Annotation_for_Testing_Videos.txt
    ├── ReadMe-Anomaly-Detection.txt
    └── uca/                      UCA, added 2026-10-07 (OMNI-603); not part of the UCF-Crime download
        ├── SOURCE_COMMIT
        ├── txt/   UCFCrime_{Train,Val,Test}.txt
        └── json/  UCFCrime_{Train,Val,Test}.json, revised_en_UCFCrime_Train.json (0 bytes)
```

**950 anomaly videos across 13 classes, 950 normal, plus 50 event-recognition
extras — 1,950 total.** Counts verified after extraction on 2026-09-21.

### Where the labels are

| File | What it holds | Entries |
|---|---|---|
| `annotations/Anomaly_Train.txt` | **the training list** — `Class/filename.mp4`, video-level labels | 1,610 |
| `annotations/Anomaly_Detection_splits/Anomaly_Test.txt` | the test list | 290 |
| `annotations/Temporal_Anomaly_Annotation_for_Testing_Videos.txt` | anomaly start and end frames, **test videos only** | 290 |

1,610 train + 290 test = **1,900**, the complete anomaly-detection set. Every entry
in all three files was checked against disk on 2026-09-21: none missing.

**UCA (UCF-Crime Annotation)** — event times for the training videos (OMNI-603, D-21).
Yuan et al., CVPR 2024, `github.com/Xuange923/Surveillance-Video-Understanding`, folder
`UCF Annotation`, commit `e478cb5b` (2024-04-30, written to `uca/SOURCE_COMMIT`), Apache-2.0,
academic and research use. Downloaded 2026-10-07; every size equals the repository's.

| File | Bytes | Videos | Segments |
|---|---|---|---|
| `uca/json/UCFCrime_Train.json` | 3,091,246 | 1,165 | |
| `uca/json/UCFCrime_Val.json` | 678,678 | 379 | |
| `uca/json/UCFCrime_Test.json` | 842,652 | 310 | |
| `uca/txt/UCFCrime_Train.txt` | 2,164,341 | same videos as the json | one line per segment |
| `uca/txt/UCFCrime_Val.txt` | 454,914 | | |
| `uca/txt/UCFCrime_Test.txt` | 586,652 | | |
| `uca/json/revised_en_UCFCrime_Train.json` | **0** | empty in the repository | |

1,854 videos in all (950 anomaly-class names minus 6, plus 910 normal), none in two UCA
splits, **every one of them in the official lists**. UCA's own Train / Val / Test is **not**
the official split (86 official test anomalies sit in UCA's Train) and is not used; the
official split is. json: `{name: {duration, timestamps: [[start_s, end_s], ...], sentences:
[...]}}`, times in seconds at 0.1 s. txt: `name mm:ss.s mm:ss.s ##sentence`. The
gender-neutral `txt_mask/` variant was not downloaded.

**Coverage:** 804 of the 810 official training anomaly videos are in UCA (missing:
`Assault045`, `Assault046`, `RoadAccidents063`, `RoadAccidents144`, `Robbery139`,
`Vandalism037`); all 140 official test anomalies are.

**UCA describes every event in a video, not only the crime** (people walking in, cars
passing). The crime's segment is picked by a rule (D-21, `scripts/uca_event_times.py`):
the earliest-starting segment whose sentence matches one of the class's word patterns; no
match, no time. **594 of the 810 training anomalies get a time** this way.

**Temporal annotation format** — one line per test video, space-separated:

```
Abuse028_x264.mp4  Abuse  165  240  -1  -1
<filename>         <class> <start1> <end1> <start2> <end2>
```

Up to **two** anomaly intervals per video; `-1` means "no second interval". Values
are **frame numbers at 30 fps**. Normal test videos carry the class `Normal`.

**Not used:** `Action_Regnition_splits/` and `Normal_Videos_for_Event_Recognition/`
belong to a different task in the original paper.

### How a video is matched to its label

- **Identity: the filename**, once `Normal_Videos_for_Event_Recognition/` is
  excluded. With it excluded, all 1,900 remaining filenames are unique
- **Class:** the name of the folder the video sits in — `…/Robbery/Robbery048_x264.mp4`
  is a robbery. The `Anomaly-Videos-Part-N` level is just how the archives were
  split; it carries no meaning
- **Train or test:** match the **filename** against `Anomaly_Train.txt` and
  `Anomaly_Test.txt`. Match on the basename, not the full path — the lists write
  `Class/filename.mp4`, which does not include the `Part-N` level the files
  actually sit under
- **Timing:** for test videos, look the filename up in the temporal annotation
  file. Training videos have none in the download; UCA gives 594 of 810 a time (D-21)

### Traps

- **50 filenames exist twice.** Every file in
  `Normal_Videos_for_Event_Recognition/` has a namesake in
  `Testing_Normal_Videos_Anomaly/`. Exclude the event-recognition folder — it is
  unused anyway — and the collision disappears. A loader that walks all of
  `videos/` without excluding it will silently pick one of each pair
- **`Anomaly_Detection_splits/Anomaly_Train.txt` is a 0-byte file.** The real
  training list is the top-level `annotations/Anomaly_Train.txt`. A loader pointed
  at the split folder gets an empty training set and no error
- **Videos are long and untrimmed, at 30 fps** — a sampled clip ran 91 seconds.
  The opposite of CCD: plenty of footage before each event. Sampling interval
  choices matter far more here
- **Training labels are video-level only** — "a robbery happens somewhere in this
  video". Only the test set is timed (UCA adds times for most training videos, D-21).
  **UCA's own Train / Val / Test is not the official split** — use the official lists. The lead-up windows the forecasting model
  trains on are *derived* in slice 6, by working backward from annotated events
  and hand-checking a sample. They are not in the download
- **The normal footage is split three ways** — `Testing_Normal_Videos_Anomaly/`
  for evaluation, the two `Training-Normal-Videos-Part-*` folders for training.
  SM-4's false-alarm rate is measured on the testing normals; mixing them into
  training would contaminate that number
- **Ignore the `Part-N` folder level** when deriving class. A loader that uses
  the grandparent folder as the class gets `Anomaly-Videos-Part-3` instead of
  `Robbery`

---

## CCD — Car Crash Dataset

### Where the videos are

```
ccd/
└── videos/
    ├── Crash-1500/       000001.mp4 … 001500.mp4     1,500
    ├── Normal/           000001.mp4 … 003000.mp4     3,000
    ├── Crash-1500.txt
    ├── YouTube_download.py
    └── ytb_list.txt
```

Counts verified after extraction on 2026-09-21, and every clip sampled was
exactly **50 frames at 10.0 fps — 5.0 seconds**. All 1,500 label lines match a
crash video on disk. The pre-extracted VGG-16 features
the dataset also offers were deliberately not downloaded — the project uses its
own encoders.

### Where the labels are

`videos/Crash-1500.txt` — one line per crash clip:

| Field | Meaning |
|---|---|
| `vidname` | the clip id, e.g. `000001` |
| `binlabels` | 50 values, one per frame: `1` where the accident is happening |
| `startframe` | where this clip started in the original YouTube video |
| `youtubeID` | source video |
| `timing` | Day or Night |
| `weather` | Normal, Snowy or Rainy |
| `egoinvolve` | whether the recording car is involved |

Normal clips have no label file. Every frame is negative.

### How a video is matched to its label

- **Crash clip:** the line in `Crash-1500.txt` whose `vidname` equals the file's id
- **Normal clip:** no lookup; all 50 frames are label `0`
- **Accident start:** the index of the first `1` in `binlabels`

### Traps

- **The label line cannot be split on commas.** A real line:
  `000001,[0, 0, … 0, 1, 1, … 1],000285,0000,Day,Normal,Yes` — the 50 frame labels
  sit inside brackets, *with* commas. Split on commas and you get 56 fields instead
  of 7. Pull the bracketed block out with a regex first, then split the rest.
  In that line the first `1` is at index 32: the accident starts at **3.2 s**
- **Filenames collide across the two folders.** `000001.mp4` exists in both
  `Crash-1500/` and `Normal/`, and they are different videos. A clip's identity
  is **`(subset, id)`** — never the filename alone. This destroyed the crash set
  once during download, when both archives were unzipped into one folder and the
  normal clips silently overwrote the crashes
- **Every clip is 50 frames at 10 fps — 5 seconds end to end.** That bounds how
  much lead time SM-3 can ever measure, and is why the SM-3 target is set from
  this data in slice 6 rather than fixed in advance. See `docs/decisions.md`,
  D-2
- **The normal clips come from a different source** — BDD100K — than the crashes.
  A model can learn to tell the two sources apart instead of learning what an
  accident looks like. Worth checking in slice 10 whether performance survives on
  crash clips' own pre-accident frames

---

## VIRAT

### Where the videos are

```
virat/
├── videos_original/     VIRAT_S_XXXXXX_*.mp4     329
├── annotations/         VIRAT_S_XXXXXX_*.viratdata.{events,objects,mapping}.txt
├── docs/
├── homographies/
├── software/
└── viratdata.sums.txt
```

329 videos across 11 outdoor scenes. Every file verified against
`viratdata.sums.txt` on 2026-09-20: 1,236 checksums OK, none failed.

**Videos per scene** — very uneven:

| Scene | 0000 | 0001 | 0002 | 0100 | 0101 | 0102 | 0400 | 0401 | 0500 | 0502 | 0503 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Videos | 5 | 2 | 39 | 58 | 46 | 76 | 28 | 17 | 14 | 30 | 14 |

### Where the labels are

`annotations/`, three files per video, sharing its base name:

| Suffix | Holds |
|---|---|
| `.viratdata.events.txt` | the activities — what happened, and between which frames |
| `.viratdata.objects.txt` | the tracked people and vehicles, frame by frame |
| `.viratdata.mapping.txt` | which objects take part in which event |

### How a video is matched to its label

`videos_original/<name>.mp4` ↔ `annotations/<name>.viratdata.*.txt` — same base
name, different folder.

### Traps

- **A missing annotation is an empty folder, not an absent file.** 122 of the 987
  `*.viratdata.*.txt` names in `annotations/` are empty directories left by the
  archive. `os.path.exists()` says yes, `open()` fails with *Is a directory*.
  Check `os.path.isfile()`. An earlier audit here counted names only and wrongly
  reported all 329 as fully annotated
- **54 videos have no events, so they cannot serve SM-1.** Filter to the 275
  with a real `events.txt`. Scene `0102` alone is a quarter of those
- **The three annotation files must be read together.** Events say *what* and
  *when*; objects say *where*; mapping connects them. Reading events alone gives
  an activity without knowing who did it
- **The scene ID is in the filename** — `VIRAT_S_0500xx` is scene `0500`.
- **Scenes are badly unbalanced** — scene `0102` has 76 videos, `0001` has 2. A
  query set drawn at random will be dominated by three car parks. Draw SM-1's
  queries per scene, or the result only proves search works where there happens
  to be the most footage

### Annotation coverage — checked 2026-09-21

| | Videos |
|---|---|
| all three annotation files present | **275 / 329** |
| `objects` only, no events or mapping | 40 |
| no annotation at all | 14 |

**Usable for SM-1: 275 videos**, and every one of the 11 scenes still has some:

| Scene | 0000 | 0001 | 0002 | 0100 | 0101 | 0102 | 0400 | 0401 | 0500 | 0502 | 0503 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| With events | 5 | 2 | 31 | 55 | 26 | 72 | 19 | 16 | 14 | 23 | 12 |

---

## Local mirror

Docker reads local disk, not Drive. `phase-b/data/` holds a **small subset** of each
dataset, in exactly the relative paths above, for development, for the OMNI-318 gating
check, and since OMNI-608 the hand-check sample loaded into the product (copied by
`scripts/copy_dataset_subsets.py`):

| Dataset | Subset |
|---|---|
| UCF-Crime | ~10 anomaly clips across several classes, ~5 from `Testing_Normal_Videos_Anomaly/`, the **30 sampled clips** (OMNI-608), plus the annotations folder (with UCA), `video_files.txt` and `video_probe.csv` |
| CCD | 10 from `Crash-1500/`, 10 from `Normal/`, the **30 sampled crash clips** (OMNI-608), plus `Crash-1500.txt`, `video_files.txt` and `video_probe.csv` |
| VIRAT | 3 videos from different scenes, plus the **full** `annotations/` (987 names: 865 files, 122 empty directories, added 2026-10-08) and `video_files.txt` |

The full sets stay on Drive, where Colab reads them for encoding and training. The
local subset is also what the ten MediaMTX simulator feeds loop.

Nothing under `data/` is ever committed — `.gitignore` keeps only `README.md` and
the `.gitkeep` placeholders.

## Getting footage into the running system

This layout describes how files sit on disk for the loaders. A clip enters the running
product only through the upload path: `POST /datasets/{name}/load` (admin, OMNI-608)
reads each clip from the mirror (mounted read-only into `query` at `/datasets`) and hands
it to `store_video()`, **the same function `POST /videos/upload` runs** (same sniff, same
storage, same probe), then extracts it like any video, one clip at a time. It is a loop
over the manifest, not a separate pipeline. Two things differ: `source = dataset`, and no
retention date, because research data is never deleted (D-25).

What goes in (D-26): only the **60 clips of the hand-check sample**
(`datasets/hand_check/sample.csv`: 30 UCF-Crime, 30 CCD), which the window view plays.
Real users never see dataset footage; training and every model measurement run on Colab,
from Drive. `GET /datasets` reports each one's progress; `dataset_manifest.video_id` links
a clip to its video.
