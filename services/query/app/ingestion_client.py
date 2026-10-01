import httpx

from app.settings import settings

REQUEST_TIMEOUT_S = 15.0


class IngestionUnavailableError(Exception):
    pass


def probe_stream(rtsp_url: str) -> dict:
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/probe/stream",
            json={"rtsp_url": rtsp_url},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def extract_file(
    video_id: int,
    path: str,
    source_type: str,
    camera_id: int | None,
    *,
    stride_s: float | None = None,
    grid_size: int | None = None,
    cell_threshold: float | None = None,
    min_active_cells: int | None = None,
) -> dict:
    # The four gate overrides default to None here too, so a normal
    # extraction (which never passes them) sends a payload identical to
    # before OMNI-306 — ingestion falls back to its own settings for any of
    # them left out.
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/extract/file",
            json={
                "video_id": video_id,
                "path": path,
                "source_type": source_type,
                "camera_id": camera_id,
                "stride_s": stride_s,
                "grid_size": grid_size,
                "cell_threshold": cell_threshold,
                "min_active_cells": min_active_cells,
            },
            timeout=settings.ingestion_extract_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def publish_extraction(
    video_id: int,
    path: str,
    source_type: str,
    camera_id: int | None,
    extraction_id: str,
) -> dict:
    """Ask ingestion to decode and gate a file and put every segment on the
    durable queue (OMNI-311). Returns once the broker has confirmed them all —
    `{ok, published, error, <the gate parameters used>}` — not once they are
    stored; the consumer does that, and the caller waits for it."""
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/extract/publish",
            json={
                "video_id": video_id,
                "path": path,
                "source_type": source_type,
                "camera_id": camera_id,
                "extraction_id": extraction_id,
            },
            timeout=settings.ingestion_extract_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def probe_file(path: str) -> dict:
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/probe/file",
            json={"path": path},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def ensure_playback(path: str) -> dict:
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/playback/file",
            json={"path": path},
            timeout=settings.ingestion_playback_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def start_worker(camera_id: int, rtsp_url: str) -> dict:
    """Ask ingestion to start capturing a camera (OMNI-312). Returns
    `{ok, worker_id, status, error, already_running}`; the request waits for the
    stream's first frame, so it gets its own, longer, timeout."""
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/workers/start",
            json={"camera_id": camera_id, "rtsp_url": rtsp_url},
            timeout=settings.ingestion_worker_start_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def list_workers() -> list[dict]:
    """The workers ingestion is running right now (OMNI-504): one dict per
    camera, with at least `camera_id` and `status`. Short timeout: this is asked
    on every camera wall refresh and every resume check, and a slow answer is
    treated the same as no answer."""
    try:
        resp = httpx.get(
            f"{settings.ingestion_base_url}/workers",
            timeout=settings.ingestion_workers_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()


def stop_worker(camera_id: int) -> dict:
    """Ask ingestion to stop a camera's worker. `{ok, status, was_running}`."""
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/workers/stop",
            json={"camera_id": camera_id},
            timeout=settings.ingestion_worker_stop_timeout_s,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise IngestionUnavailableError(str(exc)) from exc
    return resp.json()

