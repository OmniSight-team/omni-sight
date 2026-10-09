"""OMNI-608: dataset footage goes through the upload path, never expires, and resumes.

Requires Postgres (`docker compose up -d`). A throwaway dataset (`omni608_test`) is added
to the load list with its own manifest rows, its own sample file (D-26: only sampled clips
are loaded) and files under a tmp mirror; storage is a
tmp_path. Ingestion's probe and the extraction are stubbed: this file proves the loader's
own logic (the shared upload function, the manifest link, retention, resuming, refusals),
not decoding, which `test_video_probe.py` and `test_video_extract.py` cover.
"""

import time
from pathlib import Path

import pytest
from app import datasets as datasets_module
from app import videos as videos_module
from app.db import SessionLocal
from app.main import app
from app.models import DatasetManifest, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Domain, Role, VideoSource, VideoStatus
from omnisight_common.datasets import AnnotationSource

client = TestClient(app)

DATASET = "omni608_test"
TEST_PASSWORD = "Omni608Pass!"
EMAILS = {Role.ADMIN: "omni608-admin@omnisight.local", Role.OPERATOR: "omni608-operator@omnisight.local"}
MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 12


@pytest.fixture(scope="module", autouse=True)
def users():
    with SessionLocal() as session:
        for role, email in EMAILS.items():
            session.add(User(email=email, password_hash=hash_password(TEST_PASSWORD), role=role, is_active=True))
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(User).filter(User.email.in_(EMAILS.values())).delete(synchronize_session=False)
        session.commit()


def _headers(role: Role) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": EMAILS[role], "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    """Three clips on disk, one manifest row each, one listed clip missing from disk."""
    storage, root = tmp_path / "videos", tmp_path / "mirror"
    storage.mkdir()
    (root / DATASET / "clips").mkdir(parents=True)
    monkeypatch.setattr(settings, "video_storage_path", str(storage))
    monkeypatch.setattr(settings, "datasets_path", str(root))
    monkeypatch.setitem(datasets_module.DOMAINS, DATASET, Domain.TRAFFIC)
    # The sample names four clips; t.mp4 is in the manifest but not in the sample.
    sample = tmp_path / "sample.csv"
    lines = ["dataset,clip_key,video_relpath,event_class,annotation_source,split"]
    lines += [f"{DATASET},{n},clips/{n},Normal,normal,held_out" for n in ("a.mp4", "b.mp4", "c.mp4", "gone.mp4")]
    sample.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "hand_check_sample_path", str(sample))
    monkeypatch.setattr(datasets_module, "_refused", {})

    clips = {"a.mp4": "held_out", "b.mp4": "held_out", "c.mp4": "held_out", "gone.mp4": "held_out", "t.mp4": "train"}
    for name in ("a.mp4", "b.mp4", "c.mp4", "t.mp4"):
        (root / DATASET / "clips" / name).write_bytes(MP4_HEADER + name.encode() * 100)
    with SessionLocal() as session:
        for name, split in clips.items():
            session.add(
                DatasetManifest(
                    dataset=DATASET, clip_key=name, domain=Domain.TRAFFIC, event_class="Normal",
                    annotation_source=AnnotationSource.NORMAL, split=split, video_relpath=f"clips/{name}",
                )
            )
        session.commit()

    monkeypatch.setattr(
        videos_module, "ingestion_probe_file",
        lambda path: {"ok": True, "duration_s": 5.0, "fps": 10.0, "width": 64, "height": 48},
    )
    monkeypatch.setattr(videos_module, "ingestion_ensure_playback", lambda path: {"ok": True, "playback_path": None})
    extracted: list[int] = []

    def fake_extraction(video_id: int, extraction_id: str) -> None:
        extracted.append(video_id)
        with SessionLocal() as session:
            session.query(Video).filter_by(id=video_id, extraction_id=extraction_id).update(
                {"status": VideoStatus.READY, "gate_stride_s": 0.0}, synchronize_session=False
            )
            session.commit()

    monkeypatch.setattr(datasets_module, "run_extraction", fake_extraction)
    yield root, storage, extracted

    with SessionLocal() as session:
        ids = [v for (v,) in session.query(DatasetManifest.video_id).filter_by(dataset=DATASET) if v]
        session.query(DatasetManifest).filter_by(dataset=DATASET).delete(synchronize_session=False)
        session.query(Video).filter(Video.id.in_(ids)).delete(synchronize_session=False)
        session.commit()


