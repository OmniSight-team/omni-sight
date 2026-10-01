# Known issues

Problems found and not fixed, with the evidence and when each has to be dealt with. When
one is fixed, move it to the bottom with the date and the result that shows it.

| # | Issue | Affects | Found | Must be dealt with by |
|---|---|---|---|---|
| K-2 | 10 concurrent feeds not sustained at 0.2 s sampling | NFR-4 | OMNI-317 | Slice 5 |
| K-3 | `/thumbs/` and `/media/` served without a token | NFR-7 | OMNI-307/308 | Before the demo |
| K-4 | Gate cannot tell camera motion from scene motion | FR-1b, SM-2/SM-3 on CCD | OMNI-318 | Slice 6 |
| K-5 | After an ingestion restart, workers do not resume and the camera still reads `connected` | FR-1a | OMNI-312, OMNI-319 | Slice 5 (camera wall) |
| K-6 | Re-gate takes 1.4-2.0 s, grows with length | OMNI-310 target | OMNI-310 | When long recordings are used |
| K-7 | Publishing costs 12-15 ms per frame | Upload throughput, K-1 | OMNI-311 | With K-1 |
| K-8 | Storage grows about 7.7 GB per camera per day, nothing prunes | Disk | OMNI-312 | Slice 16 (retention) |
| K-9 | Failure cases not tested | NFR-5 | OMNI-311/313/319 | Before the final NFR-5 claim |
| K-10 | Small items | - | various | Any time |
| K-11 | The restart loss check reads index gaps as lost frames; live rows now have gaps by design | NFR-5 (the mid-capture check) | OMNI-501 | Slice 5 definition of done |
| K-12 | On a live feed every preview poll is a 200: OMNI-506's "mostly 304s on still scenes" cannot hold as written | OMNI-506 acceptance, wall bandwidth | OMNI-503 | OMNI-506 |

---

## K-2 · 10 concurrent feeds not sustained

At 0.2 s sampling: 8 feeds sustained, 9 unreliable, 10 backs up within a minute (max
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

## K-5 · Workers are not resumed after a restart

After `docker compose restart ingestion` or a kill, `GET /workers` is empty and the camera
still reads `connected` with nobody capturing, until capture is started again. No data is
lost (OMNI-319); the status is wrong.

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

## Fixed

| # | Issue | Affected | Found | Fixed |
|---|---|---|---|---|
| K-1 | Live latency breaks 5 s while a long file is extracted | NFR-1 | OMNI-316 | OMNI-502, 2026-10-01 |

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
