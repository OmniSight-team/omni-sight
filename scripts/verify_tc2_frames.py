"""TC-2, frame half (OMNI-704): the admitted frames of a 30 s uploaded MP4 and of 30 s from a
live camera each encode to one 1152-D, unit-length SigLIP 2 vector, with no error.

  1. Cuts the first 30 s of a VIRAT demo video (default 3229, scene 0102, the one with the
     most motion admissions) into a new H.264 MP4, uploads it through nginx and extracts it
     (Algorithm 1, the product's own path), waits for `ready`.
  2. Registers `cam05` (the realistic simulator set), starts it, waits for `live`, captures
     30 s, stops it.
  3. Reads every admitted frame's `frame_path` from Postgres, for both.
  4. Stops the `ai-workers` service and encodes every one of those frames in a one-off
     container of the same image, code and mounts (one copy of the model in memory, not
     two), batches of 8, from the stored JPEG, with `FrameTextEncoder.encode_images`; then
     starts the service again. Each frame's vector is checked: 1152 dimensions, finite,
     length 1 within 1e-5; a batch that raises is recorded as an error for its frames.

Run from the repo root with the stack up:

  PYTHONIOENCODING=utf-8 PYTHONPATH=services/query uv run --package omnisight-query python scripts/verify_tc2_frames.py

Everything it creates (a throwaway admin, the camera, the uploaded video, their frames) is
removed at the end. Exits 1 if a check fails.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}


# --- inside the one-off ai-workers container ------------------------------------------------


def _encode(listing: str) -> None:
    sys.path.insert(0, "/workspace/services/ai_workers")
    import numpy as np

    from app.encoder import EMBEDDING_DIM, FrameTextEncoder, ensure_checkpoint
    from app.settings import settings

    frames = json.loads(Path(listing).read_text())
    encoder = FrameTextEncoder(ensure_checkpoint(settings.frame_model_id, settings.frame_model_revision, settings.frame_model_dir))
    results = []
    for source, items in frames.items():
        started = time.perf_counter()
        for i in range(0, len(items), 8):
            batch = items[i : i + 8]
            try:
                vectors = encoder.encode_images([path for _, path in batch])
            except Exception as exc:  # noqa: BLE001 - recorded per frame, the run carries on
                results += [{"source": source, "segment_id": sid, "error": repr(exc)} for sid, _ in batch]
                continue
            for (sid, _), vector in zip(batch, vectors, strict=True):
                results.append({"source": source, "segment_id": sid, "dim": int(vector.shape[0]),
                                "norm": float(np.linalg.norm(vector)), "finite": bool(np.all(np.isfinite(vector))),
                                "expected_dim": EMBEDDING_DIM})
        print(json.dumps({"timing": source, "frames": len(items), "seconds": round(time.perf_counter() - started, 1)}), flush=True)
    print(json.dumps({"results": results}), flush=True)


# --- on the host ----------------------------------------------------------------------------


def dc(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False, **kwargs)


def main() -> int:
    import httpx
    from app.db import SessionLocal
    from app.models import Camera, CameraStats, Segment, User, Video
    from app.security import hash_password
    from omnisight_common import Role
    from sqlalchemy import text

    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=int, default=3229)
    parser.add_argument("--camera", default="cam05")
    parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args()
    base = "https://localhost/api"
    email, password = "omni704-verify@omnisight.local", "Omni704Verify!"  # throwaway, deleted at the end
    scratch = Path(tempfile.mkdtemp(prefix="omni-tc2-"))
    checks: list[tuple[str, bool]] = []

    def check(label, ok, detail=""):
        checks.append((label, bool(ok)))
        print(f"  [{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")

    with SessionLocal() as s:
        s.query(User).filter_by(email=email).delete(synchronize_session=False)
        s.add(User(email=email, password_hash=hash_password(password), role=Role.ADMIN, is_active=True))
        s.commit()
    camera_ids, video_ids = [], []
    client = None
    try:
        token = httpx.post(f"{base}/auth/login", json={"email": email, "password": password}, verify=False).json()["access_token"]
        client = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=300)

        # --- the 30 s upload ------------------------------------------------------------------
        with SessionLocal() as s:
            source = s.get(Video, args.video)
        if source is None or source.status != "ready":
            raise SystemExit(f"video {args.video} is not a ready video in the archive")
        dc("exec", "-T", "ingestion", "sh", "-c",
           f"ffmpeg -y -loglevel error -i {source.path} -t {args.seconds} -an -c:v libx264 -preset veryfast -crf 23 "
           f"-pix_fmt yuv420p /tmp/tc2.mp4")
        local = scratch / "tc2.mp4"
        dc("cp", "ingestion:/tmp/tc2.mp4", str(local))
        with open(local, "rb") as fh:
            up = client.post("/videos/upload", files={"file": ("omni704-tc2.mp4", fh, "video/mp4")}).json()
        video_ids.append(up["id"])
        assert client.post(f"/videos/{up['id']}/extract").status_code == 202
        while (detail := client.get(f"/videos/{up['id']}").json())["status"] == "extracting":
            time.sleep(0.5)
        print(f"upload: first {args.seconds:.0f} s of {source.filename} as video {up['id']}, {detail['status']}, "
              f"{detail['duration_s']} s, {detail['segments_count']} frames gated")

        # --- 30 s of a live camera ------------------------------------------------------------
        camera_id = client.post("/cameras", json={"name": "omni704-tc2", "rtsp_url": f"rtsp://mediamtx:8554/{args.camera}",
                                                  "location": "TC-2", "group": "TC-2", "domain": "surveillance"}).json()["id"]
        camera_ids.append(camera_id)
        assert client.post(f"/cameras/{camera_id}/start").status_code == 200
        deadline = time.time() + 60
        while time.time() < deadline:
            if next(i for i in client.get("/cameras/live").json() if i["camera_id"] == camera_id)["state"] == "live":
                break
            time.sleep(0.5)
        time.sleep(args.seconds)
        client.post(f"/cameras/{camera_id}/stop")
        time.sleep(6)  # the last frames reach the database
        print(f"camera: {args.camera} as camera {camera_id}, captured {args.seconds:.0f} s")

        with SessionLocal() as s:
            upload_rows = s.execute(text("select id, frame_path from segments where video_id = :v and admitted order by id"),
                                    {"v": up["id"]}).all()
            live_rows = s.execute(text("select id, frame_path from segments where camera_id = :c and video_id is null "
                                       "and admitted order by id"), {"c": camera_id}).all()
        listing = scratch / "frames.json"
        listing.write_text(json.dumps({"upload": [list(r) for r in upload_rows], "camera": [list(r) for r in live_rows]}))
        print(f"admitted frames: upload {len(upload_rows)}, camera {len(live_rows)}")

        # --- encode them ------------------------------------------------------------------------
        subprocess.run(["docker", "compose", "stop", "ai-workers"], cwd=ROOT, env=ENV, check=True)
        try:
            run = subprocess.run(
                ["docker", "compose", "run", "--rm", "-T", "--no-deps", "-v", f"{scratch}:/tc2:ro", "ai-workers",
                 "/workspace/.venv/bin/python", "-", "encode", "/tc2/frames.json"],
                cwd=ROOT, env=ENV, input=Path(__file__).read_text(encoding="utf-8"), capture_output=True,
                # Not the Windows code page: the container's log lines are UTF-8.
                encoding="utf-8", errors="replace",
            )
        finally:
            subprocess.run(["docker", "compose", "start", "ai-workers"], cwd=ROOT, env=ENV, check=True)
        records = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        for record in records:
            if "timing" in record:
                print(f"encoded {record['frames']} {record['timing']} frames in {record['seconds']} s")
        results = next((r["results"] for r in records if "results" in r), None)
        if results is None:
            print(run.stderr[-3000:])
            check("the encoder ran", False)
            return 1

        print("\nchecks")
        for source_name, rows in (("upload", upload_rows), ("camera", live_rows)):
            mine = [r for r in results if r["source"] == source_name]
            errors = [r for r in mine if "error" in r]
            good = [r for r in mine if "error" not in r and r["dim"] == 1152 and r["finite"] and abs(r["norm"] - 1) <= 1e-5]
            norms = [r["norm"] for r in mine if "norm" in r]
            check(f"{source_name}: has admitted frames", len(rows) > 0, f"{len(rows)}")
            check(f"{source_name}: one vector per admitted frame", sorted(r["segment_id"] for r in mine) == [r[0] for r in rows],
                  f"{len(mine)} of {len(rows)}")
            check(f"{source_name}: no error", not errors, f"{len(errors)} errors" + (f", first {errors[0]['error']}" if errors else ""))
            check(f"{source_name}: every vector 1152-D, finite, unit length", len(good) == len(rows),
                  f"{len(good)} of {len(rows)}; norms {min(norms):.7f}..{max(norms):.7f}" if norms else "")
        failed = [label for label, ok in checks if not ok]
        print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
        return 1 if failed else 0
    finally:
        if client:
            # Encoding on a CPU outlasts the token's 15 idle minutes (NFR-9): log in again,
            # or the deletes below are refused and the upload is left behind.
            token = httpx.post(f"{base}/auth/login", json={"email": email, "password": password}, verify=False).json()["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
        for vid in video_ids:
            if client:
                r = client.delete(f"/videos/{vid}")
                if r.status_code != 200:
                    print(f"cleanup: deleting video {vid} answered {r.status_code}; delete it by hand")
        for cid in camera_ids:
            if client:
                client.post(f"/cameras/{cid}/stop")
            time.sleep(3)
            with SessionLocal() as s:
                s.query(Segment).filter_by(camera_id=cid).delete(synchronize_session=False)
                s.query(CameraStats).filter_by(camera_id=cid).delete(synchronize_session=False)
                s.query(Camera).filter_by(id=cid).delete(synchronize_session=False)
                s.commit()
            dc("exec", "-T", "ingestion", "sh", "-c", f"rm -rf /data/frames/camera-{cid} /data/thumbs/camera-{cid}")
        dc("exec", "-T", "ingestion", "sh", "-c", "rm -f /tmp/tc2.mp4")
        with SessionLocal() as s:
            s.query(User).filter_by(email=email).delete(synchronize_session=False)
            s.commit()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "encode":
        _encode(sys.argv[2])
    else:
        sys.exit(main())
