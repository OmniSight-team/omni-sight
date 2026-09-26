"""Live capture (OMNI-312, reconnection OMNI-313): one worker per camera, feeding
the same pipeline as a file.

A worker is a thread that reads a stream, samples it at a configurable
interval, runs each sampled frame through the processing function (the same
`process_frame` a file extractor uses) and publishes the resulting segment to
the durable queue. Nothing about the record says it came from a camera beyond
the `source_type` label.

When a stream drops, the worker does not give up: it reports the camera
unreachable, waits, and tries again, waiting longer after each failure, until
it is stopped. When the stream comes back it says so and carries on. A worker
that never got its first frame does fail, at once, because a start that cannot
deliver anything should say so rather than retry in the background.

Like pipeline.py and publisher.py this imports nothing from `app.*`: the
capture, the publisher, the processing function, the clock and the wait all
arrive as arguments. That keeps it independent of the service around it and lets
the tests drive it with a scripted fake capture instead of a camera.
"""

import logging
import random
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
    # The stream dropped and the worker is waiting to try again.
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    # Ended for a reason retrying will not fix: it never got a first frame, or
    # the broker or the gate failed.
    FAILED = "failed"


# States in which a camera has a worker that is doing, or will resume, its job.
LIVE_STATES = (WorkerState.STARTING, WorkerState.RUNNING, WorkerState.RECONNECTING)


class CaptureError(Exception):
    """The stream could not be opened or stopped delivering frames."""


class AlreadyRunning(Exception):
    """A camera already has a worker; there is only ever one."""

    def __init__(self, worker: "LiveWorker"):
        super().__init__(f"camera {worker.camera_id} already has a worker")
        self.worker = worker


class Backoff:
    """How long to wait before the next attempt: `initial_s`, then doubled
    (`factor`) after every failure, never more than `max_s`, with a little
    random jitter so a room of cameras that lost the same network do not all
    knock at the same instant.

    The point of it is the growth: a dead camera is tried at 1 s, 2 s, 4 s and
    so on up to the cap, not every 100 ms for ever.
    """

    def __init__(
        self,
        initial_s: float,
        max_s: float,
        *,
        factor: float = 2.0,
        jitter: float = 0.2,
        rng: Callable[[], float] = random.random,
    ):
        self._initial_s = initial_s
        self._max_s = max_s
        self._factor = factor
        self._jitter = jitter
        self._rng = rng
        self.failures = 0

    def next(self) -> float:
        base = min(self._max_s, self._initial_s * self._factor**self.failures)
        self.failures += 1
        jittered = base * (1 + self._jitter * (2 * self._rng() - 1))
        return min(self._max_s, max(0.0, jittered))

    def reset(self) -> None:
        self.failures = 0


