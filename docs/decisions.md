# Decisions

Choices that change what the system does or how a requirement is measured, each with the
reason and the evidence. Departures from Phase A's Algorithm 1 (§3.5.1, Appendix B.1) are
marked **Deviation**. Measurements themselves are in `results.md`.

| # | Decision | Date | Status |
|---|---|---|---|
| D-1 | CCD replaces DoTA as the traffic dataset | 2026-09-20 | Done |
| D-2 | SM-3 measured as mean time-to-accident, target set from CCD in slice 6 | 2026-09-20 | Target pending (slice 6) |
| D-3 | Files: every decoded frame is gated, no sampling step | 2026-09-23 | Done |
| D-4 | **Deviation:** blur before differencing | 2026-09-23 | Done |
| D-5 | **Addition:** a row for every frame of a file, image files only for admitted frames; live cameras store admitted frames only | 2026-09-23, 09-30 | Done |
| D-6 | Re-gating decodes the source again | 2026-09-23 | Done |
| D-7 | H.264 playback copy made at upload | 2026-09-24 | Done |
| D-8 | Durable queue: persistent messages, confirm per publish, ack after commit | 2026-09-25 | Done |
| D-9 | Live capture gates every frame; the sampling deviation is removed | 2026-09-30 | Done |
| D-10 | Live worker drops frames when downstream is slow, and counts them | 2026-09-26 | Done |
| D-11 | Reconnect with exponential backoff and jitter | 2026-09-26 | Done |
| D-12 | Camera start waits for the stream to open, not for a frame | 2026-09-26 | Done |
| D-13 | Live frames on a queue and a consumer of their own | 2026-10-01 | Done |
| D-14 | The wall's preview: one file per camera, ETag from its write time, served by query | 2026-10-01 | Done |
| D-15 | Camera state from evidence; query, not ingestion, resumes capture | 2026-10-02 | Done |
| D-16 | The rewind buffer is the stored admitted frames, not a separate buffer | 2026-10-02 | Done |
| D-17 | Live needs frames arriving steadily, not one fresh frame (K-13) | 2026-10-02 | Done |
| D-18 | Each camera's worker in a process of its own; one thread per decoder and per OpenCV call | 2026-10-03 | Done |
| D-19 | **NFR-4 revised:** 3 live feeds per machine of this class, sustained over 10 minutes (was 10) | 2026-10-03 | Done |
| D-20 | The live worker's buffer holds about 2 s of frames (`LIVE_QUEUE_SIZE` 10 → 60) | 2026-10-03 | Done |

---

## D-1 · CCD replaces DoTA · 2026-09-20

**Why:** DoTA cannot be obtained. All three Google Drive links in its repository (the 55 GB
frame archive, the split archives, the extras folder) return 404; GitHub issue #43 has
access requests with no reply. The repository's `DoTA_urls.txt` lists the 184 YouTube
sources; every one was probed with `yt-dlp --simulate` on 2026-09-20: **0 alive, 184
dead**, while a control URL resolved on the same machine and version.

**Instead:** CCD (Car Crash Dataset): 1,500 crash clips and 3,000 normal clips as video
files, with per-frame accident labels, built for accident anticipation.

**Knock-on:** CCD replaces DoTA for SM-2, SM-5 and TC-5; `data/dota/` renamed `data/ccd/`;
`datasets.md`, `dataset-layout.md` and the slice plan updated.

## D-2 · SM-3 revised · 2026-09-20

**Why:** Phase A §4.1 set SM-3 at "warnings fire at least 15 seconds before the event". The
DoTA annotations survive in the repository, so its timings could still be measured, across
all 4,677 clips at 10 fps:

| Measure | Value |
|---|---|
| Median clip length | 9.9 s |
| Mean footage before the anomaly | 3.8 s |
| **Median footage before the anomaly** | **3.6 s** |
| 90th percentile | 5.8 s |
| Maximum | 23.0 s |
| Clips with at least 5 s before | 903 of 4,677 (19.3%) |
| Clips with at least 10 s before | 41 of 4,677 (0.9%) |
| **Clips with at least 15 s before** | **8 of 4,677 (0.2%)** |

