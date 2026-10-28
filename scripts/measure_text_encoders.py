"""ai_workers' two text encoders on this laptop (OMNI-706): ms per query and the container's
memory, with SigLIP 2 and InternVideo2's text side loaded together (D-32).

ai_workers has no host port, so the queries are sent from inside `query`, the service that
calls it in the product; this script, run on the host, pipes itself in, then reads the
container's memory with `docker stats`:

    docker compose up -d
    uv run python scripts/measure_text_encoders.py [--runs 20]

Each run sends the same 10 search-style queries once to `/encode/text` (SigLIP 2) and once
to `/encode/clip-text` (InternVideo2), one at a time; the first round is a warm-up and not
counted. Times are the HTTP round trip inside the Docker network (the encode plus a few ms).
"""

import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

QUERIES = [
    "a person opening the trunk of a car",
    "a person closing the trunk of a car",
    "a person getting into a car",
    "a person getting out of a car",
    "a person carrying a box",
    "a person walking into a building",
    "two people talking in a parking lot",
    "a white van parked next to a building",
    "a car crash at an intersection",
    "a person running at night",
]
ENDPOINTS = {"siglip2": "/encode/text", "internvideo2": "/encode/clip-text"}


def _inside(runs: int) -> None:
    def post(path: str, q: str) -> float:
        request = urllib.request.Request(
            f"http://ai-workers:8000{path}", data=json.dumps({"q": q}).encode(), headers={"Content-Type": "application/json"}
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
        elapsed = (time.perf_counter() - started) * 1000
        assert len(body["vector"]) in (512, 1152)
        return elapsed

    for name, path in ENDPOINTS.items():
        for q in QUERIES:
            post(path, q)  # warm-up round
        times = [post(path, q) for _ in range(runs) for q in QUERIES]
        times.sort()
        print(json.dumps({
            "encoder": name,
            "queries": len(times),
            "p50_ms": round(statistics.median(times), 1),
            "p95_ms": round(times[int(0.95 * (len(times) - 1))], 1),
            "max_ms": round(times[-1], 1),
        }))


def _memory() -> str:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"], capture_output=True, text=True, check=True
    ).stdout
    return next(line for line in out.splitlines() if "ai-workers" in line)


if __name__ == "__main__":
    args = sys.argv[1:]
    runs = int(args[args.index("--runs") + 1]) if "--runs" in args else 20
    if args[:1] == ["--inside"]:
        _inside(runs)
        sys.exit(0)
    print("before:", _memory())
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "python", "-", "--inside", "--runs", str(runs)],
        input=Path(__file__).read_bytes(),
    )
    print("after: ", _memory())
    sys.exit(result.returncode)
