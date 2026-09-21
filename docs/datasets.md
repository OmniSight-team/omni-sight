# Datasets — what OmniSight needs, and where to get it

Five datasets. Three train the prediction model, one for each setting. Two have a
single specific job: VIRAT tests search, AI City tests multi-camera reports.

Ordered by when they are first needed.

---

## 1. UCF-Crime — surveillance

**Used for:** SM-2 (prediction accuracy, surveillance domain), SM-4 (false alarm
rate), TC-6 (verification cascade)
**First needed:** slice 6 · **Critical for:** slice 10, slice 12

Real security-camera footage — shops, streets, buildings. 1,900 untrimmed videos,
about 128 hours, 13 anomaly classes, plus a large amount of ordinary uneventful
footage.

**The normal footage is the point.** SM-4 measures whether the system cries wolf,
and you can only measure that on footage where nothing happens.

**Get it:** <https://www.crcv.ucf.edu/projects/real-world/>
Two mirrors: the UNCC Vision Lab link, or the Dropbox folder (lets you pull parts
separately). You want:

- `Anomaly-Videos-Part-1` through `Part-4`
- `Testing_Normal_Videos` and `Training_Normal_Videos`
- `UCF_Crimes-Train-Test-Split`
- `Temporal_Anomaly_Annotation_for_Testing_Videos.txt`

**Size:** no official figure published. Budget well over 100 GB.

**Note:** labels are video-level — *"a robbery happens somewhere in this video"* —
not timed. Slice 6 derives the lead-up windows by working backward from each event
and hand-checking a sample.

---

## 2. CCD — traffic  *(replaces DoTA)*

**Used for:** SM-2 (traffic domain), **SM-3 (early warning time)**, TC-5
**First needed:** slice 6 · **Critical for:** slice 10

Car Crash Dataset — dash-cam footage of real road accidents, built specifically for
accident *anticipation*. 1,500 crash clips plus 3,000 normal clips sampled from
BDD100K, at 10 fps, with per-frame accident labels in `Crash-1500.txt`.

**Get it:** <https://github.com/Cogito2012/CarCrashDataset> — the README links a
Google Drive folder with `videos/` (real `.mp4` files, no YouTube step) and
pre-extracted VGG-16 features you do not need.

The 3,000 normal clips are a bonus: they feed SM-4's false-alarm rate alongside
UCF-Crime's normal footage.

---

### Why DoTA is not used

DoTA was the Phase A choice. It is no longer obtainable, and it would not have
satisfied SM-3 even if it were.

**Unobtainable.** All three of the author's Google Drive links return 404 — the
55 GB frame archive, the split archives, and the extras folder. GitHub issue #43
has several researchers asking for access with no reply. A probe of every one of
the 184 source YouTube URLs in `DoTA_urls.txt` returned **0 alive, 184 dead**.

**And it never fit SM-3.** The DoTA annotations survive in the repo, so the clip
timings can still be analysed. Across all 4,677 clips:

| | |
|---|---|
| median clip length | 9.9 s |
| median footage *before* the anomaly | **3.6 s** |
| 90th percentile | 5.8 s |
| clips with ≥ 15 s before the anomaly | **8 of 4,677 (0.2%)** |

Phase A set SM-3 at "at least 15 seconds before the event begins". Dash-cam
accident datasets are trimmed tight around the crash — CCD's clips are 5 seconds
end to end, DADA-2000's are around 10 — so no available dataset carries 15 seconds
of pre-event footage. Published work in this area reports time-to-accident in the
low single digits.

**The revision.** SM-3 keeps its intent and loses its number. The metric becomes
mean Time-to-Accident, the standard in this literature, and the target is set from
the measured pre-event distribution in slice 6 — *before* any training, so it
cannot be chosen to flatter the result. Both the original target and this analysis
belong in the Phase B book.

---

## 3. VIRAT — surveillance, for search

**Used for:** **SM-1 (semantic search quality)**, TC-4
**First needed:** slice 6 (loaded) · **Critical for:** slice 8

Fixed outdoor cameras watching car parks and building entrances. 329 videos across
11 locations, with tracks for people and vehicles and labels for everyday
activities — a person getting out of a car, carrying a box.

