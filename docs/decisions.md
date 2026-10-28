# Decisions

Choices that change what the system does or how a requirement is measured, each with the
reason and the evidence. Departures from Phase A's Algorithm 1 (§3.5.1, Appendix B.1) are
marked **Deviation**. Measurements themselves are in `results.md`.

| # | Decision | Date | Status |
|---|---|---|---|
| D-1 | CCD replaces DoTA as the traffic dataset | 2026-09-20 | Done |
| D-2 | SM-3 measured as mean time-to-accident, target set from CCD in slice 6 | 2026-09-20 | Done (target 1.80 s, D-23) |
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
| D-21 | UCF-Crime training event times come from UCA, picked by a written rule | 2026-10-07 | Done |
| D-22 | The train / validation / held-out split, fixed once | 2026-10-08 | Done |
| D-23 | The SM-3 target rule, written before CCD's footage was measured | 2026-10-08 | Done (mTTA ≥ 1.80 s) |
| D-24 | How lead-up windows are cut, and when an event gets none | 2026-10-09 | Done |
| D-25 | Dataset footage enters through the upload function | 2026-10-09 | Done |
| D-26 | Model measurements on Colab; the product holds only the hand-check sample (and, since OMNI-702, a 9-video VIRAT demo sample) | 2026-10-09, 10-18 | Done |
| D-27 | The hand-check criterion, written before any window was checked | 2026-10-10 | Done |
| D-28 | The dashboard's rollup is kept by triggers on `segments` | 2026-10-11 | Done |
| D-29 | **Deviation:** `frame_vectors` point id = segment id (B.2 line 4); `captured_at` absolute for every source; payload times to the microsecond | 2026-10-19 | Done |
| D-30 | The SigLIP 2 checkpoint (`google/siglip2-so400m-patch14-384` @ `e8e48729`), float32, lowercased text padded to 64 tokens | 2026-10-19 | Done |
| D-31 | The encoder's speed is measured on a GPU (Colab); the laptop proves it works; NFR-1, NFR-2 = local stack times + GPU encode time | 2026-10-19 | Done |
| D-32 | The laptop loads only InternVideo2's text side; clip vectors of the product's footage are made on Colab | 2026-10-28 | Done |
| D-33 | **Deviation:** the InternVideo2 checkpoint (`OpenGVLab/InternVideo2_CLIP_S` @ `1f9fca13`), 512-D not 768, float32, its model code copied into the repo | 2026-10-28 | Done |
| D-34 | Embed jobs: a frame's domain, and the model pin shared by every service | 2026-10-28 | Done |
| D-35 | OMNI-705 is proved on one video; the archive is not backfilled | 2026-10-28 | Done |
| D-36 | Search is open to operators, analysts and admins (Phase A), not operators and admins only (the ticket) | 2026-10-28 | Done |

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

**2026-10-16 (OMNI-613): the one-operation grid tried; the number stays 3.** The cell means
computed in one array operation (identical scores, Algorithm 1 unchanged) make the gate's step
1.4-1.8 ms a frame cheaper. With the wall open, 5 feeds now hold for 3 minutes (they did not),
and 4 feeds over 10 minutes drop nothing at 229% (8 dropped at 331% before), but one feed read
not `live` for 2 seconds, so 4 is still not sustained under the unchanged definition; 5 over
10 minutes fails the same way. `results.md`, OMNI-613. Every software candidate in K-2 has now
been tried; what is left is hardware.

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

## D-24 · How lead-up windows are cut, and when an event gets none · 2026-10-09

**Why:** Phase A derives lead-up windows "by working backward from each known event"
(§3.4, §3.6) and runs the predictor on "30s and 60s" windows (TC-5), but does not say what
happens at the edges: an event near the start of its video, a video with two events, a
dataset whose clips are 5 s long, or where negative windows come from. The rules are fixed
here, in `omnisight_common.datasets.windows`, before the windows are used.

