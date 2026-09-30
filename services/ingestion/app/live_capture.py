"""Live capture (OMNI-312), reconnection (OMNI-313), bounded queue (OMNI-314),
every frame gated (OMNI-501): one worker per camera, feeding the same pipeline
as a file.

A worker is two threads joined by a small bounded queue.

    capture thread:    read stream -> decode -> put on the queue, or drop it
    processing thread: take from the queue -> process_frame -> publish if admitted

Every decoded frame is gated, as Algorithm 1 is written and exactly as a file's
frames are: there is no sampling step before the gate. What differs for a live
camera is only what is published. Algorithm 1 forwards admitted frames
(pseudocode line 8) and drops the rest (line 10), so an admitted frame becomes a
segment and a discarded one is counted and nothing more: no row, no file.

The capture thread only reads, decodes and enqueues, and never waits on anything
downstream, so a slow gate or a slow broker cannot stall the stream. When the
processing side falls behind the queue fills, and a frame that does not fit is
**dropped and counted**, rather than being held until memory runs out. The
processing thread also owns the broker connection (a pika connection is not
shared between threads) and sends the worker's counters to `camera_stats`.

The counters balance, and are meant to be checked:

    captured = gated + dropped      (plus whatever is still in the queue)
    gated    = admitted + discarded

When a stream drops, the worker does not give up: it reports the camera
unreachable, waits, and tries again, waiting longer after each failure, until
it is stopped. A worker that never got its first frame does fail, at once,
because a start that cannot deliver anything should say so rather than retry in
the background.

Like pipeline.py and publisher.py this imports nothing from `app.*`: the
capture, the publisher, the processing function, the clock and the wait all
arrive as arguments. That keeps it independent of the service around it and lets
the tests drive it with a scripted fake capture instead of a camera.
"""