The 15 s target was unreachable on the dataset Phase A assigned to it, under any model.
Dash-cam accident datasets are trimmed tight around the crash (CCD clips are 5 s, DADA-2000
around 10 s), and published accident anticipation reports time-to-accident in low single
digits.

**Instead:** SM-3 keeps its intent (warn early enough to act) and becomes **mean
time-to-accident (mTTA)** on CCD, the literature's standard metric. The target is set in
slice 6 from CCD's measured pre-event distribution, **before any model is trained**, and
the full distribution is reported with the mean. Phase A's 15 s, this analysis and the
revised target all go in the Phase B book. Taken in week 4, before any forecasting code.

## D-3 · Files: every decoded frame is gated · 2026-09-23

**Why:** the first implementation sampled one frame a second and gated the samples with a
5-sample buffer. Algorithm 1 has no sampling step, and the sampling made every 5 s CCD clip
fall entirely inside the warm-up (0 scored; `results.md`, OMNI-303/304).

**Instead:** every decoded frame is gated; the buffer is time-based, warm-up while
`Buffer.duration < 2Δ`, Δ = `MOTION_STRIDE_S` = 0.5 s; each frame is compared with the
buffered frame nearest `t - Δ`; the admitted frame carries its causal clip
`[t - 2Δ, t]` (`clip_start_s`, `clip_end_s`). Timestamps are compared with a 1e-6 s
epsilon so floating-point error cannot flip a frame back into warm-up.

## D-4 · Deviation: blur before differencing · 2026-09-23

**Why:** without it, two frames of a still scene differ pixel by pixel from sensor noise,
which forces a higher cell threshold (missing real motion) or admits noise as motion.

**What:** `cv2.GaussianBlur`, kernel `MOTION_BLUR_KERNEL` = 21, before the difference.
**Cost:** 0.57 s of 0.83 s scoring on a 300-frame 30 fps clip (OMNI-310). The same 21 px
kernel is a larger share of a 320x240 frame than of 1280x720; effect not measured.

## D-5 · Addition: a row for every frame, files only for admitted frames · 2026-09-23

**Why:** the UI shows discarded frames with their reason and score, so every frame needs a
row; writing a JPEG for every frame is the disk cost sampling used to avoid. Algorithm 1
only forwards admitted frames; the rows for discarded ones are an addition, not a change to
what is admitted.

**Live cameras store admitted frames only** (OMNI-501, 2026-09-30) — a row per frame at
15 fps is about 1.3 million rows per camera per day; the counters keep the gate explainable
(`camera_stats`: `gated`, `admitted_motion`, `admitted_heartbeat`, `discarded`, beside
`captured` and `dropped`). The row for every frame stays for files, where the threshold
slider needs the discarded scores.

**Heartbeat (step 5):** `HEARTBEAT_INTERVAL_S` = 1.0 s, untuned.

## D-6 · Re-gating decodes the source again · 2026-09-23

**Why:** only admitted frames have a JPEG, so re-scoring stored images could only ever
discard more; lowering the threshold could never bring a frame back. That is a correctness
problem, not a speed one. The plan said gating runs from stored frames so the slider is
fast; the build does not do that.

**Cost:** 0.3 s on a 5 s 10 fps clip, 1.4-2.0 s on a 10 s 30 fps clip, growing with length
(open in `known-issues.md`).

## D-7 · H.264 playback copy at upload · 2026-09-24

**Why:** CCD is MPEG-4 Part 2, which browsers do not play. A non-H.264 upload gets a
transcoded copy (`videos.playback_path`) made inside the upload request; the original is
kept for decoding. 0.66 s on a 5 s clip. `/thumbs/` and `/media/` are served by nginx
straight from the volumes so the grid and player do not go through the API; that is also
why they have no token check (open in `known-issues.md`).

## D-8 · Durable queue · 2026-09-25

**What:** persistent messages, each publish waits for the broker's confirm, the consumer
acknowledges only after the database commit. **Why:** NFR-5; it survived a consumer kill and
a broker recreate with 1,800 of 1,800 frames (OMNI-311). **Cost:** 12-15 ms per frame,
because confirms are one at a time; batching them was not built (open in
`known-issues.md`).

