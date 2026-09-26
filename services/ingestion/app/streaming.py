import concurrent.futures
import contextlib
import os
import socket
import tempfile
import threading
from urllib.parse import urlparse

import cv2

# Fast rejection for a dead host or a closed port, before ever touching cv2.
CONNECT_TIMEOUT_S = 3
# Hard deadline for the RTSP handshake + first frame, enforced in a worker
# thread so a stream that never responds can never hang the request itself.
STREAM_OPEN_TIMEOUT_S = 5

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="stream-probe")

# cv2's ffmpeg backend writes its own errors (including "401 Unauthorized")
# straight to the process's stderr file descriptor, not to anything Python
# can catch. Capturing that descriptor is the only way to see why a stream
# refused to open, but the redirect is process-wide, so concurrent probes
# must take turns using it.
_stderr_capture_lock = threading.Lock()


class ProbeError(Exception):
    """A stream could not be opened. `reason` is one of "unreachable",
    "authentication failed" or "timeout" — never a generic message."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


@contextlib.contextmanager
def _capture_stderr():
    with _stderr_capture_lock:
        saved_fd = os.dup(2)
        with tempfile.TemporaryFile(mode="w+b") as tmp:
            os.dup2(tmp.fileno(), 2)
            try:
                yield tmp
            finally:
                os.dup2(saved_fd, 2)
                os.close(saved_fd)


def classify_open_failure(log_text: str) -> str:
    lowered = log_text.lower()
    if "401" in log_text or "unauthorized" in lowered or "authorization" in lowered:
        return "authentication failed"
    return "unreachable"


def _tcp_preflight(host: str, port: int) -> None:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S):
            return
    except TimeoutError as exc:
        raise ProbeError("timeout", f"no response connecting to {host}:{port}") from exc
    except OSError as exc:
        raise ProbeError("unreachable", str(exc)) from exc


def _open_and_read(rtsp_url: str, read_frame: bool = True) -> tuple[str, float]:
    with _capture_stderr() as captured:
        capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        try:
            opened = capture.isOpened()
            ok, frame = capture.read() if opened and read_frame else (True, None)
            fps = float(capture.get(cv2.CAP_PROP_FPS)) if opened else 0.0
            props_size = (
                int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
        finally:
            capture.release()

        captured.seek(0)
        log_text = captured.read().decode(errors="replace")

    if not opened or not ok or (read_frame and frame is None):
        raise ProbeError(classify_open_failure(log_text), log_text.strip()[-500:])

    if frame is not None:
        height, width = frame.shape[:2]
    else:
        width, height = props_size
    return f"{width}x{height}", fps


def probe_stream(
    rtsp_url: str,
    open_timeout_s: float = STREAM_OPEN_TIMEOUT_S,
    *,
    read_first_frame: bool = True,
) -> dict[str, str | float]:
    """Open an RTSP stream, read one frame, report resolution and fps, and
    always close it again — on success, on failure, and on timeout alike.

    `open_timeout_s` is how long the whole probe may take. A stream sends
    nothing useful until its next keyframe, which can be several seconds after
    connecting, so a caller that does not need a frame (starting a live capture,
    OMNI-312, whose own first frame is the real confirmation) can pass
    `read_first_frame=False` and get a verdict as soon as the stream has opened
    or been refused: reachable, wrong credentials, or dead. The resolution then
    comes from the stream's own properties and may be 0x0."""
    parsed = urlparse(rtsp_url)
    if not parsed.hostname:
        raise ProbeError("unreachable", "no host in rtsp url")

    _tcp_preflight(parsed.hostname, parsed.port or 554)

    future = _executor.submit(_open_and_read, rtsp_url, read_first_frame)
    try:
        resolution, fps = future.result(timeout=open_timeout_s)
    except concurrent.futures.TimeoutError as exc:
        # The worker thread is left running — it releases its own capture
        # once the remote end finally responds or errors — but the request
        # this call is serving returns right now regardless.
        raise ProbeError("timeout", "stream did not open in time") from exc

    return {"resolution": resolution, "fps": fps}