**The rules** (seed **607**, inputs sorted before any random draw):

| Case | Rule |
|---|---|
| Positive, UCF-Crime | `[event_start - L, event_start)` for L = 30 s and 60 s. Half-open: a window never contains any part of the event |
| Less than L before the event | the window starts at 0 instead, keeps its nominal L, and is flagged `shortened` |
| Second interval (16 UCF-Crime test videos) | no window: its lead-up runs through the first event. Skipped and counted, per L |
| Event at 0 s | no window (no footage before it). Skipped and counted |
| Event after the probed end of its video | no window. Skipped and counted |
| Anomaly with no time (216 UCF-Crime training videos, D-21) | no window. Recorded as skipped, per L, so every anomaly is accounted for |
| Positive, CCD | one window `[0, accident_start)`, as long as the footage is (3.0-4.9 s, D-23). Its nominal length is empty: no 30 s or 60 s window exists on CCD and none is made |
| Negative, UCF-Crime | one window per normal video and L, start drawn uniformly from `[0, duration - L]` (floored to the millisecond); a video shorter than L gives `[0, duration)`, flagged `shortened` |
| Negative, CCD | one window per normal clip; its length drawn from the crash windows of the **same split**, so negatives have the positives' length distribution; position drawn as above |
| Split | every window takes its clip's split from `datasets/splits/` (D-22) |

**Duration and fps from each video's own probe, never assumed.** The full videos are on
Drive; `scripts/probe_dataset_videos.py` runs `ffprobe` on every UCF-Crime and CCD file in
Colab and writes `video_probe.csv` (fps, frame count, duration). The derivation stops if any
video has no probe. UCF-Crime's official frame numbers stay converted at 30 fps (its readme);
every video not at 30 fps (CCD: 10 fps) is listed in `results.md`, not silently re-timed.

**Shortened windows are kept, not dropped.** A positive window of 1 s before an event is
still lead-up footage; dropping it would remove most UCF-Crime events whose annotated start
sits in the first seconds. The flag and the real `length_s` travel with every window, so
training can filter by length without the windows being re-derived.

**Fixed once, like the split:** `scripts/build_event_windows.py` exports
`datasets/windows/{dataset}.csv` and `{dataset}_skipped.csv` and refuses to overwrite an
existing file with different content; `event_windows` rows are inserted, never replaced, so
OMNI-609's hand-check verdicts survive a rerun. Counts and hashes: `results.md`, OMNI-607.

**Disclosed:** before this entry was written, the build script was smoke-tested once with
stand-in durations (UCA's, 600 s otherwise) to check that it runs end to end; that output
was deleted. The rules above were in the code before that run and were not changed after it.

## D-25 · Dataset footage enters through the upload function · 2026-10-09

**Why:** the sprint rule is that dataset footage is ordinary footage: no back door into the
product.

**How:**
- `POST /videos/upload`'s body became `store_video()` (sniff, stream to storage, row,
  probe), unchanged in behaviour; `POST /datasets/{name}/load` calls the same function for
  each clip, read from the mirror mounted read-only into `query` at `/datasets`, then
  extracts it like any video, one clip at a time. Only two things differ: `source =
  dataset`, and `retention_until` is NULL, never a date. `scripts/backfill_retention.py`
  now skips dataset rows, which it would otherwise have given a date
- Resumable without a queue of its own: a clip is done when its video is `ready` with a
  finished extraction; each call takes the clips not done yet. The manifest link is written
  in the video row's own transaction, so a restart never stores a clip twice
- Which clips: D-26

**Tests on their own database** (K-18): the query tests now run on `omnisight_test`,
created and migrated by their `conftest.py`, so `uv run pytest` can never delete footage
loaded into the stack.

**Considered and reverted the same day:** for the full load the ticket first planned
(5,065 clips), the upload limit was raised to 2,048 MB (19 files over 500 MB) and the
extract timeout to 2,400 s (two hour-long videos). D-26 dropped the full load, so both are
back to 500 MB and 900 s: no change to the product without a reason that still holds.

