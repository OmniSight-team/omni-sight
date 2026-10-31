"""NFR-1 (OMNI-714): from capture, searchable in under 5 seconds, on the running stack.

**`--gpu` (D-31, the combined figure):** one camera, 10 minutes. ai_workers' own `EmbedWorker` consumes the
real embed queue, batching and acknowledging as it does in the product, and upserts into a scratch
collection on the real Qdrant; only its encoder is a stand-in that takes the GPU's measured time
(OMNI-706, L4, 108 ms a frame) and returns a unit vector. So queueing, batching and the upsert are measured,
and the encode is the GPU's. Labelled so: this laptop has no GPU.

**`--cpu` (information, D-31):** the same camera for a short window with the real ai_workers and its real
encoder, into the real `frame_vectors`; a frame counts as searchable when its point is first seen.

For each frame, all on one clock (the containers share the Docker VM's):

    capture   = the frame's `timestamp_s`
    stored    = `segments.created_at`
    batched   = the batch closed and its encode began
    upserted  = Qdrant applied the batch's points (`wait=True`); the frame is searchable

Everything it creates is removed at the end: the camera, its rows and files, the scratch collection or the
points. For `--gpu`, ai_workers is stopped during the run and started again. From the repo root:

    uv run python scripts/measure_nfr1.py --gpu --seconds 600 --out <file.json>
    uv run python scripts/measure_nfr1.py --cpu --seconds 20 --out <file.json>
"""

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = "cam05"  # the camera of the earlier live measurements, with still stretches (OMNI-501)
SCRATCH = "frame_vectors_nfr1"
GPU_S_PER_FRAME = 0.108  # OMNI-706: SigLIP 2, NVIDIA L4, batch 1 (106 ms at batch 8)
API = "http://localhost:8000"
TARGET_S = 5.0
DRAIN_QUIET_S = 20.0
FIRST_JOB_LIMIT_S = 180.0
CPU_DRAIN_LIMIT_S = 1800.0
PYTHON = "/workspace/.venv/bin/python"


# --- inside ai_workers' image: the real worker with a stand-in encoder --------------------


def _worker_inside(seconds: float) -> None:
    sys.path.insert(0, "/workspace/services/ai_workers")
    import numpy as np
    from app.embed_worker import EmbedWorker
    from app.settings import settings
    from omnisight_common import connection_parameters
    from omnisight_common.frame_vectors import FRAME_VECTOR_SIZE, qdrant_client

    records: dict[int, dict] = {}
    pending: list[float] = []
    last_job = [time.time()]

    class GpuTimedEncoder:
        def encode_images(self, paths):
            pending.append(time.time())
            time.sleep(GPU_S_PER_FRAME * len(paths))
            vectors = np.zeros((len(paths), FRAME_VECTOR_SIZE), np.float32)
            vectors[:, 0] = 1.0
            return vectors

    class TimedQdrant:
        """The real client; `upsert` is timed, per point."""

        def __init__(self, client) -> None:
            self.client = client

        def __getattr__(self, name):
            return getattr(self.client, name)

        def upsert(self, **kwargs):
            started = time.time()
            result = self.client.upsert(**kwargs)
            finished = time.time()
            batched = pending.pop() if pending else started
            for point in kwargs["points"]:
                records[int(point.id)] = {
                    "capture": point.payload["timestamp_s"], "batched": batched, "upsert_start": started,
                    "upserted": finished, "batch_size": len(kwargs["points"]),
                }
            last_job[0] = finished
            return result

        def close(self):
            self.client.close()

    worker = EmbedWorker(
        GpuTimedEncoder(),
        lambda: TimedQdrant(qdrant_client(settings)),
        connection_params=connection_parameters(settings),
        queue=settings.embed_queue,
        collection=SCRATCH,
        model=settings.frame_model_id,
        model_revision=settings.frame_model_revision,
        batch_size=settings.embed_batch_size,
        batch_wait_s=settings.embed_batch_wait_s,
    )
    print("worker ready", file=sys.stderr, flush=True)
    worker.start()
    started = time.time()
    time.sleep(seconds)
    # The camera starts after this worker: it waits for the first job, then for the queue to go quiet.
    while (not records and time.time() - started < seconds + FIRST_JOB_LIMIT_S) or (records and time.time() - last_job[0] < DRAIN_QUIET_S):
        time.sleep(1)
    worker.stop(30)
    with __import__("contextlib").closing(qdrant_client(settings)) as client:
        client.delete_collection(SCRATCH)
    sys.stdout.write(json.dumps({"records": records, "dead_lettered": worker.dead_lettered, "embedded": worker.embedded}))


