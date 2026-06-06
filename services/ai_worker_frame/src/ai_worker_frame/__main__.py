"""Demo CLI: run Algorithm 2 (SigLIP2 frame embedding) on a video file.

Usage:
    python -m ai_worker_frame path/to/video.mp4 [options]
    python -m ai_worker_frame path/to/video.mp4 --in-memory --every-n 15
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniSight ai-worker-frame Phase A demo")
    parser.add_argument("video", help="Path to input video file")
    parser.add_argument("--camera-id", default="cam-0")
    parser.add_argument("--domain", default="general")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--in-memory", action="store_true", help="Use in-memory Qdrant (no server needed)")
    parser.add_argument("--every-n", type=int, default=30, help="Sample every N-th frame (default: 30)")
    parser.add_argument("--max-frames", type=int, default=None, help="Stop after embedding this many frames")
    args = parser.parse_args()

    import cv2
    from qdrant_client import QdrantClient

    from .pipeline import process_frame

    client = QdrantClient(location=":memory:" if args.in_memory else args.qdrant_url)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"Cannot open {args.video}", file=sys.stderr)
        sys.exit(1)

    stored = 0
    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % args.every_n == 0:
                ts = datetime.datetime.utcnow().isoformat()
                rec = process_frame(client, frame, args.camera_id, ts, args.domain)
                stored += 1
                print(f"[{frame_idx:6d}] frame_id={rec.frame_id}")
                if args.max_frames and stored >= args.max_frames:
                    break
            frame_idx += 1
    finally:
        cap.release()

    print(f"\nDone. Embedded {stored} frames → Qdrant DB_frame.")


if __name__ == "__main__":
    main()
