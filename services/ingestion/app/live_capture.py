"""Live capture (OMNI-312): one worker per camera, feeding the same pipeline as
a file.

A worker is a thread that reads a stream, samples it at a configurable
interval, runs each sampled frame through `process` (the same `process_frame`
a file extractor uses) and publishes the resulting segment to the durable
queue. Nothing about the record says it came from a camera beyond the
`source_type` label.

Like pipeline.py and publisher.py this imports nothing from `app.*`: the
capture, the publisher, the processing function and the clock all arrive as
arguments. That keeps it independent of the service around it and lets the
tests drive it with a scripted fake capture and a fake clock instead of a
camera.

Reconnection when a stream drops is OMNI-313. Until then a worker whose stream
fails stops cleanly and reports why; it does not retry.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

logger = logging.getLogger("app.live_capture")


class WorkerState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class CaptureError(Exception):
    """The stream could not be opened or stopped delivering frames."""


class AlreadyRunning(Exception):
    """A camera already has a worker; there is only ever one."""

    def __init__(self, worker: "LiveWorker"):
        super().__init__(f"camera {worker.camera_id} already has a worker")
        self.worker = worker


class LiveWorker:
    """Reads one camera until told to stop, or until its stream fails.

    Every frame is read (decoding a stream cannot skip frames without falling
    behind), but only one per `sample_interval_s` is retrieved, processed and
    published — "never process every frame at 25 fps". The next sample is due
    an interval after the last one was *taken*, not after it was due, so a slow
    frame does not cause a burst of catch-up samples afterwards.

    The stream, the publisher's broker connection and the thread all belong to
    the worker, and all are released in `finally`, however the loop ends.
    """

    def __init__(
        self,
        camera_id: int,
        *,
        open_capture: Callable[[], Any],
        make_publisher: Callable[[], Any],
        process: Callable[[Any, float, int], Any],
        sample_interval_s: float,
        clock: Callable[[], float] = time.time,
    ):
        self.camera_id = camera_id
        self.worker_id = uuid.uuid4().hex
        self._open_capture = open_capture
        self._make_publisher = make_publisher
        self._process = process
        self._interval = sample_interval_s
        self._clock = clock

        self._stop = threading.Event()
        self._settled = threading.Event()  # set once RUNNING or FAILED
        self._lock = threading.Lock()
        self._state = WorkerState.STARTING
        self._error: str | None = None
        self._thread = threading.Thread(
            target=self._run, name=f"live-capture-{camera_id}", daemon=True
        )

        self.started_at = clock()
        # Frames read from the stream, and the subset that were processed and
        # published. The difference is what sampling saved.
        self.grabbed = 0
        self.published = 0
        self.decode_errors = 0

    @property
    def state(self) -> WorkerState:
        with self._lock:
            return self._state

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def _set_state(self, state: WorkerState, error: str | None = None) -> None:
        with self._lock:
            # A worker that has failed or been stopped stays that way.
            if self._state in (WorkerState.FAILED, WorkerState.STOPPED):
                return
            self._state = state
            if error is not None:
                self._error = error
        if state in (WorkerState.RUNNING, WorkerState.FAILED):
            self._settled.set()

    def start(self, timeout_s: float) -> WorkerState:
        """Begin capturing and wait until the first frame arrives (RUNNING) or
        the worker fails. Returns whatever state it reached, which is still
        STARTING if the stream neither delivered nor failed in time."""
        self._thread.start()
        self._settled.wait(timeout_s)
        return self.state

    def stop(self, timeout_s: float) -> bool:
        """Ask the worker to stop and wait for its thread to end. Returns
        whether it did. A worker blocked reading a stalled stream ends when that
        read times out, so this can take up to the read timeout."""
        self._stop.set()
        self._settled.set()
        if self._thread.is_alive():
            self._thread.join(timeout_s)
        with self._lock:
            if self._state is not WorkerState.FAILED:
                self._state = WorkerState.STOPPED
        return not self._thread.is_alive()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def snapshot(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "worker_id": self.worker_id,
            "status": self.state.value,
            "error": self.error,
            "started_at": self.started_at,
            "grabbed": self.grabbed,
            "published": self.published,
            "decode_errors": self.decode_errors,
        }

    def _run(self) -> None:
        capture = None
        publisher = None
        try:
            capture = self._open_capture()
            if not capture.isOpened():
                raise CaptureError("could not open the stream")
            publisher = self._make_publisher()

            index = 0
            next_sample_at: float | None = None
            while not self._stop.is_set():
                if not capture.grab():
                    if self._stop.is_set():
                        break
                    raise CaptureError("the stream stopped delivering frames")
                self.grabbed += 1
                self._set_state(WorkerState.RUNNING)

                now = self._clock()
                if next_sample_at is not None and now < next_sample_at:
                    continue
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    self.decode_errors += 1
                    continue
                next_sample_at = now + self._interval

                record = self._process(frame, now, index)
                index += 1
                publisher.publish(record)
                self.published += 1
        except Exception as exc:  # noqa: BLE001 - the worker must always release what it holds
            logger.warning(
                "live capture stopped on an error",
                extra={"extra_fields": {"camera_id": self.camera_id, "error": str(exc)[:300]}},
            )
            self._set_state(WorkerState.FAILED, str(exc)[:300])
        finally:
            if publisher is not None:
                try:
                    publisher.close()
                except Exception:
                    logger.warning("closing the publisher failed", exc_info=True)
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    logger.warning("releasing the stream failed", exc_info=True)
            self._settled.set()


class WorkerRegistry:
    """The workers running in this process — at most one per camera."""

    def __init__(self) -> None:
        self._workers: dict[int, LiveWorker] = {}
        self._lock = threading.Lock()

    def start(
        self, camera_id: int, factory: Callable[[], LiveWorker], timeout_s: float
    ) -> LiveWorker:
        """Start a worker for the camera and wait for its first frame.

        Raises AlreadyRunning if the camera has a live one. A worker that
        failed or was stopped is replaced. The new worker is registered before
        it is started, so a second request arriving while this one waits sees it
        and is refused rather than starting a duplicate; the wait itself happens
        outside the lock so one camera's slow start never blocks another's.
        """
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing is not None and existing.state in (
                WorkerState.STARTING,
                WorkerState.RUNNING,
            ):
                raise AlreadyRunning(existing)
            worker = factory()
            self._workers[camera_id] = worker

        state = worker.start(timeout_s)
        if state is not WorkerState.RUNNING:
            worker.stop(timeout_s)
        return worker

    def stop(self, camera_id: int, timeout_s: float) -> bool:
        """Stop the camera's worker and forget it. Returns whether there was one."""
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is None:
            return False
        worker.stop(timeout_s)
        return True

    def stop_all(self, timeout_s: float) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop(timeout_s)

    def get(self, camera_id: int) -> LiveWorker | None:
        with self._lock:
            return self._workers.get(camera_id)

    def snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            workers = list(self._workers.values())
        return [worker.snapshot() for worker in workers]
