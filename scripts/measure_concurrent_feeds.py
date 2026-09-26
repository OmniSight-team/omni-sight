"""How many simultaneous camera feeds one machine sustains (OMNI-317, NFR-4).

Registers as many cameras as the largest step needs, pointing at the RTSP
simulator's feeds (cam01 to cam10, reused round-robin beyond ten), then climbs a
ladder of N. At each step it starts N cameras, lets them settle, watches a window,
and reports what the pipeline did:

  - frames stored per second per camera (the live sampling rate is 5 a second)
  - frames dropped, and why (the worker's counters)
  - capture-to-stored latency across every camera (NFR-1's 5 s limit)
  - the segment queue's peak depth, read from the broker
  - CPU and memory of every container, and how many workers stayed `running`

  capture time  = segments.timestamp_s  (Unix time the worker read the frame)
  stored time   = segments.created_at   (Postgres now() at the insert)

Needs the stack up and the simulator running. Run from the repo root:

  PYTHONPATH=services/query uv run --package omnisight-query \\
      python scripts/measure_concurrent_feeds.py --steps 1,2,4,6,8,10

Everything it creates (a throwaway admin, the cameras, their frames) is removed at
the end. The simulator and the measuring script share the machine with the
services, which is part of what is being measured.
"""

import argparse
import json
import os
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
parser.add_argument("--steps", default="1,2,4,6,8,10", help="comma-separated numbers of simultaneous cameras")
parser.add_argument("--window", type=float, default=30.0, help="seconds watched at each step")
parser.add_argument("--settle", type=float, default=8.0, help="seconds between all cameras running and the window")
parser.add_argument("--consumer-capacity", type=int, default=0, help="measure the consumer alone with this many queued frames, then exit")
parser.add_argument("--no-cpu-sampling", action="store_true", help="skip the container and host CPU samplers: they cost CPU themselves, which matters on a machine at its limit")
parser.add_argument("--start-parallelism", type=int, default=4, help="cameras started at once")
ARGS = parser.parse_args()
STEPS = [int(x) for x in ARGS.steps.split(",")]
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"
EMAIL = "omni317-measure@omnisight.local"
PASSWORD = "Omni317Measure!"  # a throwaway account, deleted at the end
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
CONTAINERS = ("ingestion", "consumer", "postgres", "rabbitmq", "query", "mediamtx")


def dc(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, env=ENV, check=False)


def workers():
    code = "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/workers').read().decode())"
    return json.loads(dc("exec", "-T", "ingestion", "/workspace/.venv/bin/python", "-c", code).stdout.strip() or "[]")


def pct(sorted_values, q):
    if not sorted_values:
        return float("nan")
    return sorted_values[min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))]


def to_mib(text_value):
    value = float("".join(ch for ch in text_value if ch.isdigit() or ch == "."))
    return value * (1024 if "GiB" in text_value else 1 if "MiB" in text_value else 1 / 1024)


class Sampler(threading.Thread):
    """Container CPU and memory, and the segment queue's depth, while a step runs."""

    def __init__(self, cpu_enabled=True):
        super().__init__(daemon=True)
        self.cpu_enabled = cpu_enabled
        self.stop_flag = threading.Event()
        self.cpu: dict[str, list[float]] = {}
        self.cpu_at: dict[str, list[tuple[float, float]]] = {}
        self.mem: dict[str, list[float]] = {}
        self.depth: list[int] = []
        self.depth_at: list[tuple[float, int]] = []
        self._depth_thread = threading.Thread(target=self._depth_loop, daemon=True)

    def start(self):
        super().start()
        self._depth_thread.start()

    def _depth_loop(self):
        settings = CommonSettings()
        with pika.BlockingConnection(connection_parameters(settings)) as conn:
            ch = conn.channel()
            while not self.stop_flag.is_set():
                depth = ch.queue_declare(settings.segment_queue, passive=True).method.message_count
                self.depth.append(depth)
                self.depth_at.append((time.time(), depth))
                time.sleep(0.2)

    def run(self):
        while self.cpu_enabled and not self.stop_flag.is_set():
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
                capture_output=True, text=True, env=ENV, check=False).stdout
            for line in out.splitlines():
                name, cpu, mem = (line.split("|") + ["", ""])[:3]
                key = name.replace("phase-b-", "").replace("-1", "")
                try:
                    self.cpu.setdefault(key, []).append(float(cpu.strip("%")))
                    self.cpu_at.setdefault(key, []).append((time.time(), float(cpu.strip("%"))))
                    self.mem.setdefault(key, []).append(to_mib(mem.split("/")[0].strip()))
                except ValueError:
                    pass