import logging
import queue
import random
import threading
import time
import uuid
from collections import deque
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

    Every frame the stream delivers is decoded and offered to the pipeline,
    which gates it (Algorithm 1 has no sampling step). Only a frame the gate
    admits is published; the others are counted as discarded.

    `queue_size` bounds how many decoded frames wait for the processing thread.
    A frame that arrives when it is full is dropped. `max_backlog`, if set, is
    the most segments the durable queue may hold before frames are dropped
    instead of added to it: without it a consumer that has fallen behind would
    let the broker's queue grow for ever.

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
        clock: Callable[[], float] = time.time,
        backoff: Backoff | None = None,
        # A connection that lasted less than this before dropping again does not
        # earn a fresh backoff, or a camera that flaps every couple of seconds
        # would be retried at the shortest delay for ever.
        stable_after_s: float = 10.0,
        wait: Callable[[float], bool] | None = None,
        queue_size: int = 10,
        max_backlog: int | None = None,
        stats_interval_s: float = 5.0,
        drop_log_interval_s: float = 5.0,
        fps_window_s: float = 10.0,
        backlog_check_interval_s: float = 1.0,
    ):
        self.camera_id = camera_id
        self.worker_id = uuid.uuid4().hex
        self._open_capture = open_capture
        self._make_publisher = make_publisher
        self._make_process = make_process
        self._clock = clock
        self._backoff = backoff or Backoff(1.0, 30.0)
        self._stable_after_s = stable_after_s
        self._max_backlog = max_backlog
        self._stats_interval_s = stats_interval_s
        self._drop_log_interval_s = drop_log_interval_s
        self._fps_window_s = fps_window_s
        self._backlog_check_interval_s = backlog_check_interval_s

        self._stop = threading.Event()
        # Waits, returning True as soon as the worker is asked to stop. A test
        # replaces it to run through many backoff periods without sleeping.
        self._wait = wait or self._stop.wait
        self._settled = threading.Event()  # set once RUNNING or FAILED
        self._capture_done = threading.Event()  # the capture thread has ended
        self._lock = threading.Lock()
        self._state = WorkerState.STARTING
        self._error: str | None = None
        self._pending_grab = False
        # The next frame's index within this worker's session. Kept here, not in
        # the read loop, so a reconnection carries on counting: a frame's file is
        # named by it, and starting again from zero would overwrite files that
        # stored segments still point at. Every frame handed to the pipeline
        # takes one, admitted or not, as a file's frames do, so the stored
        # segments' indexes have gaps where frames were discarded.
        self._next_index = 0

        # The bounded queue, and a small unbounded one for the few status
        # changes the capture thread reports (they must never be dropped, and
        # they cannot be published from the capture thread, which does not own
        # the broker connection).
        self._frames: queue.Queue = queue.Queue(maxsize=queue_size)
        self._control: queue.SimpleQueue = queue.SimpleQueue()
        self._capture_thread = threading.Thread(
            target=self._run, name=f"live-capture-{camera_id}", daemon=True
        )
        self._processor_thread = threading.Thread(
            target=self._process_loop, name=f"live-process-{camera_id}", daemon=True
        )

        self.started_at = clock()
        # What the stream delivered.
        self.grabbed = 0
        # Decoded frames offered to the pipeline ("captured" in camera_stats),
        # and those dropped because it could not keep up.
        self.captured = 0
        self.dropped = 0
        self.dropped_backlog = 0
        # What the gate did with the rest (OMNI-501): every frame it was shown,
        # the ones it admitted, by reason, and the ones it discarded.
        # `gated = admitted_motion + admitted_heartbeat + discarded`, always.
        self.gated = 0
        self.admitted_motion = 0
        self.admitted_heartbeat = 0
        self.discarded = 0
        # Admitted frames handed to the broker. Equal to the admitted ones unless
        # a publish failed, which also ends the worker.
        self.published = 0
        self.decode_errors = 0
        # Times the stream came back after a drop, and attempts that did not.
        self.reconnects = 0
        self.failed_attempts = 0
        self.last_frame_at: float | None = None

        self._processed_at: deque[float] = deque()
        self._drops_since_log = 0
        self._last_drop_log_at: float | None = None
        self._drop_reasons_since_log: dict[str, int] = {}
        self._backlog_cache = 0
        self._backlog_checked_at: float | None = None

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
        self._processor_thread.start()
        self._capture_thread.start()
        self._settled.wait(timeout_s)
        return self.state

    def stop(self, timeout_s: float) -> bool:
        """Ask the worker to stop and wait for both threads to end. Returns
        whether they did. A worker waiting out a backoff ends at once; one blocked
        reading a stalled stream ends when that read times out, so this can take
        up to the read timeout. Frames already queued are still processed."""
        self._stop.set()
        self._settled.set()
        deadline = time.monotonic() + timeout_s
        if self._capture_thread.is_alive():
            self._capture_thread.join(timeout_s)
        # The capture thread has finished with the queue; the processing thread
        # drains what is left, reports its final totals and closes the broker
        # connection.
        self._capture_done.set()
        if self._processor_thread.is_alive():
            self._processor_thread.join(max(0.1, deadline - time.monotonic()))
        with self._lock:
            if self._state is not WorkerState.FAILED:
                self._state = WorkerState.STOPPED
        return not self.alive

    @property
    def alive(self) -> bool:
        return self._capture_thread.is_alive() or self._processor_thread.is_alive()

    # --- counters ------------------------------------------------------------

    @property
    def admitted(self) -> int:
        return self.admitted_motion + self.admitted_heartbeat

    def fps_effective(self) -> float:
        """Frames actually gated per second, over the last `fps_window_s` (or
        since the start, if that is shorter). On a pipeline that keeps up this
        is the stream's own frame rate."""
        now = self._clock()
        cutoff = now - self._fps_window_s
        with self._lock:
            while self._processed_at and self._processed_at[0] < cutoff:
                self._processed_at.popleft()
            count = len(self._processed_at)
        span = min(self._fps_window_s, max(now - self.started_at, 1e-9))
        return count / span if span > 0 else 0.0

    def uptime_s(self) -> float:
        return max(0.0, self._clock() - self.started_at) if self.state in LIVE_STATES else 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "worker_id": self.worker_id,
            "status": self.state.value,
            "error": self.error,
            "started_at": self.started_at,
            "grabbed": self.grabbed,
            "captured": self.captured,
            "dropped": self.dropped,
            "dropped_backlog": self.dropped_backlog,
            "gated": self.gated,
            "admitted": self.admitted,
            "admitted_motion": self.admitted_motion,
            "admitted_heartbeat": self.admitted_heartbeat,
            "discarded": self.discarded,
            "published": self.published,
            "queue_depth": self._frames.qsize(),
            "queue_size": self._frames.maxsize,
            "fps_effective": round(self.fps_effective(), 3),
            "uptime_s": round(self.uptime_s(), 1),
            "decode_errors": self.decode_errors,
            "reconnects": self.reconnects,
            "failed_attempts": self.failed_attempts,
            "last_frame_at": self.last_frame_at,
        }

    def _stats_report(self, running: bool) -> dict[str, Any]:
        # One lock for the gate's counters, so a report never catches them
        # between two increments and they balance in every report.
        with self._lock:
            gate_counters = {
                "gated": self.gated,
                "admitted_motion": self.admitted_motion,
                "admitted_heartbeat": self.admitted_heartbeat,
                "discarded": self.discarded,
            }
        return {
            "camera_id": self.camera_id,
            "worker_id": self.worker_id,
            "started_at": self.started_at,
            "at": self._clock(),
            "captured": self.captured,
            "dropped": self.dropped,
            **gate_counters,
            "fps_effective": self.fps_effective(),
            "last_frame_at": self.last_frame_at,
            "running": running,
        }

    def _drop(self, reason: str) -> None:
        """Throw a captured frame away before the gate sees it, and make sure
        someone can tell.

        Counted every time. Logged as a warning when a stretch of drops begins,
        and then as a summary every `drop_log_interval_s`, not once per frame:
        that would bury everything else, and a line per frame is no more
        informative than a count.
        """
        now = self._clock()
        with self._lock:
            self.dropped += 1
            if reason == "backlog":
                self.dropped_backlog += 1
            self._drops_since_log += 1
            self._drop_reasons_since_log[reason] = self._drop_reasons_since_log.get(reason, 0) + 1
            first = self._last_drop_log_at is None
            due = first or now - self._last_drop_log_at >= self._drop_log_interval_s
            if not due:
                return
            since = self._last_drop_log_at
            count, reasons = self._drops_since_log, dict(self._drop_reasons_since_log)
            self._last_drop_log_at = now
            self._drops_since_log = 0
            self._drop_reasons_since_log = {}
        logger.warning(
            "dropping frames: the pipeline is not keeping up",
            extra={
                "extra_fields": {
                    "camera_id": self.camera_id,
                    "dropped_since_last_report": count,
                    "reasons": reasons,
                    "over_s": None if since is None else round(now - since, 1),
                    "dropped_total": self.dropped,
                    "queue_depth": self._frames.qsize(),
                }
            },
        )

    # --- the capture thread --------------------------------------------------

    def _run(self) -> None:
        capture = None
        try:
            ever_running = False
            connected_at = 0.0

            while not self._stop.is_set():
                try:
                    capture = self._open_stream()
                except CaptureError as exc:
                    if not ever_running:
                        raise  # a start that cannot deliver says so, it does not retry
                    self._attempt_failed(str(exc))
                    self._wait_to_retry()
                    continue

                if ever_running:
                    self.reconnects += 1
                    self._notify("connected")
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
                    self._read_until_lost(capture, self._make_process())
                except CaptureError as exc:
                    self._release(capture)
                    capture = None
                    if self._stop.is_set():
                        break
                    if self._clock() - connected_at >= self._stable_after_s:
                        self._backoff.reset()
                    self._lost(str(exc))
                    self._wait_to_retry()
        except Exception as exc:  # noqa: BLE001 - the worker must always release what it holds
            logger.warning(
                "live capture stopped on an error",
                extra={"extra_fields": {"camera_id": self.camera_id, "error": str(exc)[:300]}},
            )
            self._set_state(WorkerState.FAILED, str(exc)[:300])
        finally:
            self._release(capture)
            self._capture_done.set()
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

    def _read_until_lost(self, capture: Any, process: Any) -> None:
        """Read the stream until it is lost (raising CaptureError) or the worker
        is stopped (returning). Every decoded frame goes on the bounded queue, or
        is dropped if the queue is full; nothing here ever waits for the
        pipeline."""
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
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                self.decode_errors += 1
                continue

            self.captured += 1
            try:
                self._frames.put_nowait((process, frame, now, self._next_index))
            except queue.Full:
                self._drop("processing")
            else:
                self._next_index += 1

    def _lost(self, reason: str) -> None:
        """The stream dropped after working: say so at once, not on the next poll."""
        self._set_state(WorkerState.RECONNECTING, reason)
        self._notify("unreachable")
        logger.warning(
            "stream lost, reconnecting",
            extra={"extra_fields": {"camera_id": self.camera_id, "reason": reason}},
        )

    def _attempt_failed(self, reason: str) -> None:
        self.failed_attempts += 1
        self._set_state(WorkerState.RECONNECTING, reason)

    def _wait_to_retry(self) -> None:
        """Wait out the next backoff delay, giving up the wait the moment the
        worker is stopped."""
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
            remaining -= step

    def _notify(self, status: str) -> None:
        """Report a change of reachability, through the processing thread that
        owns the broker connection."""
        self._control.put((status, self._clock()))

    @staticmethod
    def _release(capture: Any) -> None:
        if capture is None:
            return
        try:
            capture.release()
        except Exception:
            logger.warning("releasing the stream failed", exc_info=True)

    # --- the processing thread -----------------------------------------------

    def _process_loop(self) -> None:
        publisher = None
        try:
            publisher = self._make_publisher()
            # The first report goes out at once, not after a full interval: it is
            # what tells `camera_stats` (and so the camera screen) that this
            # camera is now being captured, and waiting seconds to say so makes
            # a camera that was just started look stopped.
            next_report_at = self._clock()
            while True:
                self._send_status_changes(publisher)
                try:
                    process, frame, timestamp_s, index = self._frames.get(timeout=0.25)
                except queue.Empty:
                    if self._capture_done.is_set() and self._frames.empty():
                        break
                    # Nothing to do: keep answering the broker's heartbeats.
                    publisher.keepalive()
                else:
                    self._handle(publisher, process, frame, timestamp_s, index)
                if self._clock() >= next_report_at:
                    self._report(publisher, running=True)
                    next_report_at = self._clock() + self._stats_interval_s
            self._send_status_changes(publisher)
        except Exception as exc:  # noqa: BLE001 - the worker must always release what it holds
            logger.warning(
                "live processing stopped on an error",
                extra={"extra_fields": {"camera_id": self.camera_id, "error": str(exc)[:300]}},
            )
            self._set_state(WorkerState.FAILED, str(exc)[:300])
            self._stop.set()  # the capture thread has nothing to hand frames to any more
        finally:
            if publisher is not None:
                # Whatever happened, say how the session ended.
                try:
                    self._report(publisher, running=False)
                except Exception:
                    logger.warning("could not send the final camera stats", exc_info=True)
                try:
                    publisher.close()
                except Exception:
                    logger.warning("closing the publisher failed", exc_info=True)
            self._settled.set()

    def _handle(self, publisher: Any, process: Any, frame: Any, timestamp_s: float, index: int) -> None:
        if self._backlog_exceeded(publisher):
            self._drop("backlog")
            return
        # Algorithm 1 on every frame, through the same `process_frame` as a
        # file: the frame and thumbnail are written here if it is admitted.
        record = process(frame, timestamp_s, index)
        with self._lock:
            self.gated += 1
            if not record.admitted:
                self.discarded += 1
            elif record.admission_reason == "heartbeat":
                self.admitted_heartbeat += 1
            else:
                self.admitted_motion += 1
            self._processed_at.append(self._clock())
        if not record.admitted:
            return  # line 10: drop(f_t). Counted above; no row and no file.
        # Line 8: forward(f_t, W). The record carries the clip [t - 2Δ, t].
        publisher.publish(record)
        with self._lock:
            self.published += 1

    def _backlog_exceeded(self, publisher: Any) -> bool:
        """Is the durable queue already holding more than it should? Read at most
        once per `backlog_check_interval_s`: the depth is a coarse signal, and
        asking the broker for every frame would be a round trip per frame."""
        if self._max_backlog is None:
            return False
        now = self._clock()
        if self._backlog_checked_at is None or now - self._backlog_checked_at >= self._backlog_check_interval_s:
            self._backlog_cache = publisher.backlog()
            self._backlog_checked_at = now
        return self._backlog_cache >= self._max_backlog

    def _send_status_changes(self, publisher: Any) -> None:
        """Report reachability changes the capture thread noted. Best effort:
        failing to say so must not stop the capture, which is what matters."""
        while True:
            try:
                status, at = self._control.get_nowait()
            except queue.Empty:
                return
            try:
                publisher.publish_event(self.camera_id, status, at, self.worker_id)
            except Exception:
                logger.warning(
                    "could not report a camera status change",
                    extra={"extra_fields": {"camera_id": self.camera_id, "status": status}},
                    exc_info=True,
                )

    def _report(self, publisher: Any, *, running: bool) -> None:
        """Send the running totals to `camera_stats`. Best effort while running:
        a report that could not be sent is simply superseded by the next one,
        because the totals are cumulative."""
        try:
            publisher.publish_stats(self._stats_report(running))
        except Exception:
            if running:
                logger.warning(
                    "could not report camera stats",
                    extra={"extra_fields": {"camera_id": self.camera_id}},
                    exc_info=True,
                )
            else:
                raise


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
        # RECONNECTING counts as started: a worker only gets there after its
        # first frame, so the stream worked and has dropped again since, and the
        # worker is doing exactly what it is meant to. A stream can drop within
        # a moment of delivering that frame, before this reads the state.
        if state not in (WorkerState.RUNNING, WorkerState.RECONNECTING):
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
