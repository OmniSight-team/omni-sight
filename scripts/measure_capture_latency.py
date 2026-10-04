"""Capture-to-stored latency and the TC-1 checks (OMNI-316, rerun in OMNI-502), on
the running stack.

Runs two 30 s windows against the real services: a live camera alone (A), then a
live camera and an uploaded file through ingestion together (B). For each it
reports the capture-to-stored latency per frame, and after B it checks, from the
stored rows, that both sources decoded without error and that only frames with
motion (or the heartbeat) were forwarded.

  capture time  = segments.timestamp_s  (Unix time the worker read the frame)
  stored time   = segments.created_at   (Postgres now() at the insert)
  API-visible   = host time a poller on GET /cameras/{id}/frames first saw it

The host, the Docker VM and Postgres must agree on the time for the API figure to
mean anything; the script prints their offset first.

Since OMNI-501 a live camera stores admitted frames only, so every live row is an
admitted frame. Since OMNI-502 live frames and a file's segments travel on two
queues with a consumer each; both queues' depth is sampled.

Needs the stack up (`docker compose up -d`), at least one `ready` video in the
archive to loop into the uploaded file, and an RTSP simulator feed. Run from the
repo root:

  PYTHONPATH=services/query uv run --package omnisight-query       python scripts/measure_capture_latency.py --camera cam01 --loops 3 --runs AB

Everything it creates (a throwaway admin, a camera, an uploaded video, their
frames) is removed at the end. The uploaded video goes through the real DELETE
route; live frames have no such route yet, so they are deleted directly.
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
import pika
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User, Video
from app.security import hash_password
from omnisight_common import CommonSettings, Role, connection_parameters
from sqlalchemy import text

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--camera", default="cam01", help="simulator path to capture, e.g. cam01 (constant motion) or cam05 (motion, stillness, heartbeats)")
parser.add_argument("--loops", type=int, default=3, help="times the archive clip is looped to make the uploaded file")
parser.add_argument("--runs", default="AB", help="A (live alone), B (live and file together), or AB")
parser.add_argument("--video-id", type=int, default=None, help="archive video to loop (default: the longest ready one)")
parser.add_argument("--min-active-cells", type=int, default=3, help="the motion gate's k, to check forwarded frames against")
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(tempfile.mkdtemp(prefix="omni-latency-"))
LOOPS, CAM, RUNS = ARGS.loops, ARGS.camera, ARGS.runs
WINDOW_S = 30.0
WARMUP_S = 6.0
BASE = "http://127.0.0.1:8000"
EMAIL = "omni316-measure@omnisight.local"
PASSWORD = "Omni316Measure!"  # a throwaway account, deleted at the end
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
MIN_ACTIVE_CELLS = ARGS.min_active_cells


def dc(*args, **kw):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False, **kw)


def ing_py(code):
    return dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c", code).stdout.strip()


def worker_snapshot(camera_id):
    out = ing_py("import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())")
    for w in json.loads(out):
        if w["camera_id"] == camera_id:
            return w
    return None


def pct(sorted_values, q):
    if not sorted_values:
        return float("nan")
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


def summary(values):
    v = sorted(values)
    if not v:
        return {"n": 0}
    return {"n": len(v), "min": v[0], "mean": sum(v) / len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95),
            "p99": pct(v, 0.99), "max": v[-1]}


def fmt(d):
    if d["n"] == 0:
        return "n=0"
    return (f"n={d['n']:>4}  min {d['min'] * 1000:7.0f} ms  mean {d['mean'] * 1000:7.0f}  p50 {d['p50'] * 1000:7.0f}  "
            f"p95 {d['p95'] * 1000:7.0f}  p99 {d['p99'] * 1000:7.0f}  max {d['max'] * 1000:7.0f} ms")


class Observer(threading.Thread):
    """Polls the real frames endpoint and records when each admitted frame first
    became readable through it."""

    def __init__(self, client, camera_id):
        super().__init__(daemon=True)
        self.client, self.camera_id = client, camera_id
        self.stop_flag = threading.Event()
        self.seen: dict[int, tuple[float, float]] = {}  # segment_id -> (host_time_seen, timestamp_s)

    def run(self):
        since = None
        while not self.stop_flag.is_set():
            try:
                params = {"limit": 500} if since is None else {"since": since, "limit": 500}
                frames = self.client.get(f"/cameras/{self.camera_id}/frames", params=params).json()
                now = time.time()
                for f in frames:
                    self.seen.setdefault(f["segment_id"], (now, f["timestamp_s"]))
                if frames:
                    since = frames[-1]["timestamp_s"]
            except Exception:  # noqa: BLE001, S110 - a missed poll is just a later first-seen time
                pass
            time.sleep(0.1)


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


class DepthSampler(threading.Thread):
    """Both segment queues' ready depth, read straight from the broker every 200 ms:
    `points` is the file queue, `live_points` the live queue."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.points: list[tuple[float, int]] = []
        self.live_points: list[tuple[float, int]] = []

    def run(self):
        settings = CommonSettings()
        with pika.BlockingConnection(connection_parameters(settings)) as conn:
            ch = conn.channel()
            while not self.stop_flag.is_set():
                now = time.time()
                self.points.append((now, ch.queue_declare(settings.segment_queue, passive=True).method.message_count))
                self.live_points.append((now, ch.queue_declare(settings.live_segment_queue, passive=True).method.message_count))
                time.sleep(0.2)


