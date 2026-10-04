# RTSP camera simulator

Looping RTSP feeds standing in for real cameras during development (OMNI-201,
realistic set since OMNI-509). Config lives in `infra/mediamtx/`, started by
`docker compose up -d mediamtx` (or as part of the full stack).

## Addresses

```
rtsp://mediamtx:8554/cam01
rtsp://mediamtx:8554/cam02
rtsp://mediamtx:8554/cam03
rtsp://mediamtx:8554/cam04
rtsp://mediamtx:8554/cam05
rtsp://mediamtx:8554/cam06
rtsp://mediamtx:8554/cam07
rtsp://mediamtx:8554/cam08
rtsp://mediamtx:8554/cam09
rtsp://mediamtx:8554/cam10
...
rtsp://mediamtx:8554/cam20
```

These only resolve **inside the Docker network** — no port is published to
the host, on purpose, matching the rest of the ingestion path: only
`services/ingestion` ever opens a stream (see `docs/context/week-02.md`,
OMNI-200). One of these is the address to type into the Add Camera form
(OMNI-208) when you don't have a real camera handy.

## How it works

Each path runs an `ffmpeg -stream_loop -1` process on init that republishes a
short local clip back into that same path. The `mediamtx` service uses the
`bluenviron/mediamtx:latest-ffmpeg` image specifically because it bundles ffmpeg
for this hook — the plain `mediamtx` image doesn't.

## Two clip sets

**Realistic, the default** (`infra/mediamtx/mediamtx.real.yml`, OMNI-509): twenty
paths over ten real surveillance clips, re-encoded from `data/` by
`scripts/make_simulator_clips.py` into `infra/mediamtx/clips/real/` (gitignored):

| Paths | Clips | Size, rate |
|---|---|---|
| `cam01`-`cam03` | VIRAT, outdoor | 1280x720, 23.97 fps |
| `cam04`-`cam07` | UCF-Crime normal | 320x240, 30 fps |
| `cam08`-`cam10` | UCF-Crime with an incident (Arrest, Burglary, Robbery) | 320x240, 30 fps |
| `cam11`-`cam20` | the same ten again, for tests beyond ten feeds | |

H.264, no audio, a keyframe every 2 s; each loops every 7 to 37 s. Run
`uv run python scripts/make_simulator_clips.py` once (it needs the local subset in
`data/` and `ffmpeg`), then `docker compose up -d mediamtx`.

**Synthetic, the worst case** (`infra/mediamtx/mediamtx.yml`, OMNI-201): ten paths over
five `ffmpeg` test patterns in `infra/mediamtx/clips/` (gitignored, not project data),
640x360 at 15 fps, moving all the time. Choose it with
`MEDIAMTX_CONFIG=mediamtx.yml docker compose up -d mediamtx`; run `docker compose up -d
mediamtx` again to go back.

## Checking a feed yourself

No host port is published, so point a client at it from inside the network
rather than from your own machine — e.g. from inside the `mediamtx`
container itself:

```bash
docker compose exec mediamtx ffprobe -rtsp_transport tcp rtsp://localhost:8554/cam01
```

or from any other container on the same Docker network, using the service
name: `rtsp://mediamtx:8554/cam01`.

## Capturing a feed (OMNI-312)

Add one of the addresses above as a camera (Add Camera form, or `POST /cameras`),
then start it: `POST /cameras/{id}/start`. The ingestion service opens the feed
and gates every frame of it (Algorithm 1, the same settings as a file), and the
frames the gate admits appear as segments; `GET
/cameras/{id}/frames?since=<timestamp_s>` lists them. `POST /cameras/{id}/stop`
ends it and releases the stream.

Expect a start to take a few seconds: a stream sends nothing useful until its next
keyframe (every 2 s in the realistic set), and each camera's worker runs in a process of
its own, which takes a moment to come up.

If a feed drops while a camera is being captured (try `docker compose stop
mediamtx`), the camera goes `unreachable` within a second, the worker retries with
a growing wait (about 1, 2, 4, 8, 16, then 30 seconds), and once the feed is back
capture resumes by itself (`docker compose start mediamtx`). Nothing needs to be
restarted. A feed that stalls without closing (`docker compose pause mediamtx`) reads
`frozen` on the camera wall within about 3 s and `offline` once the read times out
(OMNI-504, OMNI-507). If ingestion itself restarts, query starts every camera that was
being captured again within about 15 s (OMNI-504).

`GET /cameras/{id}/stats` shows how a captured feed is keeping up: `captured` (frames
decoded), `dropped` (of those, thrown away because the pipeline could not keep up),
`gated` (the rest), `admitted` (`admitted_motion` plus `admitted_heartbeat`, the only
frames stored), `discarded`, `fps_effective` (frames gated per second) and `uptime_s`.
The counters balance: `captured = gated + dropped` and `gated = admitted + discarded`.
To see it drop frames, freeze the broker for a while
(`docker compose pause rabbitmq`, then `unpause`): `dropped` climbs, memory does not.

