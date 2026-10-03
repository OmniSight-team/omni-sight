"""A camera's live worker in a process of its own (OMNI-510a).

OMNI-509 found ingestion falling behind with ten cameras while the gate's own work
was about half of what it spent: every camera's capture and processing threads ran
in one Python process, taking turns on its interpreter lock. Here each camera's
`LiveWorker` runs in a child process instead, so cameras no longer wait on each
other. Nothing about what a worker does changes: the child builds the same worker
(`app.main._live_worker_for`), which gates every frame and publishes the admitted
ones exactly as before.

`ProcessWorker` is what the registry and the routes hold in the parent. It has the
parts of `LiveWorker` they use (`start`, `stop`, `state`, `error`, `worker_id`,
`alive`, `snapshot`), answered from the reports the child sends over a pipe every
`report_interval_s`. A child that dies without saying so reads as failed, and query
resumes the camera (D-15).

Processes are started with "spawn", never "fork": the parent has threads (uvicorn's,
other cameras'), and forking a threaded process can leave locks held for ever.
"""

import importlib
import logging
import multiprocessing
import threading
import time
from typing import Any

from app.live_capture import WorkerState

logger = logging.getLogger("app.worker_process")

# Extra time a start may take for the child process itself to come up (import
# OpenCV, NumPy, the broker client) before the stream is even opened.
SPAWN_MARGIN_S = 15.0


def run_camera_worker(conn, factory: str, camera_id: int, rtsp_url: str, start_timeout_s: float,
                      report_interval_s: float) -> None:
    """The child process: build the camera's worker, start it, report on it, and
    stop it when told to (or when the parent goes away)."""
    module, name = factory.split(":")
    worker = getattr(importlib.import_module(module), name)(camera_id, rtsp_url)
    stop_timeout_s = 15.0
    try:
        worker.start(start_timeout_s)
        conn.send(("started", worker.snapshot()))
        while True:
            if conn.poll(report_interval_s):
                message = conn.recv()
                if message[0] == "stop":
                    stop_timeout_s = message[1]
                    break
            conn.send(("snapshot", worker.snapshot()))
            if not worker.alive:
                break  # failed, or never got going
    except (EOFError, BrokenPipeError, OSError):
        pass  # the parent is gone: stop, releasing the stream and the broker connection
    finally:
        worker.stop(stop_timeout_s)
        try:
            conn.send(("ended", worker.snapshot()))
        except (BrokenPipeError, OSError):
            pass
        conn.close()


class ProcessWorker:
    """One camera's worker, running in a child process."""

    def __init__(self, camera_id: int, rtsp_url: str, *, factory: str = "app.main:_live_worker_for",
                 report_interval_s: float = 0.5):
        self.camera_id = camera_id
        context = multiprocessing.get_context("spawn")
        self._conn, child_conn = context.Pipe()
        self._child_conn = child_conn
        self._factory, self._rtsp_url = factory, rtsp_url
        self._report_interval_s = report_interval_s
        self._context = context
        self._process = None
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._ended = threading.Event()
        self._snapshot: dict[str, Any] = {"camera_id": camera_id, "worker_id": "", "status": WorkerState.STARTING.value,
                                          "error": None, "started_at": time.time()}

    # --- what the registry and the routes read -------------------------------------------

    @property
    def worker_id(self) -> str:
        with self._lock:
            return self._snapshot.get("worker_id", "")

    @property
    def state(self) -> WorkerState:
        with self._lock:
            return WorkerState(self._snapshot.get("status", WorkerState.FAILED.value))

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._snapshot.get("error")

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._snapshot)

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self, timeout_s: float) -> WorkerState:
        """Start the child and wait until its worker has a first frame, has failed,
        or the time is up. Returns the state reached, like `LiveWorker.start`."""
        self._process = self._context.Process(
            target=run_camera_worker,
            args=(self._child_conn, self._factory, self.camera_id, self._rtsp_url, timeout_s, self._report_interval_s),
            name=f"camera-{self.camera_id}",
            daemon=True,
        )
        self._process.start()
        self._child_conn.close()  # the child's end; only the child uses it now
        threading.Thread(target=self._read_reports, name=f"camera-{self.camera_id}-reports", daemon=True).start()
        self._started.wait(timeout_s + SPAWN_MARGIN_S)
        return self.state

    def stop(self, timeout_s: float) -> bool:
        """Ask the child to stop its worker and wait for it to exit. A child that
        does not exit in time is terminated. Returns whether it is gone."""
        if self._process is None:
            return True
        try:
            self._conn.send(("stop", timeout_s))
        except (BrokenPipeError, OSError):
            pass  # already gone
        self._process.join(timeout_s + 5.0)
        if self._process.is_alive():
            logger.warning("camera worker process did not stop; terminating", extra={"extra_fields": {"camera_id": self.camera_id}})
            self._process.terminate()
            self._process.join(5.0)
        self._ended.wait(1.0)
        with self._lock:
            if self._snapshot.get("status") != WorkerState.FAILED.value:
                self._snapshot["status"] = WorkerState.STOPPED.value
        return not self._process.is_alive()

    def _read_reports(self) -> None:
        try:
            while True:
                kind, snapshot = self._conn.recv()
                with self._lock:
                    self._snapshot = snapshot
                if kind in ("started", "ended"):
                    self._started.set()
                if kind == "ended":
                    self._ended.set()
                    return
        except (EOFError, OSError):
            # The child went away without saying so (killed, crashed).
            with self._lock:
                if self._snapshot.get("status") not in (WorkerState.STOPPED.value, WorkerState.FAILED.value):
                    self._snapshot["status"] = WorkerState.FAILED.value
                    self._snapshot["error"] = "the camera's worker process ended unexpectedly"
            self._started.set()
            self._ended.set()
