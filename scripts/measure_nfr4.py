"""NFR-4: how many live feeds one machine sustains (OMNI-509), on the running stack.

One run measures one number of feeds, N. It registers N cameras on the RTSP
simulator's paths cam01 ... camN (by default the realistic clip set,
infra/mediamtx/mediamtx.real.yml), starts them, waits until all of them read
`live`, then watches a window and decides whether N was **sustained**.

"Sustained", fixed before any of these runs (docs/results.md, OMNI-509): over the
window,
  1. no frame dropped on any feed (the worker's `dropped` counter does not move);
  2. every feed's worst capture-to-stored time is under 5 s (NFR-1);
  3. the live queue is not trending up over the second half of the window: the
     least-squares slope of its depth is at most 0.1 messages a second, and the
     mean of the last quarter is at most 10 messages above the third quarter's;
  4. every feed reads `live` at every 1 s sample of `GET /cameras/live` (what the
     wall's tiles show).

Reported per feed: capture-to-stored p50 / p95 / max, frames dropped, frames
admitted (stored) per second, frames gated per second, and how many samples it
was not live. Overall: both segment queues' depth every second, CPU and memory of
every container (`docker stats`; no host sampler), and a per-minute breakdown.

  capture time  = segments.timestamp_s  (Unix time the worker read the frame)
  stored time   = segments.created_at   (Postgres now() at the insert)

Needs the stack up (`docker compose up -d`). Run from the repo root, one N at a time:

  PYTHONPATH=services/query uv run --package omnisight-query python scripts/measure_nfr4.py --feeds 10 --window 600

Everything it creates (a throwaway admin, the cameras, their frames) is removed at
the end. A JSON report with every number goes to a temporary folder (printed).
"""

import argparse
import json
import os
import statistics
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pika
from app.db import SessionLocal
from app.models import Camera, CameraStats, Segment, User
from app.security import hash_password
from omnisight_common import CommonSettings, Role, connection_parameters
from sqlalchemy import text

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--feeds", type=int, required=True, help="number of simultaneous cameras")
parser.add_argument("--first", type=int, default=1, help="first simulator path: --first 4 --feeds 7 is cam04 ... cam10")
parser.add_argument("--paths", default="", help="simulator paths to take the first N of, instead of --first, e.g. "
                    "4,1,5,6,2,7,8,3,9,10 for a realistic mix (about one HD feed in three at any N)")
parser.add_argument("--window", type=float, default=600.0, help="seconds watched once every feed is live")
parser.add_argument("--settle", type=float, default=15.0, help="seconds between every feed reading live and the window")
parser.add_argument("--start-parallelism", type=int, default=2, help="cameras started at once (K-16: ten at once time out)")
parser.add_argument("--label", default="", help="a name for this run in the report")
ARGS = parser.parse_args()
N = ARGS.feeds
PATHS = [int(p) for p in ARGS.paths.split(",")][:N] if ARGS.paths else list(range(ARGS.first, ARGS.first + N))
assert len(PATHS) == N, "fewer --paths than --feeds"
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "omni509-measure@omnisight.local"
PASSWORD = "Omni509Measure!"  # a throwaway account, deleted at the end
PREFIX = "nfr4-"
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
CONTAINERS = ("ingestion", "consumer", "consumer-live", "postgres", "rabbitmq", "query", "mediamtx", "nginx", "frontend")
SETTINGS = CommonSettings()

# The definition of "sustained", as above.
MAX_LATENCY_S = 5.0
MAX_SLOPE_PER_S = 0.1
MAX_QUARTER_RISE = 10


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def workers() -> dict[int, dict]:
    code = "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())"
    out = dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c", code).stdout.strip() or "[]"
    return {w["camera_id"]: w for w in json.loads(out)}


def pct(values, q):
    v = sorted(values)
    if not v:
        return float("nan")
    return v[min(len(v) - 1, max(0, round(q * (len(v) - 1))))]


def slope(points):
    """Least-squares slope of (t, y) points, per second."""
    if len(points) < 2:
        return 0.0
    ts = [p[0] for p in points]
    ys = [p[1] for p in points]
    mt, my = statistics.fmean(ts), statistics.fmean(ys)
    den = sum((t - mt) ** 2 for t in ts)
    return sum((t - mt) * (y - my) for t, y in zip(ts, ys, strict=True)) / den if den else 0.0


