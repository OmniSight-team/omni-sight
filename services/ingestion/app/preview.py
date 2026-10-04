"""The current frame of a live camera, as one small JPEG (OMNI-503).

A wall of sixteen cameras cannot afford sixteen video streams. Each tile asks
for the camera's current frame about once a second instead, and this is what it
gets: one file per camera, rewritten by the camera's worker at most every
`interval_s`, whatever the gate decided about the frame. Query serves it with
the token check and an ETag taken from the file's write time, so a poll that
finds nothing new costs a 304 and no image.

The file is replaced atomically: written to a temporary name in the same folder,
then renamed over the old one. A reader opening the file at any moment gets
either the whole previous frame or the whole new one, never half of each.

Like pipeline.py this imports nothing from `app.*`; the folder and the sizes
arrive as arguments.
"""

import os
from pathlib import Path

import cv2


def preview_path(previews_dir: str | Path, camera_id: int) -> Path:
    """Where a camera's preview lives. Query computes the same path to serve it."""
    return Path(previews_dir) / f"camera-{camera_id}.jpg"


class PreviewWriter:
    """Writes one camera's preview file. Not thread-safe: one worker's capture
    thread owns it."""

    def __init__(self, path: Path, *, max_side_px: int, quality: int):
        self.path = Path(path)
        self._tmp = self.path.with_name(self.path.name + ".tmp")
        self._max_side_px = max_side_px
        self._quality = quality

    def write(self, frame) -> None:
        """Replace the preview with this frame, scaled down so its longest side
        is at most `max_side_px` (never scaled up)."""
        height, width = frame.shape[:2]
        longest = max(height, width)
        if longest > self._max_side_px:
            scale = self._max_side_px / longest
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not ok:
            raise OSError("could not encode the preview")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._tmp, "wb") as handle:
            handle.write(encoded.tobytes())
        os.replace(self._tmp, self.path)

    def clear(self) -> None:
        """Remove the preview, so a camera that is no longer captured has none to
        serve: an old frame must never be shown as if it were current."""
        for path in (self.path, self._tmp):
            path.unlink(missing_ok=True)
