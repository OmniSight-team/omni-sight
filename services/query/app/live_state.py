"""What a camera is doing right now, from evidence (OMNI-504).

The camera wall needs to see at once which feeds are healthy, and a stored flag
cannot tell it: a camera read `connected` for as long as nobody changed it, with
no worker behind it after an ingestion restart (K-5). So the state is worked out
on every request from two things that cannot lie for long:

  - the worker ingestion is running for the camera, if any, and what it says it
    is doing (`GET /workers`), and
  - when its newest frame arrived: the preview file's write time (OMNI-503),
    rewritten every 0.5 s while frames come in.

    live     a worker is reading and a frame arrived in the last
             `live_stale_after_s` (3 s)
    frozen   a worker is reading but no new frame for longer: the stream has
             stalled without closing (it becomes offline when the read times out)
    offline  the camera should be captured but cannot be: the worker is
             reconnecting or still connecting, or there is no worker at all, or
             ingestion cannot be reached
    stopped  the camera is not being captured, and nobody asked for it to be

`capture_enabled` only decides between offline and stopped when no worker is
running: it is what someone asked for, not what is happening. A worker that is
running counts whatever the flag says.
"""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class LiveState(StrEnum):
    LIVE = "live"
    FROZEN = "frozen"
    OFFLINE = "offline"
    STOPPED = "stopped"


# What ingestion's worker statuses mean here. `starting` has no frame yet.
_READING = "running"
_CONNECTING = ("starting", "reconnecting")


def newest_frame_at(previews_path: str, camera_id: int) -> datetime | None:
    """The preview's write time, which is when the newest frame arrived; None
    when there is no preview."""
    try:
        written = (Path(previews_path) / f"camera-{camera_id}.jpg").stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(written, UTC)


def derive_state(
    *,
    worker_status: str | None,
    ingestion_reachable: bool,
    capture_enabled: bool,
    last_frame_at: datetime | None,
    now: datetime,
    stale_after_s: float,
) -> LiveState:
    if ingestion_reachable and worker_status == _READING:
        if last_frame_at is not None and (now - last_frame_at).total_seconds() <= stale_after_s:
            return LiveState.LIVE
        return LiveState.FROZEN
    if ingestion_reachable and worker_status in _CONNECTING:
        return LiveState.OFFLINE
    # No worker reading: ingestion is down, the worker failed or was stopped, or
    # there never was one.
    return LiveState.OFFLINE if capture_enabled else LiveState.STOPPED
