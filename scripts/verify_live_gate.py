"""Algorithm 1 on a live camera (OMNI-501), checked on the running stack.

Captures one simulator feed for a window (60 s by default), stops it, and checks
from the worker's counters and the stored rows that:

  - every decoded frame was gated: the gated rate is the feed's frame rate, and
    `captured = gated + dropped`
  - only admitted frames were stored: every row is admitted, has a reason
    (motion or heartbeat), a frame file and a thumbnail, and its clip
    `[t - 2Δ, t]`; the number of rows equals the `admitted` counter and the
    number of image files on disk
  - the heartbeat held: no two consecutive stored frames are more than the
    heartbeat interval (plus one frame) apart
  - the counters balance exactly: `gated = admitted + discarded`, with
    `admitted = admitted_motion + admitted_heartbeat`

The balance is read after the stop, from the worker's final report: while a
worker runs, a few captured frames are always waiting in its queue, neither
gated nor dropped yet.

Needs the stack up (`docker compose up -d`). Run from the repo root:

  PYTHONPATH=services/query uv run --package omnisight-query python scripts/verify_live_gate.py --camera cam05 --seconds 60

Everything it creates (a throwaway admin, a camera, its frames) is removed at the
end. Exits 1 if a check fails.
"""

import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User
from app.security import hash_password
from omnisight_common import Role
from sqlalchemy import text

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--camera", default="cam05", help="simulator path to capture, e.g. cam05 (motion, stillness, heartbeats)")
parser.add_argument("--seconds", type=float, default=60.0, help="length of the window")
parser.add_argument("--stride-s", type=float, default=0.5, help="the gate's Δ, to check the clip window against")
parser.add_argument("--heartbeat-s", type=float, default=1.0, help="the heartbeat interval, to check the gaps against")
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"
EMAIL = "omni501-verify@omnisight.local"
PASSWORD = "Omni501Verify!"  # a throwaway account, deleted at the end
NAME = "omni501-verify"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
WARMUP_S = 5.0


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def worker_snapshot(camera_id):
    out = dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c",
             "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())").stdout
    for worker in json.loads(out):
        if worker["camera_id"] == camera_id:
            return worker
    return None


class CpuSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.samples: dict[str, list[float]] = {}

    def run(self):
        while not self.stop_flag.is_set():
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}}"],
                capture_output=True, text=True, env=ENV, check=False).stdout
            for line in out.splitlines():
                name, _, cpu = line.partition(" ")
                try:
                    self.samples.setdefault(name.replace("phase-b-", "").replace("-1", ""), []).append(float(cpu.strip("%")))
                except ValueError:
                    pass


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


with SessionLocal() as s:  # anything a killed earlier run left behind
    leftovers = [row.id for row in s.query(Camera).filter_by(name=NAME)]
cleanup(leftovers)
with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()

camera_id = None
checks: list[tuple[str, bool, str]] = []


def check(label, ok, detail=""):
    checks.append((label, bool(ok), detail))
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")


