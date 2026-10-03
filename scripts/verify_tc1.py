"""TC-1 in full (OMNI-511): a live camera and an uploaded recording ingested at the
same time, keeping only frames with motion (or the heartbeat), with the camera wall
open. Checked on the running stack.

  1. Loops the archive's `Arson049` recording five times into one 1,930-frame file
     (as OMNI-316 did) and uploads it.
  2. Registers and starts `cam05` (by default; the realistic simulator set), and
     waits until it reads `live`.
  3. Starts the file's extraction and watches the camera for `--window` seconds
     (30 by default) from that moment, sampling `GET /cameras/live` every 0.5 s,
     and goes on watching until the extraction has finished.
  4. Stops the camera and checks, from the stored rows and the counters:
       file: `ready`, no error, every frame of the file stored (1,930 of 1,930);
             every admitted frame has a reason and its two image files; no
             discarded frame has a file; motion admissions at or above the gate's
             3 active cells, heartbeat ones below it, discarded ones below it
       live: the worker ran with no decode error; every stored row is admitted,
             with a reason and its files; the counters balance exactly
             (captured = gated + dropped, gated = admitted + discarded,
             admitted = motion + heartbeat) and match the stored rows
       wall: the camera read `live` at every sample, in the 30 s window and for
             the whole overlap with the extraction

Needs the stack up, at least one `ready` video (Arson049) in the archive, and the
wall open in a browser for the "with the wall open" part (the script cannot see
the browser; record the wall separately). Run from the repo root:

  PYTHONIOENCODING=utf-8 PYTHONPATH=services/query uv run --package omnisight-query python scripts/verify_tc1.py

Everything it creates (a throwaway admin, the camera, the uploaded video, their
frames) is removed at the end. Exits 1 if a check fails.
"""

import argparse
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import cv2
import httpx
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User, Video
from app.security import hash_password
from omnisight_common import Role
from sqlalchemy import text

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--camera", default="cam05")
parser.add_argument("--window", type=float, default=30.0)
parser.add_argument("--loops", type=int, default=5)
parser.add_argument("--min-active-cells", type=int, default=3)
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "omni511-verify@omnisight.local"
PASSWORD = "Omni511Verify!"  # a throwaway account, deleted at the end
NAME = "omni511-tc1"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
SCRATCH = Path(tempfile.mkdtemp(prefix="omni-tc1-"))
K = ARGS.min_active_cells


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def worker_snapshot(camera_id):
    out = dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c",
             "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())").stdout
    return next((w for w in json.loads(out or "[]") if w["camera_id"] == camera_id), None)


checks: list[tuple[str, bool, str]] = []


def check(label, ok, detail=""):
    checks.append((label, bool(ok), detail))
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")


class StateSampler(threading.Thread):
    def __init__(self, client, camera_id):
        super().__init__(daemon=True)
        self.client, self.camera_id = client, camera_id
        self.stop_flag = threading.Event()
        self.samples: list[tuple[float, str | None]] = []

    def run(self):
        while not self.stop_flag.is_set():
            at = time.time()
            try:
                item = next(i for i in self.client.get("/cameras/live").json() if i["camera_id"] == self.camera_id)
                self.samples.append((at, item["state"]))
            except Exception:  # noqa: BLE001 - a failed sample is recorded as such
                self.samples.append((at, None))
            time.sleep(max(0.0, 0.5 - (time.time() - at)))


def cleanup(camera_ids, video_ids, client):
    for vid in video_ids:
        try:
            client.delete(f"/videos/{vid}")
        except Exception:  # noqa: BLE001, S110 - cleanup must carry on
            pass
    for cid in camera_ids:
        try:
            client.post(f"/cameras/{cid}/stop")
        except Exception:  # noqa: BLE001, S110
            pass
    time.sleep(3)
    for cid in camera_ids:
        with SessionLocal() as s:
            s.query(Segment).filter_by(camera_id=cid).delete(synchronize_session=False)
            s.query(CameraStats).filter_by(camera_id=cid).delete(synchronize_session=False)
            s.query(Camera).filter_by(id=cid).delete(synchronize_session=False)
            s.commit()
        dc("exec", "-T", "ingestion", "sh", "-c", f"rm -rf /data/frames/camera-{cid} /data/thumbs/camera-{cid}")
    dc("exec", "-T", "ingestion", "sh", "-c", "rm -f /tmp/tc1-long.mp4")
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()


