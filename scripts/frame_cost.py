"""What one live frame costs in ingestion, step by step (OMNI-509).

Runs inside the ingestion container, on one simulator clip at a time, with the
service's own code and settings: decode (`grab` + `retrieve`), Algorithm 1's gate
(`MotionGate` inside `HeartbeatGate`: grayscale, the 21 px blur, the difference,
the grid), the preview (scale to 640 px, JPEG, rename) and, for an admitted frame,
the frame and thumbnail JPEGs. Single-threaded, nothing else from this script
running, so the numbers are each step's own CPU time per frame.

Run from the repo root (the clips are mounted in the simulator, so copy one in):

  docker compose cp infra/mediamtx/clips/real/real01_VIRAT_S_010003_07_000608_000636.mp4 ingestion:/tmp/clip.mp4
  docker compose exec -T ingestion /workspace/.venv/bin/python /workspace/scripts_frame_cost.py /tmp/clip.mp4

(`docker compose cp scripts/frame_cost.py ingestion:/workspace/scripts_frame_cost.py` first.)
"""

import sys
import tempfile
import time
from pathlib import Path

import cv2

sys.path.insert(0, "/workspace/services/ingestion")
from app.pipeline import (
    FrameSource,
    HeartbeatGate,
    MotionGate,
    process_frame,
)
from app.preview import PreviewWriter
from app.settings import settings

path = sys.argv[1]
frames_to_time = int(sys.argv[2]) if len(sys.argv) > 2 else 300
capture = cv2.VideoCapture(path)
fps = capture.get(cv2.CAP_PROP_FPS)
work = Path(tempfile.mkdtemp())
gate = HeartbeatGate(
    MotionGate(grid_size=settings.motion_grid_size, cell_threshold=settings.motion_cell_threshold,
               min_active_cells=settings.motion_min_active_cells, stride_s=settings.motion_stride_s,
               blur_kernel=settings.motion_blur_kernel),
    heartbeat_interval_s=settings.heartbeat_interval_s, stride_s=settings.motion_stride_s,
)
preview = PreviewWriter(work / "preview.jpg", max_side_px=settings.live_preview_max_side_px,
                        quality=settings.live_preview_jpeg_quality)
(work / "f").mkdir()
(work / "t").mkdir()
spent = {"decode": 0.0, "gate + files (process_frame)": 0.0, "preview": 0.0}
admitted = n = 0
shape = None
while n < frames_to_time:
    t = time.perf_counter()
    if not capture.grab():
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        continue
    ok, frame = capture.retrieve()
    spent["decode"] += time.perf_counter() - t
    shape = frame.shape
    t = time.perf_counter()
    record = process_frame(
        frame, FrameSource(source_type="camera", frame_index=n, timestamp_s=n / fps, camera_id=1), gate,
        work / "f", work / "t", thumb_width=settings.thumb_width_px, frame_quality=settings.frame_jpeg_quality,
        thumb_quality=settings.thumb_jpeg_quality,
    )
    spent["gate + files (process_frame)"] += time.perf_counter() - t
    admitted += record.admitted
    if n % max(1, round(fps / 2)) == 0:  # the preview is written twice a second
        t = time.perf_counter()
        preview.write(frame)
        spent["preview"] += time.perf_counter() - t
    n += 1

# The part of the gate that D-4 added: grayscale and the blur, on the last frame.
blur = 0.0
for _ in range(100):
    b = time.perf_counter()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cv2.GaussianBlur(gray, (settings.motion_blur_kernel, settings.motion_blur_kernel), 0)
    blur += time.perf_counter() - b

total = sum(spent.values())
print(f"{Path(path).name}: {shape[1]}x{shape[0]} at {fps:.2f} fps, {n} frames, {admitted} admitted ({100 * admitted / n:.0f}%)")
for name, seconds in spent.items():
    print(f"  {name:30s} {1000 * seconds / n:7.2f} ms a frame")
print(f"  {'of which grayscale + blur':30s} {10 * blur:7.2f} ms a frame (measured separately, 100 frames)")
print(f"  {'total':30s} {1000 * total / n:7.2f} ms a frame -> {total / n * fps:.2f} of one core at {fps:.0f} fps")
