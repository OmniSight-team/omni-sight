"""Measure the dashboard endpoints on the running stack, and check their counts (OMNI-610).

Two parts, against the real stack through nginx (`https://localhost/api`):

  1. Exactness on the real pipeline: one CCD clip from the mirror is uploaded, extracted
     (ingestion -> queue -> consumer), re-gated at a higher threshold, then deleted. After
     each step `GET /dashboard/summary`'s `segments`, `videos` and storage are (and the rollup's admitted count) compared
     with a direct count over `segments` and `videos`; after the extraction, every admitted row
     of the clip must carry its file bytes (written by the consumer from the message).
  2. Timing: `GET /dashboard/summary` and `GET /dashboard/activity?hours=24`, 100 calls
     each after 5 warm-up calls, one at a time; p50, p95 and max of the client-side time,
     plus the row counts they stand on (`segments` and `segment_hourly`), and for
     comparison the time of one direct `count(*)` over `segments`.

Signs in as a throwaway admin, deleted at the end. From the repo root, with `docker compose up -d`:

  uv run --package omnisight-query python -u scripts/measure_dashboard.py
"""

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "query"))

import httpx
from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from omnisight_common import Role
from sqlalchemy import text

BASE = "https://localhost/api"
EMAIL = "dashboard-610@omnisight.local"
PASSWORD = "Dashboard610!"  # a throwaway account, deleted at the end of every run
CLIP = ROOT / "data" / "ccd" / "videos" / "Crash-1500" / "000026.mp4"
CALLS = 100
WARMUP = 5


def direct_counts() -> dict:
    with SessionLocal() as db:
        segments, admitted, file_bytes = db.execute(
            text("SELECT count(*), count(*) FILTER (WHERE admitted), coalesce(sum(file_bytes), 0) FROM segments")
        ).one()
        videos, video_bytes = db.execute(text("SELECT count(*), coalesce(sum(size_bytes), 0) FROM videos")).one()
    return {
        "segments": segments,
        "admitted": admitted,
        "videos": videos,
        "storage_gb": round(int(video_bytes + file_bytes) / 1e9, 3),
    }


def check(client: httpx.Client, step: str) -> bool:
    summary = client.get("/dashboard/summary").json()
    direct = direct_counts()
    with SessionLocal() as db:
        # Not on the summary, but in the rollup: what a re-gate changes.
        summary["admitted"] = db.execute(text("SELECT coalesce(sum(admitted), 0) FROM segment_hourly")).scalar_one()
    same = all(summary[key] == direct[key] for key in ("segments", "admitted", "videos", "storage_gb"))
    print(
        f"{step:<24} summary segments={summary['segments']} admitted={summary['admitted']} "
        f"videos={summary['videos']} storage_gb={summary['storage_gb']} | direct segments={direct['segments']} "
        f"admitted={direct['admitted']} videos={direct['videos']} storage_gb={direct['storage_gb']} "
        f"-> {'equal' if same else 'DIFFERENT'}"
    )
    return same


def wait_ready(client: httpx.Client, video_id: int) -> dict:
    while True:
        video = client.get(f"/videos/{video_id}").json()
        if video["status"] in ("ready", "failed"):
            return video
        time.sleep(1)


def timings(client: httpx.Client, path: str) -> list[float]:
    for _ in range(WARMUP):
        client.get(path).raise_for_status()
    out = []
    for _ in range(CALLS):
        start = time.perf_counter()
        client.get(path).raise_for_status()
        out.append((time.perf_counter() - start) * 1000)
    return out


def describe(name: str, ms: list[float]) -> None:
    q = statistics.quantiles(ms, n=100)
    print(f"{name:<34} n={len(ms)} p50={q[49]:.1f} ms p95={q[94]:.1f} ms max={max(ms):.1f} ms")


def main() -> int:
    with SessionLocal() as db:
        db.query(User).filter(User.email == EMAIL).delete()
        db.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
        db.commit()
    ok = True
    video_id = None
    try:
        client = httpx.Client(base_url=BASE, verify=False, timeout=120)
        token = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        client.event_hooks["response"] = [
            lambda r: client.headers.__setitem__("Authorization", f"Bearer {r.headers['X-Access-Token']}")
            if "X-Access-Token" in r.headers
            else None
        ]

        print("== exactness on the real pipeline ==")
        ok &= check(client, "before")
        with CLIP.open("rb") as f:
            video_id = client.post("/videos/upload", files={"file": (CLIP.name, f, "video/mp4")}).json()["id"]
        client.post(f"/videos/{video_id}/extract").raise_for_status()
        video = wait_ready(client, video_id)
        print(f"  clip {CLIP.name}: video {video_id} {video['status']}")
        with SessionLocal() as db:
            admitted, without_bytes = db.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE file_bytes = 0) FROM segments "
                    "WHERE video_id = :v AND admitted"
                ),
                {"v": video_id},
            ).one()
        print(f"  admitted rows {admitted}, of which without file bytes {without_bytes}")
        ok &= admitted > 0 and without_bytes == 0
        ok &= check(client, "after upload + extract")
        gated = client.post(f"/videos/{video_id}/gate", json={"cell_threshold": 60.0}).json()
        print(f"  re-gated at cell_threshold 60: {gated}")
        ok &= check(client, "after re-gate")
        client.delete(f"/videos/{video_id}").raise_for_status()
        video_id = None
        ok &= check(client, "after delete")

        print("== timing ==")
        with SessionLocal() as db:
            segments = db.execute(text("SELECT count(*) FROM segments")).scalar_one()
            start = time.perf_counter()
            db.execute(text("SELECT count(*) FROM segments")).scalar_one()
            count_ms = (time.perf_counter() - start) * 1000
            rollup_rows = db.execute(text("SELECT count(*) FROM segment_hourly")).scalar_one()
        print(f"segments rows={segments}; segment_hourly rows={rollup_rows}; one direct count(*) {count_ms:.1f} ms")
        describe("GET /dashboard/summary", timings(client, "/dashboard/summary"))
        describe("GET /dashboard/activity?hours=24", timings(client, "/dashboard/activity?hours=24"))
    finally:
        if video_id is not None:
            client.delete(f"/videos/{video_id}")
        with SessionLocal() as db:
            db.query(User).filter(User.email == EMAIL).delete()
            db.commit()
    print("all equal" if ok else "SOME COUNTS DIFFERED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
