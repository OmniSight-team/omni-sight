"""What SigLIP 2 costs on this machine's CPU (OMNI-704): model load time, image encode ms per
frame at batch 1 and batch 8, text encode ms per query, and the container's memory.

The `ai-workers` service is stopped for the run and a one-off container of the same image,
code and mounts does the measuring, so one copy of the model is in memory, not two. The
host samples that container's memory with `docker stats` once a second. Frames are a VIRAT
demo video's stored admitted frames (OMNI-702), read from `frame_path` as the service does.

    docker compose up -d
    uv run python scripts/measure_encoder.py [--video 3233] [--frames 32] [--batches 8]

The rest of the stack keeps running (idle: no camera capturing, no extraction). Afterwards
the service is started again and its own memory, idle and after 20 text queries, is read.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

QUERIES = [
    "a person walking", "a white car", "a man carrying a bag", "two people talking",
    "a truck parked by a building", "someone opening a car door", "a person on a bicycle",
    "people crossing a parking lot", "a red vehicle turning", "an empty street at night",
]


# --- inside the one-off container -----------------------------------------------------------


def _measure(video: int, frames: int, batches: int) -> None:
    sys.path.insert(0, "/workspace/services/ai_workers")
    import numpy as np
    import torch

    from app.encoder import FrameTextEncoder, ensure_checkpoint
    from app.settings import settings

    def ms(samples):
        return {"median": round(statistics.median(samples), 1), "p95": round(float(np.percentile(samples, 95)), 1),
                "min": round(min(samples), 1), "max": round(max(samples), 1), "n": len(samples)}

    paths = sorted(str(p) for p in Path(f"/data/frames/{video}").glob("*.jpg"))
    need = max(frames, batches * 8) + 2
    if len(paths) < need:
        raise SystemExit(f"video {video} has {len(paths)} stored frames, {need} needed")
    print(json.dumps({"stage": "start", "torch_threads": torch.get_num_threads(), "torch": torch.__version__}), flush=True)

    started = time.perf_counter()
    encoder = FrameTextEncoder(ensure_checkpoint(settings.frame_model_id, settings.frame_model_revision, settings.frame_model_dir))
    load_s = time.perf_counter() - started
    print(json.dumps({"stage": "loaded", "load_s": round(load_s, 1)}), flush=True)

    # The weights are memory-mapped: the first image and the first text read their tower
    # from disk. Timed on their own, then not counted below.
    t = time.perf_counter()
    encoder.encode_images(paths[:1])
    first_image_s = time.perf_counter() - t
    t = time.perf_counter()
    encoder.encode_texts(["warm-up"])
    first_text_s = time.perf_counter() - t
    encoder.encode_images(paths[1:2])
    batch1 = []
    for path in paths[2 : 2 + frames]:
        t = time.perf_counter()
        encoder.encode_images([path])
        batch1.append((time.perf_counter() - t) * 1000)
    batch8 = []
    for i in range(batches):
        chunk = paths[2 + i * 8 : 2 + (i + 1) * 8]
        t = time.perf_counter()
        encoder.encode_images(chunk)
        batch8.append((time.perf_counter() - t) * 1000 / len(chunk))

    text = []
    for q in QUERIES * 2:
        t = time.perf_counter()
        encoder.encode_texts([q])
        text.append((time.perf_counter() - t) * 1000)

    print(json.dumps({"stage": "done", "load_s": round(load_s, 1), "first_image_s": round(first_image_s, 1),
                      "first_text_s": round(first_text_s, 1), "image_ms_per_frame_batch1": ms(batch1),
                      "image_ms_per_frame_batch8": ms(batch8), "text_ms": ms(text),
                      "frame_size": __import__("PIL.Image", fromlist=["Image"]).open(paths[0]).size}), flush=True)


# --- on the host ----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}
NAME = "omni704-measure"
UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "kB": 1000, "MB": 1000**2, "GB": 1000**3}


def _mem_bytes(container: str) -> int | None:
    """`docker stats`' figure. It leaves out file-backed pages, and the weights are
    memory-mapped from the checkpoint file, so it reads far below what the model holds."""
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
                         capture_output=True, text=True, env=ENV).stdout.strip()
    match = re.match(r"([\d.]+)\s*([A-Za-z]+)", out)
    return int(float(match.group(1)) * UNITS[match.group(2)]) if match else None


def _rss_bytes(container: str) -> int | None:
    """The largest process's resident memory inside the container (VmRSS: its own memory
    plus the mapped weights it has read)."""
    out = subprocess.run(["docker", "exec", container, "sh", "-c", "grep -h VmRSS /proc/[0-9]*/status"],
                         capture_output=True, text=True, env=ENV).stdout
    values = [int(line.split()[1]) * 1024 for line in out.splitlines() if line.startswith("VmRSS")]
    return max(values) if values else None


class MemorySampler(threading.Thread):
    def __init__(self, container: str):
        super().__init__(daemon=True)
        self.container, self.samples, self.rss, self.stop_flag = container, [], [], threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            value, rss = _mem_bytes(self.container), _rss_bytes(self.container)
            if value:
                self.samples.append((time.time(), value))
            if rss:
                self.rss.append((time.time(), rss))
            time.sleep(1)


def _gib(value: float) -> str:
    return f"{value / 1024**3:.2f} GiB"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=int, default=3233)
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--batches", type=int, default=8)
    args = parser.parse_args()

    subprocess.run(["docker", "compose", "stop", "ai-workers"], cwd=ROOT, env=ENV, check=True)
    sampler = MemorySampler(NAME)
    sampler.start()
    marks = {}
    proc = subprocess.Popen(
        ["docker", "compose", "run", "--rm", "-T", "--no-deps", "--name", NAME, "ai-workers",
         "/workspace/.venv/bin/python", "-", "measure", str(args.video), str(args.frames), str(args.batches)],
        cwd=ROOT, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    proc.stdin.write(Path(__file__).read_text(encoding="utf-8"))
    proc.stdin.close()
    result = None
    for line in proc.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        record = json.loads(line)
        marks[record["stage"]] = time.time()
        print(line, flush=True)
        if record["stage"] == "done":
            result = record
    proc.wait()
    sampler.stop_flag.set()
    sampler.join()
    if result is None:
        print("the measurement did not finish", file=sys.stderr)
        return 1

    loaded = [v for t, v in sampler.samples if marks.get("loaded", 0) <= t <= marks.get("done", 0)]
    print(f"\none-off container, docker stats: peak {_gib(max(v for _, v in sampler.samples))}, "
          f"while encoding {_gib(min(loaded))}-{_gib(max(loaded))} ({len(sampler.samples)} samples)")
    print(f"one-off container, process RSS: peak {_gib(max(v for _, v in sampler.rss))} ({len(sampler.rss)} samples)")

    # The service itself, as it runs in the stack.
    subprocess.run(["docker", "compose", "start", "ai-workers"], cwd=ROOT, env=ENV, check=True)
    started = time.time()
    service = subprocess.run(["docker", "compose", "ps", "-q", "ai-workers"], cwd=ROOT, capture_output=True,
                             text=True, env=ENV).stdout.strip()
    while time.time() - started < 600:
        health = subprocess.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", service],
                                capture_output=True, text=True).stdout.strip()
        if health == "healthy":
            break
        time.sleep(2)
    print(f"service healthy {time.time() - started:.0f} s after start (health is polled every 10 s); "
          f"idle: docker stats {_gib(_mem_bytes(service))}, RSS {_gib(_rss_bytes(service))}")
    first = time.perf_counter()
    for q in QUERIES * 2:
        subprocess.run(["docker", "compose", "exec", "-T", "query", "/workspace/.venv/bin/python", "-c",
                        "import json,sys,urllib.request as u;r=u.Request('http://ai-workers:8000/encode/text',"
                        "data=json.dumps({'q':sys.argv[1]}).encode(),headers={'Content-Type':'application/json'});"
                        "v=json.load(u.urlopen(r))['vector'];assert len(v)==1152", q],
                       cwd=ROOT, env=ENV, check=True, capture_output=True)
        if first:
            print(f"first query to the warmed service, round trip through docker exec: {time.perf_counter() - first:.1f} s")
            first = None
    print(f"service after 20 text queries: docker stats {_gib(_mem_bytes(service))}, RSS {_gib(_rss_bytes(service))}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "measure":
        _measure(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    else:
        sys.exit(main())
