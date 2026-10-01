"""OMNI-504: what a camera is doing right now, from evidence, and capture that
resumes by itself.

Requires Postgres with `alembic upgrade head`. Ingestion is faked at the client
boundary (its worker list and its start call), which is what query's own logic
is made of; the whole chain, with the simulator paused and ingestion restarted,
was run on the real stack (docs/context/week-05.md, OMNI-504).
"""

import itertools
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from app import cameras as cameras_module
from app.capture_resume import CaptureResumer
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.live_state import LiveState, derive_state
from app.main import app
from app.models import Camera, User
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import CameraStatus, Domain, Role

client = TestClient(app)

PASSWORD = "Omni504Pass!"
EMAILS = {
    Role.ADMIN: "omni504-admin@omnisight.local",
    Role.OPERATOR: "omni504-operator@omnisight.local",
    Role.ANALYST: "omni504-analyst@omnisight.local",
}
NAME_PREFIX = "omni504-"
NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def omni504_users():
    with SessionLocal() as session:
        session.add_all(
            User(email=email, password_hash=hash_password(PASSWORD), role=role, is_active=True)
            for role, email in EMAILS.items()
        )
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(User).filter(User.email.in_(EMAILS.values())).delete(synchronize_session=False)
        session.commit()


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%")).delete(synchronize_session=False)
        session.commit()


def _headers(role):
    resp = client.post("/auth/login", json={"email": EMAILS[role], "password": PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def operator():
    return _headers(Role.OPERATOR)


@pytest.fixture
def previews(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "previews_path", str(tmp_path))
    return tmp_path


def _camera(name="cam", *, enabled=False, group="site-a", status=CameraStatus.CONNECTED) -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}{name}",
            rtsp_url=f"rtsp://mediamtx:8554/{name}",
            location="hall",
            group_name=group,
            domain=Domain.SURVEILLANCE,
            status=status,
            capture_enabled=enabled,
        )
        session.add(camera)
        session.commit()
        return camera.id


def _enabled(camera_id) -> bool:
    with SessionLocal() as session:
        return session.get(Camera, camera_id).capture_enabled


def _preview(previews, camera_id, age_s):
    path = previews / f"camera-{camera_id}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xd9")
    written = time.time() - age_s
    os.utime(path, (written, written))


def _workers(monkeypatch, workers=None, *, down=False):
    def fake():
        if down:
            raise IngestionUnavailableError("connection refused")
        return [{"camera_id": cid, "status": status} for cid, status in (workers or {}).items()]

    monkeypatch.setattr(cameras_module, "ingestion_list_workers", fake)


# --- the rule ---------------------------------------------------------------------


def _state(worker_status, *, age_s=0.5, enabled=True, reachable=True):
    return derive_state(
        worker_status=worker_status,
        ingestion_reachable=reachable,
        capture_enabled=enabled,
        last_frame_at=None if age_s is None else NOW - timedelta(seconds=age_s),
        now=NOW,
        stale_after_s=3.0,
    )


def test_a_worker_reading_with_a_fresh_frame_is_live():
    assert _state("running", age_s=0.5) is LiveState.LIVE
    assert _state("running", age_s=3.0) is LiveState.LIVE  # the limit itself still counts


def test_a_worker_reading_with_no_new_frame_for_longer_is_frozen():
    assert _state("running", age_s=3.1) is LiveState.FROZEN
    assert _state("running", age_s=None) is LiveState.FROZEN  # no preview at all


def test_a_worker_reconnecting_or_still_connecting_is_offline():
    assert _state("reconnecting", age_s=0.5) is LiveState.OFFLINE  # whatever its last frame
    assert _state("starting", age_s=None) is LiveState.OFFLINE


def test_no_worker_is_offline_if_capture_was_asked_for_and_stopped_if_not():
    for status in (None, "failed", "stopped"):
        assert _state(status, enabled=True) is LiveState.OFFLINE
        assert _state(status, enabled=False) is LiveState.STOPPED


def test_with_ingestion_unreachable_nothing_reads_live():
    """K-5: no camera reads live without a worker, even with a fresh preview."""
    assert _state("running", age_s=0.1, reachable=False, enabled=True) is LiveState.OFFLINE
    assert _state("running", age_s=0.1, reachable=False, enabled=False) is LiveState.STOPPED


def test_a_running_worker_counts_whatever_the_flag_says():
    assert _state("running", age_s=0.5, enabled=False) is LiveState.LIVE


