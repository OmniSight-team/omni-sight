# Known issues

Problems found and not fixed, with the evidence and when each has to be dealt with. When
one is fixed, move it to the bottom with the date and the result that shows it.

| # | Issue | Affects | Found | Must be dealt with by |
|---|---|---|---|---|
| K-2 | 10 concurrent feeds not sustained: gating every frame, 1 feed is; after D-18 still not, on a full machine | NFR-4 | OMNI-317, OMNI-509, OMNI-510a | **Ahmad's decision** (D-9 trade-off) |
| K-3 | `/thumbs/` and `/media/` served without a token | NFR-7 | OMNI-307/308 | Before the demo |
| K-4 | Gate cannot tell camera motion from scene motion | FR-1b, SM-2/SM-3 on CCD | OMNI-318 | Slice 6 |
| K-6 | Re-gate takes 1.4-2.0 s, grows with length | OMNI-310 target | OMNI-310 | When long recordings are used |
| K-7 | Publishing costs 12-15 ms per frame | Upload throughput, K-1 | OMNI-311 | With K-1 |
| K-8 | Storage grows about 7.7 GB per camera per day, nothing prunes | Disk | OMNI-312 | Slice 16 (retention) |
| K-9 | Failure cases not tested | NFR-5 | OMNI-311/313/319 | Before the final NFR-5 claim |
| K-10 | Small items | - | various | Any time |
| K-11 | The restart loss check reads index gaps as lost frames; live rows now have gaps by design | NFR-5 (the mid-capture check) | OMNI-501 | Slice 5 definition of done |
| K-12 | On a live feed every preview poll is a 200: OMNI-506's "mostly 304s on still scenes" cannot hold as written | OMNI-506 acceptance, wall bandwidth | OMNI-503 | OMNI-506 |
| K-13 | A stalled stream still delivers late bursts of old frames: `offline` after about 30 s, not 10, and the frame age shown is too young (the flicker back to `live` is fixed, D-17) | FR-9 (honest tile state) | OMNI-504 | OMNI-509 |
| K-14 | A live capture test fails now and then: a frame read on reconnecting is not counted if the worker stops at that instant | Test suite reliability | OMNI-504 | Any time |
| K-16 | Ten camera starts at once: five fail with "timeout" | Resume after a restart (D-15), starting a wall | OMNI-506 | Before the slice 5 definition of done |
| K-17 | The wall's layout went back to 3x3 by itself, without a reload | FR-9 (the wall), OMNI-512 | OMNI-509 | OMNI-512 |

---

## K-2 · 10 concurrent feeds not sustained

**Since 2026-10-03 (OMNI-509), gating every frame:** 1 feed sustained, HD or SD; 2 HD feeds
drop about 1% of their frames; 10 realistic feeds drop most of theirs (8,412-12,298 each in
10 minutes) and the worst frame takes 6.65 s. The live queue stays empty in every run: storage
keeps up. Frames are lost before the gate, in the worker's queue: ingestion gates 4.2 of 24
HD frames a second and 7-11 of 30 SD frames with ten feeds, spending 3.6-4.1 cores on about
1.9 cores of measured work (`results.md`, OMNI-509). Ingestion is one Python process with
196 threads at ten feeds.
**Fix candidates, none tried:** cap OpenCV/FFmpeg's decoder threads per stream (one or two
instead of a pool each); run the camera workers in several processes instead of one (Python's
interpreter lock); compute the 8x8 grid's cell means in one array operation instead of 64
(the same arithmetic, less Python per frame); more machines. Not candidates: skipping frames
before the gate (Algorithm 1, D-9); batching the consumer's commits (OMNI-510; the consumer is
idle).

**2026-10-03 (OMNI-510a, D-18):** with a process per camera and one thread per decoder
and per OpenCV call, ten realistic feeds gate 157 frames a second with the wall open (was
80.5) and the worst frame takes 3.87 s (was 6.65), but every feed still drops frames and
the containers use 821% of the 800% Docker has: this 4-core laptop is now the limit. Left:
the vectorised grid (less CPU per frame), and hardware with more cores; neither tried.
OMNI-510 (consumer batching) stays unneeded: the live queue peaked at 8 and did not grow.

