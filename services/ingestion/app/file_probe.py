from pathlib import Path

import cv2


class FileProbeError(Exception):
    """A local file could not be probed. Always caught by the route — a
    corrupt or truncated file is a clean, reported failure, never a crash."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def probe_file(path: str) -> dict[str, float | int]:
    """Open a local video file, read one frame, report duration/fps/width/
    height, and always release the capture — success or failure alike."""
    if not Path(path).is_file():
        raise FileProbeError("file not found")

    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise FileProbeError("could not open file")

        ok, frame = capture.read()
        if not ok or frame is None:
            raise FileProbeError("could not read a frame from file")

        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frame_count <= 0:
            raise FileProbeError("could not determine video duration")

        height, width = frame.shape[:2]
        duration_s = frame_count / fps
        return {"duration_s": duration_s, "fps": fps, "width": width, "height": height}
    finally:
        capture.release()
