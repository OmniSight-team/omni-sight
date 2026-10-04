"""After an ingestion restart, does every camera on the wall come back by itself, and
how long does it take? (Slice 5's definition of done; K-16.)

Expects the cameras already running (`scripts/wall_cameras.py up`). Restarts (or
kills and starts) ingestion, then watches `GET /api/cameras/live` every 0.5 s until
every one of them reads `live` again, and reports when each did. Counts query's "could not resume
capture" log lines in the same period: each is a start that failed and waits for
the retry (K-16: ten starts at once used to time out).

Run from the repo root:

  PYTHONIOENCODING=utf-8 PYTHONPATH=services/query uv run --package omnisight-query python scripts/verify_resume_all.py --action restart

Uses a throwaway admin of its own, removed at the end. Exits 1 if a camera is not
back within `--timeout` seconds.
"""

import argparse
import os
import subprocess
import time
from pathlib import Path

import httpx
from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from omnisight_common import Role

parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
parser.add_argument("--action", choices=("restart", "kill"), default="restart")
parser.add_argument(
    "--prefix", default="wall-", help="the cameras to watch: names starting with this"
)
parser.add_argument("--timeout", type=float, default=180.0)
ARGS = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
BASE = "https://localhost/api"
EMAIL = "omni513-resume@omnisight.local"
PASSWORD = "Omni513Resume!"  # a throwaway account, deleted at the end
ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}


def dc(*args):
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=ENV,
        check=False,
    )


with SessionLocal() as s:
    s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
    s.add(
        User(
            email=EMAIL,
            password_hash=hash_password(PASSWORD),
            role=Role.ADMIN,
            is_active=True,
        )
    )
    s.commit()
ok = False
try:
    token = httpx.post(
        f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, verify=False
    ).json()["access_token"]
    client = httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {token}"},
        verify=False,
        timeout=30,
    )

    def states():
        return {
            c["name"]: c["state"]
            for c in client.get("/cameras/live").json()
            if c["name"].startswith(ARGS.prefix)
        }

    before = states()
    print(f"{len(before)} cameras, before: {sorted(set(before.values()))}")
    if not before or set(before.values()) != {"live"}:
        raise SystemExit("not every camera is live before the restart")

    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    t0 = time.time()
    if ARGS.action == "restart":
        dc("restart", "ingestion")
    else:
        dc("kill", "ingestion")
        dc("start", "ingestion")
    t_back = time.time()
    print(f"`docker compose {ARGS.action}` returned after {t_back - t0:.1f} s")

    live_at: dict[str, float] = {}
    while time.time() < t_back + ARGS.timeout and len(live_at) < len(before):
        try:
            now = states()
        except httpx.HTTPError:
            time.sleep(0.5)
            continue
        for name, state in now.items():
            if state == "live" and name not in live_at:
                live_at[name] = time.time() - t_back
        time.sleep(0.5)

    for name in sorted(before):
        print(
            f"  {name}: {f'live again after {live_at[name]:.1f} s' if name in live_at else 'NOT back'}"
        )
    failed_resumes = sum(
        1
        for line in dc("logs", "--since", since, "query").stdout.splitlines()
        if "could not resume capture" in line
    )
    ok = len(live_at) == len(before)
    if live_at:
        print(
            f"all back: {'yes' if ok else 'no'}; first {min(live_at.values()):.1f} s, last {max(live_at.values()):.1f} s "
            f"after the command returned; failed resume attempts (retried) {failed_resumes}"
        )
finally:
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.commit()

raise SystemExit(0 if ok else 1)
