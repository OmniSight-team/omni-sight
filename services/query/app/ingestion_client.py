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