## D-9 · Live capture gates every frame · opened 2026-09-26, done 2026-09-30

**Was (a deviation, 2026-09-26 to 09-30):** the live worker read the stream frame by frame
but gated and published only one frame per `LIVE_SAMPLE_INTERVAL_S` = 0.2 s (about 4.2
frames/s from a 15 fps feed), the same kind of sampling D-3 removed from files. The reason
given in the code was that a live stream "cannot afford to" gate every frame. At 0.2 s this
machine sustained 8 feeds, not 10 (OMNI-317).

**Now (OMNI-501):** Algorithm 1 as written, no sampling. Every decoded frame of a live
stream goes through the same `MotionGate` and `process_frame()` as a file, with the same
settings (Δ, grid, threshold, active cells, blur, heartbeat). `LIVE_SAMPLE_INTERVAL_S` is
removed. The deviation is closed; D-4 (blur) is the only one left in the gate.

**Why sampling was the wrong lever:** the load in OMNI-317 came from storing a row for
every sampled frame, not from gating. The live worker now publishes only admitted frames
(D-5), so the gate sees 15 frames/s and the queue sees what it admits.

**Evidence:** `cam05`, two 60 s runs: 15.0 frames/s gated, 0 dropped, 3.1-3.3 frames/s
admitted and stored, ingestion at 36-39% of one core (`results.md`, OMNI-501). One camera
only; ten feeds are measured in OMNI-509.

## D-10 · Live worker drops and counts · 2026-09-26

In-process queue of 10 frames and a broker backlog limit of 2,000 (`LIVE_MAX_BACKLOG`);
beyond either, frames are dropped, counted (`captured = published + dropped + queued`) and
logged as a summary about every 5 s. Memory stays flat instead of growing (OMNI-314). Sizes
untuned. A dropped frame was never accepted, so NFR-5 does not count it.

## D-11 · Reconnect with backoff · 2026-09-26

First retry 1 s, doubling, cap 30 s, jitter 20%, so a dead camera is not retried every
100 ms and ten cameras do not retry in step. Recovery takes up to the cap plus the source's
first keyframe (11.4-20.5 s measured, OMNI-313).

## D-12 · Camera start waits for the stream to open · 2026-09-26

The reachability check before a start waits for the stream to open, not for a frame; the
worker's own first frame confirms it. Waiting for a frame twice made a start take about 17 s
and failed healthy starts, because the simulator's first frame takes 3-5 s. Start is now
about 7 s (OMNI-312).

## D-13 · Live frames on a queue and a consumer of their own · 2026-10-01

**Why:** NFR-1. Live frames and a file's segments shared one queue and one consumer, first in
first out, and an extraction publishes its frames in one burst; a live frame waited behind
it, 6.14 s with a 1,930-frame file (K-1, OMNI-316).

**What (OMNI-502):** live workers publish to `omnisight.segments.live`; file extraction keeps
`omnisight.segments`. A second consumer service, `consumer-live`, runs the same image and
code with `CONSUMER_ROLE=live` and reads the live queue only, not even the camera queue, so
nothing waits in front of a live frame inside the process either. `consumer` keeps the file
queue and the camera status and stats queue. Both queues are declared the same way (durable,
with a dead-letter queue); messages are persistent and confirmed by the same publisher, and
acknowledged after the commit by the same callback (D-8, NFR-5). `LIVE_MAX_BACKLOG` now
measures the live queue only, so a large upload no longer makes live capture drop frames.

**Not chosen:** a priority queue on one consumer (live frames would still share that one
consumer's throughput with the file, and wait behind messages it already holds; not
measured), batched commits (OMNI-510, only if NFR-4 needs it).

## D-14 · The wall's preview · 2026-10-01

**Why:** FR-9. Sixteen tiles must not be sixteen video streams; a tile needs the current
frame about once a second.

