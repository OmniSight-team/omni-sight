"""The VIRAT archive, both streams, cached and resumable (OMNI-708).

Run from `notebooks/virat_archive_gpu.ipynb` on Colab's GPU; the notebook clones the repo and
imports this file, so everything here is the repo's code: Algorithm 1 is ingestion's own
`pipeline.py` (loaded by path, `load_gate`), the encoders are ai_workers' (D-30, D-33).

For every video: decode every frame and gate it with `process_frame`, exactly as an upload is
extracted (`extract_file`); for every admitted frame,

- the SigLIP 2 frame vector, encoded from the JPEG `process_frame` wrote (as ai_workers
  encodes the stored frame, OMNI-704), 1152-D
- the InternVideo2 clip vector of its window `[t − 2Δ, t]`: the frames inside it
  (`window_span`), 8 spread evenly (`uniform_indices`), taken from the frames just decoded,
  512-D

Encoding runs on one background thread while the next frames are decoded and gated, so the
GPU and the CPU work at once; nothing is skipped or sampled.

Output, one file per video, `{out}/{clip_key}.npz`: `frame_index`, `timestamp_s`,
`admission_reason`, `motion_score`, `clip_start_s`, `clip_end_s`, `frame_vectors`,
`clip_vectors`, `fps`, `frames_decoded`. `{out}/manifest.json` is rewritten after every
video; a video is done when it is in the manifest and its file exists, and a rerun skips it,
so a lost session resumes where it stopped. The manifest also holds the pins and the gate's
settings; a rerun with different ones is refused rather than mixed into the same archive.

`match_product` (step 6) gives the product's own segments their archive vectors: the same
video gated by the same code with the same settings keeps the same frames, so each segment
is matched by `clip_key` and `frame_index`, and every one must be found.

Locally (correctness only, D-31): `uv run pytest scripts/tests`.
"""

import csv
import importlib.util
import json
import os
import shutil
import sys
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

GATE_SETTINGS = (
    "motion_stride_s",
    "motion_grid_size",
    "motion_cell_threshold",
    "motion_min_active_cells",
    "motion_blur_kernel",
    "heartbeat_interval_s",
)
FILE_SETTINGS = ("thumb_width_px", "frame_jpeg_quality", "thumb_jpeg_quality")
BATCH = 16  # items per encoder call; on the L4 a batch is no cheaper per item (OMNI-706)
MANIFEST = "manifest.json"


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_gate(repo: Path):
    """Ingestion's `pipeline` module and its settings' defaults (the values `.env.example`
    sets). Loaded by path: ingestion and ai_workers both name their package `app`.
    `settings.py` builds a Settings at import, which needs the broker login; there is no
    broker here, so placeholders (never used) let it load."""
    os.environ.setdefault("RABBITMQ_USER", "unused")
    os.environ.setdefault("RABBITMQ_PASSWORD", "unused")
    ingestion = repo / "services" / "ingestion" / "app"
    pipeline = _load_by_path("ingestion_pipeline", ingestion / "pipeline.py")
    fields = _load_by_path("ingestion_settings", ingestion / "settings.py").Settings.model_fields
    settings = {name: fields[name].default for name in GATE_SETTINGS + FILE_SETTINGS}
    return pipeline, settings


def new_gate(pipeline, settings: dict):
    """A fresh gate for one file, built as ingestion's `_gate_for` builds it: its buffer and
    heartbeat clock never cross from one video into another."""
    return pipeline.HeartbeatGate(
        pipeline.MotionGate(
            grid_size=settings["motion_grid_size"],
            cell_threshold=settings["motion_cell_threshold"],
            min_active_cells=settings["motion_min_active_cells"],
            stride_s=settings["motion_stride_s"],
            blur_kernel=settings["motion_blur_kernel"],
        ),
        heartbeat_interval_s=settings["heartbeat_interval_s"],
        stride_s=settings["motion_stride_s"],
        start_s=0.0,
    )