**Before (OMNI-317, 2026-09-26, sampling every 0.2 s, superseded):** At 0.2 s sampling: 8 feeds sustained, 9 unreliable, 10 backs up within a minute (max
12-12.6 s), drops start at 15. Ceiling is total CPU on one machine: the full stack stores
50-56 frames/s, ten feeds offer about 42. At 0.5 s sampling ten feeds are sustained (worst
1.7 s). Tied to D-9 (the sampling interval is an open deviation). K-1 makes the margin at
eight smaller.
**2026-09-30 (OMNI-501):** sampling is removed and live cameras store admitted frames only,
so these numbers describe a load that no longer exists. One camera gates 15 frames/s at
36-39% of one core in ingestion; several feeds at once are not measured yet (OMNI-509).
**Fix candidates, most measured first:** a longer sampling interval (measured); batched
consumer commits (unmeasured); a separate live queue (K-1); services off the one machine.

## K-3 · Static routes without a token (NFR-7)

`GET /thumbs/...jpg` and `GET /media/..._playback.mp4` return 200 with no `Authorization`
header. Thumbnail paths are predictable (`/thumbs/{video_id}/{frame_index:06d}.jpg`);
`/media/` exposes whole recordings. Every API route enforces the token (TC-10).
**Fix candidates:** nginx `auth_request` to `query`, or signed short-lived URLs.

## K-4 · Camera motion looks like scene motion

On daylight dash-cam footage (CCD crash) the gate keeps 57%; four clips keep every scoreable
frame. Raising the threshold cuts fixed-camera activity too, so it is not a fix. A design
question for Algorithm 1 (e.g. compensating for global motion) before CCD is loaded at
scale.

## K-6 · Re-gate latency

1.4-2.0 s on a 10 s, 30 fps clip against "about a second"; decode 0.22 s, scoring 0.83 s
(blur 0.57 s). Every re-gate recomputes the threshold-independent part (blur, diff,
per-cell means). **Fix candidate:** store the per-cell means once at extraction, so a
re-gate is a comparison, not a decode.

## K-7 · Publish cost

One confirm per message: 3.5-4.4 s for 300 frames, 21.8-27.0 s for 1,800; a 10-minute 30 fps
recording would take about 4 minutes (extrapolated). **Fix candidate:** asynchronous or
batched confirms.

## K-8 · Storage growth

24.2 KB per admitted frame at 320x240: about 7.7 GB per camera per day in constant motion,
2.1 GB for a static scene; real cameras are larger. Nothing prunes until slice 16.
**2026-09-30 (OMNI-501):** those figures are from 0.2 s sampling (at most about 4.2 stored
frames/s). Every frame is now gated, so a scene in constant motion can store up to the
feed's own rate (15/s on the simulator), about 3.5 times as much; `cam05` stored 3.1-3.3/s.
Not measured per day.

## K-9 · Failure cases not tested

- A stream that stalls without closing (should take the 10 s read timeout)
- Several cameras dropping at once (what the jitter is for)
- A broker restart during live capture: the worker reconnects to the camera, **not to the
  broker**
- Ingestion crashing part-way through publishing a file; query crashing while an
  extraction waits
- A kill between a JPEG write and the broker's confirm (by construction, not by test)
- A broker freeze longer than the 30 s heartbeat

## K-10 · Small items

- The video archive table wraps Size and Uploaded onto several lines with long names (VIRAT)
  at 1114 px and gets a horizontal scrollbar
- Starting cameras is sequential, about 3.9 s each (37-42 s for ten)
- The playback transcode runs inside the upload request with a 150 s timeout never measured
  against a long recording
- The frontend dev server on port 3000 cannot serve `/media/`; use nginx at
  `https://localhost`
- `scripts/measure_concurrent_feeds.py` still speaks of sampled frames and reads only the
  file queue's depth; to be brought up to date when it is rerun (OMNI-509).
  `measure_capture_latency.py` was updated in OMNI-502, apart from its TC-1 live line, which
  says "frames gated" for what are stored (admitted) rows
- The camera screen does not show the new gate counters (`gated`, `admitted`, `discarded`);
  they are in `GET /cameras/{id}/stats` only
- The frontend dev server in Docker does not see file changes on this Windows machine (a new
  page folder answered 404, an edited component stayed old) until `docker compose restart
  frontend` (OMNI-506)
- nginx resolves `query` and `frontend` once, when it starts. Restarting them together can
  swap their container addresses, and nginx then answers 502 for everything until it is
  restarted too (`docker compose restart nginx`; seen 2026-10-02, OMNI-507)