**What (OMNI-503):** each live worker writes the frame the stream just delivered, admitted
or not, to `/data/previews/camera-{id}.jpg` (volume `preview_storage`) at most every
`LIVE_PREVIEW_INTERVAL_S` = 0.5 s, longest side at most 640 px, JPEG quality 70. It is
written on the capture thread, before the gate and the queue, so it shows the stream even
when the pipeline drops frames; a failed write is counted and never stops capture. The file
is written to a temporary name and renamed over the old one. The worker removes it when it
ends. `GET /cameras/{id}/preview` in query serves it with the token check (operator or
admin), not through nginx, so K-3 does not grow. `ETag` is the file's write time in
nanoseconds, read from the open file so the tag and the bytes are the same frame;
`If-None-Match` with it gives a 304 and no body; `Cache-Control: no-cache`; `Last-Modified`
lets a client show the frame's age. 404 with the reason when there is no file, or when the
camera's last stats report says it is not being captured (stopped, or silent for
`CAMERA_STATS_STALE_S`), so a file left behind by a killed worker is not served as current.

**Consequence:** the ETag changes on every write, so on a live feed a tile polling once a
second gets a new JPEG every time, still scene or not; a 304 means no new frame was written
(a frozen or lost feed). That is what makes the ETag usable as liveness (OMNI-504, OMNI-507),
and it is why OMNI-506's "mostly 304s on still scenes" does not hold as written (K-12).

## D-15 · Camera state from evidence; query resumes capture · 2026-10-02

**Why:** FR-9, *see immediately which feeds are healthy*, and K-5: after an ingestion
restart nothing captured, while the camera still read `connected`.

**State (OMNI-504):** `GET /cameras/live` works out each camera's state on every request
from ingestion's worker list (`GET /workers`) and the preview's write time (OMNI-503), never
from a stored status. `live`: a worker is reading and the newest frame is at most
`LIVE_STALE_AFTER_S` = 3 s old. `frozen`: a worker is reading, the frame is older.
`offline`: the worker is reconnecting or still connecting, or capture was asked for and
there is no worker, or ingestion cannot be reached. `stopped`: no worker and nobody asked for
one. The existing `cameras.status` is left as it was, the last observed reachability; the
wall does not use it.

**Resume:** `cameras.capture_enabled`, set by a start that worked, cleared by stop, disable
and delete. The ticket says ingestion resumes capture on startup, but ingestion has no
database and so cannot know which cameras were being captured. **Query does it instead**:
every `CAPTURE_RESUME_INTERVAL_S` = 5 s it reads ingestion's worker list and starts every
`capture_enabled` camera without one, through the same call as the Start button, each start
on its own thread; a camera whose start fails is retried after 5, 10, 20, 40 s, then every
60 s. The effect asked for is the same (capture comes back with nobody pressing Start), and
it also covers query restarting and a worker that failed. Ingestion stays a service nothing
but query calls, and that calls nothing but the broker.

**Not chosen:** ingestion reading `cameras` from Postgres on startup (a database dependency
for the service that only touches video); ingestion calling an internal route on query (a
second direction of calls, and a route that would need its own protection).

## D-16 · The rewind buffer is the stored admitted frames · 2026-10-02

**Data model:** there is no separate short-term buffer. A live camera stores every frame the
gate admits (OMNI-501), each as a `segments` row (`video_id` null) with a full JPEG under
`/data/frames/camera-{id}/` and a thumbnail; the heartbeat admits at least one a second on a
still scene, more when something moves. That **is** the last few minutes, on disk, so
`GET /cameras/{id}/buffer?minutes=N` (1-10, default 5, OMNI-505) reads those rows: admitted
frames whose capture time is in the last N minutes, oldest first. No second copy is kept,
and nothing is held in memory.

**What it is:** a flip-book of stills at the gate's pace, not video: about one frame a
second on a still scene, up to the feed's frame rate in constant motion; frames the gate
discarded are not in it.

**Images:** each frame carries `thumb_url` (nginx, `/thumbs/`, no token, as every thumbnail
since OMNI-307, K-3) and `frame_url`, a new route, `GET /cameras/{id}/frames/{segment_id}/image`,
which serves the full frame through query with the token check, so full frames are still
never served by nginx.