**Why this one for search:** its annotations are precise enough to know which clip
correctly answers a query like *"a person carrying a box"*. That is what makes
recall@5 a real measurement rather than a judgement call.

**Get it:** no account and no form needed — the Kitware portal is public.
[VIRAT Ground Dataset](https://data.kitware.com/#collection/56f56db28d777f753209ba9f/folder/56f57e748d777f753209bed7)

Direct, resumable:

```bash
B=https://data.kitware.com/api/v1/item
curl -L -C - -o annotations-and-docs.zip $B/67914e81f07d3010406a7d21/download
curl -L -C - -o videos-00.zip            $B/67915001f07d3010406a7d24/download   # 14.2 GB
curl -L -C - -o videos-01.zip            $B/67915027f07d3010406a7d27/download   #  1.5 GB
curl -L -C - -o videos-04.zip            $B/6791519ff07d3010406a7d2a/download   # 14.8 GB
curl -L -C - -o videos-05.zip            $B/67915258f07d3010406a7d2d/download   #  7.2 GB
curl -L -o viratdata.sums.txt            $B/67914d4ff07d3010406a7d1e/download
```

**Size: 37.6 GB.** `-C -` resumes a broken download. Verify against the sums file.

The `videos_original` folder on the portal has individual `.mp4` files (0.6–1.5 GB
each) if you only want a handful.

There is a VIRAT Video Dataset Protection Agreement referenced on
<https://viratdata.org/> — read it, though nothing blocks the download.

---

## 4. SoccerNet — sport

**Used for:** SM-2 (sports domain), **SM-5 (cross-domain transfer)**, TC-5
**First needed:** slice 10 · **Critical for:** slice 11

Broadcast football matches, about 500 of them, with precise timings for goals,
fouls and cards.

**Why sport:** it is the third setting, and it looks nothing like the other two. A
build-up to a goal has no visual resemblance to a build-up to a crash. That is what
makes SM-5 — one backbone transferring across domains — a real claim.

**Get it:** the form is done and the password is in hand. Download with their
package:

```bash
pip install SoccerNet
```

**Use the low-resolution (224p) version.** The full-resolution broadcast video runs
to terabytes; the pre-processed version is a fraction of that and is enough for
training a temporal model.

---

## 5. AI City Challenge — multi-camera

**Used for:** **SM-6 (forensic report)**, TC-7
**First needed:** slice 13 · **Critical for:** slice 14

Road incidents filmed by several synchronised cameras at once.

**The only dataset where more than one camera sees the same event.** Without it
there is no way to test combining footage from multiple cameras into one incident
report — which is SM-6, and a headline capability of the product.

**Get it:** <https://www.aicitychallenge.org/> — registration on their site. The
request form that used to be required is no longer needed.

**Needed by:** late November. Not urgent, but confirm access well before then — it
is the only remaining item whose timing is not fully under your control.

---

## How they fit together

| Dataset | Domain | Job |
|---|---|---|
| UCF-Crime | surveillance | trains the surveillance head; measures false alarms |
| CCD | traffic | trains the traffic head; carries the early-warning timing |
| SoccerNet | sport | trains the sports head; proves cross-domain transfer |
| VIRAT | surveillance | **tests search**, nothing else |
| AI City | traffic | **tests multi-camera reports**, nothing else |

Three settings that look nothing like each other, which is the point: it is what
stops the prediction model from being tuned to one kind of scene.

---

## Disk

| Dataset | Approximate |
|---|---|
| UCF-Crime | 100 GB+ |
| CCD | tens of GB |
| VIRAT | 37.6 GB |
| SoccerNet (224p) | tens of GB |
| AI City | not yet confirmed |

**Budget 250 GB and do not put it on the system drive.** None of it is ever
committed — `.gitignore` already covers `data/`.

---

## Folder layout

See **`docs/dataset-layout.md`** — it is the single source of truth for how these
sit on disk and in Drive, and the slice 6 loaders are written against it.

One folder per dataset under `data/`, with each clip's annotation beside its video
sharing the same base filename.
