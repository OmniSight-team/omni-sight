"""Slice 6's definition of done, the scripted part, on the running stack.

The plan's proof: the dashboard shows accurate live counts; a dataset loads through the
normal pipeline, appears in the archive, and its derived lead-up windows can be checked on
screen. Against the real API through nginx (`https://localhost/api`):

  1. `GET /dashboard/summary` equals a direct count (videos, segments, admitted, storage,
     cameras), and `GET /datasets` equals the database for each dataset (clips loaded of the
     sample, windows derived, checked, verified).
  2. The last N sampled clips of one dataset (default 3 of UCF-Crime) are deleted with
     `DELETE /videos/{id}`, the archive's own delete. Counts checked again.
  3. They are loaded again with `POST /datasets/{name}/load` (the upload function, D-25),
     polling `GET /datasets` until the load ends. Each clip must come back `ready`, extracted,
     `source = dataset`, no retention date, in `GET /videos?source=dataset`, with as many
     segment rows and admitted frames as before; each of its sampled windows must point at
     the new video, keep its verdict, and its playback file answer a range request with 206.
  4. Counts checked a last time.

Signs in as a throwaway admin, deleted at the end. From the repo root, with `docker compose up -d`:

  uv run --package omnisight-query python -u scripts/verify_slice6_dod.py [--dataset ucf_crime] [--clips 3]
"""

import argparse
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

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--dataset", default="ucf_crime")
parser.add_argument("--clips", type=int, default=3)
ARGS = parser.parse_args()

BASE = "https://localhost/api"
EMAIL = "dod-slice6@omnisight.local"
PASSWORD = "DodSlice6Check!"  # a throwaway account, deleted at the end of every run
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'pass' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}")
    return ok


def check_counts(client: httpx.Client, step: str) -> None:
    summary = client.get("/dashboard/summary").json()
    with SessionLocal() as db:
        segments, admitted, file_bytes = db.execute(
            text("SELECT count(*), count(*) FILTER (WHERE admitted), coalesce(sum(file_bytes), 0) FROM segments")
        ).one()
        videos, video_bytes = db.execute(text("SELECT count(*), coalesce(sum(size_bytes), 0) FROM videos")).one()
        cameras = db.execute(text("SELECT count(*) FROM cameras")).scalar_one()
        rollup_admitted = db.execute(text("SELECT coalesce(sum(admitted), 0) FROM segment_hourly")).scalar_one()
        rows = {
            name: db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE v.status = 'ready' AND v.gate_stride_s IS NOT NULL) "
                    "FROM dataset_manifest m LEFT JOIN videos v ON v.id = m.video_id "
                    "WHERE m.dataset = :d AND m.clip_key = ANY(:keys)"
                ),
                {"d": name, "keys": keys},
            ).scalar_one()
            for name, keys in SAMPLE.items()
        }
        windows = {
            name: db.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE w.verified IS NOT NULL), count(*) FILTER (WHERE w.verified) "
                    "FROM event_windows w JOIN dataset_manifest m ON m.id = w.manifest_id WHERE m.dataset = :d"
                ),
                {"d": name},
            ).one()
            for name in SAMPLE
        }
    storage = round(int(video_bytes + file_bytes) / 1e9, 3)
    got = (summary["videos"], summary["segments"], summary["storage_gb"], summary["cameras_total"], rollup_admitted)
    want = (videos, segments, storage, cameras, admitted)
    record(f"{step}: dashboard equals a direct count", got == want,
           f"videos {got[0]}/{want[0]}, segments {got[1]}/{want[1]}, storage {got[2]}/{want[2]} GB, "
           f"cameras {got[3]}/{want[3]}, admitted {got[4]}/{want[4]}")
    for d in client.get("/datasets").json():
        if d["name"] not in SAMPLE:
            continue
        derived, checked, verified = windows[d["name"]]
        got = (d["videos_loaded"], d["total"], d["windows_derived"], d["windows_checked"], d["windows_verified"])
        want = (rows[d["name"]], len(SAMPLE[d["name"]]), derived, checked, verified)
        record(f"{step}: GET /datasets equals the database for {d['name']}", got == want,
               f"loaded {got[0]}/{got[1]} ({d['status']}), windows {got[2]} derived, {got[3]} checked, {got[4]} verified")


def sample_keys() -> dict[str, list[str]]:
    # The committed sample, read the way `GET /datasets` reads it (dataset, clip_key, ...).
    rows = [ln.split(",") for ln in (ROOT / "datasets" / "hand_check" / "sample.csv").read_text(encoding="utf-8").splitlines()[1:]]
    return {name: sorted(r[1] for r in rows if r[0] == name) for name in ("ccd", "ucf_crime")}