try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    camera_id = c.post("/cameras", json={"name": NAME, "rtsp_url": f"rtsp://mediamtx:8554/{ARGS.camera}",
                                         "location": "sim", "group": "sim", "domain": "surveillance"}).json()["id"]
    r = c.post(f"/cameras/{camera_id}/start")
    assert r.status_code == 200, r.text
    time.sleep(WARMUP_S)

    cpu = CpuSampler()
    cpu.start()
    first = worker_snapshot(camera_id)
    t0 = time.time()
    time.sleep(ARGS.seconds)
    last = worker_snapshot(camera_id)
    t1 = time.time()
    cpu.stop_flag.set()
    running_stats = c.get(f"/cameras/{camera_id}/stats").json()
    c.post(f"/cameras/{camera_id}/stop")

    # The final report and the last frames go through the queue: wait for the
    # stored totals to stop moving.
    stats = None
    for _ in range(40):
        time.sleep(0.5)
        now = c.get(f"/cameras/{camera_id}/stats").json()
        with SessionLocal() as s:
            rows_now = s.query(Segment).filter_by(camera_id=camera_id).count()
        if stats is not None and now == stats[0] and rows_now == stats[1] and now["uptime_s"] == 0.0:
            break
        stats = (now, rows_now)
    stats = stats[0]

    window = t1 - t0
    gated = last["gated"] - first["gated"]
    grabbed = last["grabbed"] - first["grabbed"]
    admitted = last["admitted"] - first["admitted"]
    print(f"\n{ARGS.camera}, {window:.1f} s window (after {WARMUP_S:.0f} s of warm-up), worker {last['status']}")
    print(f"  in the window: read {grabbed} ({grabbed / window:.2f}/s), gated {gated} ({gated / window:.2f}/s), "
          f"admitted {admitted} ({admitted / window:.2f}/s: "
          f"{last['admitted_motion'] - first['admitted_motion']} motion, "
          f"{last['admitted_heartbeat'] - first['admitted_heartbeat']} heartbeat), "
          f"discarded {last['discarded'] - first['discarded']}, dropped {last['dropped'] - first['dropped']}, "
          f"decode errors {last['decode_errors'] - first['decode_errors']}")
    print(f"  fps_effective reported while running: {running_stats['fps_effective']:.2f}")
    cpu_txt = {k: f"avg {sum(v) / len(v):.0f}% max {max(v):.0f}%" for k, v in cpu.samples.items()
               if k in ("ingestion", "consumer", "postgres", "rabbitmq", "query")}
    print(f"  container CPU during the window (100% = one core): {cpu_txt}")
    print(f"  whole session, from GET /cameras/{{id}}/stats after the stop: {stats}")

    with SessionLocal() as s:
        rows = s.execute(text(
            "select timestamp_s, admitted, admission_reason::text as reason, motion_score, frame_path, thumb_path, "
            "clip_start_s, clip_end_s from segments where camera_id = :c and video_id is null order by timestamp_s"),
            {"c": camera_id}).all()
    frames_on_disk = int(dc("exec", "-T", "ingestion", "sh", "-c",
                            f"find /data/frames/camera-{camera_id} -name '*.jpg' | wc -l").stdout.strip() or 0)
    thumbs_on_disk = int(dc("exec", "-T", "ingestion", "sh", "-c",
                            f"find /data/thumbs/camera-{camera_id} -name '*.jpg' | wc -l").stdout.strip() or 0)
    motion = [row for row in rows if row.reason == "motion"]
    heartbeat = [row for row in rows if row.reason == "heartbeat"]
    gaps = [later.timestamp_s - earlier.timestamp_s for earlier, later in zip(rows, rows[1:], strict=False)]
    frame_period = window / max(grabbed, 1)
    clip_errors = max((max(abs(row.clip_end_s - row.timestamp_s), abs(row.clip_start_s - (row.timestamp_s - 2 * ARGS.stride_s)))
                       for row in rows if row.clip_start_s is not None and row.clip_end_s is not None), default=0.0)

    print("\nchecks")
    # A snapshot of a running worker is not atomic: at each end of the window one
    # frame can be between the queue and the gate's counter, so this one check
    # allows a frame either way at each end. The exact balance is the final one.
    accounted = (gated + (last["dropped"] - first["dropped"]) + (last["decode_errors"] - first["decode_errors"])
                 + (last["queue_depth"] - first["queue_depth"]))
    check("every frame read in the window was gated or dropped (within 2, the frames in flight at its two ends)",
          abs(accounted - grabbed) <= 2,
          f"read {grabbed}, gated {gated}, queue depth {first['queue_depth']} -> {last['queue_depth']}")
    check("every stored row is admitted", all(row.admitted for row in rows), f"{len(rows)} rows")
    check("every stored row has a reason", len(motion) + len(heartbeat) == len(rows),
          f"{len(motion)} motion, {len(heartbeat)} heartbeat")
    check("every stored row has a frame file and a thumbnail",
          all(row.frame_path and row.thumb_path for row in rows) and frames_on_disk == thumbs_on_disk == len(rows),
          f"{len(rows)} rows, {frames_on_disk} frames and {thumbs_on_disk} thumbnails on disk")
    check("every stored row carries its clip [t - 2Δ, t]",
          all(row.clip_start_s is not None and row.clip_end_s is not None for row in rows) and clip_errors < 1e-6,
          f"largest error {clip_errors:.2e} s")
    check("stored rows equal the admitted counter",
          len(rows) == stats["admitted"] and len(motion) == stats["admitted_motion"] and len(heartbeat) == stats["admitted_heartbeat"],
          f"rows {len(rows)} ({len(motion)} + {len(heartbeat)}), counter {stats['admitted']} "
          f"({stats['admitted_motion']} + {stats['admitted_heartbeat']})")
    check("the heartbeat held: at least one stored frame a second",
          bool(gaps) and max(gaps) <= ARGS.heartbeat_s + 2 * frame_period,
          f"largest gap {max(gaps, default=float('nan')):.3f} s, frame period {frame_period * 1000:.0f} ms")
    check("captured = gated + dropped, exactly", stats["captured"] == stats["gated"] + stats["dropped"],
          f"{stats['captured']} = {stats['gated']} + {stats['dropped']}")
    check("gated = admitted + discarded, exactly", stats["gated"] == stats["admitted"] + stats["discarded"],
          f"{stats['gated']} = {stats['admitted']} + {stats['discarded']}")
    check("admitted = motion + heartbeat, exactly",
          stats["admitted"] == stats["admitted_motion"] + stats["admitted_heartbeat"],
          f"{stats['admitted']} = {stats['admitted_motion']} + {stats['admitted_heartbeat']}")

    failed = [label for label, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
finally:
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

raise SystemExit(1 if any(not ok for _, ok, _ in checks) or not checks else 0)
