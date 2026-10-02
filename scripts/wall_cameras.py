"""Put the simulator's ten feeds on the camera wall, or take them off again
(OMNI-506 onwards).

  up    registers `cam01` ... `cam10` as cameras named `wall-cam01` ...,
        `cam01`-`cam05` in group "Building A" and `cam06`-`cam10` in "Building B",
        and starts every one (ten starts in parallel, since each waits for the
        stream's first frame)
  down  stops them and removes them, their frames and their stats

Uses a throwaway admin account of its own, created and removed by each run, so
nothing here needs anyone's password. Needs the stack up (`docker compose up -d`).
Run from the repo root:

  PYTHONPATH=services/query uv run --package omnisight-query python scripts/wall_cameras.py up
  PYTHONPATH=services/query uv run --package omnisight-query python scripts/wall_cameras.py down
"""

import argparse
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User
from app.security import hash_password
from omnisight_common import Role

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("action", choices=("up", "down"))
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "wall-setup@omnisight.local"
PASSWORD = "WallSetup506!"  # a throwaway account, deleted at the end of every run
PREFIX = "wall-"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
FEEDS = [f"cam{n:02d}" for n in range(1, 11)]


def group_of(feed: str) -> str:
    return "Building A" if int(feed[3:]) <= 5 else "Building B"


with SessionLocal() as s:
    s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, verify=False).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=90)
    with SessionLocal() as s:
        existing = {cam.name: cam.id for cam in s.query(Camera).filter(Camera.name.like(f"{PREFIX}%"))}

    if ARGS.action == "up":
        ids = {}
        for feed in FEEDS:
            name = f"{PREFIX}{feed}"
            if name in existing:
                ids[feed] = existing[name]
                continue
            ids[feed] = c.post("/cameras", json={
                "name": name, "rtsp_url": f"rtsp://mediamtx:8554/{feed}",
                "location": f"{group_of(feed)}, {feed}", "group": group_of(feed), "domain": "surveillance",
            }).json()["id"]

        def start(feed):
            began = time.time()
            r = c.post(f"/cameras/{ids[feed]}/start")
            return feed, r.status_code, r.json().get("detail") if r.status_code != 200 else None, time.time() - began

        with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
            for feed, code, detail, took in pool.map(start, FEEDS):
                print(f"{feed}: camera {ids[feed]}, start {code} in {took:.1f} s" + (f" ({detail})" if detail else ""))
    else:
        for name, camera_id in sorted(existing.items()):
            c.post(f"/cameras/{camera_id}/stop")
        time.sleep(5)  # let the live queue empty, or the delete fails on the foreign key
        for name, camera_id in sorted(existing.items()):
            with SessionLocal() as s:
                s.query(Segment).filter_by(camera_id=camera_id).delete(synchronize_session=False)
                s.query(CameraStats).filter_by(camera_id=camera_id).delete(synchronize_session=False)
                s.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
                s.commit()
            subprocess.run(["docker", "compose", "exec", "-T", "ingestion", "sh", "-c",
                            f"rm -rf /data/frames/camera-{camera_id} /data/thumbs/camera-{camera_id}"],
                           cwd=ROOT, capture_output=True, env=ENV, check=False)
            print(f"{name}: stopped and removed")
finally:
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()