SAMPLE = sample_keys()


def main() -> int:
    with SessionLocal() as db:
        db.query(User).filter(User.email == EMAIL).delete()
        db.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
        db.commit()
    try:
        client = httpx.Client(base_url=BASE, verify=False, timeout=120)
        token = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        client.event_hooks["response"] = [
            lambda r: client.headers.__setitem__("Authorization", f"Bearer {r.headers['X-Access-Token']}")
            if "X-Access-Token" in r.headers
            else None
        ]

        print("== 1. counts on the fresh stack ==")
        check_counts(client, "fresh")

        keys = SAMPLE[ARGS.dataset][-ARGS.clips :]
        with SessionLocal() as db:
            before = {
                key: db.execute(
                    text(
                        "SELECT m.id, m.video_id, (SELECT count(*) FROM segments s WHERE s.video_id = m.video_id), "
                        "(SELECT count(*) FROM segments s WHERE s.video_id = m.video_id AND s.admitted) "
                        "FROM dataset_manifest m WHERE m.dataset = :d AND m.clip_key = :k"
                    ),
                    {"d": ARGS.dataset, "k": key},
                ).one()
                for key in keys
            }
        windows_before = {w["id"]: w for w in client.get("/windows").json() if w["dataset"] == ARGS.dataset and w["clip_key"] in keys}

        print(f"== 2. delete {len(keys)} sampled {ARGS.dataset} clips through the archive ==")
        for key, (_mid, video_id, segments, admitted) in before.items():
            r = client.delete(f"/videos/{video_id}")
            record(f"DELETE /videos/{video_id} ({key}, {segments} rows, {admitted} admitted)", r.status_code == 200, str(r.status_code))
        check_counts(client, "after the delete")

        print(f"== 3. load them again from POST /datasets/{ARGS.dataset}/load ==")
        start = time.time()
        r = client.post(f"/datasets/{ARGS.dataset}/load", json={"limit": ARGS.clips})
        record("load accepted", r.status_code == 202 and r.json().get("queued") == len(keys), f"{r.status_code} {r.text}")
        while True:
            d = next(x for x in client.get("/datasets").json() if x["name"] == ARGS.dataset)
            if d["load_queued"] is None:
                break
            time.sleep(2)
        elapsed = time.time() - start
        record("load finished", d["failed"] == 0, f"{elapsed:.0f} s, {d['videos_loaded']}/{d['total']}, failed {d['failed']}")

        archive = {v["id"] for v in client.get("/videos", params={"source": "dataset", "limit": 200}).json()}
        with SessionLocal() as db:
            for key, (mid, old_id, segments, admitted) in before.items():
                vid, status, source, retention, stride, rows, kept = db.execute(
                    text(
                        "SELECT v.id, v.status, v.source, v.retention_until, v.gate_stride_s, "
                        "(SELECT count(*) FROM segments s WHERE s.video_id = v.id), "
                        "(SELECT count(*) FROM segments s WHERE s.video_id = v.id AND s.admitted) "
                        "FROM dataset_manifest m JOIN videos v ON v.id = m.video_id WHERE m.id = :m"
                    ),
                    {"m": mid},
                ).one()
                record(
                    f"{key}: back as video {vid} (was {old_id})",
                    vid != old_id and status == "ready" and source == "dataset" and retention is None and stride is not None
                    and vid in archive and rows == segments and kept == admitted,
                    f"{status}, source {source}, retention {retention}, in the archive {vid in archive}, "
                    f"rows {rows}/{segments}, admitted {kept}/{admitted}",
                )
                for wid, w in windows_before.items():
                    if w["clip_key"] != key:
                        continue
                    detail = client.get(f"/windows/{wid}").json()
                    play = httpx.get("https://localhost" + detail["playback_url"], headers={"Range": "bytes=0-1023"}, verify=False) \
                        if detail["playback_url"] else None
                    record(
                        f"{key}: window {wid} ({w['window_start_s']:.1f}-{w['window_end_s']:.1f} s)",
                        detail["video_id"] == vid and detail["verified"] == w["verified"] and play is not None
                        and play.status_code == 206,
                        f"video {detail['video_id']}, verdict {detail['verified']} (was {w['verified']}), "
                        f"playback {play.status_code if play else None}",
                    )

        print("== 4. counts after the load ==")
        check_counts(client, "after the load")
    finally:
        with SessionLocal() as db:
            db.query(User).filter(User.email == EMAIL).delete()
            db.commit()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
