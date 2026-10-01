"""Capture resumes by itself (OMNI-504, K-5).

After ingestion restarts it runs no workers, and before this nobody started them
again until an operator pressed Start. Ingestion has no database and cannot know
which cameras were being captured; query does, in `cameras.capture_enabled`. So
query checks every `capture_resume_interval_s` that every camera with
`capture_enabled` set has a worker, and starts the ones that do not, through the
same ingestion call as the Start button. This also covers query itself
restarting, and a worker that failed.

A camera whose start fails (its stream is down) is tried again after a wait that
doubles each time, up to `capture_resume_max_backoff_s`, so one dead camera is
not asked for every few seconds for ever. Each start runs on a thread of its own:
a start waits for the first frame, several seconds, and ten cameras resumed one
after the other would take most of a minute.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from omnisight_common import CameraStatus

from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.ingestion_client import list_workers as ingestion_list_workers
from app.ingestion_client import start_worker as ingestion_start_worker
from app.models import Camera
from app.settings import settings

logger = logging.getLogger("app.capture_resume")

# Worker statuses in which a camera has a worker doing, or about to resume, its job.
ACTIVE_WORKER_STATUSES = ("starting", "running", "reconnecting")


def _spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="capture-resume", daemon=True).start()


class CaptureResumer:
    """One check is `check()`; `run_forever()` repeats it until `stop()`. The
    ingestion calls, the clock and how a start is run are arguments, so a test
    can drive it without ingestion and without threads."""

    def __init__(
        self,
        *,
        list_workers: Callable[[], list[dict]] = ingestion_list_workers,
        start_worker: Callable[[int, str], dict] = ingestion_start_worker,
        spawn: Callable[[Callable[[], None]], None] = _spawn,
        clock: Callable[[], float] = time.monotonic,
        first_backoff_s: float | None = None,
        max_backoff_s: float | None = None,
    ):
        self._list_workers = list_workers
        self._start_worker = start_worker
        self._spawn = spawn
        self._clock = clock
        self._first_backoff_s = first_backoff_s or settings.capture_resume_interval_s or 5.0
        self._max_backoff_s = max_backoff_s or settings.capture_resume_max_backoff_s
        self._lock = threading.Lock()
        self._in_flight: set[int] = set()
        # camera id -> (when it may be tried again, the wait after the next failure)
        self._retry: dict[int, tuple[float, float]] = {}
        self._stop = threading.Event()

    def check(self) -> list[int]:
        """Start every camera that should be captured and has no worker. Returns
        the cameras it started (or set off starting).

        The workers are read before the cameras, on purpose: a stop clears
        `capture_enabled` before it asks ingestion to stop, so a camera seen here
        without a worker because it was just stopped is already seen without the
        flag too, and is not started again behind the operator's back."""
        try:
            workers = self._list_workers()
        except IngestionUnavailableError:
            return []  # ingestion is down or restarting; the next check will see it
        active = {w["camera_id"] for w in workers if w.get("status") in ACTIVE_WORKER_STATUSES}

        with SessionLocal() as db:
            wanted = [
                (camera.id, camera.rtsp_url)
                for camera in db.query(Camera).filter(
                    Camera.capture_enabled.is_(True), Camera.status != CameraStatus.DISABLED
                )
            ]

        now = self._clock()
        started = []
        for camera_id, rtsp_url in wanted:
            with self._lock:
                if camera_id in active:
                    self._retry.pop(camera_id, None)
                    continue
                if camera_id in self._in_flight:
                    continue
                if camera_id in self._retry and now < self._retry[camera_id][0]:
                    continue
                self._in_flight.add(camera_id)
            started.append(camera_id)
            self._spawn(lambda cid=camera_id, url=rtsp_url: self._resume(cid, url))
        return started

    def _resume(self, camera_id: int, rtsp_url: str) -> None:
        try:
            try:
                result = self._start_worker(camera_id, rtsp_url)
            except IngestionUnavailableError as exc:
                result = {"ok": False, "error": f"ingestion unavailable: {exc}"}
            ok = result.get("ok") or result.get("already_running")
            self._record(camera_id, ok, result.get("error"))
        finally:
            with self._lock:
                self._in_flight.discard(camera_id)

    def _record(self, camera_id: int, ok: bool, error: str | None) -> None:
        with SessionLocal() as db:
            camera = db.get(Camera, camera_id)
            if camera is not None and camera.capture_enabled and camera.status != CameraStatus.DISABLED:
                camera.status = CameraStatus.CONNECTED if ok else CameraStatus.UNREACHABLE
                if ok:
                    camera.last_seen_at = datetime.now(UTC)
                db.commit()
        if ok:
            with self._lock:
                self._retry.pop(camera_id, None)
            logger.info("capture resumed", extra={"extra_fields": {"camera_id": camera_id}})
            return
        with self._lock:
            _, wait = self._retry.get(camera_id, (0.0, self._first_backoff_s))
            self._retry[camera_id] = (self._clock() + wait, min(wait * 2, self._max_backoff_s))
        logger.warning(
            "could not resume capture",
            extra={"extra_fields": {"camera_id": camera_id, "error": (error or "")[:300], "retry_in_s": wait}},
        )

    def run_forever(self, interval_s: float) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:
                logger.exception("capture resume check failed")
            self._stop.wait(interval_s)

    def stop(self) -> None:
        self._stop.set()


def start_background(interval_s: float) -> CaptureResumer | None:
    """Run the checks on a thread of their own for as long as query runs. None
    when turned off (an interval of 0)."""
    if interval_s <= 0:
        return None
    resumer = CaptureResumer()
    threading.Thread(
        target=resumer.run_forever, args=(interval_s,), name="capture-resume-loop", daemon=True
    ).start()
    return resumer
