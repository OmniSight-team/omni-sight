"""Any video, with its vectors, made ready on Colab for the system to add (OMNI-X05).

Run from `notebooks/encode_upload_gpu.ipynb` on Colab's GPU. Everything is the VIRAT archive's
code (`encode_virat_archive.encode_video`, OMNI-708): ingestion's Algorithm 1 with the
product's settings, SigLIP 2 on the JPEG `process_frame` writes, InternVideo2 on the 8 frames
of each admitted frame's window. Only the packaging is new: each video goes into a folder
named by its fingerprint, the SHA-256 of its bytes (D-47), the same value the system stores
on the `videos` row, so the system knows the copy it holds is the file Colab encoded.

Output, one folder per video, `{out}/{fingerprint}/`:

- the video file itself, under its original name
- `vectors.npz`: what `encode_video` returns (`frame_index`, `timestamp_s`,
  `admission_reason`, `motion_score`, `clip_start_s`, `clip_end_s`, `frame_vectors`,
  `clip_vectors`, `fps`, `frames_decoded`)
- `info.json`: `file` (the original name), `pins` and `gate` (the model pins and the
  extraction settings it was made with; the system refuses a folder whose either differs
  from its own), `frames_decoded`, `admitted`, `fps`, `duration_s`

The folder is built as `{fingerprint}.part/` and renamed when complete, so the system never
sees half of one. A video whose folder is already there with the same pins and settings is
skipped, so a lost session resumes; one made with others is refused, never overwritten.

Locally (correctness only, D-31): `uv run pytest scripts/tests`.
"""

import hashlib
import json
import shutil
import time
from pathlib import Path

import encode_virat_archive as archive
import numpy as np

CHUNK = 1 << 20
VECTORS = "vectors.npz"
INFO = "info.json"


def fingerprint(path: Path) -> str:
    """The SHA-256 of the file's bytes, hex: what query computes as a file is stored."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def encode_upload(
    video: Path, out: Path, pipeline, settings: dict, pins: dict,
    frame_encoder, clip_encoder_module, clip_encoder, scratch: Path, *, log=print,
) -> dict:
    """Make `{out}/{fingerprint}/` for one video; returns a summary of it."""
    out.mkdir(parents=True, exist_ok=True)
    key = fingerprint(video)
    target = out / key
    if (target / INFO).is_file():
        info = json.loads((target / INFO).read_text())
        if (info["pins"], info["gate"]) != (pins, settings):
            raise RuntimeError(f"{key} ({video.name}) was made with other pins or settings; delete its folder to redo it")
        log(f"{video.name}: already ready ({key[:12]})")
        return {"video": video.name, "fingerprint": key, "skipped": True}
    start = time.perf_counter()
    result = archive.encode_video(video, pipeline, settings, frame_encoder, clip_encoder_module, clip_encoder, scratch / key)
    seconds = time.perf_counter() - start
    part = out / f"{key}.part"
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir()
    shutil.copyfile(video, part / video.name)
    np.savez(part / VECTORS, **result)
    reasons = result["admission_reason"]
    info = {
        "file": video.name,
        "fingerprint": key,
        "pins": pins,
        "gate": settings,
        "frames_decoded": int(result["frames_decoded"]),
        "admitted": len(reasons),
        "fps": float(result["fps"]),
        "duration_s": round(int(result["frames_decoded"]) / float(result["fps"]), 3),
    }
    (part / INFO).write_text(json.dumps(info, indent=1))
    shutil.rmtree(target, ignore_errors=True)  # an unfinished folder (no info.json) from a lost session
    part.rename(target)
    summary = {
        "video": video.name,
        "fingerprint": key,
        "skipped": False,
        "frames_decoded": info["frames_decoded"],
        "admitted": info["admitted"],
        "motion": int((reasons == "motion").sum()),
        "heartbeat": int((reasons == "heartbeat").sum()),
        "seconds": round(seconds, 1),
    }
    log(f"{video.name}: {summary['frames_decoded']} frames, {summary['admitted']} kept, {seconds:.0f} s -> {key}/")
    return summary