def latencies(camera_id, t0, t1):
    with SessionLocal() as s:
        rows = s.execute(
            text("select extract(epoch from created_at) - timestamp_s as l, admitted from segments "
                 "where camera_id = :c and video_id is null and timestamp_s >= :t0 and timestamp_s < :t1"),
            {"c": camera_id, "t0": t0, "t1": t1},
        ).all()
    return [r.l for r in rows], [r.l for r in rows if r.admitted], [r.l for r in rows if not r.admitted]


def motion_only_check(session, *, where_sql, params, label, files_dir_count=None):
    """Only frames with motion (or the heartbeat) are forwarded."""
    rows = session.execute(text(
        f"select admitted, admission_reason::text as reason, motion_score, frame_path, thumb_path from segments where {where_sql}"),
        params).all()
    admitted = [r for r in rows if r.admitted]
    discarded = [r for r in rows if not r.admitted]
    motion = [r for r in admitted if r.reason == "motion"]
    heartbeat = [r for r in admitted if r.reason == "heartbeat"]
    problems = {
        "admitted without a reason": sum(1 for r in admitted if r.reason is None),
        "admitted without a file": sum(1 for r in admitted if r.frame_path is None or r.thumb_path is None),
        "motion frames below the threshold": sum(1 for r in motion if r.motion_score is None or r.motion_score < MIN_ACTIVE_CELLS),
        "heartbeat frames that had motion": sum(1 for r in heartbeat if r.motion_score is not None and r.motion_score >= MIN_ACTIVE_CELLS),
        "discarded with a file (forwarded)": sum(1 for r in discarded if r.frame_path is not None or r.thumb_path is not None),
        "discarded with motion": sum(1 for r in discarded if r.motion_score is not None and r.motion_score >= MIN_ACTIVE_CELLS),
    }
    print(f"  {label}: {len(rows)} frames gated -> {len(admitted)} forwarded "
          f"({len(motion)} motion, {len(heartbeat)} heartbeat), {len(discarded)} discarded "
          f"({100 * len(admitted) / max(len(rows), 1):.0f}% forwarded)")
    print(f"    violations: {problems}  -> {'OK' if not any(problems.values()) else 'PROBLEM'}")
    if files_dir_count is not None:
        print(f"    JPEG files on disk {files_dir_count} vs forwarded frames {len(admitted)}: {'match' if files_dir_count == len(admitted) else 'MISMATCH'}")
    return {"rows": len(rows), "forwarded": len(admitted), "motion": len(motion), "heartbeat": len(heartbeat), "violations": problems}