**Not covered here:** how long frames are kept (until retention, slice 16; K-8) and the
response size of ten minutes of a busy camera (no paging).

## D-17 · Live needs frames arriving steadily, not one fresh frame · 2026-10-02

**Why:** K-13. With the simulator paused, the worker still received late bursts of old
frames at each 10 s read timeout; each burst rewrote the preview, and by OMNI-504's rule (a
frame in the last 3 s) the camera read `live` for about 3 s, twice. On the wall that is a
frozen picture looking live, which OMNI-507 forbids.

**What (OMNI-507):** the live worker keeps the arrival times of the last
`LIVE_STEADY_WINDOW_S` = 3 s of frames and reports `receiving` in its snapshot: at least two
frames that arrived at least `LIVE_STEADY_MIN_SPAN_S` = 1 s apart. A healthy 15 fps stream
has about forty spread over the window; a burst lands within milliseconds; a 1 fps camera
still counts. `GET /cameras/live` now reads `live` only when the worker is running **and**
receiving **and** the newest frame is at most 3 s old; running otherwise is `frozen`. This
changes D-15's rule for `live`; the other states are unchanged.

**Evidence:** `verify_camera_states.py` with the simulator paused: before, `live` at 10.5 s
and 20.5 s; after, `frozen` at 2.4 s and nothing else until `offline` (`results.md`,
OMNI-507). On the wall, nine tiles went Live, Frozen, Offline with no Live in between.

**Cost:** a camera that has just started or reconnected reads `frozen` for about a second
before `live`, until a second of steady frames has arrived. Not chosen: hysteresis in the
browser (each client would decide on its own, and the API would still say `live`).

## D-18 · Each camera's worker in a process of its own; one thread per decoder and per OpenCV call · 2026-10-03

**Why:** NFR-4 (K-2). OMNI-509 found ten realistic feeds losing most of their frames before
the gate, with ingestion spending about twice the gate's measured work: one Python process
running every camera's threads, and each stream's decoder starting a thread per CPU (196
threads for ten cameras on 8 CPUs).

**What (OMNI-510a):** `LIVE_WORKER_PROCESSES` (on): each camera's `LiveWorker` runs in a child
process (`app/worker_process.py`, started with "spawn"); the parent's registry and routes talk
to it through a pipe, and a child that dies reads as failed and is resumed (D-15).
`LIVE_DECODER_THREADS` = 1: one decoder thread per stream (it keeps up with 1280x720 at 24 fps).
`OPENCV_THREADS` = 1: one thread per OpenCV call, process-wide; the cameras are the
parallelism. **Every frame is still gated** (Algorithm 1, D-9); nothing is skipped.

**Evidence (`results.md`, OMNI-510a):** ten realistic feeds, 3 minutes, without the wall:
gated 80 → 108 frames a second with the decoder cap, 118 with both thread caps, 228 with processes as well (of 282
offered). The 10-minute rerun with the wall open: 157 frames a second gated, worst latency
6.65 s → 3.87 s, all containers at 821% of the 800% Docker has. Still not sustained (K-2).

**Cost:** about 90 MiB more memory per camera (ingestion peaked at 903 MiB with ten); a start
takes a second or two longer while the child process comes up. File extraction (uploads) runs
its blur on one thread now too; not measured.

## D-19 · NFR-4 revised: 3 live feeds per machine of this class · 2026-10-03

**Phase A's NFR-4:** handle 10 or more live video feeds at once without slowing down.

**Why it is revised:** measured unreachable on the development machine with Algorithm 1 as
written (every frame gated, D-9), and the reason measured, as D-1 and D-2 did for DoTA and
SM-3. OMNI-509: 1 feed sustained, 10 realistic feeds losing most of their frames, with
storage idle; the loss was in ingestion. OMNI-510a (D-18) removed most of ingestion's
overhead and 10 feeds still did not fit: the containers needed more than the 800% of CPU
Docker has. The limit is this 4-core machine, not a part of the design.

