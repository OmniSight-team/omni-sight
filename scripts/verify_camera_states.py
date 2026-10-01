"""Camera states from evidence, and capture that resumes by itself (OMNI-504),
checked on the running stack.

Starts one simulator camera, then watches `GET /api/cameras/live` (through nginx,
as the wall will) every 0.25 s while it:

  1. lets the camera run: it must read `live`, its newest frame at most ~0.5 s old
  2. pauses the simulator (`docker compose pause mediamtx`): `frozen` within about
     3 s of the last frame, then `offline` once the worker's read times out
  3. unpauses it: `live` again, with nobody doing anything
  4. restarts ingestion (`docker compose restart ingestion`): the camera must not
     read `live` while ingestion has no worker, and capture must resume by itself
  5. kills ingestion (`docker compose kill`, then `start`): the same
  6. stops the camera: `stopped`

Every transition is printed with its time. Ingestion's own worker list is read
after each restart to show the worker is back.

Needs the stack up (`docker compose up -d`). Run from the repo root:

  PYTHONPATH=services/query uv run --package omnisight-query python scripts/verify_camera_states.py --camera cam05

Everything it creates (a throwaway admin, a camera, its frames) is removed at the
end, and the simulator is unpaused and ingestion started whatever happens. Exits 1
if a check fails.
"""

import argparse
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User
from app.security import hash_password
from omnisight_common import Role

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--camera", default="cam05")
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "omni504-verify@omnisight.local"
PASSWORD = "Omni504Verify!"  # a throwaway account, deleted at the end
NAME = "omni504-verify"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
STALE_S = 3.0


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def workers():
    out = dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c",
             "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())").stdout
    try:
        return json.loads(out)
    except ValueError:
        return None


