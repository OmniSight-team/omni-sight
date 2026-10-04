"""What sixteen wall tiles polling one camera's preview cost (OMNI-503), on the
running stack.

Starts one simulator camera, then runs sixteen clients that each ask for
`GET /api/cameras/{id}/preview` once a second through nginx (the path the wall
will use), sending back the ETag they last got in `If-None-Match`. Three phases:

  idle    no polling, to see what query costs on its own
  live    the camera delivering frames: the preview is rewritten every 0.5 s,
          so most polls find a new frame and get a 200 with the JPEG
  frozen  the simulator paused (`docker compose pause mediamtx`): no new frame
          is written, so every poll after the first should be a 304 with no body

For each phase: requests, 200s and 304s, body bytes per second, header bytes per
second (approximate: status line and headers as received, no TLS or TCP), response
time, and query's CPU from `docker stats`. At the end the camera is stopped and the
preview must turn into a 404.

Needs the stack up (`docker compose up -d`). Run from the repo root:

  PYTHONPATH=services/query uv run --package omnisight-query python scripts/measure_preview_polling.py --camera cam05

Everything it creates (a throwaway admin, a camera, its frames) is removed at the
end, and the simulator is unpaused whatever happens.
"""

import argparse
import os
import random
import subprocess
import threading
import time
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User
from app.security import hash_password
from omnisight_common import Role

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--camera", default="cam05")
parser.add_argument("--clients", type=int, default=16)
parser.add_argument("--live-s", type=float, default=60.0)
parser.add_argument("--frozen-s", type=float, default=30.0)
parser.add_argument("--idle-s", type=float, default=20.0)
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "omni503-measure@omnisight.local"
PASSWORD = "Omni503Measure!"  # a throwaway account, deleted at the end
NAME = "omni503-measure"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


class CpuSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.samples: dict[str, list[float]] = {}

    def run(self):
        while not self.stop_flag.is_set():
            out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}}"],
                                 capture_output=True, text=True, env=ENV, check=False).stdout
            for line in out.splitlines():
                name, _, cpu = line.partition(" ")
                try:
                    self.samples.setdefault(name.replace("phase-b-", "").replace("-1", ""), []).append(float(cpu.strip("%")))
                except ValueError:
                    pass


class Tile(threading.Thread):
    """One wall tile: a poll a second, with the last ETag it got."""

    def __init__(self, token, camera_id, until):
        super().__init__(daemon=True)
        self.client = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=10)
        self.camera_id, self.until = camera_id, until
        self.etag = None
        self.results: list[tuple[int, int, int, float]] = []  # status, body bytes, header bytes, seconds

    def run(self):
        time.sleep(random.random())  # tiles do not all ask at the same instant
        next_at = time.monotonic()
        while time.monotonic() < self.until:
            headers = {"If-None-Match": self.etag} if self.etag else {}
            started = time.perf_counter()
            try:
                resp = self.client.get(f"/cameras/{self.camera_id}/preview", headers=headers)
            except httpx.HTTPError:
                self.results.append((0, 0, 0, time.perf_counter() - started))
            else:
                elapsed = time.perf_counter() - started
                header_bytes = len(f"HTTP/1.1 {resp.status_code}\r\n") + sum(
                    len(k) + len(v) + 4 for k, v in resp.headers.raw) + 2
                self.results.append((resp.status_code, len(resp.content), header_bytes, elapsed))
                if resp.status_code == 200:
                    self.etag = resp.headers.get("etag")
            next_at += 1.0
            time.sleep(max(0.0, next_at - time.monotonic()))
        self.client.close()


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, max(0, round(q * (len(v) - 1))))] if v else float("nan")


def phase(label, token, camera_id, seconds, *, poll=True):
    cpu = CpuSampler()
    cpu.start()
    tiles = []
    t0 = time.monotonic()
    if poll:
        tiles = [Tile(token, camera_id, t0 + seconds) for _ in range(ARGS.clients)]
        for tile in tiles:
            tile.start()
        for tile in tiles:
            tile.join()
    else:
        time.sleep(seconds)
    window = time.monotonic() - t0
    cpu.stop_flag.set()
    cpu.join()
    results = [r for tile in tiles for r in tile.results]
    q = cpu.samples.get("query", [0.0])
    ng = cpu.samples.get("nginx", [0.0])
    ing = cpu.samples.get("ingestion", [0.0])
    print(f"\n=== {label}: {window:.1f} s, {len(tiles)} clients")
    if results:
        ok = [r for r in results if r[0] == 200]
        nm = [r for r in results if r[0] == 304]
        other = [r for r in results if r[0] not in (200, 304)]
        body = sum(r[1] for r in results)
        head = sum(r[2] for r in results)
        times = [r[3] for r in results]
        print(f"  requests {len(results)} ({len(results) / window:.1f}/s): 200 {len(ok)}, 304 {len(nm)}, other {len(other)} {sorted({r[0] for r in other})}")
        print(f"  body {body / window / 1024:.1f} KiB/s (mean JPEG {sum(r[1] for r in ok) / max(len(ok), 1) / 1024:.1f} KiB, "
              f"304 bodies {sum(r[1] for r in nm)} bytes in total), headers {head / window / 1024:.2f} KiB/s")
        print(f"  response time p50 {pct(times, 0.5) * 1000:.0f} ms, p95 {pct(times, 0.95) * 1000:.0f} ms, max {max(times) * 1000:.0f} ms")
    print(f"  CPU (100% = one core): query avg {sum(q) / len(q):.1f}% max {max(q):.1f}%, "
          f"nginx avg {sum(ng) / len(ng):.1f}%, ingestion avg {sum(ing) / len(ing):.1f}%  ({len(q)} samples)")
    return results


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
    phase("idle: no camera, no polling", token, camera_id, ARGS.idle_s, poll=False)
    assert c.post(f"/cameras/{camera_id}/start").status_code == 200
    time.sleep(5)
    first = c.get(f"/cameras/{camera_id}/preview")
    print(f"\nfirst preview: {first.status_code}, {len(first.content)} bytes, ETag {first.headers.get('etag')}, "
          f"Last-Modified {first.headers.get('last-modified')}, Cache-Control {first.headers.get('cache-control')}")
    phase(f"capturing, no polling ({ARGS.camera})", token, camera_id, ARGS.idle_s, poll=False)
    phase(f"live: {ARGS.camera} delivering frames", token, camera_id, ARGS.live_s)

    dc("pause", "mediamtx")
    time.sleep(2)  # let the last frame before the pause be written
    phase("frozen: simulator paused, no new frame", token, camera_id, ARGS.frozen_s)
    dc("unpause", "mediamtx")

    c.post(f"/cameras/{camera_id}/stop")
    t_stop = time.monotonic()
    status_after = None
    while time.monotonic() - t_stop < 15:
        r = c.get(f"/cameras/{camera_id}/preview")
        status_after = (r.status_code, r.json().get("detail") if r.status_code == 404 else None)
        if r.status_code == 404:
            break
        time.sleep(0.25)
    print(f"\nafter stop: {status_after[0]} {status_after[1]!r} within {time.monotonic() - t_stop:.1f} s of the stop returning")
finally:
    dc("unpause", "mediamtx")
    if camera_id is not None:
        try:
            c.post(f"/cameras/{camera_id}/stop")
        except Exception:  # noqa: BLE001, S110 - cleanup must carry on
            pass
        time.sleep(3)  # let the queue empty, or the delete fails on the foreign key
        cleanup([camera_id])
    else:
        cleanup([])
    print("cleaned up")
