# RTSP camera simulator

Ten looping RTSP feeds, standing in for real cameras during development
(OMNI-201). Config lives in `infra/mediamtx/`, started by `docker compose up
-d mediamtx` (or as part of the full stack).

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
```

These only resolve **inside the Docker network** — no port is published to
the host, on purpose, matching the rest of the ingestion path: only
`services/ingestion` ever opens a stream (see `docs/context/week-02.md`,
OMNI-200). One of these is the address to type into the Add Camera form
(OMNI-208) when you don't have a real camera handy.

## How it works

Each path in `infra/mediamtx/mediamtx.yml` runs an `ffmpeg -stream_loop -1`
process on init that republishes a short local clip back into that same
path. The `mediamtx` service uses the `bluenviron/mediamtx:latest-ffmpeg`
image specifically because it bundles ffmpeg for this hook — the plain
`mediamtx` image doesn't.

Ten paths, five source clips (`infra/mediamtx/clips/`, gitignored —
scaffolding generated with `ffmpeg`'s synthetic test sources, not project
data). Each clip is reused across two paths; nothing about the ten feeds
requires ten distinct source files.

## Checking a feed yourself

No host port is published, so point a client at it from inside the network
rather than from your own machine — e.g. from inside the `mediamtx`
container itself:

```bash
docker compose exec mediamtx ffprobe -rtsp_transport tcp rtsp://localhost:8554/cam01
```

or from any other container on the same Docker network, using the service
name: `rtsp://mediamtx:8554/cam01`.