def encode_video(video: Path, pipeline, settings: dict, frame_encoder, clip_encoder_module, clip_encoder, scratch: Path) -> dict:
    """Gate every frame of one video and encode both streams of every admitted frame.
    `clip_encoder_module` is ai_workers' `clip_encoder` (its window and sampling functions),
    `clip_encoder` the loaded `ClipTextEncoder`."""
    import cv2

    window = clip_encoder_module
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise pipeline.ExtractError("could not open file")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        raise pipeline.ExtractError("could not determine frame rate")

    frames_dir, thumbs_dir = scratch / "frames", scratch / "thumbs"
    for directory in (frames_dir, thumbs_dir):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)

    gate = new_gate(pipeline, settings)
    # The frames a window can still reach: 2Δ of video, plus a margin.
    recent: deque[tuple[int, np.ndarray]] = deque(maxlen=int(2 * settings["motion_stride_s"] * fps) + 3)
    kept: list = []
    frame_paths: list[str] = []
    clips: list[list[np.ndarray]] = []
    frame_jobs: list[Future] = []
    clip_jobs: list[Future] = []
    worker = ThreadPoolExecutor(max_workers=1)

    def flush_clips() -> None:
        # At most two batches of full frames wait for the GPU at once, so memory stays bounded.
        if len(clip_jobs) >= 2:
            clip_jobs[-2].result()
        clip_jobs.append(worker.submit(clip_encoder.encode_clips, list(clips)))
        clips.clear()

    index = -1
    try:
        # Decoding as `extract_file` decodes: grab() False is the end of the file; a frame
        # grab() found that retrieve() cannot decode is an error, not the end.
        while capture.grab():
            index += 1
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                raise pipeline.ExtractError(f"could not decode frame {index}")
            recent.append((index, frame))
            record = pipeline.process_frame(
                frame,
                pipeline.FrameSource(source_type="upload", frame_index=index, timestamp_s=index / fps),
                gate,
                frames_dir,
                thumbs_dir,
                thumb_width=settings["thumb_width_px"],
                frame_quality=settings["frame_jpeg_quality"],
                thumb_quality=settings["thumb_jpeg_quality"],
            )
            if not record.admitted:
                continue
            kept.append(record)
            frame_paths.append(record.frame_path)
            first, last = window.window_span(record.clip_start_s, record.clip_end_s, fps)
            available = dict(recent)
            indices = window.uniform_indices(first, last)
            missing = [i for i in indices if i not in available]
            if missing:
                raise RuntimeError(f"frames {missing} of frame {index}'s window are no longer held")
            clips.append([cv2.cvtColor(available[i], cv2.COLOR_BGR2RGB) for i in indices])
            if len(clips) == BATCH:
                flush_clips()
            if len(frame_paths) % BATCH == 0:
                frame_jobs.append(worker.submit(frame_encoder.encode_images, frame_paths[-BATCH:]))
        if index < 0:
            raise pipeline.ExtractError("no frames could be read from file")
        if clips:
            flush_clips()
        if len(frame_paths) % BATCH:
            frame_jobs.append(worker.submit(frame_encoder.encode_images, frame_paths[-(len(frame_paths) % BATCH):]))
        frame_vectors = [job.result() for job in frame_jobs]
        clip_vectors = [job.result() for job in clip_jobs]
    finally:
        worker.shutdown(wait=True, cancel_futures=True)
        capture.release()
        shutil.rmtree(scratch, ignore_errors=True)

    def stack(parts: list[np.ndarray], dim: int) -> np.ndarray:
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, dim), np.float32)

    result = {
        "frame_index": np.array([r.frame_index for r in kept], np.int32),
        "timestamp_s": np.array([r.timestamp_s for r in kept], np.float64),
        "admission_reason": np.array([r.admission_reason for r in kept], dtype="U9"),
        "motion_score": np.array([np.nan if r.motion_score is None else r.motion_score for r in kept], np.float32),
        "clip_start_s": np.array([r.clip_start_s for r in kept], np.float64),
        "clip_end_s": np.array([r.clip_end_s for r in kept], np.float64),
        "frame_vectors": stack(frame_vectors, 1152),
        "clip_vectors": stack(clip_vectors, window.EMBEDDING_DIM),
        "fps": np.float64(fps),
        "frames_decoded": np.int64(index + 1),
    }
    if not (len(result["frame_vectors"]) == len(result["clip_vectors"]) == len(kept)):
        raise RuntimeError(f"{len(kept)} kept, {len(result['frame_vectors'])} frame and {len(result['clip_vectors'])} clip vectors")
    return result


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def read_manifest(out: Path) -> dict:
    path = out / MANIFEST
    return json.loads(path.read_text()) if path.is_file() else {}