def to_mib(value):
    number = float("".join(ch for ch in value if ch.isdigit() or ch == ".") or 0)
    return number * (1024 if "GiB" in value else 1 if "MiB" in value else 1 / 1024)


class Sampler(threading.Thread):
    """Every second: both queues' depth and every camera's state on the wall's
    endpoint. In a second thread: container CPU and memory from `docker stats`."""

    def __init__(self, client, camera_ids):
        super().__init__(daemon=True)
        self.client, self.camera_ids = client, set(camera_ids)
        self.stop_flag = threading.Event()
        self.depth: list[tuple[float, int, int]] = []  # (t, live queue, file queue)
        self.states: list[tuple[float, dict[int, str]]] = []
        self.cpu: dict[str, list[tuple[float, float]]] = {}
        self.mem: dict[str, list[float]] = {}
        self._cpu_thread = threading.Thread(target=self._cpu_loop, daemon=True)

    def start(self):
        super().start()
        self._cpu_thread.start()

    def run(self):
        with pika.BlockingConnection(connection_parameters(SETTINGS)) as conn:
            ch = conn.channel()
            while not self.stop_flag.is_set():
                t = time.time()
                live_q = ch.queue_declare(SETTINGS.live_segment_queue, passive=True).method.message_count
                file_q = ch.queue_declare(SETTINGS.segment_queue, passive=True).method.message_count
                self.depth.append((t, live_q, file_q))
                try:
                    items = self.client.get("/cameras/live").json()
                    self.states.append((t, {i["camera_id"]: i["state"] for i in items if i["camera_id"] in self.camera_ids}))
                except Exception:  # noqa: BLE001 - a missed sample is recorded as missing
                    self.states.append((t, {}))
                time.sleep(max(0.0, 1.0 - (time.time() - t)))

    def _cpu_loop(self):
        while not self.stop_flag.is_set():
            out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
                                 capture_output=True, text=True, env=ENV, check=False).stdout
            t = time.time()
            for line in out.splitlines():
                name, cpu, mem = (line.split("|") + ["", ""])[:3]
                key = name.replace("phase-b-", "").removesuffix("-1")
                try:
                    self.cpu.setdefault(key, []).append((t, float(cpu.strip("%"))))
                    self.mem.setdefault(key, []).append(to_mib(mem.split("/")[0].strip()))
                except ValueError:
                    pass


def cleanup(camera_ids, client=None):
    if client is not None:
        for cid in camera_ids:
            try:
                client.post(f"/cameras/{cid}/stop")
            except Exception:  # noqa: BLE001, S110 - cleanup must carry on
                pass
    if camera_ids:
        deadline = time.time() + 900
        while time.time() < deadline:  # the consumer may still be storing their frames
            with pika.BlockingConnection(connection_parameters(SETTINGS)) as conn:
                if conn.channel().queue_declare(SETTINGS.live_segment_queue, passive=True).method.message_count == 0:
                    break
            time.sleep(2)
        time.sleep(3)
        with SessionLocal() as s:
            s.query(Segment).filter(Segment.camera_id.in_(camera_ids)).delete(synchronize_session=False)
            s.query(CameraStats).filter(CameraStats.camera_id.in_(camera_ids)).delete(synchronize_session=False)
            s.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
            s.commit()
        dirs = " ".join(f"/data/frames/camera-{cid} /data/thumbs/camera-{cid}" for cid in camera_ids)
        dc("exec", "-T", "ingestion", "sh", "-c", f"rm -rf {dirs}")
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()


with SessionLocal() as s:
    leftovers = [c.id for c in s.query(Camera).filter(Camera.name.like(f"{PREFIX}%"))]
cleanup(leftovers)
with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()

