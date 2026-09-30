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