class HostSampler(threading.Thread):
    """The whole machine's CPU utilisation, and Windows' "processor performance"
    counter (100% is the nominal clock; well below it means the CPU has slowed
    itself down, from heat or power limits). Windows only; silently empty elsewhere."""

    COMMAND = (
        r"(Get-Counter '\Processor Information(_Total)\% Processor Time',"
        r"'\Processor Information(_Total)\% Processor Performance' -SampleInterval 1 -MaxSamples 1)"
        ".CounterSamples | ForEach-Object { $_.CookedValue }"
    )

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.points: list[tuple[float, float, float]] = []  # (time, utilisation %, performance %)

    def run(self):
        while not self.stop_flag.is_set():
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command", self.COMMAND],
                                     capture_output=True, text=True, timeout=20, check=False).stdout.split()
                self.points.append((time.time(), float(out[0]), float(out[1])))
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                return
            time.sleep(2)


def idle_baseline(seconds=12.0):
    s = Sampler()
    s.start()
    time.sleep(seconds)
    s.stop_flag.set()
    return s


def fmt_cpu(sampler, name):
    v = sampler.cpu.get(name, [])
    return f"{sum(v) / len(v):4.0f}% / {max(v):4.0f}%" if v else "n/a"


with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()
camera_ids: list[int] = []
results = []


def measure_consumer_capacity(client, count):
    """Queue `count` live frames with the consumer stopped, then time how fast it
    stores them once started: the pipeline's ceiling, with no cameras involved."""
    from omnisight_common import SegmentMessage, declare_segment_queue

    cid = client.post("/cameras", json={"name": "omni317-capacity", "rtsp_url": "rtsp://mediamtx:8554/cam01",
                                        "location": "sim", "group": "sim", "domain": "surveillance"}).json()["id"]
    camera_ids.append(cid)
    settings = CommonSettings()
    dc("stop", "consumer")
    base = time.time() - 100_000
    t = time.time()
    with pika.BlockingConnection(connection_parameters(settings)) as conn:
        ch = conn.channel()
        ch.confirm_delivery()
        declare_segment_queue(ch, settings.segment_queue)
        for i in range(count):
            body = SegmentMessage(video_id=None, camera_id=cid, frame_index=i, timestamp_s=base + i * 0.2, frame_path=None,
                                  thumb_path=None, motion_score=1.0, admitted=False, source_type="camera").model_dump_json().encode()
            ch.basic_publish("", settings.segment_queue, body, pika.BasicProperties(delivery_mode=2), mandatory=True)
    print(f"queued {count} frames in {time.time() - t:.0f} s; starting the consumer")
    dc("start", "consumer")
    first = last = None
    series = []
    while True:
        with SessionLocal() as s:
            stored = s.query(Segment).filter_by(camera_id=cid).count()
        now = time.time()
        if stored > 0 and first is None:
            first = now
            first_stored = stored
        series.append((now, stored))
        if stored >= count:
            last = now
            break
        if first is not None and now - first > 300:
            break
        time.sleep(0.25)
    if first is None or last is None:
        print("the consumer did not finish")
        return
    rate = (count - first_stored) / max(last - first, 1e-9)
    print(f"the consumer stored {count} frames in {last - first:.1f} s once running: {rate:.0f} messages a second "
          f"(each is its own transaction: a lookup, an insert, a commit)")
    mid = [r for (t2, v), (t1, v1) in zip(series[1:], series, strict=False) for r in [(v - v1) / max(t2 - t1, 1e-9)]]
    print(f"rate over the run: min {min(mid):.0f}, max {max(mid):.0f}")