## D-26 · Model measurements on Colab; the product holds only the hand-check sample · 2026-10-09

**Why:** OMNI-608 planned to load CCD (4,500), VIRAT (275) and UCF-Crime held-out (290)
into the product, so models could later be measured inside it. Measured first (`results.md`,
OMNI-608): 50 GB, 2.13M frames, **about 20-23 h of extraction on this machine** with the
simulator stopped, 27-34 h with it running. But real users never see dataset footage: they
connect cameras and upload files. The system is aimed at organisations that already run
GPUs, and the model measurements (SM-1 to SM-4: embeddings, search quality, forecasting)
need one; this laptop has none. Running them through a CPU-only local stack would measure
the laptop, not the method.

**Decision (Ahmad, 2026-10-09):**
- **Model measurements run on Colab** (GPU), from Drive, with the same code
  (`services/common`) and the committed split, windows and sample files. The "real running
  stack" rule in `CLAUDE.md` applies to system measurements (latency, throughput, data loss,
  storage, the dashboard), not to model accuracy
- **The product holds only what it needs to show:** the 60 clips of OMNI-609's hand-check
  sample (30 UCF-Crime: 15 official, 15 UCA, every class; 30 CCD), drawn once with seed 609
  into `datasets/hand_check/sample.csv`, loaded through D-25's path. The window view plays
  them
- VIRAT is not loaded; SM-1's search evaluation runs on Colab

**Not a Phase A deviation:** Phase A does not say where the success metrics are computed.
It is a change to this sprint's plan (OMNI-608's "what goes in").

**What it costs:** the dashboard's "real footage volumes" are the sample's (60 clips), not
5,065. The CCD retention on all 4,500 clips (K-4) is a property of Algorithm 1, not of the
stack, so it moves to a Colab run of the same gate code.

**Amended 2026-10-18 (OMNI-702): the product also holds a VIRAT demo sample.** Search
(slice 7) needs real surveillance footage with people and vehicles to be demonstrated at
all, and none of the 60 hand-check clips is VIRAT, Phase A's search dataset. So the
product also holds **one VIRAT video per scene**, drawn once with seed 702 from the 275
videos with events into `datasets/demo/virat_sample.csv`
(`omnisight_common.datasets.demo`, `scripts/build_virat_demo_sample.py`) and loaded through
D-25's path (`POST /datasets/virat/load`). SM-1 still runs on Colab over all 275.
- **9 scenes, not 11.** Only videos the product accepts are eligible: a file over the
  500 MB upload limit would be refused like any upload. Scenes `0000` (5 videos) and `0001`
  (2) have none under it (642-1,608 MB, 9,075-29,580 frames each, also far past the 900 s
  extraction timeout on this machine), so they are left out before the draw. The limits are
  not raised for demo footage: D-25 tried that for the full load and reverted it the same
  day. Decided with Ahmad. Those two scenes are searchable on Colab only
- A first draw without the size rule (not committed) picked 1,456 MB and 1,111 MB videos for
  scenes 0000 and 0001; the rule was added and the sample redrawn, which also changes the
  other scenes' picks