# --- GET /cameras/live --------------------------------------------------------------


def _by_id(body):
    return {item["camera_id"]: item for item in body}


def test_the_wall_gets_every_camera_with_its_state(operator, previews, monkeypatch):
    live = _camera("live", enabled=True)
    frozen = _camera("frozen", enabled=True)
    offline = _camera("offline", enabled=True)
    resuming = _camera("resuming", enabled=True)
    stopped = _camera("stopped")
    _preview(previews, live, 0.4)
    _preview(previews, frozen, 8.0)
    _preview(previews, offline, 12.0)
    _workers(monkeypatch, {live: "running", frozen: "running", offline: "reconnecting"})

    resp = client.get("/cameras/live", headers=operator)

    assert resp.status_code == 200
    got = _by_id(resp.json())
    assert got[live]["state"] == "live"
    assert got[frozen]["state"] == "frozen"
    assert got[offline]["state"] == "offline"
    assert got[resuming]["state"] == "offline"  # wanted, but no worker (yet)
    assert got[stopped]["state"] == "stopped"
    item = got[live]
    assert set(item) == {"camera_id", "name", "location", "group_name", "state", "last_frame_at"}
    assert (item["name"], item["location"], item["group_name"]) == (f"{NAME_PREFIX}live", "hall", "site-a")
    seen = datetime.fromisoformat(item["last_frame_at"])
    assert abs((datetime.now(UTC) - seen).total_seconds() - 0.4) < 1.0  # the preview's write time
    assert got[stopped]["last_frame_at"] is None


def test_no_camera_reads_live_while_ingestion_is_down(operator, previews, monkeypatch):
    camera_id = _camera("down", enabled=True)
    _preview(previews, camera_id, 0.2)  # a fresh file, left by a worker that was killed
    _workers(monkeypatch, down=True)

    got = _by_id(client.get("/cameras/live", headers=operator).json())

    assert got[camera_id]["state"] == "offline"


def test_a_disabled_camera_is_stopped(operator, previews, monkeypatch):
    camera_id = _camera("disabled", enabled=True, status=CameraStatus.DISABLED)
    _workers(monkeypatch, {})

    got = _by_id(client.get("/cameras/live", headers=operator).json())

    assert got[camera_id]["state"] == "stopped"


def test_the_wall_is_ordered_by_group_then_name(operator, previews, monkeypatch):
    b2 = _camera("b2", group="site-b")
    a2 = _camera("a2", group="site-a")
    b1 = _camera("b1", group="site-b")
    a1 = _camera("a1", group="site-a")
    _workers(monkeypatch, {})

    ids = [item["camera_id"] for item in client.get("/cameras/live", headers=operator).json()]

    mine = [cid for cid in ids if cid in (a1, a2, b1, b2)]
    assert mine == [a1, a2, b1, b2]


def test_the_wall_is_for_operators_and_admins(previews, monkeypatch):
    _workers(monkeypatch, {})

    assert client.get("/cameras/live").status_code == 401
    assert client.get("/cameras/live", headers=_headers(Role.ANALYST)).status_code == 403
    assert client.get("/cameras/live", headers=_headers(Role.ADMIN)).status_code == 200


# --- capture_enabled: set by start, cleared by stop ----------------------------------


@pytest.fixture
def ingestion(monkeypatch):
    calls = {"start": [], "stop": []}
    answer = {"start": {"ok": True, "worker_id": "w", "status": "running", "error": None, "already_running": False}}

    def start(camera_id, rtsp_url):
        calls["start"].append(camera_id)
        return answer["start"]

    def stop(camera_id):
        calls["stop"].append(camera_id)
        return {"ok": True, "status": "stopped", "was_running": True}

    monkeypatch.setattr(cameras_module, "ingestion_start_worker", start)
    monkeypatch.setattr(cameras_module, "ingestion_stop_worker", stop)
    calls["answer"] = answer
    return calls


def test_a_successful_start_sets_capture_enabled(operator, ingestion):
    camera_id = _camera("start")

    assert client.post(f"/cameras/{camera_id}/start", headers=operator).status_code == 200

    assert _enabled(camera_id) is True


def test_a_start_that_fails_does_not(operator, ingestion):
    camera_id = _camera("fails")
    ingestion["answer"]["start"] = {"ok": False, "error": "connection refused", "already_running": False}

    assert client.post(f"/cameras/{camera_id}/start", headers=operator).status_code == 502

    assert _enabled(camera_id) is False  # not retried in the background either