with SessionLocal() as s:
    s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()
camera_ids, video_ids = [], []
client = None
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, verify=False).json()["access_token"]
    client = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=180)

    # --- the recording: the archive's Arson049, looped --------------------------------------
    with SessionLocal() as s:
        source = s.query(Video).filter(Video.filename.like("Arson049%"), Video.status == "ready").first()
    if source is None:
        raise SystemExit("the archive has no ready Arson049 recording to loop")
    src = source.playback_path or source.path
    dc("exec", "-T", "ingestion", "sh", "-c",
       f"ffmpeg -y -loglevel error -stream_loop {ARGS.loops - 1} -i {src} -an -c:v libx264 -preset veryfast -crf 23 "
       f"-pix_fmt yuv420p /tmp/tc1-long.mp4")
    local = SCRATCH / "tc1-long.mp4"
    dc("cp", "ingestion:/tmp/tc1-long.mp4", str(local))
    cap = cv2.VideoCapture(str(local))
    frames_in_file = 0
    while cap.grab():
        frames_in_file += 1
    cap.release()
    with open(local, "rb") as fh:
        up = client.post("/videos/upload", files={"file": ("omni511-tc1.mp4", fh, "video/mp4")}).json()
    video_ids.append(up["id"])
    print(f"recording: {source.filename} looped x{ARGS.loops}: {frames_in_file} frames, uploaded as video {up['id']} ({up['status']})")

    # --- the camera --------------------------------------------------------------------------------
    camera_id = client.post("/cameras", json={"name": NAME, "rtsp_url": f"rtsp://mediamtx:8554/{ARGS.camera}",
                                              "location": "TC-1", "group": "TC-1", "domain": "surveillance"}).json()["id"]
    camera_ids.append(camera_id)
    r = client.post(f"/cameras/{camera_id}/start")
    assert r.status_code == 200, r.text
    deadline = time.time() + 60
    while time.time() < deadline:
        item = next(i for i in client.get("/cameras/live").json() if i["camera_id"] == camera_id)
        if item["state"] == "live":
            break
        time.sleep(0.5)
    time.sleep(3)
    print(f"camera: {ARGS.camera} as camera {camera_id}, live")

    # --- both at once ------------------------------------------------------------------------------
    sampler = StateSampler(client, camera_id)
    sampler.start()
    t0 = time.time()
    assert client.post(f"/videos/{video_ids[0]}/extract").status_code == 202
    while True:
        detail = client.get(f"/videos/{video_ids[0]}").json()
        if detail["status"] != "extracting":
            break
        time.sleep(0.5)
    t_done = time.time()
    while time.time() < t0 + ARGS.window:
        time.sleep(0.2)
    sampler.stop_flag.set()
    t_end = time.time()
    snap = worker_snapshot(camera_id)
    client.post(f"/cameras/{camera_id}/stop")
    time.sleep(6)  # the last frames and the final stats report
    stats = client.get(f"/cameras/{camera_id}/stats").json()
    print(f"extraction: {detail['status']} in {t_done - t0:.1f} s; window {ARGS.window:.0f} s from its start; "
          f"camera watched for {t_end - t0:.1f} s")

    in_window = [state for at, state in sampler.samples if t0 <= at < t0 + ARGS.window]
    in_overlap = [state for at, state in sampler.samples if t0 <= at < max(t_done, t0 + ARGS.window)]

    print("\nchecks")
    # both decode without error
    check("file: extraction finished `ready` with no error", detail["status"] == "ready" and not detail.get("error"),
          f"status {detail['status']}, error {detail.get('error')!r}")
    check("file: every frame decoded and stored", detail["segments_count"] == frames_in_file,
          f"{detail['segments_count']} of {frames_in_file}")
    check("live: the worker ran with no decode error", snap is not None and snap["decode_errors"] == 0
          and snap["status"] == "running", f"status {snap and snap['status']}, decode errors {snap and snap['decode_errors']}")

    with SessionLocal() as s:
        file_rows = s.execute(text(
            "select admitted, admission_reason::text as reason, motion_score, frame_path, thumb_path "
            "from segments where video_id = :v"), {"v": video_ids[0]}).all()
        live_rows = s.execute(text(
            "select admitted, admission_reason::text as reason, motion_score, frame_path, thumb_path, clip_start_s, clip_end_s "
            "from segments where camera_id = :c and video_id is null"), {"c": camera_id}).all()
    files_on_disk = int(dc("exec", "-T", "ingestion", "sh", "-c",
                           f"find /data/frames/{video_ids[0]} -name '*.jpg' | wc -l").stdout.strip() or 0)
    live_files = int(dc("exec", "-T", "ingestion", "sh", "-c",
                        f"find /data/frames/camera-{camera_id} -name '*.jpg' | wc -l").stdout.strip() or 0)

    # the file: OMNI-316's checks
    admitted = [r for r in file_rows if r.admitted]
    discarded = [r for r in file_rows if not r.admitted]
    motion = [r for r in admitted if r.reason == "motion"]
    heartbeat = [r for r in admitted if r.reason == "heartbeat"]
    print(f"  file: {len(file_rows)} frames gated, {len(admitted)} admitted ({len(motion)} motion, {len(heartbeat)} heartbeat), "
          f"{len(discarded)} discarded")
    check("file: every admitted frame has a reason", all(r.reason in ("motion", "heartbeat") for r in admitted))
    check("file: every admitted frame has its frame and thumbnail", all(r.frame_path and r.thumb_path for r in admitted)
          and files_on_disk == len(admitted), f"{files_on_disk} frame files for {len(admitted)} admitted")
    check("file: no discarded frame has a file", all(not r.frame_path and not r.thumb_path for r in discarded))
    check(f"file: motion admissions at or above {K} active cells", all((r.motion_score or 0) >= K for r in motion))
    check(f"file: heartbeat admissions and discarded frames below {K}",
          all(r.motion_score is None or r.motion_score < K for r in heartbeat + discarded))

    # live: OMNI-501's checks
    l_motion = [r for r in live_rows if r.reason == "motion"]
    l_heartbeat = [r for r in live_rows if r.reason == "heartbeat"]
    print(f"  live: {len(live_rows)} stored ({len(l_motion)} motion, {len(l_heartbeat)} heartbeat); counters {stats}")
    check("live: every stored row is admitted, with a reason", all(r.admitted for r in live_rows)
          and len(l_motion) + len(l_heartbeat) == len(live_rows))
    check("live: every stored row has its files and its clip", all(r.frame_path and r.thumb_path and r.clip_end_s for r in live_rows)
          and live_files == len(live_rows), f"{live_files} frame files for {len(live_rows)} rows")
    check("live: captured = gated + dropped", stats["captured"] == stats["gated"] + stats["dropped"],
          f"{stats['captured']} = {stats['gated']} + {stats['dropped']}")
    check("live: gated = admitted + discarded", stats["gated"] == stats["admitted"] + stats["discarded"],
          f"{stats['gated']} = {stats['admitted']} + {stats['discarded']}")
    check("live: admitted = motion + heartbeat, and equal to the stored rows",
          stats["admitted"] == stats["admitted_motion"] + stats["admitted_heartbeat"] == len(live_rows),
          f"{stats['admitted']} = {stats['admitted_motion']} + {stats['admitted_heartbeat']}; {len(live_rows)} rows")

    # the tile
    check(f"camera `live` at every sample of the {ARGS.window:.0f} s window", in_window and all(s == "live" for s in in_window),
          f"{len(in_window)} samples, states {sorted({str(s) for s in in_window})}")
    check("camera `live` for the whole time the file was extracting", in_overlap and all(s == "live" for s in in_overlap),
          f"{len(in_overlap)} samples over {max(t_done, t0 + ARGS.window) - t0:.1f} s")

    failed = [label for label, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
    print(f"window for the wall's recorder: unix {t0:.0f} to {t0 + ARGS.window:.0f}; extraction until {t_done:.0f}")
finally:
    if client is not None:
        cleanup(camera_ids, video_ids, client)
    (SCRATCH / "tc1-long.mp4").unlink(missing_ok=True)
    print("cleaned up")

raise SystemExit(1 if not checks or any(not ok for _, ok, _ in checks) else 0)