- `LIVE_QUEUE_SIZE` = 10 was sized for 5 frames/s (about 2 s); at 15 frames/s it is about
  0.7 s. No drops on one camera (OMNI-501); not checked under load

## K-11 · The restart loss check no longer fits live rows

`scripts/verify_definition_of_done.py` (OMNI-319) decides that a frame was lost across a
restart from three things: a row without a file, a file without a row, and **a gap in a
session's frame indexes**. Since OMNI-501 a live camera stores admitted frames only while the
index still counts every gated frame, so gaps are normal and the third check will report
loss where there is none. Read from the code, not run. The first two checks still hold.
Since OMNI-502 it also waits for the wrong queue to empty: it reads the file queue
(`segment_queue`), and live frames are on `omnisight.segments.live`.
**Fix candidate:** drop the gap check for live sessions and rely on files against rows, or
compare the stored rows with the `admitted` counter.

## K-12 · Preview polls on a live feed are never 304

The preview's ETag is its write time (OMNI-503 as specified), and a live worker rewrites it
every 0.5 s whether the scene moved or not. A tile polling once a second therefore always
finds a new file: 960 of 960 polls were 200 on `cam05`, about 387 KiB/s for 16 tiles; 304s
only came while the simulator was paused (432 of 480). OMNI-506's acceptance ("the network
tab shows mostly 304s on still scenes") cannot be met this way; OMNI-504 and OMNI-507 need
the ETag to change with every new frame, so they agree with what was built.
**Options:** reword OMNI-506's acceptance to 304s on frozen or lost feeds (no code change;
the bandwidth is 24.5 KiB per tile per second on `cam05`); or rewrite the preview only when
the picture changed, with liveness taken from somewhere else. The first is the
recommendation.

---

## K-13 · A stalled stream delivers late bursts of old frames