def test_stop_clears_it(operator, ingestion):
    camera_id = _camera("stop", enabled=True)

    assert client.post(f"/cameras/{camera_id}/stop", headers=operator).status_code == 200

    assert _enabled(camera_id) is False


def test_disabling_a_camera_clears_it(ingestion):
    camera_id = _camera("disable", enabled=True)

    resp = client.patch(f"/cameras/{camera_id}", json={"status": "disabled"}, headers=_headers(Role.ADMIN))

    assert resp.status_code == 200
    assert _enabled(camera_id) is False


# --- capture resumes by itself ----------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _resumer(workers, *, start_ok=True, down=False, clock=None):
    started = []

    def list_workers():
        if down:
            raise IngestionUnavailableError("connection refused")
        return [{"camera_id": cid, "status": status} for cid, status in workers.items()]

    def start_worker(camera_id, rtsp_url):
        started.append(camera_id)
        if start_ok:
            workers[camera_id] = "running"
            return {"ok": True, "worker_id": "w", "status": "running", "already_running": False}
        return {"ok": False, "error": "could not open the stream", "already_running": False}

    resumer = CaptureResumer(
        list_workers=list_workers, start_worker=start_worker, spawn=lambda f: f(),
        clock=clock or FakeClock(), first_backoff_s=5.0, max_backoff_s=60.0,
    )
    return resumer, started


def test_after_a_restart_every_camera_that_was_capturing_is_started_again():
    wanted = [_camera("r1", enabled=True), _camera("r2", enabled=True)]
    not_wanted = _camera("r3", enabled=False)
    workers = {}  # ingestion just restarted: no workers at all
    resumer, started = _resumer(workers)

    resumer.check()

    assert sorted(cid for cid in started if cid in wanted + [not_wanted]) == sorted(wanted)
    assert all(workers[cid] == "running" for cid in wanted)


def test_a_camera_that_already_has_a_worker_is_left_alone():
    camera_id = _camera("busy", enabled=True)
    for status in ("running", "starting", "reconnecting"):
        resumer, started = _resumer({camera_id: status})

        resumer.check()

        assert camera_id not in started


def test_a_failed_worker_is_started_again():
    camera_id = _camera("failed", enabled=True)
    resumer, started = _resumer({camera_id: "failed"})

    resumer.check()

    assert camera_id in started


def test_a_disabled_camera_is_never_resumed():
    camera_id = _camera("dis", enabled=True, status=CameraStatus.DISABLED)
    resumer, started = _resumer({})

    resumer.check()

    assert camera_id not in started


def test_nothing_happens_while_ingestion_is_down():
    camera_id = _camera("down2", enabled=True)
    resumer, started = _resumer({}, down=True)

    assert resumer.check() == []
    assert camera_id not in started


def test_a_camera_that_cannot_be_started_is_retried_later_and_less_often():
    camera_id = _camera("dead", enabled=True)
    clock = FakeClock()
    resumer, started = _resumer({}, start_ok=False, clock=clock)

    times = []
    for _ in range(60):  # five minutes of checks, one every 5 s
        before = len([c for c in started if c == camera_id])
        resumer.check()
        if len([c for c in started if c == camera_id]) > before:
            times.append(clock.now)
        clock.now += 5.0

    gaps = [later - earlier for earlier, later in itertools.pairwise(times)]
    assert gaps[:4] == [5.0, 10.0, 20.0, 40.0]  # the wait doubles...
    assert all(gap <= 60.0 for gap in gaps)  # ...up to the cap
    with SessionLocal() as session:
        assert session.get(Camera, camera_id).status == CameraStatus.UNREACHABLE


def test_a_resumed_camera_reads_connected():
    camera_id = _camera("back", enabled=True, status=CameraStatus.UNREACHABLE)
    resumer, _ = _resumer({})

    resumer.check()

    with SessionLocal() as session:
        camera = session.get(Camera, camera_id)
        assert camera.status == CameraStatus.CONNECTED and camera.last_seen_at is not None


def test_a_camera_being_started_is_not_started_twice():
    camera_id = _camera("twice", enabled=True)
    pending = []
    resumer, started = _resumer({})
    resumer._spawn = pending.append  # the start has not finished yet

    resumer.check()
    resumer.check()

    assert len([f for f in pending]) == 1
    pending[0]()
    assert started.count(camera_id) == 1
