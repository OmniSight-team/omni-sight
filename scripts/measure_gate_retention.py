"""What fraction of frames Algorithm 1's motion gate keeps on real dataset footage
(OMNI-318).

Runs every clip found under the local dataset mirror through the real pipeline:
upload it, extract it (decode and gate every frame, at the service's default
parameters), read the stored rows, delete it. Reports, per dataset group and per
clip, the retention: the share of frames the gate forwarded (admitted), split into
motion admissions and heartbeat admissions, and how active the frames were (the
motion score is the number of the grid's 64 cells that changed).

The parameters are the defaults on purpose. This measures what the gate does as
configured; it does not tune it.

`--sensitivity 50:3,100:3` additionally re-gates each clip at other
`cell_threshold:min_active_cells` pairs (through POST /videos/{id}/gate) and
reports the retention at each, to show what would change the answer. The defaults
remain the result.

Needs the stack up. Run from the repo root, in the background for long runs:

  PYTHONPATH=services/query uv run --package omnisight-query \\
      python scripts/measure_gate_retention.py

Everything it creates (a throwaway admin and one video at a time) is removed at the
end, videos through the real DELETE route.
"""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from omnisight_common import Role
from sqlalchemy import text

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--data-root", default="data", help="the dataset mirror (default: data/)")
parser.add_argument("--sensitivity", default="", help="extra cell_threshold:min_active_cells pairs, e.g. 50:3,100:3")
parser.add_argument("--limit", type=int, default=0, help="at most this many clips per group (0 = all)")
ARGS = parser.parse_args()
REPO = Path(__file__).resolve().parents[1]
DATA = (REPO / ARGS.data_root) if not Path(ARGS.data_root).is_absolute() else Path(ARGS.data_root)
BASE = "http://127.0.0.1:8000"
EMAIL = "omni318-measure@omnisight.local"
PASSWORD = "Omni318Measure!"  # a throwaway account, deleted at the end
PREFIX = "omni318-"
GRID_CELLS = 64  # the default 8 x 8 grid
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov"}


def group_of(path: Path) -> str:
    parts = path.relative_to(DATA).parts
    if parts[0] == "ccd":
        return "CCD crash (dash-cam)" if "Crash-1500" in parts else "CCD normal (dash-cam)"
    if parts[0] == "ucf_crime":
        return "UCF-Crime normal (fixed CCTV)" if any("Normal" in p for p in parts) else "UCF-Crime anomaly (fixed CCTV)"
    if parts[0] == "virat":
        return "VIRAT (fixed ground camera)"
    return parts[0]


def clips():
    found = sorted(p for p in DATA.rglob("*") if p.suffix.lower() in VIDEO_SUFFIXES)
    by_group: dict[str, list[Path]] = {}
    for p in found:
        by_group.setdefault(group_of(p), []).append(p)
    if ARGS.limit:
        by_group = {g: v[: ARGS.limit] for g, v in by_group.items()}
    return by_group


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, max(0, round(q * (len(v) - 1))))] if v else float("nan")


with SessionLocal() as s:
    s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
    s.commit()