def run(
    keys: list[str],
    video_dir: Path,
    out: Path,
    pipeline,
    settings: dict,
    pins: dict,
    frame_encoder,
    clip_encoder_module,
    clip_encoder,
    scratch: Path,
    *,
    session: str = "",
    log=print,
) -> dict:
    """Encode every video of `keys` not already done, in order; returns the manifest."""
    out.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(out) or {"pins": pins, "gate": settings, "videos": {}, "failed": {}}
    if manifest["pins"] != pins or manifest["gate"] != settings:
        raise RuntimeError(
            f"{out} was made with other pins or gate settings: {manifest['pins']}, {manifest['gate']}; "
            "an archive is never mixed"
        )
    done = {k for k in manifest["videos"] if (out / f"{k}.npz").is_file()}
    todo = [k for k in keys if k not in done]
    log(f"{len(done)} of {len(keys)} done already, {len(todo)} to go")
    for n, key in enumerate(todo, 1):
        start = time.perf_counter()
        try:
            result = encode_video(video_dir / f"{key}.mp4", pipeline, settings, frame_encoder, clip_encoder_module, clip_encoder, scratch / key)
        except Exception as exc:  # recorded, not hidden; a rerun tries it again
            manifest["failed"][key] = f"{type(exc).__name__}: {exc}"
            _write_json(out / MANIFEST, manifest)
            log(f"[{n}/{len(todo)}] {key}: FAILED {manifest['failed'][key]}")
            continue
        seconds = time.perf_counter() - start
        # The vectors first, then the manifest: a session lost between the two redoes this
        # video, never counts a missing file as done.
        tmp = out / f"{key}.tmp.npz"
        np.savez(tmp, **result)
        os.replace(tmp, out / f"{key}.npz")
        reasons = result["admission_reason"]
        manifest["failed"].pop(key, None)
        manifest["videos"][key] = {
            "frames_decoded": int(result["frames_decoded"]),
            "admitted": len(reasons),
            "motion": int((reasons == "motion").sum()),
            "heartbeat": int((reasons == "heartbeat").sum()),
            "fps": float(result["fps"]),
            "seconds": round(seconds, 1),
            "session": session,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _write_json(out / MANIFEST, manifest)
        v = manifest["videos"][key]
        log(
            f"[{n}/{len(todo)}] {key}: {v['frames_decoded']} frames, {v['admitted']} kept, {seconds:.0f} s "
            f"({v['frames_decoded'] / seconds:.0f} frames/s decoded, {v['admitted'] / seconds:.2f} kept/s encoded)"
        )
    return manifest


def check(keys: list[str], out: Path) -> dict:
    """Every video in the manifest once, with its file and the counts the file holds; none
    missing from `keys`. A dict cannot hold a key twice, so "encoded twice" shows as a
    file whose contents disagree with its entry, or a session that redid a finished video."""
    manifest = read_manifest(out)
    videos = manifest.get("videos", {})
    problems = []
    for key, entry in videos.items():
        path = out / f"{key}.npz"
        if not path.is_file():
            problems.append(f"{key}: in the manifest, no file")
            continue
        with np.load(path) as data:
            n = len(data["frame_index"])
            if not (n == entry["admitted"] == len(data["frame_vectors"]) == len(data["clip_vectors"])):
                problems.append(f"{key}: manifest says {entry['admitted']}, file holds {n}")
    missing = [k for k in keys if k not in videos]
    extra = sorted(p.stem for p in out.glob("*.npz") if p.stem not in videos and not p.stem.endswith(".tmp"))
    return {
        "videos": len(videos),
        "missing": missing,
        "failed": manifest.get("failed", {}),
        "files_not_in_manifest": extra,
        "problems": problems,
        "frames_decoded": sum(v["frames_decoded"] for v in videos.values()),
        "admitted": sum(v["admitted"] for v in videos.values()),
        "motion": sum(v["motion"] for v in videos.values()),
        "heartbeat": sum(v["heartbeat"] for v in videos.values()),
        "seconds": round(sum(v["seconds"] for v in videos.values()), 1),
        "sessions": sorted({v["session"] for v in videos.values()}),
    }


def match_product(segments_json: Path, archive: Path, out: Path) -> dict:
    """Step 6: the product's VIRAT segments (`export_segments_for_colab.py`) get their archive
    vectors, matched by `clip_key` and `frame_index`; the timestamp and the admission
    reason must agree too. Writes `{out}/{video_id}.npz` keyed by segment id. Where the
    export carries the laptop's own frame vector (OMNI-705), the cosine against the
    archive's is reported (step 7's agreement)."""
    export = json.loads(segments_json.read_text())
    by_video: dict[int, list[dict]] = {}
    for segment in export["segments"]:
        by_video.setdefault(segment["video_id"], []).append(segment)
    out.mkdir(parents=True, exist_ok=True)
    report = {"videos": {}, "unmatched": [], "agreement": []}
    for video_id, segments in sorted(by_video.items()):
        key = segments[0]["clip_key"]
        with np.load(archive / f"{key}.npz") as data:
            row_of = {int(i): r for r, i in enumerate(data["frame_index"])}
            rows, ids = [], []
            for s in segments:
                r = row_of.get(s["frame_index"])
                if (
                    r is None
                    or abs(float(data["timestamp_s"][r]) - s["timestamp_s"]) > 1e-6
                    or str(data["admission_reason"][r]) != s["admission_reason"]
                ):
                    report["unmatched"].append({"segment_id": s["segment_id"], "clip_key": key, "frame_index": s["frame_index"]})
                    continue
                rows.append(r)
                ids.append(s["segment_id"])
                if s.get("laptop_frame_vector") is not None:
                    laptop = np.asarray(s["laptop_frame_vector"], np.float32)
                    report["agreement"].append(
                        {"segment_id": s["segment_id"], "clip_key": key, "frame_index": s["frame_index"],
                         "cosine": float(laptop @ data["frame_vectors"][r])}
                    )
            np.savez(
                out / f"{video_id}.npz",
                segment_id=np.array(ids, np.int64),
                frame_vectors=data["frame_vectors"][rows],
                clip_vectors=data["clip_vectors"][rows],
            )
            report["videos"][video_id] = {
                "clip_key": key, "segments": len(segments), "matched": len(ids), "archive_frames": len(row_of),
            }
    return report


def evaluation_keys(repo: Path, first: list[str] = ()) -> list[str]:
    """The 275 VIRAT evaluation videos (`datasets/splits/virat.csv`, D-37), `first` at the
    front (the product's 9, so OMNI-710 can import them early)."""
    with open(repo / "datasets" / "splits" / "virat.csv", newline="") as f:
        keys = [row["clip_key"] for row in csv.DictReader(f) if row["split"] == "evaluation"]
    front = [k for k in first if k in keys]
    return front + [k for k in keys if k not in front]


def product_keys(repo: Path) -> list[str]:
    with open(repo / "datasets" / "demo" / "virat_sample.csv", newline="") as f:
        return [row["clip_key"] for row in csv.DictReader(f) if row["dataset"] == "virat"]
