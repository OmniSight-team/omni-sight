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