# --- inside query's image: the camera, the rows, the cleanup ----------------------------


def _control_inside(seconds: float, poll_real: bool, feed: str) -> None:
    import os
    import urllib.request

    sys.path.insert(0, "/workspace/services/query")
    from app.db import SessionLocal
    from app.models import Camera, CameraStats, Segment
    from app.settings import settings
    from omnisight_common.frame_vectors import qdrant_client
    from qdrant_client import models
    from sqlalchemy import text

    def call(method: str, path: str, body=None, token=None):
        request = urllib.request.Request(
            API + path, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    token = call("POST", "/auth/login", {"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})["access_token"]
    camera_id = call("POST", "/cameras", {"name": "omni714-nfr1", "rtsp_url": f"rtsp://mediamtx:8554/{feed}", "location": "sim", "group": "sim", "domain": "surveillance"}, token)["id"]
    seen: dict[int, float] = {}
    qdrant = qdrant_client(settings)

    def poll_points() -> None:
        matching = models.Filter(must=[models.FieldCondition(key="camera_id", match=models.MatchValue(value=camera_id))])
        offset = None
        while True:
            points, offset = qdrant.scroll(settings.frame_collection, scroll_filter=matching, limit=1000, offset=offset, with_payload=False)
            now = time.time()
            for point in points:
                seen.setdefault(int(point.id), now)
            if offset is None:
                return

    try:
        call("POST", f"/cameras/{camera_id}/start", token=token)
        started = time.time()
        while time.time() - started < seconds:
            time.sleep(1)
            if poll_real:
                poll_points()
        stats = call("GET", f"/cameras/{camera_id}/stats", token=token)
        call("POST", f"/cameras/{camera_id}/stop", token=token)
        time.sleep(3)
        if poll_real:
            with SessionLocal() as s:
                total = s.query(Segment).filter_by(camera_id=camera_id, admitted=True).count()
            drain_started = time.time()
            while len(seen) < total and time.time() - drain_started < CPU_DRAIN_LIMIT_S:
                poll_points()
                time.sleep(1)
        with SessionLocal() as s:
            rows = s.execute(
                text("select id, timestamp_s, extract(epoch from created_at) as stored, admission_reason::text as reason "
                     "from segments where camera_id = :c and video_id is null and admitted"),
                {"c": camera_id},
            ).all()
        sys.stdout.write(json.dumps({
            "camera_id": camera_id,
            "stats": stats,
            "window": [started, started + seconds],
            "rows": [{"id": r.id, "capture": r.timestamp_s, "stored": float(r.stored), "reason": r.reason} for r in rows],
            "seen": seen,
        }))
    finally:
        try:
            call("POST", f"/cameras/{camera_id}/stop", token=token)
        except Exception:  # noqa: BLE001, S110 - cleanup must carry on
            pass
        time.sleep(2)
        qdrant.delete(settings.frame_collection, models.Filter(must=[models.FieldCondition(key="camera_id", match=models.MatchValue(value=camera_id))]))
        qdrant.close()
        with SessionLocal() as s:
            s.query(Segment).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(CameraStats).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
            s.commit()


# --- on the host ------------------------------------------------------------------------


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values), "min": round(min(values), 3), "p50": round(_percentile(values, 0.5), 3),
        "p95": round(_percentile(values, 0.95), 3), "p99": round(_percentile(values, 0.99), 3), "max": round(max(values), 3),
    }


def gpu_report(control: dict, worker: dict) -> dict:
    """Per frame, the stages and the total, and whether the second half trends above the first."""
    records = {int(k): v for k, v in worker["records"].items()}
    frames = []
    for row in control["rows"]:
        record = records.get(row["id"])
        if record is not None:
            frames.append({**row, **record})
    frames.sort(key=lambda f: f["capture"])
    total = [f["upserted"] - f["capture"] for f in frames]
    middle = len(frames) // 2
    return {
        "frames_stored": len(control["rows"]),
        "frames_with_a_point": len(frames),
        "dead_lettered": worker["dead_lettered"],
        "capture_to_stored_s": stats([f["stored"] - f["capture"] for f in frames]),
        "stored_to_batched_s": stats([f["batched"] - f["stored"] for f in frames]),
        "batched_to_upsert_s": stats([f["upsert_start"] - f["batched"] for f in frames]),
        "upsert_s": stats([f["upserted"] - f["upsert_start"] for f in frames]),
        "capture_to_searchable_s": stats(total),
        "first_half_s": stats(total[:middle]),
        "second_half_s": stats(total[middle:]),
        "batch_size": stats([float(f["batch_size"]) for f in frames]),
        "over_target": sum(t >= TARGET_S for t in total),
        "passed": bool(total) and max(total) < TARGET_S and len(frames) == len(control["rows"]),
        "camera_stats": control["stats"],
    }


def cpu_report(control: dict) -> dict:
    seen = {int(k): v for k, v in control["seen"].items()}
    rows = sorted(control["rows"], key=lambda r: r["capture"])
    latency = [seen[r["id"]] - r["capture"] for r in rows if r["id"] in seen]
    return {
        "frames_stored": len(rows),
        "frames_with_a_point": len(latency),
        "capture_to_stored_s": stats([r["stored"] - r["capture"] for r in rows]),
        "capture_to_searchable_s": stats(latency),
        "first_frames_s": [round(x, 1) for x in latency[:5]],
        "last_frames_s": [round(x, 1) for x in latency[-5:]],
        "camera_stats": control["stats"],
    }


def _inside(service_args: list[str], flag: list[str], **kwargs) -> subprocess.Popen:
    return subprocess.Popen(
        ["docker", "compose", *service_args, "-T", *kwargs.pop("target"), PYTHON, "-", *flag],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )


def _run(process: subprocess.Popen, label: str) -> dict:
    script = Path(__file__).read_text(encoding="utf-8")
    output, errors = process.communicate(script)
    if process.returncode != 0:
        raise RuntimeError(f"{label} failed: {errors[-1500:]}")
    return json.loads(output)


def _remove_files(camera_id: int) -> None:
    subprocess.run(
        ["docker", "compose", "exec", "-T", "ingestion", "sh", "-c", f"rm -rf /data/frames/camera-{camera_id} /data/thumbs/camera-{camera_id}"],
        cwd=ROOT, check=False, capture_output=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--gpu", action="store_true")
    group.add_argument("--cpu", action="store_true")
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--feed", default=FEED, help="simulator path; cam01 is constant motion, the heavy case")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    seconds = str(args.seconds)

    if args.cpu:
        control = _run(_inside(["exec"], ["--control", seconds, args.feed, "--poll-real"], target=["query"]), "control")
        _remove_files(control["camera_id"])
        report = cpu_report(control)
    else:
        subprocess.run(["docker", "compose", "stop", "ai-workers"], cwd=ROOT, check=True, capture_output=True)
        try:
            worker_process = _inside(["run", "--rm", "--no-deps"], ["--worker", seconds], target=["ai-workers"])
            holder: dict = {}
            thread = threading.Thread(target=lambda: holder.update(worker=_run(worker_process, "worker")))
            thread.start()
            time.sleep(20)  # the stand-in worker is connected before the camera starts
            control = _run(_inside(["exec"], ["--control", seconds, args.feed], target=["query"]), "control")
            thread.join()
            _remove_files(control["camera_id"])
            report = gpu_report(control, holder["worker"])
        finally:
            subprocess.run(["docker", "compose", "start", "ai-workers"], cwd=ROOT, check=False, capture_output=True)

    args.out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        _worker_inside(float(sys.argv[2]))
        sys.exit(0)
    if sys.argv[1:2] == ["--control"]:
        _control_inside(float(sys.argv[2]), "--poll-real" in sys.argv, sys.argv[3])
        sys.exit(0)
    sys.exit(main())
