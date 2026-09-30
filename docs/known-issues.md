# Known issues

Problems found and not fixed, with the evidence and when each has to be dealt with. When
one is fixed, move it to the bottom with the date and the result that shows it.

| # | Issue | Affects | Found | Must be dealt with by |
|---|---|---|---|---|
| K-1 | Live latency breaks 5 s while a long file is extracted | NFR-1 | OMNI-316 | Slice 5 |
| K-2 | 10 concurrent feeds not sustained at 0.2 s sampling | NFR-4 | OMNI-317 | Slice 5 |
| K-3 | `/thumbs/` and `/media/` served without a token | NFR-7 | OMNI-307/308 | Before the demo |
| K-4 | Gate cannot tell camera motion from scene motion | FR-1b, SM-2/SM-3 on CCD | OMNI-318 | Slice 6 |
| K-5 | After an ingestion restart, workers do not resume and the camera still reads `connected` | FR-1a | OMNI-312, OMNI-319 | Slice 5 (camera wall) |
| K-6 | Re-gate takes 1.4-2.0 s, grows with length | OMNI-310 target | OMNI-310 | When long recordings are used |
| K-7 | Publishing costs 12-15 ms per frame | Upload throughput, K-1 | OMNI-311 | With K-1 |
| K-8 | Storage grows about 7.7 GB per camera per day, nothing prunes | Disk | OMNI-312 | Slice 16 (retention) |
| K-9 | Failure cases not tested | NFR-5 | OMNI-311/313/319 | Before the final NFR-5 claim |
| K-10 | Small items | - | various | Any time |

---

## K-1 · Live latency breaks 5 s while a long file is extracted

Live alone: worst frame 49 ms. With a 1,158-frame file extracting: 4.67-4.91 s. With a
1,930-frame file: **6.14 s**. Live frames and the file's segments share one queue and one
consumer; extraction publishes its frames in one burst (queue peak 323-544) and live frames
wait behind it. The delay grows with the file.
**Fix candidates:** a separate queue or priority for live frames; a consumer that commits in
batches; publishing while decoding instead of in one burst.

## K-2 · 10 concurrent feeds not sustained

At 0.2 s sampling: 8 feeds sustained, 9 unreliable, 10 backs up within a minute (max
12-12.6 s), drops start at 15. Ceiling is total CPU on one machine: the full stack stores
50-56 frames/s, ten feeds offer about 42. At 0.5 s sampling ten feeds are sustained (worst
1.7 s). Tied to D-9 (the sampling interval is an open deviation). K-1 makes the margin at
eight smaller.
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

---

## Fixed

(none yet)