try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=180)

    if ARGS.consumer_capacity:
        measure_consumer_capacity(c, ARGS.consumer_capacity)
        raise SystemExit(0)

    if not ARGS.no_cpu_sampling:
        print("idle baseline (nothing capturing), 12 s of container CPU:")
        idle = idle_baseline()
        print("  " + "  ".join(f"{n} {fmt_cpu(idle, n)}" for n in CONTAINERS) + "   (average / peak, 100% = one core)")

    for i in range(max(STEPS)):
        r = c.post("/cameras", json={"name": f"omni317-{i + 1:02d}", "rtsp_url": f"rtsp://mediamtx:8554/cam{(i % 10) + 1:02d}",
                                     "location": "sim", "group": "sim", "domain": "surveillance"})
        camera_ids.append(r.json()["id"])

    for n in STEPS:
        ids = camera_ids[:n]
        print(f"\n=== {n} simultaneous camera{'s' if n > 1 else ''}")
        sampler = Sampler(cpu_enabled=not ARGS.no_cpu_sampling)
        host = HostSampler()
        sampler.start()
        if not ARGS.no_cpu_sampling:
            host.start()
        t_start = time.time()

        def start_one(cid):
            r = c.post(f"/cameras/{cid}/start")
            return cid, r.status_code, (r.json().get("detail") if r.status_code != 200 else None)

        with ThreadPoolExecutor(max_workers=ARGS.start_parallelism) as pool:
            started = list(pool.map(start_one, ids))
        failed = [(cid, code, detail) for cid, code, detail in started if code != 200]
        print(f"  started {n - len(failed)} of {n} in {time.time() - t_start:.0f} s"
              + (f"; failures: {[(cid, detail) for cid, _, detail in failed][:4]}" if failed else ""))
        time.sleep(ARGS.settle)

        t0 = time.time()
        time.sleep(ARGS.window)
        t1 = time.time()
        snapshot = workers()
        for cid in ids:
            c.post(f"/cameras/{cid}/stop")
        sampler.stop_flag.set()
        host.stop_flag.set()
        time.sleep(8)  # let the queue drain and the final stats reports arrive

        with SessionLocal() as s:
            rows = s.execute(
                text("select camera_id, extract(epoch from created_at) - timestamp_s as l from segments "
                     "where camera_id = any(:ids) and video_id is null and timestamp_s >= :t0 and timestamp_s < :t1"),
                {"ids": ids, "t0": t0, "t1": t1}).all()
            stats = {row.camera_id: row for row in s.query(CameraStats).filter(CameraStats.camera_id.in_(ids))}
        lat = sorted(r.l for r in rows)
        per_camera = {cid: 0 for cid in ids}
        for r in rows:
            per_camera[r.camera_id] += 1
        rates = sorted(v / ARGS.window for v in per_camera.values())
        live = [w for w in snapshot if w["camera_id"] in ids]
        running = sum(1 for w in live if w["status"] == "running")
        step = {
            "n": n, "started": n - len(failed), "running_at_end": running,
            "rate_min": rates[0], "rate_mean": sum(rates) / len(rates), "rate_max": rates[-1],
            "stored": len(rows),
            "captured": sum(w["captured"] for w in live), "published": sum(w["published"] for w in live),
            "dropped": sum(w["dropped"] for w in live), "dropped_backlog": sum(w["dropped_backlog"] for w in live),
            "reconnects": sum(w["reconnects"] for w in live), "decode_errors": sum(w["decode_errors"] for w in live),
            "lat_p50": pct(lat, 0.5), "lat_p95": pct(lat, 0.95), "lat_p99": pct(lat, 0.99), "lat_max": lat[-1] if lat else float("nan"),
            "queue_peak": max(sampler.depth, default=0),
            "cpu": {k: [sum(v) / len(v), max(v)] for k, v in sampler.cpu.items()},
            "mem_max": {k: max(v) for k, v in sampler.mem.items()},
            "stats_dropped": sum(getattr(v, "dropped", 0) for v in stats.values()),
        }
        results.append(step)
        print(f"  workers running at the end: {running} of {n}; reconnects {step['reconnects']}, decode errors {step['decode_errors']}")
        print(f"  frames stored per camera per second: min {step['rate_min']:.2f}  mean {step['rate_mean']:.2f}  max {step['rate_max']:.2f}"
              f"   ({len(rows)} frames in the {ARGS.window:.0f} s window)")
        print(f"  sampled {step['captured']}, published {step['published']}, dropped {step['dropped']} "
              f"({step['dropped_backlog']} because the queue was too deep) over the whole step")
        print(f"  capture -> stored: p50 {step['lat_p50'] * 1000:.0f} ms  p95 {step['lat_p95'] * 1000:.0f}  p99 {step['lat_p99'] * 1000:.0f}  max {step['lat_max'] * 1000:.0f} ms")
        print(f"  segment queue peak {step['queue_peak']} messages")
        if ARGS.window >= 90:
            print("  per 30 s slice of the window (does it creep?):")
            for k in range(int(ARGS.window // 30)):
                a, b = t0 + k * 30, t0 + (k + 1) * 30
                sl = sorted(r.l for r in rows if False) or []
                with SessionLocal() as s2:
                    sl = sorted(x.l for x in s2.execute(
                        text("select extract(epoch from created_at) - timestamp_s as l from segments "
                             "where camera_id = any(:ids) and video_id is null and timestamp_s >= :a and timestamp_s < :b"),
                        {"ids": ids, "a": a, "b": b}).all())
                dq = [d for (tt, d) in sampler.depth_at if a <= tt < b]
                def avg_cpu(name, a=a, b=b, sampler=sampler):
                    v = [x for (tt, x) in sampler.cpu_at.get(name, []) if a <= tt < b]
                    return sum(v) / len(v) if v else float("nan")

                hs = [p for p in host.points if a <= p[0] < b]
                hostcol = (f"  host CPU {sum(p[1] for p in hs) / len(hs):3.0f}% perf {sum(p[2] for p in hs) / len(hs):3.0f}%") if hs else ""
                print(f"    cpu:  ingestion {avg_cpu('ingestion'):4.0f}%  consumer {avg_cpu('consumer'):4.0f}%  postgres {avg_cpu('postgres'):4.0f}%  "
                      f"rabbitmq {avg_cpu('rabbitmq'):4.0f}%{hostcol}")
                print(f"    +{k * 30:>3}-{(k + 1) * 30:<3}s  frames {len(sl):>4}  latency p50 {pct(sl, 0.5) * 1000:6.0f} ms  p99 {pct(sl, 0.99) * 1000:6.0f} ms  "
                      f"max {(sl[-1] if sl else float('nan')) * 1000:6.0f} ms   queue depth mean {sum(dq) / max(len(dq), 1):5.0f}  max {max(dq, default=0):4d}")
        hp = [p for p in host.points if t0 <= p[0] < t1]
        if hp:
            print(f"  whole machine during the window: CPU {sum(p[1] for p in hp) / len(hp):.0f}% avg / {max(p[1] for p in hp):.0f}% peak; "
                  f"processor performance {min(p[2] for p in hp):.0f}% lowest / {sum(p[2] for p in hp) / len(hp):.0f}% avg")
        print("  CPU avg / peak: " + "  ".join(f"{k} {fmt_cpu(sampler, k)}" for k in CONTAINERS))
        print("  memory peak MiB: " + "  ".join(f"{k} {step['mem_max'].get(k, 0):.0f}" for k in CONTAINERS))

    print("\n=== summary")
    print(f"{'N':>3} {'running':>8} {'fps/cam':>8} {'dropped':>8} {'p99 ms':>7} {'max ms':>7} {'queue':>6} {'ingest cpu':>11} {'consumer':>9} {'rabbit':>7} {'ingest MiB':>10}")
    for r in results:
        print(f"{r['n']:>3} {r['running_at_end']:>3}/{r['n']:<4} {r['rate_mean']:>8.2f} {r['dropped']:>8} {r['lat_p99'] * 1000:>7.0f} {r['lat_max'] * 1000:>7.0f} "
              f"{r['queue_peak']:>6} {r['cpu'].get('ingestion', [0])[0]:>10.0f}% {r['cpu'].get('consumer', [0])[0]:>8.0f}% "
              f"{r['cpu'].get('rabbitmq', [0])[0]:>6.0f}% {r['mem_max'].get('ingestion', 0):>10.0f}")
    report_path = Path(tempfile.mkdtemp(prefix="omni-feeds-")) / "concurrent-feeds-report.json"
    report_path.write_text(json.dumps(results, indent=1, default=str))
    print(f"raw numbers written to {report_path}")
finally:
    dc("start", "consumer")  # the capacity measurement stops it; never leave it stopped
    for cid in camera_ids:
        try:
            c.post(f"/cameras/{cid}/stop")
        except Exception:  # noqa: BLE001, S110 - cleanup must carry on
            pass
    # A step that overloaded the pipeline leaves a backlog, and the consumer keeps
    # storing frames for these cameras until it clears. Deleting a camera while it
    # does would fail on the segments' foreign key, so wait for the queue to empty.
    if camera_ids:
        settings = CommonSettings()
        deadline = time.time() + 600
        while time.time() < deadline:
            with pika.BlockingConnection(connection_parameters(settings)) as conn:
                if conn.channel().queue_declare(settings.segment_queue, passive=True).method.message_count == 0:
                    break
            time.sleep(2)
        time.sleep(3)
    if camera_ids:
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
    print("cleaned up")
