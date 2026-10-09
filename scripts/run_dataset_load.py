"""Load the hand-check sample into the running product through the API (OMNI-608, D-26).

For each dataset in turn (CCD, UCF-Crime): `POST /datasets/{name}/load` with a limit
covering its sampled clips, then poll `GET /datasets` until the load is no longer running.
Prints, per dataset, the wall-clock time and the final counts. A dataset whose load ends
with clips not loaded is loaded once more (failures are retried once). The clips must be in
the mirror first (`scripts/copy_dataset_subsets.py`).

Signs in as a throwaway admin created for the run and deleted at the end (like
`wall_cameras.py`), through nginx at `https://localhost/api`. From the repo root:

  uv run --package omnisight-query python -u scripts/run_dataset_load.py > load.log 2>&1
"""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "query"))

import httpx
from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from omnisight_common import Role

BASE = "https://localhost/api"
EMAIL = "dataset-load@omnisight.local"
PASSWORD = "DatasetLoad608!"  # a throwaway account, deleted at the end of every run
ORDER = ("ccd", "ucf_crime")
POLL_S = 5


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class Api:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE, verify=False, timeout=60)
        self.login()

    def login(self) -> None:
        token = self.client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {token}"

    def call(self, method: str, path: str, **kw) -> httpx.Response:
        resp = self.client.request(method, path, **kw)
        if resp.status_code == 401:
            self.login()
            resp = self.client.request(method, path, **kw)
        if renewed := resp.headers.get("X-Access-Token"):
            self.client.headers["Authorization"] = f"Bearer {renewed}"
        return resp

    def status(self, dataset: str) -> dict:
        return next(d for d in self.call("GET", "/datasets").json() if d["name"] == dataset)


def load(api: Api, dataset: str) -> None:
    for attempt in (1, 2):
        before = api.status(dataset)
        if before["videos_loaded"] == before["total"]:
            break
        resp = api.call("POST", f"/datasets/{dataset}/load", json={"limit": before["total"]})
        print(f"{now()} {dataset}: load attempt {attempt}: {resp.status_code} {resp.text}", flush=True)
        resp.raise_for_status()
        start = time.monotonic()
        while (s := api.status(dataset))["status"] == "loading":
            print(f"{now()} {dataset}: {s['videos_loaded']}/{s['total']} loaded, {s['failed']} failed", flush=True)
            time.sleep(POLL_S)
        print(
            f"{now()} {dataset}: attempt {attempt} done in {(time.monotonic() - start) / 3600:.2f} h: "
            f"{s['videos_loaded']}/{s['total']} loaded, {s['failed']} failed, status {s['status']}",
            flush=True,
        )


def main() -> None:
    with SessionLocal() as s:
        s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
        s.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.ADMIN, is_active=True))
        s.commit()
    try:
        api = Api()
        for dataset in ORDER:
            load(api, dataset)
        print(f"{now()} final: {api.call('GET', '/datasets').json()}", flush=True)
    finally:
        with SessionLocal() as s:
            s.query(User).filter_by(email=EMAIL).delete(synchronize_session=False)
            s.commit()


if __name__ == "__main__":
    main()
