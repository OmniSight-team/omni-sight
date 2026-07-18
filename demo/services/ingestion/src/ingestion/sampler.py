"""
Algorithm 1 — ROI-Aware Spatial-Motion Sampling.
Reads a frame source, applies a motion-grid filter, and yields admitted Payloads.
Output contract: (f_t, W) consumed by Algorithm 2 (Dual-Stream Embedding Generation).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_FPS = 30.0


# ---------------------------------------------------------------------------
# Data contract
# ---------------------------------------------------------------------------

@dataclass
class Payload:
    frame: np.ndarray          # admitted f_t (BGR)
    window: list[np.ndarray]   # [t-2Δ … t], oldest→newest
    t: int                     # frame index
    source_id: str


# ---------------------------------------------------------------------------
# Buffer
# ---------------------------------------------------------------------------

class Buffer:
    """Rolling buffer of length 2Δ+1 for one camera."""

    def __init__(self, delta: int) -> None:
        self._delta = delta
        self._buf: deque[np.ndarray] = deque(maxlen=2 * delta + 1)

    def append(self, frame: np.ndarray) -> None:
        self._buf.append(frame)

    def is_warm(self) -> bool:
        return len(self._buf) == self._buf.maxlen

    def frame_at_lag(self, d: int) -> np.ndarray:
        """Return the frame d steps behind the current tail."""
        return self._buf[-1 - d]

    def window(self) -> list[np.ndarray]:
        """All buffered frames, oldest→newest."""
        return list(self._buf)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class VideoFileSource:
    """Streams frames from a video file one at a time (no full-load into memory)."""

    def __init__(self, path: str, fallback_fps: float = _DEFAULT_FPS) -> None:
        self._path = path
        self._fallback_fps = fallback_fps
        self._fps: float | None = None

    @property
    def fps(self) -> float:
        if self._fps is None:
            cap = cv2.VideoCapture(self._path)
            self._fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            if not self._fps:
                logger.warning("FPS unreadable for %s; using %.1f", self._path, self._fallback_fps)
                self._fps = self._fallback_fps
        return self._fps

    def iter_frames(self) -> Iterator[np.ndarray]:
        cap = cv2.VideoCapture(self._path)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame
        finally:
            cap.release()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grid_active_cells(diff: np.ndarray, G: int, tau: float) -> int:
    """Count G×G cells in diff whose mean pixel value exceeds tau."""
    h, w = diff.shape
    ch, cw = h // G, w // G
    count = 0
    for r in range(G):
        r0, r1 = r * ch, (r + 1) * ch if r < G - 1 else h
        for c in range(G):
            c0, c1 = c * cw, (c + 1) * cw if c < G - 1 else w
            if diff[r0:r1, c0:c1].mean() > tau:
                count += 1
    return count


# ---------------------------------------------------------------------------
# Algorithm 1
# ---------------------------------------------------------------------------

def roi_aware_sampler(
    source,
    G: int = 8,
    tau: float = 10.0,
    k: int = 4,
    delta: int = 15,
    max_gap: int = 90,
    source_id: str = "default",
) -> Iterator[Payload]:
    """Yields a Payload for each admitted frame; warmup and drops produce no yield.

    max_gap: force-admit a frame every this many frames so static scenes
    (parked cars, empty hallways) are always represented in the index.
    """
    if not (0 <= tau <= 255):
        raise ValueError(f"tau must be in [0, 255], got {tau}")
    if G < 1:
        raise ValueError(f"G must be >= 1, got {G}")
    if not (1 <= k <= G * G):
        raise ValueError(f"k must be in [1, G²], got {k}")
    if delta < 1:
        raise ValueError(f"delta must be >= 1, got {delta}")

    buf = Buffer(delta)
    frames_since_admit = 0

    for t, f_t in enumerate(source.iter_frames()):
        # 1: append
        buf.append(f_t)

        # 2: warmup
        if not buf.is_warm():
            logger.debug("frame %d: warmup", t)
            continue

        # 3: diff
        gray_t = cv2.cvtColor(f_t, cv2.COLOR_BGR2GRAY)
        gray_lag = cv2.cvtColor(buf.frame_at_lag(delta), cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_t, gray_lag)

        # 4-5: grid activation
        active = _grid_active_cells(diff, G, tau)

        # 6-9: admit on motion or max_gap fallback
        force = frames_since_admit >= max_gap
        if active >= k or force:
            W = buf.window()
            yield Payload(frame=f_t, window=W, t=t, source_id=source_id)
            frames_since_admit = 0
            if force:
                logger.debug("frame %d: force-admitted (gap=%d)", t, frames_since_admit)
        else:
            logger.debug("frame %d: dropped (active=%d)", t, active)
            frames_since_admit += 1