results: list[dict] = []
client = None
current_video = None
try:
    token = httpx.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    client = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=300)

    # a run that was killed part-way may have left a clip behind
    for v in client.get("/videos", params={"limit": 200}).json():
        if v["filename"].startswith(PREFIX):
            client.delete(f"/videos/{v['id']}")

    combos = [tuple(c.split(":")) for c in ARGS.sensitivity.split(",") if c]
    groups = clips()
    print(f"{sum(len(v) for v in groups.values())} clips in {len(groups)} groups under {DATA}")
    for group, files in groups.items():
        print(f"\n=== {group}: {len(files)} clips")
        for path in files:
            name = f"{PREFIX}{path.parent.name}-{path.stem}.mp4"
            row = {"group": group, "clip": str(path.relative_to(DATA)), "status": "failed"}
            results.append(row)
            try:
                with open(path, "rb") as fh:
                    up = client.post("/videos/upload", files={"file": (name, fh, "video/mp4")})
                if up.status_code != 201 and up.status_code != 200:
                    row["error"] = f"upload {up.status_code}: {up.text[:120]}"
                    print(f"  {path.name:<40} UPLOAD FAILED {row['error']}")
                    continue
                current_video = up.json()["id"]
                started = time.time()
                if client.post(f"/videos/{current_video}/extract").status_code != 202:
                    row["error"] = "extract refused"
                    continue
                while True:
                    d = client.get(f"/videos/{current_video}").json()
                    if d["status"] != "extracting":
                        break
                    time.sleep(0.3)
                if d["status"] != "ready":
                    row["error"] = d.get("error") or d["status"]
                    print(f"  {path.name:<40} EXTRACTION FAILED {row['error']}")
                    continue
                with SessionLocal() as s:
                    r = s.execute(text(
                        "select count(*) total, coalesce(sum(admitted::int),0) admitted, "
                        "coalesce(sum((admission_reason::text='motion')::int),0) motion, "
                        "coalesce(sum((admission_reason::text='heartbeat')::int),0) heartbeat, "
                        "count(motion_score) scored, avg(motion_score) mean_active, "
                        "percentile_cont(0.5) within group (order by motion_score) median_active "
                        "from segments where video_id = :v"), {"v": current_video}).one()
                    g = s.execute(text(
                        "select gate_stride_s, gate_grid_size, gate_cell_threshold, gate_min_active_cells, fps, width, height "
                        "from videos where id = :v"), {"v": current_video}).one()
                row.update({
                    "status": "ok", "frames": r.total, "forwarded": int(r.admitted), "motion": int(r.motion),
                    "heartbeat": int(r.heartbeat), "scored": r.scored,
                    "mean_active": float(r.mean_active) if r.mean_active is not None else None,
                    "median_active": float(r.median_active) if r.median_active is not None else None,
                    "fps": g.fps, "size": f"{g.width}x{g.height}",
                    "params": {"stride_s": g.gate_stride_s, "grid": g.gate_grid_size, "cell_threshold": g.gate_cell_threshold,
                               "min_active_cells": g.gate_min_active_cells},
                    "seconds": time.time() - started, "sensitivity": {},
                })
                for thr, k in combos:
                    res = client.post(f"/videos/{current_video}/gate", json={"cell_threshold": float(thr), "min_active_cells": int(k)})
                    if res.status_code == 200:
                        row["sensitivity"][f"{thr}:{k}"] = res.json()["admitted"]
                pctv = 100 * row["forwarded"] / row["frames"]
                print(f"  {path.name:<40} {row['size']:>9} {row['fps']:>4.0f} fps  {row['frames']:>5} frames  forwarded {row['forwarded']:>5} "
                      f"({pctv:5.1f}%)  motion {row['motion']:>5}  heartbeat {row['heartbeat']:>3}  "
                      f"median active cells {row['median_active'] if row['median_active'] is not None else float('nan'):4.0f}/{GRID_CELLS}")
            finally:
                if current_video is not None:
                    client.delete(f"/videos/{current_video}")
                    current_video = None

    print("\n=== retention by group (forwarded frames / all frames), default parameters")
    print(f"{'group':<34} {'clips':>5} {'frames':>7} {'forwarded':>9} {'retention':>9}   per clip: {'min':>5} {'median':>6} {'max':>5}   "
          f"{'by motion':>9} {'heartbeat':>9}  {'median active cells':>19}")
    summary = {}
    for group in groups:
        ok = [r for r in results if r["group"] == group and r["status"] == "ok"]
        if not ok:
            continue
        frames = sum(r["frames"] for r in ok)
        fwd = sum(r["forwarded"] for r in ok)
        per = [100 * r["forwarded"] / r["frames"] for r in ok]
        med_active = statistics.median([r["median_active"] for r in ok if r["median_active"] is not None] or [float("nan")])
        summary[group] = {"clips": len(ok), "failed": sum(1 for r in results if r["group"] == group and r["status"] != "ok"),
                          "frames": frames, "forwarded": fwd, "retention": 100 * fwd / frames, "per_clip": per}
        print(f"{group:<34} {len(ok):>5} {frames:>7} {fwd:>9} {100 * fwd / frames:>8.1f}%   {'':>9}{min(per):>5.0f}% {pct(per, 0.5):>5.0f}% {max(per):>4.0f}%   "
              f"{100 * sum(r['motion'] for r in ok) / frames:>8.1f}% {100 * sum(r['heartbeat'] for r in ok) / frames:>8.1f}%  {med_active:>15.0f} / {GRID_CELLS}")
    failed = [r for r in results if r["status"] != "ok"]
    if failed:
        print(f"\n{len(failed)} clips failed: " + "; ".join(f"{r['clip']} ({r.get('error')})" for r in failed))
    if combos:
        print("\n=== retention at other parameters (cell_threshold:min_active_cells), same clips")
        for group in groups:
            ok = [r for r in results if r["group"] == group and r["status"] == "ok"]
            if not ok:
                continue
            frames = sum(r["frames"] for r in ok)
            cells = "  ".join(f"{k} -> {100 * sum(r['sensitivity'].get(k, 0) for r in ok) / frames:5.1f}%" for k in [f"{a}:{b}" for a, b in combos])
            print(f"  {group:<34} default -> {summary[group]['retention']:5.1f}%   {cells}")
    params = next((r["params"] for r in results if r["status"] == "ok"), None)
    print(f"\nparameters used (recorded on each video): {params}; heartbeat interval 1.0 s, blur kernel 21")
    out = Path(tempfile.mkdtemp(prefix="omni-gate-")) / "gate-retention.json"
    out.write_text(json.dumps({"results": results, "summary": summary}, indent=1, default=str))
    print(f"raw numbers written to {out}")
finally:
    if current_video is not None and client is not None:
        try:
            client.delete(f"/videos/{current_video}")
        except Exception:  # noqa: BLE001, S110 - cleanup must carry on
            pass
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()
    print("cleaned up")