**The revised requirement:** **3 live feeds per machine of this class** (Intel i7-1165G7, 4
cores / 8 threads; Docker with 8 CPUs and 7.6 GiB; everything on the one machine), every frame
gated, on realistic surveillance footage with about one 1280x720 feed in three, with the camera
wall open and polling, **sustained** under the definition fixed before any NFR-4 run (OMNI-509:
no frame dropped, every frame stored within 5 s, the live queue not growing, every feed `live`
at every second), **over 10 minutes**. More cameras by adding machines: each camera's worker
already runs in a process of its own (D-18) and cameras share nothing in ingestion. That is
the design's answer, **not measured** here.

**How the number was chosen:** from the measurement, not from what passes. The definition was
not changed. A ladder with the wall visible (`results.md`, NFR-4 revision): 4 mixed feeds
sustained over 3 minutes but **not** over 10 (8 frames dropped, 1-4 seconds not `live` per
feed, from hiccups on a machine at 331%); 3 mixed feeds sustained over 10 minutes (0 dropped,
worst 166 ms, always `live`). The 10-minute run decides. Phase A's 10, the measurements and
this revision all go in the Phase B book.

## D-20 · The live worker's buffer holds about 2 s of frames · 2026-10-03

**Why:** the bounded queue between a camera's capture and its gate (OMNI-314) held 10 frames,
sized when only sampled frames went through it (about 2 s at 5 a second). Once every frame was
gated (OMNI-501) it held a third of a second of a 30 fps stream, and a moment's hiccup dropped
frames even with the machine mostly idle: 2-6 mixed feeds dropped 4 to 1,345 frames in 3
minutes at 150-422% CPU.

**What:** `LIVE_QUEUE_SIZE` = 60: 2 s at 30 fps, 2.5 s at 24 fps. Nothing is skipped; a short
hiccup is absorbed instead of dropped. **Cost:** memory, at most about 166 MB per 1280x720
camera while its queue is full. **Evidence:** 4 mixed feeds, 3 minutes, wall hidden: 406
frames dropped with 10, 0 with 60.

## D-21 · UCF-Crime training event times come from UCA, picked by a written rule · 2026-10-07

**Why:** lead-up windows are derived by working backward from each event (Phase A §3.4,
§3.6), and UCF-Crime times its anomalies for the 290 test videos only. The 810 training
anomalies have a class and no time.

**Obtained:** UCA (Yuan et al., CVPR 2024) from the project's GitHub repository, commit
`e478cb5b`, Apache-2.0, academic use. Unlike DoTA (D-1) it downloads: every file, every size
equal to the repository's (`dataset-layout.md`). Its 1,854 video names all match the official
lists; 804 of the 810 training anomalies are covered.

**Where every UCF-Crime event time comes from:**

| Videos | Source | Timed |
|---|---|---|
| 140 official test anomalies | `Temporal_Anomaly_Annotation_for_Testing_Videos.txt` (frame numbers at 30 fps) | 140 |
| 810 official training anomalies | UCA, by the rule below | **594** |
| of which not in UCA | - | 6, no time |
| of which in UCA, no segment matches | - | 210, no time |
| 950 normal videos | no event | - |

**The rule** (the semi-automatic step Phase A names), written into
`scripts/uca_event_times.py` from training-video descriptions only, **before** the agreement
below was computed, and not changed after: each class has a list of word patterns naming
its act ("collided", "crash" for RoadAccidents; "shot", "gun" for Shooting; ...). The event is
the UCA segment with the earliest start whose sentence matches; start and end are that
segment's. **No match, no time:** the video gets no window. The 216 untimed training videos
are listed by the script. Inspected samples miss for wording the rule does not list
("a burst of flames" for an explosion, a fight in a robbery) or because no sentence describes
the act; no bug was found. Widening the patterns could time more, but the agreement would
then have to be measured again on data already seen, so it was left as written.

**Agreement** (`results.md`, OMNI-603): on the 140 official test anomalies, the rule times
110; its start against the official start: **median 3.0 s, mean 11.3 s** apart, 34% within
1 s, 66% within 5 s, 85% within 10 s; UCA tends to start earlier (median -0.8 s).