With the simulator paused (`docker compose pause mediamtx`) the worker kept receiving frames:
1 about 13 s after the pause command and 9 about 23 s after, then nothing (`GET /workers`,
every 0.5 s; the pause command itself took 3.5 s). They arrive in step with the 10 s read
timeout: in both acceptance runs the camera read `live` again at 10.5-10.6 s and 20.5-20.6 s
after the pause and went `offline` at 30.6-30.8 s, instead of about 10 s. They can only be
frames from before the pause (the source is frozen), released late; why exactly at the
timeouts (OpenCV/FFmpeg flushing buffered data when the read is interrupted is the likely
reading) is not established. The worker stamps a frame when it arrives, so each burst
rewrites the preview and the camera reads `live` for about 3 s. `frozen` itself came on time
(3.1-3.2 s after the last frame). The state follows the rule as the ticket wrote it ("a
frame arrived in the last 3 s"). Seen with `docker compose pause`; a real network stall may
or may not behave the same, not tested.
**Fix candidates:** leave `frozen` only after frames arrive steadily again (for example at
least a second's worth within a second), not on one frame; or stamp a frame with the
stream's own timestamp instead of its arrival time, so late frames read as old.

**2026-10-02 (OMNI-507, D-17), half fixed:** `live` now needs frames arriving steadily, so a
burst no longer reads as live: paused, the camera read `frozen` at 2.4 s and nothing else
until `offline`, and on the wall nine tiles went Live, Frozen, Offline with no Live between.
**Still open:** `offline` still comes about 30 s after the pause, not about 10 s, because
each burst restarts the read timeout; and the age a tile shows ("last frame 11 s ago") counts
from when the late frames *arrived*, not from when they were captured, so it understates how
old the picture is. Both are the second fix candidate above (stamp frames by the stream's own
time, or treat a worker that is not receiving for a read timeout as lost).

## K-14 · A live capture test fails now and then

`test_no_frame_is_lost_or_counted_twice_across_a_reconnection` failed once in a full run
(2026-10-02) and passed 15 times alone and in four full ingestion runs. Likely cause, read
from the code, not reproduced: `_open_stream` grabs a frame to prove the stream works and
leaves it pending; if the worker is stopped before the read loop counts it, `grabbed` ends
one below what the stream delivered, which is what the test compares. The frame is a
fraction of a second's worth at a moment the camera is being stopped anyway.
**Fix candidate:** count the pending frame in `grabbed` where it is grabbed.

## K-17 · The wall's layout went back to 3x3 by itself

During the 10-feed NFR-4 run (2026-10-03) the wall had been set to 4x4 with ten tiles; 19 s
into the window it showed 3x3 again, the default, with the page not reloaded (same
navigation, the in-page recorder still running). Nothing in the app shell remounts the page
on a timer. The state is only in the page's memory, so anything that re-creates the page
component resets it; what did here is not known (the Next.js dev server is the first
suspect). OMNI-512's "remember the layout" would hide it without explaining it.
Not seen again in the 10-minute OMNI-510a run (2026-10-03): 4x4 for all 600 samples.

## K-16 · Ten camera starts at once: five fail with "timeout"

Starting the simulator's ten feeds through `POST /cameras/{id}/start` in parallel
(`scripts/wall_cameras.py up`, 2026-10-02): five started (13.6-23.6 s each), five failed after
15.1-15.2 s with "could not start capture: timeout", which is the reachability check before
a start (`LIVE_PROBE_TIMEOUT_S` = 15 s). Run again (the other five already
running), the five started in 7.7-17.7 s. Starting is slow anyway (K-10: about 3.9 s each, sequentially), and ten
streams opened together take longer. This matters for D-15: after an ingestion restart the
resume check starts every camera at once, so with ten cameras some would fail and come back
only on the retry backoff (5 s, then 10 s ...). Measured once; the cause (ingestion's
probes, mediamtx, or the machine) not isolated.
**Fix candidates:** resume a few cameras at a time; or a longer probe timeout when many
starts are in flight.
**2026-10-03 (OMNI-509):** starting two at a time, every one of eleven runs (up to ten
cameras each) started without a single retry. The resume (D-15) still starts them all at once.

---

## Fixed

| # | Issue | Affected | Found | Fixed |
|---|---|---|---|---|
| K-1 | Live latency breaks 5 s while a long file is extracted | NFR-1 | OMNI-316 | OMNI-502, 2026-10-01 |
| K-5 | After an ingestion restart, workers do not resume and the camera still reads `connected` | FR-1a | OMNI-312, OMNI-319 | OMNI-504, 2026-10-02 |
| K-15 | The simulator's frame size was written as 320x240; the clips are 640x360 | Stated conditions | 2026-10-02 | OMNI-509, 2026-10-03 |

### K-1 · Live latency breaks 5 s while a long file is extracted · fixed 2026-10-01

**Was:** live alone, worst frame 49 ms. With a 1,158-frame file extracting: 4.67-4.91 s.
With a 1,930-frame file: **6.14 s**. Live frames and the file's segments shared one queue
and one consumer; extraction publishes its frames in one burst (queue peak 323-544) and live
frames waited behind it.
**Fix (OMNI-502, D-13):** live frames on their own queue, `omnisight.segments.live`, read by
a consumer of their own, `consumer-live`.
**Result:** with the 1,930-frame file extracting, worst live frame **147 ms and 373 ms** in
two runs; the file queue peaked at 306-330 and the live queue at 0 (`results.md`, OMNI-502).
One camera; ten feeds are OMNI-509.

### K-5 · Workers are not resumed after a restart · fixed 2026-10-02

**Was:** after `docker compose restart ingestion` or a kill, `GET /workers` was empty and the
camera still read `connected` with nobody capturing, until capture was started again. No
data was lost (OMNI-319); the status was wrong.
**Fix (OMNI-504, D-15):** `cameras.capture_enabled`, and a check in query every 5 s that
starts every camera with it set and no worker; the wall's state comes from evidence (the
worker list and the newest frame), so a camera with no worker never reads `live`.
**Result (two runs):** `restart ingestion`: offline from the first poll after the command
returned, `live` again 13.5-13.6 s later, worker running; `kill` then `start`: the same,
12.3-12.5 s; no `live` reading in between (35 polls each time). `cameras.status` itself is still the last observed
reachability and is not corrected by a restart; the wall does not read it.

### K-15 · The simulator's frame size was wrong in the results · fixed 2026-10-03

The simulator's synthetic clips are 640x360, not 320x240 as `results.md` said in ten places
(OMNI-312, 316, 317, 501 to 505) and the context notes in two. Each place now carries
"[corrected 2026-10-03: the simulator's clips are 640x360, K-15]" beside the old figure,
not a silent rewrite. No measured number changes; the stated conditions do. Since OMNI-509 the
default simulator clips are real footage (`mediamtx.real.yml`), stated with their sizes.
