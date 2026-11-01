"""TC-2, clip half (OMNI-710): every admitted segment of a 30 s video has one unit clip vector.

The vectors are those of OMNI-708's run on Colab: the repo's Algorithm 1 and InternVideo2 code on
the GPU, a file gated as an upload is (`encode_virat_archive.py`). This reads the result from
Drive, for the evaluation video closest to 30 s: one vector per admitted frame, 512-D, finite,
unit length, each frame once, each clip's window ending at its frame. From the repo root:

    uv run python scripts/verify_tc2_clips.py
"""

import json
import sys
from pathlib import Path

import numpy as np

ARCHIVE = Path("G:/My Drive/omnisight/embeddings/virat")


def main() -> int:
    videos = json.loads((ARCHIVE / "manifest.json").read_text())["videos"]
    key = min(videos, key=lambda k: abs(videos[k]["frames_decoded"] / videos[k]["fps"] - 30))
    entry = videos[key]
    with np.load(ARCHIVE / f"{key}.npz") as data:
        frames, clips = data["frame_index"], data["clip_vectors"]
        times, ends = data["timestamp_s"], data["clip_end_s"]
    norms = np.linalg.norm(clips, axis=1)
    print(f"{key}: {entry['frames_decoded'] / entry['fps']:.1f} s, {entry['frames_decoded']} frames, {entry['admitted']} admitted")
    print(f"clip vectors {clips.shape}, norm {norms.min():.6f} to {norms.max():.6f}")
    checks = {
        "one vector per admitted frame": len(clips) == entry["admitted"] == len(frames),
        "each frame once": len(set(frames.tolist())) == len(frames),
        "512-D": clips.shape[1] == 512,
        "finite": bool(np.isfinite(clips).all()),
        "unit length": bool(np.abs(norms - 1).max() < 1e-3),
        "each window ends at its frame": bool(np.abs(times - ends).max() < 1e-6),
    }
    for name, passed in checks.items():
        print(f"  {'ok  ' if passed else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