**What this means for the windows:** a UCA-derived window ends about 3 s from where the
official annotation would put the event (median), with a tail of large misses. Training
windows (UCA) and held-out windows (official) are therefore not equally exact. OMNI-609's
hand check samples both sources and compares them; if UCA windows are wrong noticeably more
often, it goes in `known-issues.md` before slice 9.

**Not used:** UCA's own Train / Val / Test split (it is not the official one; OMNI-605 fixes
the split from the official lists); its descriptions of non-crime events.

## D-22 · The train / validation / held-out split, fixed once · 2026-10-08

**Why:** every measurement from slice 9 on compares models on the same clips. Phase A asks
for "held-out clips" (SM-2) and "a held-out validation split" to set alert thresholds
(§3.5.4.2) but gives no fractions, so they are chosen here, before any window is used.

**The rule** (`omnisight_common.datasets.split`, seed **605**, inputs sorted before every
shuffle):

| Dataset | Held-out | Validation | Train |
|---|---|---|---|
| UCF-Crime | the official 290 test videos, exactly | 15% of the official training list, per class, and within a class per timed / untimed | the rest |
| CCD | 15% of crash clips, by whole source video; 15% of normal clips | the same | the rest |
| VIRAT | evaluation only (SM-1); no training split | - | - |

**Why 15%:** UCF-Crime's official test set is 290 of 1,900, 15%; validation and CCD's two
held-back parts use the same share, so the parts are comparable in size across the two
training datasets. Not tuned against anything.

**Choices inside the rule:**
- UCF-Crime validation is also stratified by timed / untimed, so validation keeps the same
  share of videos that get lead-up windows as train (the ticket asked for class only)
- CCD crash clips are assigned by `youtube_id`, whole groups at a time, in shuffled order,
  to held-out until it reaches 15%, then validation, then train. A group is never split,
  so held-out overshoots by part of one group: 243 crash clips instead of 225. CCD normals
  (BDD100K) have no source-video field and are split per clip
- Split names: `train`, `validation`, `held_out`, `evaluation`

**The split never moves:** the committed `datasets/splits/*.csv` are the split.
`scripts/build_dataset_split.py` rebuilds it and stops, writing nothing, if a rebuilt file
differs from the committed one; a test checks the rebuild byte for byte. `.gitattributes`
keeps `datasets/` byte-exact (no line-ending conversion) so the hashes hold on every
checkout. Counts and hashes: `results.md`, OMNI-605.

## D-23 · The SM-3 target rule, written before CCD's footage was measured · 2026-10-08

**Why:** D-2 sets SM-3's target from CCD's pre-event footage, before any model is trained,
so it cannot be chosen to flatter a result. The rule comes first, then the numbers.

**The rule** (OMNI-606's recommendation, adopted unchanged):

> **SM-3 target = mean time-to-accident (mTTA) of at least half the median pre-event
> footage in CCD's held-out crash clips.**

- *Pre-event footage* of a crash clip = seconds from the clip's first frame to its first
  accident frame = index of the first `1` in `binlabels` / 10 fps (`event_start_s` in the
  manifest)
- *Held-out crash clips* = the 243 crash clips with `split = held_out` (D-22)
- Warning at the very first frame is the ceiling any model can reach; half of the median
  means warning, on average, within the first half of the typical lead-up
- The value is used as computed, not rounded to a friendlier number

**Disclosed:** OMNI-604's sanity check printed the median start over all 1,500 crash clips
(3.6 s) before this entry was written. The rule is the one written in the ticket file when
the sprint was planned, before that; it is not changed here.

**Applied** (`scripts/ccd_pre_event.py`, `results.md` OMNI-606): held-out median pre-event
footage **3.60 s**, so **SM-3 target: mTTA ≥ 1.80 s**. The ceiling (warning at the first
frame) is the held-out mean, 3.68 s.

**What the distribution says:** every CCD crash clip has between 3.0 and 4.9 s before the
accident (none under 1 s); the accident always falls in the last 2 s of the 5 s clip. That
is how CCD was cut, not how long real lead-ups are, so the target measures early warning
within CCD's window, not the 15 s Phase A asked for (D-2).
