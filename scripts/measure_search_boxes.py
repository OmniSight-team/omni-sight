"""Boxes on search results on the running stack (OMNI-X02, D-42): the four check queries, each
searched in one VIRAT video as the player's search does (Combined, top 5), then their boxes
through `GET /search/boxes`. Also the detector's CPU time: 5 frames in one request (the screen's
case) and one frame a request, each repeated, through ai_workers' `POST /detect`.

    docker compose up -d                    # wait for ai-workers' "box detector loaded"
    uv run python scripts/measure_search_boxes.py [video_id] [--out docs/evidence/search-boxes]

The searches run inside `query` (it logs in as the admin from `.env`, never printing the
password). On the host, each result's stored frame is copied out of `query` and saved with its
boxes drawn, for the check by eye, and `docker stats` gives ai_workers' memory before and after.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

QUERIES = ["a blue car", "a person walking", "a white truck", "a person opening a trunk"]
VIDEO_ID = 3230  # VIRAT_S_040000_06_000746_000964: a parking lot, the largest VIRAT video here
API = "http://localhost:8000"
AI_WORKERS = "http://ai-workers:8000"
REPEATS = 5


def _inside(video_id: int) -> None:
    import os
    import urllib.parse
    import urllib.request

    login = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(login) as response:
        token = json.load(response)["access_token"]

    def get(path: str, params) -> dict:
        url = f"{API}{path}?{urllib.parse.urlencode(params, doseq=True)}"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)

    def detect(paths: list[str], prompts: list[str]) -> float:
        request = urllib.request.Request(
            f"{AI_WORKERS}/detect", data=json.dumps({"frame_paths": paths, "prompts": prompts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)["elapsed_ms"]

    from omnisight_common.box_prompts import prompts_for
    from sqlalchemy import create_engine, text

    from app.settings import settings

    engine = create_engine(settings.database_url)
    out = {"video_id": video_id, "queries": []}
    for q in QUERIES:
        search = get("/search", {"q": q, "mode": "fused", "k": 5, "video_id": video_id})
        ids = [hit["segment_id"] for hit in search["results"]]
        started = time.perf_counter()
        boxes = get("/search/boxes", {"q": q, "segment_ids": ids})
        first_ms = round((time.perf_counter() - started) * 1000, 1)
        with engine.connect() as db:
            paths = dict(db.execute(text("select id, frame_path from segments where id = any(:ids)"), {"ids": ids}).all())
        prompts = prompts_for(q)
        five = [detect([paths[i] for i in ids], prompts) for _ in range(REPEATS)]
        one = [detect([paths[i]], prompts) for i in ids for _ in range(REPEATS // 5 or 1)]
        out["queries"].append({
            "q": q,
            "prompts": prompts,
            "boxes_request_ms": first_ms,
            "detect_5_frames_ms": five,
            "detect_1_frame_ms": one,
            "results": [
                {"rank": rank, "segment_id": i, "timestamp_s": hit["timestamp_s"], "frame_path": paths[i],
                 "boxes": boxes[str(i)]}
                for rank, (i, hit) in enumerate(zip(ids, search["results"], strict=True), start=1)
            ],
        })
    print(json.dumps(out))


def _memory() -> str:
    return subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "phase-b-ai-workers-1"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _draw(frame: bytes, boxes: list[dict], target: Path) -> None:
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.open(BytesIO(frame)).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for box in boxes:
        x1, y1, x2, y2 = box["box"]
        draw.rectangle([x1 * width, y1 * height, x2 * width, y2 * height], outline=(250, 204, 21), width=3)
        draw.text((x1 * width + 3, max(y1 * height - 14, 0)), f"{box['label']} {box['score']:.2f}", fill=(250, 204, 21))
    image.save(target, quality=85)


def main(args: list[str]) -> int:
    video_id = int(args[0]) if args and args[0].isdigit() else VIDEO_ID
    out_dir = Path(args[args.index("--out") + 1]) if "--out" in args else Path("docs/evidence/search-boxes")
    out_dir.mkdir(parents=True, exist_ok=True)
    before = _memory()
    run = subprocess.run(
        ["docker", "compose", "exec", "-T", "-w", "/workspace/services/query", "query", "/workspace/.venv/bin/python", "-", "--inside", str(video_id)],
        input=Path(__file__).read_bytes(), capture_output=True, check=True,
    )
    after = _memory()
    report = json.loads(run.stdout)
    report["memory_before"], report["memory_after"] = before, after
    for query in report["queries"]:
        slug = re.sub(r"[^a-z]+", "-", query["q"].lower()).strip("-")
        for result in query["results"]:
            frame = subprocess.run(
                ["docker", "compose", "exec", "-T", "query", "cat", result["frame_path"]], capture_output=True, check=True
            ).stdout
            result["image"] = str(out_dir / f"{slug}-{result['rank']}.jpg")
            _draw(frame, result["boxes"], Path(result["image"]))
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inside"]:
        sys.path.insert(0, ".")
        _inside(int(sys.argv[2]))
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
