"""The rewind buffer after five minutes of capture (OMNI-505), on the running stack.

Captures one simulator feed for `--capture-s` (300 by default), then asks
`GET /api/cameras/{id}/buffer?minutes=5` through nginx, as the wall will, and
checks that it holds at least `--min-frames` (300: the heartbeat alone admits one
a second), oldest first, every frame inside the window, every one with a reason,
and that each `frame_url` it was given serves the full frame with the token
(sampled) and not without it. Also asks for one minute and for ten, and reports
the response size and time.

Needs the stack up (`docker compose up -d`). Run from the repo root:

  PYTHONPATH=services/query uv run --package omnisight-query python scripts/verify_rewind_buffer.py --camera cam05

Everything it creates (a throwaway admin, a camera, its frames) is removed at the
end. Exits 1 if a check fails.
"""

import argparse
import itertools
import os
import random
import subprocess
import time
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User
from app.security import hash_password
from omnisight_common import Role

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--camera", default="cam05")
parser.add_argument("--capture-s", type=float, default=300.0)
parser.add_argument("--min-frames", type=int, default=300)
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "omni505-verify@omnisight.local"
PASSWORD = "Omni505Verify!"  # a throwaway account, deleted at the end
NAME = "omni505-verify"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def cleanup(camera_ids):
    for camera_id in camera_ids:
        with SessionLocal() as s:
            s.query(Segment).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(CameraStats).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
            s.commit()
        dc("exec", "-T", "ingestion", "sh", "-c", f"rm -rf /data/frames/camera-{camera_id} /data/thumbs/camera-{camera_id}")
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()


checks: list[tuple[str, bool, str]] = []


def check(label, ok, detail=""):
    checks.append((label, bool(ok), detail))
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")


with SessionLocal() as s:
    leftovers = [row.id for row in s.query(Camera).filter_by(name=NAME)]
cleanup(leftovers)
with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()

camera_id = None
c = None
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, verify=False).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=60)
    camera_id = c.post("/cameras", json={"name": NAME, "rtsp_url": f"rtsp://mediamtx:8554/{ARGS.camera}",
                                         "location": "sim", "group": "sim", "domain": "surveillance"}).json()["id"]
    assert c.post(f"/cameras/{camera_id}/start").status_code == 200
    started_at = time.time()
    print(f"capturing {ARGS.camera} for {ARGS.capture_s:.0f} s")
    time.sleep(ARGS.capture_s)
    time.sleep(2)  # the last frames through the live queue

    for minutes in (1, 5, 10):
        t0 = time.time()
        resp = c.get(f"/cameras/{camera_id}/buffer", params={"minutes": minutes})
        took = time.time() - t0
        asked_at = t0
        body = resp.json()
        times = [f["timestamp_s"] for f in body]
        reasons = [f["reason"] for f in body]
        gaps = [b - a for a, b in itertools.pairwise(times)]
        print(f"\nminutes={minutes}: {resp.status_code}, {len(body)} frames "
              f"({reasons.count('motion')} motion, {reasons.count('heartbeat')} heartbeat), "
              f"{len(resp.content) / 1024:.0f} KiB, {took * 1000:.0f} ms"
              + (f", oldest {asked_at - times[0]:.1f} s ago, newest {asked_at - times[-1]:.1f} s ago, largest gap {max(gaps):.2f} s"
                 if len(times) > 1 else ""))
        window_s = minutes * 60
        check(f"[{minutes} min] oldest first", times == sorted(times))
        check(f"[{minutes} min] none outside the window",
              all(asked_at - window_s - 1.0 <= t <= asked_at for t in times),
              f"oldest {asked_at - times[0]:.1f} s ago against a {window_s} s window" if times else "empty")
        check(f"[{minutes} min] every frame has a reason", all(r in ("motion", "heartbeat") for r in reasons))
        if minutes == 5:
            check("[5 min] at least 300 frames after 5 minutes of capture", len(body) >= ARGS.min_frames,
                  f"{len(body)} frames, capture began {asked_at - started_at:.0f} s before the request")
            sample = random.Random(5).sample(body, min(20, len(body)))
            statuses = []
            for frame in sample:
                r = c.get(frame["frame_url"])
                statuses.append((r.status_code, r.headers.get("content-type"), r.content[:2] == b"\xff\xd8"))
            check("[5 min] frame_url serves the full JPEG with the token (20 sampled)",
                  all(s == (200, "image/jpeg", True) for s in statuses), f"{sorted(set(statuses))}")
            no_token = httpx.get(f"{BASE}{body[0]['frame_url']}", verify=False).status_code
            check("[5 min] and not without it", no_token == 401, f"{no_token}")
            thumb = httpx.get(f"https://localhost{body[0]['thumb_url']}", verify=False)
            print(f"  thumb_url through nginx: {thumb.status_code} {thumb.headers.get('content-type')} (no token, K-3)")

    failed = [label for label, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
finally:
    if camera_id is not None:
        try:
            c.post(f"/cameras/{camera_id}/stop")
        except Exception:  # noqa: BLE001, S110 - cleanup must carry on
            pass
        time.sleep(3)
        cleanup([camera_id])
    else:
        cleanup([])
    print("cleaned up")

raise SystemExit(1 if not checks or any(not ok for _, ok, _ in checks) else 0)