def _wait_idle(timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while datasets_module._job is not None:
        assert time.monotonic() < deadline, "load did not finish"
        time.sleep(0.05)


def _row(name: str) -> tuple[DatasetManifest, Video | None]:
    with SessionLocal() as session:
        clip = session.query(DatasetManifest).filter_by(dataset=DATASET, clip_key=name).one()
        video = session.get(Video, clip.video_id) if clip.video_id else None
        session.expunge_all()
        return clip, video


def _status() -> dict:
    resp = client.get("/datasets", headers=_headers(Role.OPERATOR))
    assert resp.status_code == 200
    return next(d for d in resp.json() if d["name"] == DATASET)


def test_load_is_admin_only(mirror):
    assert client.post(f"/datasets/{DATASET}/load", json={"limit": 1}).status_code == 401
    resp = client.post(f"/datasets/{DATASET}/load", json={"limit": 1}, headers=_headers(Role.OPERATOR))
    assert resp.status_code == 403
    assert client.post("/datasets/nope/load", json={"limit": 1}, headers=_headers(Role.ADMIN)).status_code == 404


def test_clips_go_through_the_upload_function_and_never_expire(mirror, monkeypatch):
    root, storage, extracted = mirror
    calls = []
    real = datasets_module.store_video
    monkeypatch.setattr(datasets_module, "store_video", lambda *a, **k: calls.append(k["source"]) or real(*a, **k))

    resp = client.post(f"/datasets/{DATASET}/load", json={"limit": 2}, headers=_headers(Role.ADMIN))
    assert resp.status_code == 202 and resp.json() == {"queued": 2}
    _wait_idle()

    assert calls == [VideoSource.DATASET, VideoSource.DATASET]
    for name in ("a.mp4", "b.mp4"):
        clip, video = _row(name)
        assert video is not None and clip.video_id == video.id
        assert video.source == VideoSource.DATASET and video.retention_until is None
        assert video.status == VideoStatus.READY and video.filename == name
        assert video.path.startswith(str(storage))
        assert Path(video.path).read_bytes() == (root / DATASET / "clips" / name).read_bytes()
    assert len(extracted) == 2
    assert _row("c.mp4")[0].video_id is None  # beyond the limit


def test_only_the_subset_is_loaded_and_a_missing_file_is_counted(mirror):
    client.post(f"/datasets/{DATASET}/load", json={"limit": 50}, headers=_headers(Role.ADMIN))
    _wait_idle()
    assert _row("t.mp4")[0].video_id is None  # not in the sample: stays on Colab
    assert _row("gone.mp4")[0].video_id is None
    status = _status()
    assert status["total"] == 4 and status["videos_loaded"] == 3 and status["failed"] == 1
    assert status["status"] == "partial" and status["domain"] == "traffic"


def test_a_stored_but_unextracted_clip_resumes_without_a_second_copy(mirror):
    _, storage, extracted = mirror
    with SessionLocal() as session:
        video = Video(
            filename="a.mp4", path=str(storage / "x.mp4"), source=VideoSource.DATASET, size_bytes=1,
            status=VideoStatus.READY, duration_s=5.0,
        )
        session.add(video)
        session.flush()
        session.query(DatasetManifest).filter_by(dataset=DATASET, clip_key="a.mp4").update({"video_id": video.id})
        session.commit()
        video_id = video.id
        before = session.query(Video).count()

    client.post(f"/datasets/{DATASET}/load", json={"limit": 1}, headers=_headers(Role.ADMIN))
    _wait_idle()
    with SessionLocal() as session:
        assert session.query(Video).count() == before
    assert extracted == [video_id]
    assert _row("a.mp4")[1].status == VideoStatus.READY


def test_a_finished_dataset_queues_nothing(mirror):
    client.post(f"/datasets/{DATASET}/load", json={"limit": 50}, headers=_headers(Role.ADMIN))
    _wait_idle()
    resp = client.post(f"/datasets/{DATASET}/load", json={"limit": 50}, headers=_headers(Role.ADMIN))
    assert resp.json() == {"queued": 1}  # only the missing file is tried again
    _wait_idle()


def test_upload_route_still_sets_a_retention_date(mirror):
    resp = client.post(
        "/videos/upload", files={"file": ("u.mp4", MP4_HEADER + b"x" * 100, "video/mp4")}, headers=_headers(Role.OPERATOR)
    )
    assert resp.status_code == 201
    with SessionLocal() as session:
        video = session.get(Video, resp.json()["id"])
        assert video.source == VideoSource.UPLOAD and video.retention_until is not None
        session.delete(video)
        session.commit()