class LiveWorker:
    """Reads one camera until told to stop.

    Every frame is read (decoding a stream cannot skip frames without falling
    behind), but only one per `sample_interval_s` is retrieved, processed and
    published — "never process every frame at 25 fps". The next sample is due
    an interval after the last one was *taken*, not after it was due, so a slow
    frame does not cause a burst of catch-up samples afterwards.

    The stream, the publisher's broker connection and the thread belong to the
    worker, and all are released in `finally`, however the loop ends.

    `make_process` is called once per connection, not once per worker: the
    motion gate compares a frame with earlier ones, and after a gap of seconds
    or minutes the last frames it saw are from a different moment, so the first
    frame back would read as motion. A new connection gets a new gate.
    """

    def __init__(
        self,
        camera_id: int,
        *,
        open_capture: Callable[[], Any],
        make_publisher: Callable[[], Any],
        make_process: Callable[[], Callable[[Any, float, int], Any]],
        sample_interval_s: float,
        clock: Callable[[], float] = time.time,
        backoff: Backoff | None = None,
        # A connection that lasted less than this before dropping again does not
        # earn a fresh backoff, or a camera that flaps every couple of seconds
        # would be retried at the shortest delay for ever.
        stable_after_s: float = 10.0,
        wait: Callable[[float], bool] | None = None,
    ):
        self.camera_id = camera_id
        self.worker_id = uuid.uuid4().hex
        self._open_capture = open_capture
        self._make_publisher = make_publisher
        self._make_process = make_process
        self._interval = sample_interval_s
        self._clock = clock
        self._backoff = backoff or Backoff(1.0, 30.0)
        self._stable_after_s = stable_after_s

        self._stop = threading.Event()
        # Waits, returning True as soon as the worker is asked to stop. A test
        # replaces it to run through many backoff periods without sleeping.
        self._wait = wait or self._stop.wait
        self._settled = threading.Event()  # set once RUNNING or FAILED
        self._lock = threading.Lock()
        self._state = WorkerState.STARTING
        self._error: str | None = None
        self._pending_grab = False
        # The next frame's index within this worker's session. Kept here, not in
        # the read loop, so a reconnection carries on counting: a frame's file is
        # named by it, and starting again from zero would overwrite files that
        # stored segments still point at.
        self._next_index = 0
        self._thread = threading.Thread(
            target=self._run, name=f"live-capture-{camera_id}", daemon=True
        )

        self.started_at = clock()
        # Frames read from the stream, and the subset that were processed and
        # published. The difference is what sampling saved.
        self.grabbed = 0
        self.published = 0
        self.decode_errors = 0
        # Times the stream came back after a drop, and attempts that did not.
        self.reconnects = 0
        self.failed_attempts = 0
        self.last_frame_at: float | None = None

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
        whether it did. A worker waiting out a backoff ends at once; one blocked
        reading a stalled stream ends when that read times out, so this can take
        up to the read timeout."""
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
            "reconnects": self.reconnects,
            "failed_attempts": self.failed_attempts,
            "last_frame_at": self.last_frame_at,
        }

    # --- the loop ------------------------------------------------------------

    def _run(self) -> None:
        publisher = None
        capture = None
        try:
            publisher = self._make_publisher()
            ever_running = False
            connected_at = 0.0

            while not self._stop.is_set():
                try:
                    capture = self._open_stream()
                except CaptureError as exc:
                    if not ever_running:
                        raise  # a start that cannot deliver says so, it does not retry
                    self._attempt_failed(str(exc))
                    self._wait_to_retry(publisher)
                    continue

                if ever_running:
                    self.reconnects += 1
                    self._notify(publisher, "connected")
                    logger.info(
                        "stream reconnected",
                        extra={
                            "extra_fields": {
                                "camera_id": self.camera_id,
                                "after_failed_attempts": self.failed_attempts,
                            }
                        },
                    )
                ever_running = True
                connected_at = self._clock()
                self._set_state(WorkerState.RUNNING)

                try:
                    self._read_until_lost(capture, publisher, self._make_process())
                except CaptureError as exc:
                    self._release(capture)
                    capture = None
                    if self._stop.is_set():
                        break
                    if self._clock() - connected_at >= self._stable_after_s:
                        self._backoff.reset()
                    self._lost(publisher, str(exc))
                    self._wait_to_retry(publisher)
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
            self._release(capture)
            self._settled.set()

    def _open_stream(self) -> Any:
        """Open the stream and read its first frame, so a stream that opens but
        never delivers counts as a failed attempt. That first frame is not lost:
        the next read is skipped (see `_read_until_lost`)."""
        capture = self._open_capture()
        try:
            if not capture.isOpened():
                raise CaptureError("could not open the stream")
            if not capture.grab():
                raise CaptureError("the stream opened but delivered no frame")
        except BaseException:
            self._release(capture)
            raise
        self._pending_grab = True
        return capture

    def _read_until_lost(self, capture: Any, publisher: Any, process: Any) -> None:
        """Sample the stream until it is lost (raising CaptureError) or the worker
        is stopped (returning)."""
        next_sample_at: float | None = None
        while not self._stop.is_set():
            if self._pending_grab:
                self._pending_grab = False  # the frame `_open_stream` already read
            elif not capture.grab():
                if self._stop.is_set():
                    break
                raise CaptureError("the stream stopped delivering frames")
            self.grabbed += 1

            now = self._clock()
            self.last_frame_at = now
            if next_sample_at is not None and now < next_sample_at:
                continue
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                self.decode_errors += 1
                continue
            next_sample_at = now + self._interval

            record = process(frame, now, self._next_index)
            self._next_index += 1
            publisher.publish(record)
            self.published += 1

    def _lost(self, publisher: Any, reason: str) -> None:
        """The stream dropped after working: say so at once, not on the next poll."""
        self._set_state(WorkerState.RECONNECTING, reason)
        self._notify(publisher, "unreachable")
        logger.warning(
            "stream lost, reconnecting",
            extra={"extra_fields": {"camera_id": self.camera_id, "reason": reason}},
        )

    def _attempt_failed(self, reason: str) -> None:
        self.failed_attempts += 1
        self._set_state(WorkerState.RECONNECTING, reason)

    def _wait_to_retry(self, publisher: Any) -> None:
        """Wait out the next backoff delay, keeping the broker connection alive
        and giving up the wait the moment the worker is stopped."""
        delay = self._backoff.next()
        logger.info(
            "next reconnect attempt",
            extra={
                "extra_fields": {
                    "camera_id": self.camera_id,
                    "in_s": round(delay, 2),
                    "failures": self._backoff.failures,
                }
            },
        )
        remaining = delay
        while remaining > 0 and not self._stop.is_set():
            step = min(remaining, 0.5)
            if self._wait(step):
                return
            publisher.keepalive()
            remaining -= step

    def _notify(self, publisher: Any, status: str) -> None:
        """Report a change of reachability. Best effort: failing to say so must
        not stop the capture, which is the thing that matters."""
        try:
            publisher.publish_event(self.camera_id, status, self._clock(), self.worker_id)
        except Exception:
            logger.warning(
                "could not report a camera status change",
                extra={"extra_fields": {"camera_id": self.camera_id, "status": status}},
                exc_info=True,
            )

    @staticmethod
    def _release(capture: Any) -> None:
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            logger.warning("releasing the stream failed", exc_info=True)


class WorkerRegistry:
    """The workers running in this process — at most one per camera."""

    def __init__(self) -> None:
        self._workers: dict[int, LiveWorker] = {}
        self._lock = threading.Lock()

    def start(
        self, camera_id: int, factory: Callable[[], LiveWorker], timeout_s: float
    ) -> LiveWorker:
        """Start a worker for the camera and wait for its first frame.

        Raises AlreadyRunning if the camera has a live one, which includes one
        that is waiting to reconnect. A worker that failed or was stopped is
        replaced. The new worker is registered before it is started, so a second
        request arriving while this one waits sees it and is refused rather than
        starting a duplicate; the wait itself happens outside the lock so one
        camera's slow start never blocks another's.
        """
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing is not None and existing.state in LIVE_STATES:
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