- The 9 videos: 1,120.6 MB, 23,057 frames in all (OMNI-608's probe), the largest 490.6 MB

## D-27 · The hand-check criterion, written before any window was checked · 2026-10-10

**Why:** OMNI-609 checks 60 derived lead-up windows by eye (Phase A: "check a sample by
hand"). The criterion is fixed first, so the agreement rate cannot drift to fit what is seen.

**The criterion** (the ticket's, adopted unchanged):

> **A window is correct when it ends where the event visibly begins (within 1.5 s) and shows
> none of the event.**

- *Where the event visibly begins:* the first moment the annotated event (the clip's class:
  the crash, the robbery, the fight ...) can be seen happening, judged by watching, not by
  the annotation
- *The act itself, not who will do it* (added 2026-10-10 during the check, at Arrest011,
  before judging it): the event begins at the first moment of the act, not when the people
  who will do it appear. Arrest: the first act of restraint, a physical one (grab, push
  down) or holding the person at gunpoint (added at Arrest030), not police standing nearby;
  restraint by guards or bystanders counts when they then hold the person for the police; robbery: the threat or the grab, not the robber walking in;
  fighting: the first blow; road accident: the impact; burglary: the first act of breaking
  in (forcing a door or window, breaking glass, climbing in), or, when the entry is out of
  view, the first moment the intruder is inside or starts taking things (added at Burglary); shooting:
  the first shot, pointing the gun being lead-up (added at Shooting039); robbery: the first
  threat or grab, a gun pointed at the victim included (Robbery006); stealing: the first
  act of taking (grabbing the item, breaking into or opening the vehicle, starting to carry or
  drive it off), looking around being lead-up; shoplifting: the moment the item is hidden
  (pocket, bag, clothes), not picking it up to look at it (added at Stealing). What comes before the act is lead-up,
  which is what a window should contain
- *Within 1.5 s:* the window's end may sit up to 1.5 s before or after that moment. The
  ticket said 1 s; widened to 1.5 s by Ahmad on 2026-10-10, **after 2 of the 60 windows had
  been checked** (Abuse004, Abuse028, both Verified under 1 s; a wider tolerance can only turn
  a Wrong into a correct, so both verdicts stand). Why: judging the start of an event by eye to under a
  second is not reliable, and 1.5 s is still well inside UCA's median 3.0 s distance from the
  official times (D-21), so the check can still tell a good time from a poor one
- *Shows none of the event:* if the event is visibly under way more than 1.5 s before the
  window ends, the window is wrong, whatever the reason
- **Wrong** is recorded with a short reason, one of: *ends too late* (the window contains the
  event), *ends too early* (more than 1.5 s of quiet footage between the window's end and the
  event), *wrong event* (the annotated moment is not the clip's class at all), or *cannot
  tell* (the footage does not show it clearly), plus free text
- **Which window:** one per sampled clip. On UCF-Crime the 30 s and 60 s windows of a clip end
  at the same event start, so the 30 s one is checked; on CCD the clip's only window. The
  verdict is stored on the checked window

**The sample:** `datasets/hand_check/sample.csv` (D-26), drawn before this entry: 30 UCF-Crime
(15 official, 15 UCA), 30 CCD.

## D-28 · The dashboard's rollup is kept by triggers on `segments` · 2026-10-11

**Why:** OMNI-610 asks for an hourly rollup "updated by the consumer in the same
transaction as the insert, so the counts can never drift from the rows" (NFR-5). Inserting
is not the only way `segments` changes: a failed or replaced extraction deletes a video's
rows (`extraction.py`), a re-gate rewrites `admitted` and the files in place (OMNI-306), a
deleted video takes its rows by cascade. Counting in the consumer's Python alone would drift
the first time any of those ran.

**What was built:**

- `segment_hourly (hour, source_type, segments, admitted, file_bytes)`, one row per UTC hour
  of the rows' `created_at` and per source (`upload`, `camera`; dataset footage is an upload)
- Four statement-level triggers on `segments` (insert, update, delete, truncate). Each
  statement adds one aggregated upsert per hour and source it touched, from its transition
  table, so it runs inside the statement's own transaction: the consumer's insert, the
  extraction's delete, the re-gate's update and the cascade each change the rollup in the
  same commit as the rows, or not at all. Application code never writes the rollup
- The rollup reflects the rows that exist: deleting a video takes its frames out of the hour
  they were stored in. The activity chart is "what is held, by when it was stored", not a
  log of everything ever stored
- `segments.file_bytes`: the bytes of the frame and thumbnail JPEGs a row wrote, measured by
  ingestion right after writing them and carried on the message (`SegmentMessage.file_bytes`,
  default 0 so a message queued before it still parses). The consumer cannot see the frame
  volumes, and walking the disk on every dashboard load is what the rollup is there to avoid
- The migration counts the rows already in the table; `scripts/backfill_dashboard_rollup.py`
  fills `file_bytes` on old rows from the disk and rebuilds the rollup, rerunnable

**Not a Phase A deviation:** Phase A does not say how FR-9's figures are computed. It is a
choice of mechanism inside the ticket: the update still happens in the consumer's
transaction, through the database rather than the consumer's code.

**What it costs:** every insert into `segments` runs one extra upsert. Not measured against
the consumer's throughput (OMNI-610 context). `storage_gb` counts only files that have a row:
files left on disk with no row are invisible to it (K-21).

## D-29 · `frame_vectors`: point id = segment id, an absolute `captured_at`, times to the microsecond · 2026-10-19

**Deviation:** Appendix B.2 line 4 sets the identifier shared by a frame's entries to
`frame_id = hash(camera_id, timestamp)`. An uploaded file has no camera, so two files would
give their frames at the same second the same id, and one would overwrite the other. **The
point id is the segment id** (`segments.id`): unique for every source, and the id slice 8's
`clip_vectors` will use for the same frame, which is what line 4's identifier is for
(matching a frame entry to its clip entry). It also makes a write idempotent: a redelivered
message upserts the same point instead of adding a second (shown in TC-3, OMNI-703).

**`captured_at` for every source.** The payload carries an absolute time so one filter
covers cameras and files: a live frame's capture time (its `timestamp_s` is Unix time); for
an uploaded file, which carries no wall-clock time, the upload time (`videos.created_at`)
plus `timestamp_s`. RFC 3339 in UTC, to the microsecond, under a datetime payload index.
A file's `captured_at` is therefore when it was uploaded, not when it was filmed.

**`timestamp_s` in the payload is rounded to the microsecond.** Qdrant 1.19.1 did not read
back exactly a float needing 17 significant digits: in TC-3's first run, 66 of 1,000 upload
timestamps (frame index over 23.976 fps) came back one unit in the last place off
(`results.md`, OMNI-703). Rounded to 6 decimals, a timestamp (up to Unix time) has at most
16 digits, an integer below 2^53 over a power of ten, and round-trips exactly. `segments`
keeps the full value; the payload differs from it by under half a microsecond.

**Where:** `services/common/omnisight_common/frame_vectors.py`; Qdrant `v1.19.1` in
`docker-compose.yml`, no host port, `infra/qdrant/production.yaml`.

## D-30 · The SigLIP 2 checkpoint, pinned, and how it runs · 2026-10-19

**The model:** `google/siglip2-so400m-patch14-384` at revision
**`e8e487298228002f3d8a82e0cd5c8ea9c567f57f`** (Hugging Face, last modified 2025-02-21),
1152-D image and text embeddings, Phase A's dimension. Pinned in `ai_workers` settings
(`frame_model_id`, `frame_model_revision`); the same revision runs locally and on Colab.
Changing either is a new model: stored vectors would no longer compare with new ones.

**How it runs (`services/ai_workers/app/encoder.py`):**

- `AutoModel` / `AutoProcessor`, **float32** on both machines, so local and Colab compute the
  same numbers. The embedding is `get_image_features(...).pooler_output` /
  `get_text_features(...).pooler_output` (transformers 5.20.1 returns an output object, not
  a tensor), then L2-normalised; 1152 dimensions and unit length asserted on every batch
- Frames are read from the stored full-frame JPEG (`frame_path`) and resized by the
  checkpoint's own processor (384x384, bilinear, mean and std 0.5)
- **Text:** lowercased and padded to `max_length=64` with truncation, as SigLIP 2 was trained.
  The processor does neither by default in this version (a test shows it gives a shorter
  sequence), so the encoder does both explicitly; pinned by `test_encoder.py`
- **CPU wheels:** PyTorch comes from its CPU-only index for `ai_workers` (root
  `pyproject.toml`), so the image carries no CUDA libraries (1.59 GB). Colab uses its own
  GPU build of PyTorch with the same encoder code
- **The checkpoint** sits in `models/pretrained/siglip2-so400m-patch14-384/` (never
  committed), downloaded at the pinned revision if missing; a `REVISION` file says which
  revision the folder holds, and a folder with another one is brought to the pinned one
- **Warm-up at startup:** the weights are memory-mapped and read on first use. Without a
  warm-up the first text query took 31.5 s; the service now encodes one blank image and one
  text before `/health` reports it loaded

**Not a Phase A deviation:** Phase A names SigLIP 2 and 1152 dimensions; the checkpoint,
precision and text preparation are choices inside that.

## D-31 · The encoder's speed is measured on a GPU (Colab); the laptop proves it works · 2026-10-19

**Why:** Phase A puts the AI Workers on a GPU (§3.3.2: *"SigLIP 2 and InternVideo2 on GPU,
horizontally scalable"*). This laptop has none: on its CPU SigLIP 2 takes about 9 s per frame
(`results.md`, OMNI-704), slower than one camera's admitted frames arrive and longer than
NFR-1's 5 s on its own. That number describes a machine Phase A did not design for, not the
system. **Ahmad's decision.**

**What changes:**

- **On the laptop:** the encoder is checked for correctness only (TC-2: every admitted frame
  gets a 1152-D unit vector, no error). Slow is acceptable there. Laptop CPU timings are kept
  in `results.md` as "dev machine, no GPU", for information, never pass/fail
- **On Colab's GPU:** the encoder's cost per frame (batch 1 and 8) and per query is
  measured with the same code (`services/ai_workers/app/encoder.py`) and the same pinned
  checkpoint (D-30)
- **NFR-1 and NFR-2** (OMNI-708, OMNI-709): judged as the stack's own times measured
  locally (capture, gate, queue, store, Qdrant, the API) plus the encode time measured on
  the GPU, reported as a combined figure and labelled so. The laptop's end-to-end times with
  CPU encoding are reported too, as information

**GPU used (2026-10-28, Ahmad):** Colab's A100 is often not free and the runtime falls back
to an **L4**. The timings are taken on whichever GPU the runtime gets, named in the result
(OMNI-706 ran on an L4). An L4 is slower than an A100, so an L4 figure is an upper bound.

**Revises:** OMNI-704's "measure on this machine" for the encoder's speed, and the sprint
table's "NFR-1 and NFR-2 are system measurements" (D-26) for the encoding step only.
The GPU measurement is done with OMNI-710 (the Colab ticket), on the same notebook run.

## D-32 · The laptop loads only InternVideo2's text side · 2026-10-28

**Ahmad's decision** (written in the sprint's ticket file on Wed 28, recorded here with
OMNI-706). InternVideo2's video side does not belong on the laptop: with SigLIP 2 already
taking about 4.2 GiB of Docker's 7.6 GiB, and SigLIP 2 already at 9 s a frame on this CPU,
a second video model would not fit beside it and would be slower still. So:

- **Clip vectors** of the product's footage (the 9 VIRAT videos, the 60 hand-check clips)
  are encoded on Colab and imported from Drive (OMNI-708, OMNI-710)
- **On the laptop,** a new upload or a camera gets a frame vector only; fused search ranks
  it by the frame list alone (Algorithm 3 already gives a missing rank the value ∞)
- **On a GPU machine** the same `ai_workers` code also encodes clips (`clip_encoder.py`,
  `video=True`)
- **ai_workers here** loads `ClipTextEncoder(video=False)`: the text tower's weights only

**Measured** (`results.md`, OMNI-706): with both text encoders loaded, ai_workers' process
is 3.84 GiB after 400 queries, 4.17 GiB at peak; InternVideo2's text takes 131 ms a query
(median), SigLIP 2's 1,097 ms.

**Not a Phase A deviation:** Phase A puts the AI Workers on a GPU (§3.3.2); this is where
the laptop stands in for one.

## D-33 · The InternVideo2 checkpoint, pinned, and how it runs · 2026-10-28

**The model:** `OpenGVLab/InternVideo2_CLIP_S` at revision
**`1f9fca1389fd883defc652634d95a21121c85a8c`** (Hugging Face, last modified 2025-05-22,
Apache-2.0). Pinned in `CommonSettings` (`clip_model_id`, `clip_model_revision`), like
SigLIP 2 (D-30, D-34): clip vectors are made on Colab and searched here with the text
side, so both sides must be this exact revision.

**Chosen by the ticket's three checks, not by name** (OpenGVLab's InternVideo2 checkpoints
on Hugging Face, 2026-10-28):

| Checkpoint | 8 frames at 224 | Dimension | Text side on the laptop | Result |
|---|---|---|---|---|
| `InternVideo2-Stage2_1B-224p-f4` | No: 4 frames (`f4`); gated, one 2.8 GB `.pt` | Not read (gated) | Not read (gated) | Fails the first check |
| `InternVideo2-CLIP-1B-224p-f8` | Yes (`f8`) | Not read (gated) | Not checkable: gated, and the repository holds only a 14 MB `1B_clip.pth`, far too small to be the model, so the rest comes from elsewhere | Not one usable checkpoint |
| `InternVideo2-Stage2_6B`, `InternVideo2-CLIP-6B-224p-f8` | — | — | A 6B model | Not checked further: too large |
| `InternVideo2_distillation_models` | Yes (`f8`) | — | `stage1/`: video only, no text side; `clip/`: 2-9 MB files, heads only | No text side |
| **`InternVideo2_CLIP_S`** | **Yes** (config `num_frames` 8, `img_size` 224; run) | **512** (run) | **63M parameters, 131 ms a query beside SigLIP 2** | **Passes all three** |

Its video side is a 24-layer InternVideo2 ViT (1024 wide, patch 14, 309M parameters); its
text side is MobileCLIP's text transformer (63M). It is a small InternVideo2 retrieval
model, not the 1B or 6B the paper reports.

**Deviation (dimension):** Phase A writes a 768-D clip embedding (Appendix B.2, line 3).
This checkpoint's video features are 768-D, but the space where video and text meet is
512-D (`vision_align` and the text projection), and only that space can be searched with a
query. So `clip_vectors` is 512-D: the collection follows the model, as the ticket says.
Confirmed by running it (one VIRAT clip and texts: 512-D, finite, norm 1.0).

**How it runs (`services/ai_workers/app/clip_encoder.py`):**

- **The model code is copied into the repo** (`services/ai_workers/app/internvideo2/`),
  not run from the download. The checkpoint ships its code as `.py` files beside the
  weights; running those means executing files downloaded from the internet (Claude Code's
  permission check refused it), they could change upstream, and they import `flash_attn`,
  which cannot be installed without CUDA. The copy is inference only: the flash-attention
  and fused paths (the config turns them off), training-only parts and the image-only path
  removed, module and parameter names unchanged. Only `config.json` and `model.safetensors`
  are downloaded; every weight loads with every key matched (`strict=True`), and a test
  checks no part of the checkpoint is left out (only the training temperature is unused)
- **float32 on both machines** (the weights are stored half in float16), as D-30
- **Frames:** `uniform_indices` is Algorithm 2's `uniform_subsample`: 8 frames, the middle
  of each eighth of the span, as the checkpoint's own "middle" sampling; a span under 8
  frames repeats its last frame. Each frame resized to 224 x 224 (bicubic, aspect ratio not
  kept), scaled to [0, 1], ImageNet mean and std: the checkpoint's own transform
- **Text:** open_clip's ViT-B-16 tokenizer, the one the checkpoint was trained with; it
  lowercases and cleans the text itself; 77 tokens. Nothing added (a test shows upper and
  lower case give the same vector)
- **The checkpoint** sits in `models/pretrained/internvideo2-clip-s/` (never committed;
  746 MB) and on Colab in `MyDrive/omnisight/models/pretrained/internvideo2-clip-s/`,
  downloaded at the pinned revision if missing, with a `REVISION` file (D-30's
  `ensure_checkpoint`)
- **Licences:** InternVideo2's code Apache-2.0 (OpenGVLab); the text encoder Copyright
  Apple Inc., MobileCLIP's licence; both named in the copied files

**Checked on Colab** (`notebooks/encoders_gpu.ipynb`, NVIDIA L4; `results.md`, OMNI-706):
the same vectors as on the laptop's CPU (one clip, similarity 0.0967 on both). **The motion
check is weak:** 2 of 10 clips rank their own caption first, 4 of 10 a caption of their own
type, and opening and closing a trunk are not told apart. Recorded as measured. The
checkpoint is kept: it is the only one that passes the ticket's three checks, and search
quality is judged by SM-1 (OMNI-713) with both streams fused, not by this 10-clip check.

## D-34 · Embed jobs: a frame's domain, and the model pin shared by every service · 2026-10-28

**A frame's domain** (`FramePayload.domain`, OMNI-703) is not stored on a segment. The
embed job (OMNI-705) takes it from, in order: the live frame's camera, the video's camera,
the dataset the video was loaded from (`dataset_manifest.domain`), and otherwise
**`surveillance`**. A plain upload with no camera has no domain recorded anywhere; Phase A's
main domain is surveillance. If uploads get a domain of their own later, the job takes it
from there instead.

**The pinned checkpoint moved to `CommonSettings`** (`frame_model_id`,
`frame_model_revision`; values unchanged from D-30). ai_workers writes vectors of that model
and query counts (and will search) only vectors of that model, so both read the same pin.

**`frames_embedded` counts frames, not points:** an admitted frame counts when a point of
the pinned model has its segment id. A point whose segment no longer exists (K-24) is not
counted.

**Not a Phase A deviation:** choices inside Algorithm 2's payload and storage.

## D-35 · OMNI-705 is proved on one video; the archive is not backfilled · 2026-10-28

**Ahmad's decision.** The ticket's goal is durability: every admitted frame reaches the
encoder and ends with exactly one point, even through a kill. That is shown on one VIRAT
video (3226, 44 frames; `results.md`, OMNI-705), not by encoding everything stored.

**Revises** OMNI-705's backfill line ("queue every admitted segment ... the 60 hand-check
clips, the 9 VIRAT videos") and its acceptance ("after the backfill, `frames_embedded =
frames_total` for every video"). The stack holds 34,769 admitted frames, about 87 h on this
CPU (K-25); the ticket's 2.5 h counted VIRAT only. The 60 hand-check clips (CCD and
UCF-Crime) are not searched in this sprint, and SM-1 is measured on VIRAT only (OMNI-713, on
Colab). The other VIRAT videos are queued when search needs them
(`scripts/backfill_embeddings.py queue --only virat`, about 2.5 h); the rest when something
needs it.

## D-36 · Who may search: operators, analysts and admins · 2026-10-28

**Why:** OMNI-707's ticket says *"Operator and admin"*. Phase A says *"Users (operators and
analysts) upload video (Upload Video), search it in plain language"* (§3.4, use cases), and
the analyst is the role that works with stored footage (`/windows` is analyst and admin,
OMNI-609). Phase A is the spec, so `GET /search` takes all three roles; a request without a
valid token is refused as on every route (NFR-7, tested).

**Not a Phase A deviation:** it follows Phase A where the ticket did not.

