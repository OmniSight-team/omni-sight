"""NFR-2 (OMNI-714): search results in under 3 seconds, on the running stack, through nginx.

Every query of `datasets/eval/sm1_queries.csv` from this machine to `https://localhost`, 3 rounds, in each
mode, on the product's own vectors. The queries are only a realistic set of texts here: relevance is
SM-1's, and it is ignored.

For each round and mode, `query` is restarted first, which empties its text-vector cache, then:

- `first`: no filter, every text encoded. On this CPU, the text encoders cost what a GPU would not
- `repeat`: the same queries again, from the cache (shown apart, as the ticket asks)
- `camera`, `video`: with a filter, from the cache. D-39's screens always search with one of these

Measured at the client, and split by the API's own `timings`. **`combined` (D-31):** the client's time
with the laptop's encode replaced by OMNI-706's GPU text encode (SigLIP 2 13 ms, InternVideo2 7 ms, L4),
for the `first` rows; repeats and filters have no encode. Labelled so. The raw CPU figure is information.

Before anything else, one query times what K-26 describes: the first search after ai_workers sat idle.

Logs in as the admin from `.env`, never printing the password. From the repo root, with the stack up:

    uv run python scripts/measure_nfr2.py --camera 2446 --video 3226 --out <file.json>
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
ROUNDS = 3
MODES = ("frame", "clip", "fused")
GPU_TEXT_MS = {"frame": 13.0, "clip": 7.0, "fused": 20.0}  # OMNI-706, NVIDIA L4
TIMEOUT_S = 60.0
TARGET_MS = 3000.0


def read_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and not name.strip().startswith("#"):
            env[name.strip()] = value.strip().strip('"').strip("'")
    return env


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "p50": round(percentile(values, 0.5), 1), "p95": round(percentile(values, 0.95), 1), "max": round(max(values), 1)}


def combined_ms(row: dict) -> float:
    """The client's time with the laptop's text encode replaced by the GPU's (D-31)."""
    if row["encode_cached"]:
        return row["client_ms"]
    return row["client_ms"] - row["encode_ms"] + GPU_TEXT_MS[row["mode"]]


def summarise(rows: list[dict]) -> dict:
    """Per mode and pass: the client's time, the combined figure, and the API's split."""
    summary = {}
    for mode in MODES:
        for kind in ("first", "repeat", "camera", "video"):
            chosen = [r for r in rows if r["mode"] == mode and r["pass"] == kind]
            good = [r for r in chosen if r["status"] == 200]
            summary[f"{mode}/{kind}"] = {
                "requests": len(chosen),
                "errors": len(chosen) - len(good),
                "client_ms": stats([r["client_ms"] for r in good]),
                "combined_ms": stats([combined_ms(r) for r in good]),
                **{name: stats([r[name] for r in good]) for name in ("encode_ms", "search_ms", "fusion_ms", "join_ms", "elapsed_ms")},
            }
    return summary


def passed(rows: list[dict]) -> dict:
    """Every request's combined time under the target, and how many were not."""
    good = [r for r in rows if r["status"] == 200]
    over = [r for r in good if combined_ms(r) >= TARGET_MS]
    return {
        "requests": len(rows),
        "errors": len(rows) - len(good),
        "combined_over_target": len(over),
        "cpu_over_target": sum(r["client_ms"] >= TARGET_MS for r in good),
        "passed": not over and len(good) == len(rows),
    }


def restart_query(client: httpx.Client) -> None:
    subprocess.run(["docker", "compose", "restart", "query", "nginx"], cwd=ROOT, capture_output=True, check=True)
    for _ in range(120):
        try:
            if client.get("/auth/me").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("query did not come back")


def one(client: httpx.Client, text: str, mode: str, **filters) -> dict:
    started = time.perf_counter()
    try:
        response = client.get("/search", params={"q": text, "mode": mode, **filters})
    except httpx.HTTPError as exc:
        return {"status": 0, "error": repr(exc)[:200], "client_ms": (time.perf_counter() - started) * 1000}
    client_ms = (time.perf_counter() - started) * 1000
    renewed = response.headers.get("X-Access-Token")
    if renewed:
        client.headers["Authorization"] = f"Bearer {renewed}"
    if response.status_code != 200:
        return {"status": response.status_code, "error": response.text[:200], "client_ms": client_ms}
    body = response.json()
    return {"status": 200, "client_ms": client_ms, "elapsed_ms": body["elapsed_ms"], "total": body["total"], **body["timings"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, required=True)
    parser.add_argument("--video", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    env = read_env()
    with open(ROOT / "datasets" / "eval" / "sm1_queries.csv", newline="", encoding="utf-8") as f:
        texts = [row["text"] for row in csv.DictReader(f)]

    # Certificate unchecked: nginx's own self-signed one, on this machine.
    with httpx.Client(base_url=BASE, verify=False, timeout=TIMEOUT_S) as client:  # noqa: S501
        login = client.post("/auth/login", json={"email": env["ADMIN_EMAIL"], "password": env["ADMIN_PASSWORD"]})
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

        idle = one(client, "a delivery van beside a low wall", "fused")
        print("first search after ai_workers sat idle:", idle, flush=True)

        rows = []
        passes = {"first": {}, "repeat": {}, "camera": {"camera_id": args.camera}, "video": {"video_id": args.video}}
        for round_number in range(1, ROUNDS + 1):
            for mode in MODES:
                restart_query(client)
                for kind, filters in passes.items():
                    for text in texts:
                        rows.append({"round": round_number, "mode": mode, "pass": kind, "text": text, **one(client, text, mode, **filters)})
                    done = [r for r in rows if r["round"] == round_number and r["mode"] == mode and r["pass"] == kind]
                    print(f"round {round_number} {mode} {kind}: {stats([r['client_ms'] for r in done])}", flush=True)

    result = {"idle_first": idle, "summary": summarise(rows), "verdict": passed(rows), "rows": rows}
    args.out.write_text(json.dumps(result, indent=1))
    print(json.dumps(result["verdict"]))
    for name, row in result["summary"].items():
        print(name, "errors", row["errors"], "client", row["client_ms"], "combined", row["combined_ms"], "encode", row["encode_ms"], "search", row["search_ms"], "fusion", row["fusion_ms"], "join", row["join_ms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
