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


def extract_file(video_id: int, path: str, source_type: str, camera_id: int | None) -> dict:
    try:
        resp = httpx.post(
            f"{settings.ingestion_base_url}/extract/file",
            json={
                "video_id": video_id,
                "path": path,
                "source_type": source_type,
                "camera_id": camera_id,
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