with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()
camera_id = video_id = None
report = {}
try:
    with SessionLocal() as s:  # the host and the VM must agree on the time
        best = None
        for _ in range(100):
            h1 = time.time()
            p = float(s.execute(text("select extract(epoch from clock_timestamp())")).scalar())
            h2 = time.time()
            if best is None or h2 - h1 < best[0]:
                best = (h2 - h1, p - (h1 + h2) / 2)
    print(f"clock offset, database minus host: {best[1] * 1000:+.1f} ms (+/- {best[0] * 500:.1f} ms)")
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=180)

    # --- the uploaded file: real footage from the archive, looped ---------------------
    with SessionLocal() as s:
        query = s.query(Video).filter_by(status="ready")
        source_video = (
            query.filter_by(id=ARGS.video_id).first()
            if ARGS.video_id is not None
            else query.order_by(Video.duration_s.desc()).first()
        )
    if source_video is None:
        raise SystemExit("the archive has no ready video to loop into the uploaded file")
    SOURCE = source_video.playback_path or source_video.path
    print(f"looping {source_video.filename} ({SOURCE}) x{LOOPS}")
    dc("exec", "-T", "ingestion", "sh", "-c",
       f"ffmpeg -y -loglevel error -stream_loop {LOOPS - 1} -i {SOURCE} -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p /tmp/long316.mp4")
    local = SCRATCH / "long316.mp4"
    dc("cp", "ingestion:/tmp/long316.mp4", str(local))
    cap = cv2.VideoCapture(str(local))
    frames_in_file = 0
    while cap.grab():
        frames_in_file += 1
    fps_file = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    with open(local, "rb") as fh:
        up = c.post("/videos/upload", files={"file": ("omni316-long.mp4", fh, "video/mp4")}).json()
    video_id = up["id"]
    print(f"uploaded video {video_id}: {up['status']}, {up['duration_s']:.1f} s, {frames_in_file} frames at {fps_file:.0f} fps (looped real footage)")
    report["file"] = {"frames": frames_in_file, "duration_s": up["duration_s"], "fps": fps_file}

    camera_id = c.post("/cameras", json={"name": "omni316-measure", "rtsp_url": f"rtsp://mediamtx:8554/{CAM}",
                                         "location": "sim", "group": "sim", "domain": "surveillance"}).json()["id"]

    def one_run(label, with_file):
        print(f"\n=== {label}")
        r = c.post(f"/cameras/{camera_id}/start")
        assert r.status_code == 200, r.text
        before = c.get(f"/cameras/{camera_id}/stats").json()
        time.sleep(WARMUP_S)
        obs = Observer(c, camera_id)
        cpu = CpuSampler()
        depth = DepthSampler()
        obs.start()
        cpu.start()
        depth.start()
        t0 = time.time()
        t1 = t0 + WINDOW_S
        extractions = []
        if with_file:
            while time.time() < t1:
                started = time.time()
                assert c.post(f"/videos/{video_id}/extract").status_code == 202
                while True:
                    d = c.get(f"/videos/{video_id}").json()
                    if d["status"] != "extracting":
                        break
                    time.sleep(0.25)
                extractions.append({"start": started - t0, "end": time.time() - t0, "status": d["status"],
                                    "error": d["error"], "segments": d["segments_count"]})
        while time.time() < t1:
            time.sleep(0.1)
        snap = worker_snapshot(camera_id)
        after = c.get(f"/cameras/{camera_id}/stats").json()
        c.post(f"/cameras/{camera_id}/stop")
        obs.stop_flag.set()
        cpu.stop_flag.set()
        depth.stop_flag.set()
        time.sleep(7)  # let the queue drain so every frame in the window is counted

        all_l, adm_l, disc_l = latencies(camera_id, t0, t1)
        seen = [(seen_at - ts) for (seen_at, ts) in obs.seen.values() if t0 <= ts < t1]
        print(f"  window: 30 s, worker {snap['status']}, decode errors {snap['decode_errors']}, "
              f"captured +{after['captured'] - before['captured']}, dropped +{after['dropped'] - before['dropped']}, "
              f"queue depth at end {snap['queue_depth']}")
        print("  capture -> stored (DB), every stored live frame:", fmt(summary(all_l)))
        if disc_l:
            print("      live rows that are not admitted (none expected since OMNI-501):", len(disc_l))
        print("  capture -> readable via the API, admitted:", fmt(summary(seen)))
        peak = max((d for _, d in depth.points), default=0)
        over_100 = sum(1 for _, d in depth.points if d > 100) * 0.2
        live_peak = max((d for _, d in depth.live_points), default=0)
        print(f"  file queue depth (read from the broker every 0.2 s): peak {peak}, above 100 for {over_100:.1f} s, "
              f"above 1000 for {sum(1 for _, d in depth.points if d > 1000) * 0.2:.1f} s")
        print(f"  live queue depth: peak {live_peak}, above 10 for {sum(1 for _, d in depth.live_points if d > 10) * 0.2:.1f} s")
        cpu_txt = {k: f"avg {sum(v) / len(v):.0f}% max {max(v):.0f}%" for k, v in cpu.samples.items() if k in ("ingestion", "consumer", "consumer-live", "postgres", "rabbitmq", "query")}
        print("  container CPU during the window (100% = one core):", cpu_txt)
        if with_file:
            for i, e in enumerate(extractions, 1):
                print(f"  file extraction {i}: t+{e['start']:.1f}s to t+{e['end']:.1f}s, {e['status']}, error={e['error']}, {e['segments']} segments (file has {frames_in_file} frames)")
        report[label] = {"window": [t0, t1], "worker": snap, "captured": after["captured"] - before["captured"],
                         "dropped": after["dropped"] - before["dropped"], "all": summary(all_l), "admitted": summary(adm_l),
                         "discarded": summary(disc_l), "api": summary(seen), "extractions": extractions,
                         "queue_peak": peak, "live_queue_peak": live_peak, "cpu": {k: [sum(v) / len(v), max(v)] for k, v in cpu.samples.items()}}
        return t0, t1, snap, extractions

    a = one_run(f"A: live camera ({CAM}) alone, 30 s", with_file=False) if "A" in RUNS else None
    b = one_run(f"B: live camera ({CAM}) and an uploaded file ({frames_in_file} frames) together, 30 s", with_file=True) if "B" in RUNS else None

    if b is None:
        raise SystemExit(0)
    # --- TC-1: both decode without error, only frames with motion are forwarded ------
    print("\n=== TC-1 (first half) checks, from the stored rows")
    ok_decode = (b[2]["status"] == "running" and b[2]["decode_errors"] == 0 and
                 all(e["status"] == "ready" and e["error"] is None and e["segments"] == frames_in_file for e in b[3]))
    print(f"  both decoded without error: live worker {b[2]['status']} with {b[2]['decode_errors']} decode errors; "
          f"every extraction ready, no error, {frames_in_file} of {frames_in_file} frames: {ok_decode}")
    with SessionLocal() as s:
        n_thumbs_file = int(dc("exec", "-T", "ingestion", "sh", "-c", f"ls /data/thumbs/{video_id} | wc -l").stdout.strip() or 0)
        n_thumbs_live = int(dc("exec", "-T", "ingestion", "sh", "-c",
                               f"find /data/thumbs/camera-{camera_id} -name '*.jpg' | wc -l").stdout.strip() or 0)
        live_admitted_total = s.query(Segment).filter_by(camera_id=camera_id, admitted=True).count()
        report["tc1_file"] = motion_only_check(s, where_sql="video_id = :v", params={"v": video_id},
                                               label="uploaded file", files_dir_count=n_thumbs_file)
        report["tc1_live"] = motion_only_check(s, where_sql="camera_id = :c and video_id is null", params={"c": camera_id},
                                               label="live camera (both windows)", files_dir_count=n_thumbs_live)
        assert live_admitted_total == report["tc1_live"]["forwarded"]
    report["tc1_decoded_ok"] = ok_decode
    (SCRATCH / "latency-report.json").write_text(json.dumps(report, indent=1, default=str))
    print(f"raw numbers written to {SCRATCH / 'latency-report.json'}")
finally:
    for cid_stop in (camera_id,):
        if cid_stop is not None:
            try:
                c.post(f"/cameras/{cid_stop}/stop")
            except Exception:  # noqa: BLE001, S110 - cleanup must carry on
                pass
    time.sleep(2)
    if video_id is not None:
        try:
            print("cleanup: delete video ->", c.delete(f"/videos/{video_id}").status_code)
        except Exception as exc:  # noqa: BLE001
            print("cleanup: video delete failed", exc)
    if camera_id is not None:
        with SessionLocal() as s:
            s.query(Segment).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(CameraStats).filter_by(camera_id=camera_id).delete(synchronize_session=False)
            s.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
            s.commit()
        dc("exec", "-T", "ingestion", "sh", "-c", f"rm -rf /data/frames/camera-{camera_id} /data/thumbs/camera-{camera_id} /tmp/long316.mp4")
    (SCRATCH / "long316.mp4").unlink(missing_ok=True)
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()
    print("cleaned up")