camera_ids: list[int] = []
client = None
report: dict = {"label": ARGS.label, "feeds": N, "paths": PATHS, "window_s": ARGS.window}
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, verify=False).json()["access_token"]
    client = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=180)
    names = {}
    for i in PATHS:
        group = f"Site {chr(ord('A') + (i - 1) // 5)}"
        r = client.post("/cameras", json={"name": f"{PREFIX}cam{i:02d}", "rtsp_url": f"rtsp://mediamtx:8554/cam{i:02d}",
                                          "location": f"{group}, cam{i:02d}", "group": group, "domain": "surveillance"})
        camera_ids.append(r.json()["id"])
        names[camera_ids[-1]] = f"cam{i:02d}"

    t_start = time.time()

    def start_one(cid):
        for attempt in range(1, 4):  # K-16: a start can time out when several run at once
            r = client.post(f"/cameras/{cid}/start")
            if r.status_code == 200:
                return cid, attempt, None
        return cid, 3, r.json().get("detail")

    with ThreadPoolExecutor(max_workers=ARGS.start_parallelism) as pool:
        started = list(pool.map(start_one, camera_ids))
    failed = [(names[cid], detail) for cid, _, detail in started if detail]
    retried = sum(1 for _, attempt, _ in started if attempt > 1)
    print(f"{N} feeds: started {N - len(failed)} in {time.time() - t_start:.0f} s "
          f"({ARGS.start_parallelism} at a time; {retried} needed more than one try)" + (f"; FAILED {failed}" if failed else ""))
    report["start"] = {"seconds": time.time() - t_start, "retried": retried, "failed": failed}
    if failed:
        raise SystemExit("not every camera started")

    deadline = time.time() + 90
    while time.time() < deadline:
        states = {i["camera_id"]: i["state"] for i in client.get("/cameras/live").json() if i["camera_id"] in names}
        if all(states.get(cid) == "live" for cid in camera_ids):
            break
        time.sleep(1)
    print(f"all live after {time.time() - t_start:.0f} s; settling {ARGS.settle:.0f} s")
    time.sleep(ARGS.settle)

    sampler = Sampler(client, camera_ids)
    before = workers()
    t0 = time.time()
    sampler.start()
    print(f"window: {ARGS.window:.0f} s from {time.strftime('%H:%M:%S', time.localtime(t0))} (unix {t0:.0f})")
    while time.time() < t0 + ARGS.window:
        time.sleep(min(30, t0 + ARGS.window - time.time()))
        if time.time() < t0 + ARGS.window:
            last = sampler.depth[-1] if sampler.depth else (0, 0, 0)
            print(f"  +{time.time() - t0:4.0f} s  live queue {last[1]}  file queue {last[2]}", flush=True)
    t1 = time.time()
    after = workers()
    sampler.stop_flag.set()
    report["window"] = [t0, t1]
    for cid in camera_ids:
        client.post(f"/cameras/{cid}/stop")
    print("stopped; waiting for the live queue to empty")
    drain_from = time.time()
    while time.time() < drain_from + 900:
        with pika.BlockingConnection(connection_parameters(SETTINGS)) as conn:
            if conn.channel().queue_declare(SETTINGS.live_segment_queue, passive=True).method.message_count == 0:
                break
        time.sleep(1)
    report["drain_s"] = time.time() - drain_from
    time.sleep(3)

    with SessionLocal() as s:
        rows = s.execute(text(
            "select camera_id, timestamp_s, extract(epoch from created_at) - timestamp_s as l from segments "
            "where camera_id = any(:ids) and video_id is null and timestamp_s >= :t0 and timestamp_s < :t1"),
            {"ids": camera_ids, "t0": t0, "t1": t1}).all()
    window = t1 - t0

    paths = ",".join(f"cam{p:02d}" for p in PATHS)
    print(f"\n=== {N} feeds ({paths}), {window:.0f} s window{' (' + ARGS.label + ')' if ARGS.label else ''}")
    per_feed = []
    for cid in camera_ids:
        lat = [r.l for r in rows if r.camera_id == cid]
        b, a = before.get(cid, {}), after.get(cid, {})
        not_live = sum(1 for _, st in sampler.states if st.get(cid) != "live")
        feed = {
            "feed": names[cid], "stored": len(lat), "admitted_per_s": len(lat) / window,
            "gated_per_s": (a.get("gated", 0) - b.get("gated", 0)) / window,
            "dropped": a.get("dropped", 0) - b.get("dropped", 0),
            "p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "max": max(lat, default=float("nan")),
            "not_live_samples": not_live, "status_at_end": a.get("status"),
        }
        per_feed.append(feed)
        print(f"  {feed['feed']}: gated {feed['gated_per_s']:5.1f}/s  stored {feed['admitted_per_s']:5.2f}/s  "
              f"dropped {feed['dropped']:4d}  latency p50 {feed['p50'] * 1000:6.0f} ms  p95 {feed['p95'] * 1000:6.0f} ms  "
              f"max {feed['max'] * 1000:6.0f} ms  not live {feed['not_live_samples']} of {len(sampler.states)} samples")
    report["per_feed"] = per_feed

    depth = [(t, live_q) for t, live_q, _ in sampler.depth]
    half = [p for p in depth if p[0] >= t0 + window / 2]
    q3 = [y for t, y in depth if t0 + window / 2 <= t < t0 + 3 * window / 4]
    q4 = [y for t, y in depth if t >= t0 + 3 * window / 4]
    s2 = slope(half)
    rise = (statistics.fmean(q4) if q4 else 0) - (statistics.fmean(q3) if q3 else 0)
    file_peak = max((f for _, _, f in sampler.depth), default=0)
    print(f"  live queue: mean {statistics.fmean(y for _, y in depth):.1f}, peak {max(y for _, y in depth)}, "
          f"second-half slope {s2:+.3f}/s, last quarter minus third {rise:+.1f}; file queue peak {file_peak}")
    report["queue"] = {"mean": statistics.fmean(y for _, y in depth), "peak": max(y for _, y in depth),
                       "slope_second_half": s2, "quarter_rise": rise, "file_peak": file_peak}

    print("  per minute:  stored/s  latency p95  max   live queue mean  ingestion  consumer-live  postgres  rabbitmq")
    minutes = []
    for k in range(int(window // 60) or 1):
        a, b = t0 + k * 60, min(t1, t0 + (k + 1) * 60)
        lat = [r.l for r in rows if a <= r.timestamp_s < b]
        dq = [y for t, y in depth if a <= t < b]

        def cpu(name, a=a, b=b):
            v = [c for t, c in sampler.cpu.get(name, []) if a <= t < b]
            return statistics.fmean(v) if v else float("nan")

        m = {"minute": k + 1, "stored_per_s": len(lat) / (b - a), "p95": pct(lat, 0.95), "max": max(lat, default=float("nan")),
             "queue_mean": statistics.fmean(dq) if dq else float("nan"),
             "cpu": {n: cpu(n) for n in ("ingestion", "consumer-live", "postgres", "rabbitmq", "query")}}
        minutes.append(m)
        print(f"    {k + 1:2d}       {m['stored_per_s']:6.1f}   {m['p95'] * 1000:7.0f} ms {m['max'] * 1000:6.0f} ms   {m['queue_mean']:8.1f}"
              f"        {m['cpu']['ingestion']:5.0f}%     {m['cpu']['consumer-live']:5.0f}%      {m['cpu']['postgres']:4.0f}%   {m['cpu']['rabbitmq']:5.0f}%")
    report["minutes"] = minutes

    print("  CPU avg / peak (100% = one core), memory peak MiB:")
    report["cpu"] = {}
    for name in CONTAINERS:
        v = [c for _, c in sampler.cpu.get(name, [])]
        if v:
            report["cpu"][name] = {"avg": statistics.fmean(v), "peak": max(v), "mem_peak_mib": max(sampler.mem.get(name, [0]))}
            print(f"    {name:14s} {statistics.fmean(v):5.0f}% / {max(v):5.0f}%   {max(sampler.mem.get(name, [0])):6.0f} MiB")
    total = [sum(statistics.fmean([c for t, c in sampler.cpu.get(n, []) if t0 <= t < t1] or [0]) for n in CONTAINERS)]
    print(f"    all containers together, average: {total[0]:.0f}% (the Docker VM has 8 CPUs: 800%)")
    print(f"  live queue drained {report['drain_s']:.0f} s after the stop")

    verdict = {
        "no_drops": all(f["dropped"] == 0 for f in per_feed),
        "latency_under_5s": all(f["max"] < MAX_LATENCY_S for f in per_feed),
        "queue_not_trending_up": s2 <= MAX_SLOPE_PER_S and rise <= MAX_QUARTER_RISE,
        "every_feed_live_throughout": all(f["not_live_samples"] == 0 for f in per_feed),
    }
    verdict["sustained"] = all(verdict.values())
    report["verdict"] = verdict
    print(f"\n  verdict: {'SUSTAINED' if verdict['sustained'] else 'NOT SUSTAINED'}  "
          + "  ".join(f"{k}={'yes' if v else 'NO'}" for k, v in verdict.items() if k != "sustained"))
    out = Path(tempfile.mkdtemp(prefix="omni-nfr4-")) / f"nfr4-{N}-feeds.json"
    out.write_text(json.dumps(report, indent=1, default=str))
    print(f"  report: {out}")
finally:
    cleanup(camera_ids, client)
    print("cleaned up")