class Watcher(threading.Thread):
    """Polls the wall endpoint and keeps every reading of the camera."""

    def __init__(self, client, camera_id):
        super().__init__(daemon=True)
        self.client, self.camera_id = client, camera_id
        self.stop_flag = threading.Event()
        self.readings: list[tuple[float, str | None, float | None]] = []  # time, state, frame age (s)

    def run(self):
        while not self.stop_flag.is_set():
            at = time.time()
            try:
                items = self.client.get("/cameras/live").json()
                mine = next(i for i in items if i["camera_id"] == self.camera_id)
                age = None
                if mine["last_frame_at"]:
                    age = at - datetime.fromisoformat(mine["last_frame_at"]).timestamp()
                self.readings.append((at, mine["state"], age))
            except Exception:  # noqa: BLE001 - a failed poll is recorded as such
                self.readings.append((at, None, None))
            time.sleep(0.25)

    def since(self, t0):
        return [r for r in self.readings if r[0] >= t0]

    def first(self, state, t0, timeout=60.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for at, s, _ in self.since(t0):
                if s == state:
                    return at - t0
            time.sleep(0.1)
        return None


def cleanup(camera_ids):
    for camera_id in camera_ids:
        with SessionLocal() as s:
            s.query(Segment).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(CameraStats).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
            s.commit()
        dc("exec", "-T", "ingestion", "sh", "-c",
           f"rm -rf /data/frames/camera-{camera_id} /data/thumbs/camera-{camera_id} /data/previews/camera-{camera_id}.jpg")
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()


checks: list[tuple[str, bool, str]] = []


def check(label, ok, detail=""):
    checks.append((label, bool(ok), detail))
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")


def transitions(readings, t0):
    out, last = [], object()
    for at, state, age in readings:
        if state != last:
            out.append(f"t+{at - t0:5.1f}s {state}" + (f" (frame {age:.1f} s old)" if age is not None else ""))
            last = state
    return out


with SessionLocal() as s:
    leftovers = [row.id for row in s.query(Camera).filter_by(name=NAME)]
cleanup(leftovers)
with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()

camera_id = None
c = watcher = None
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, verify=False).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=90)
    camera_id = c.post("/cameras", json={"name": NAME, "rtsp_url": f"rtsp://mediamtx:8554/{ARGS.camera}",
                                         "location": "sim", "group": "sim", "domain": "surveillance"}).json()["id"]
    watcher = Watcher(httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=10), camera_id)
    watcher.start()
    time.sleep(1)
    before = [s for _, s, _ in watcher.readings if s]
    print(f"before start: {sorted(set(before))}")
    check("a camera never started reads stopped", set(before) == {"stopped"})

    t = time.time()
    assert c.post(f"/cameras/{camera_id}/start").status_code == 200
    print(f"\n1. started in {time.time() - t:.1f} s")
    time.sleep(10)
    window = watcher.since(time.time() - 8)
    ages = [age for _, s, age in window if s == "live" and age is not None]
    check("running: live on every poll for 8 s", all(s == "live" for _, s, _ in window), f"{len(window)} polls")
    check("newest frame at most ~0.5 s old (plus a poll)", ages and max(ages) <= 1.0,
          f"age p50 {sorted(ages)[len(ages) // 2]:.2f} s, max {max(ages):.2f} s" if ages else "")

    print("\n2. pausing the simulator")
    t_pause = time.time()
    dc("pause", "mediamtx")
    t_frozen = watcher.first("frozen", t_pause, 20)
    t_offline = watcher.first("offline", t_pause, 60)
    frozen_reading = next((r for r in watcher.since(t_pause) if r[1] == "frozen"), None)
    for line in transitions(watcher.since(t_pause), t_pause):
        print("   ", line)
    check("frozen within about 3 s of the last frame", frozen_reading is not None and frozen_reading[2] <= STALE_S + 0.75,
          f"frozen at t+{t_frozen:.1f} s after the pause command, newest frame then {frozen_reading[2]:.1f} s old"
          if frozen_reading else "never frozen")
    check("then offline once the read times out", t_offline is not None and t_frozen is not None and t_offline > t_frozen,
          f"offline at t+{t_offline:.1f} s" if t_offline else "never offline")

    print("\n3. unpausing it")
    t_unpause = time.time()
    dc("unpause", "mediamtx")
    t_live = watcher.first("live", t_unpause, 90)
    for line in transitions(watcher.since(t_unpause), t_unpause):
        print("   ", line)
    check("live again by itself", t_live is not None, f"after {t_live:.1f} s" if t_live else "not within 90 s")

    for label, actions in (
        ("4. docker compose restart ingestion", [("restart", "ingestion")]),
        ("5. docker compose kill ingestion, then start", [("kill", "ingestion"), ("start", "ingestion")]),
    ):
        time.sleep(5)
        print(f"\n{label}")
        t_r = time.time()
        for action in actions:
            dc(*action)
        t_done = time.time()  # ingestion is back up, with no worker yet
        t_back = watcher.first("live", t_done, 120)
        readings = watcher.since(t_r)
        print(f"    command returned at t+{t_done - t_r:.1f} s")
        for line in transitions(readings, t_r):
            print("   ", line)
        w = workers()
        mine = [x for x in (w or []) if x["camera_id"] == camera_id]
        # From the command returning (a fresh ingestion, no worker) until the
        # resumed worker's first frame, nothing may read live.
        between = [r for r in readings if r[0] >= t_done and (t_back is None or r[0] < t_done + t_back)]
        check("no live reading while ingestion had no worker",
              between and all(s != "live" for _, s, _ in between),
              f"{len(between)} polls, states {sorted({str(s) for _, s, _ in between})}")
        check("capture resumed by itself", t_back is not None and mine and mine[0]["status"] == "running",
              f"live again {t_back:.1f} s after the command returned; worker {mine[0]['status'] if mine else None}"
              if t_back is not None else "not within 120 s")

    print("\n6. stopping the camera")
    t_s = time.time()
    c.post(f"/cameras/{camera_id}/stop")
    t_stopped = watcher.first("stopped", t_s, 15)
    check("stopped after a stop", t_stopped is not None, f"after {t_stopped:.1f} s" if t_stopped is not None else "")
    time.sleep(8)
    check("and it stays stopped (not resumed)", all(s == "stopped" for _, s, _ in watcher.since(t_s + (t_stopped or 0) + 0.5)))

    failed = [label for label, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
finally:
    dc("unpause", "mediamtx")
    dc("start", "ingestion")
    if watcher is not None:
        watcher.stop_flag.set()
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
