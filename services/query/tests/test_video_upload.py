"""OMNI-205: video storage volume and upload endpoint.

Requires Postgres to be up (`docker compose up -d`). settings.video_storage_path
is monkeypatched to a pytest tmp_path here rather than the real /data/videos —
that real Linux volume only exists inside the containers, not on a host
running this file directly, and this suite proves the endpoint's own logic
(streaming, sniffing, generated names, atomic rename, size limits), not that
the volume mount itself is wired up. The volume mount and the acceptance
criteria that need it for real (a 200 MB upload with no memory spike, the
same check against the live containers) were verified live; see
docs/context/week-02.md.

The autoprobe step OMNI-206 added is stubbed to "ingestion unavailable" for
every test here, on purpose — this file is about the storage layer, not
probing, so every upload below lands as `uploaded` and stays that way. The
probing behavior itself (ready, failed, and the unavailable case this stub
exercises for real) is covered in test_video_probe.py.
"""

from pathlib import Path

import pytest
from app import videos as videos_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Role, VideoSource, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni205Pass!"
OPERATOR_EMAIL = "omni205-operator@omnisight.local"

# A minimal ISO-base-media "ftyp" box header — enough for the endpoint's
# content sniff to recognize it as an mp4, without needing a real,
# fully-decodable video file for a storage-layer test.
MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 12


@pytest.fixture(scope="module", autouse=True)
def omni205_user():
    with SessionLocal() as session:
        session.add(
            User(
                email=OPERATOR_EMAIL,
                password_hash=hash_password(TEST_PASSWORD),
                role=Role.OPERATOR,
                is_active=True,
            )
        )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter_by(email=OPERATOR_EMAIL).delete(synchronize_session=False)
        session.commit()


@pytest.fixture
def auth_headers():
    resp = client.post("/auth/login", json={"email": OPERATOR_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "video_storage_path", str(tmp_path))
    yield
    with SessionLocal() as session:
        session.query(Video).delete()
        session.commit()


@pytest.fixture(autouse=True)
def stub_probe_unavailable(monkeypatch):
    def _unavailable(path):
        raise IngestionUnavailableError("stubbed unavailable for storage-layer tests")

    monkeypatch.setattr(videos_module, "ingestion_probe_file", _unavailable)


def test_upload_valid_video_creates_uploaded_row(auth_headers):
    content = MP4_HEADER + b"\x00" * (2 * 1024 * 1024)
    resp = client.post(
        "/videos/upload",
        files={"file": ("clip.mp4", content, "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "clip.mp4"
    assert body["status"] == VideoStatus.UPLOADED.value
    assert body["duration_s"] is None
    assert body["fps"] is None
    assert body["size_mb"] > 0

    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        assert row.source == VideoSource.UPLOAD
        assert row.status == VideoStatus.UPLOADED
        assert row.camera_id is None
        assert row.size_bytes == len(content)
        # only the path is stored — the bytes live on disk, not in the row
        assert Path(row.path).is_file()
        assert Path(row.path).read_bytes() == content


def test_stored_filename_is_generated_not_client_supplied(auth_headers):
    resp = client.post(
        "/videos/upload",
        files={"file": ("my original name.mp4", MP4_HEADER, "video/mp4")},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["filename"] == "my original name.mp4"

    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        stored_name = Path(row.path).name
        assert stored_name != "my original name.mp4"
        assert stored_name.endswith(".mp4")
        # 32 hex chars + ".mp4"
        assert len(stored_name) == 36


def test_path_traversal_filename_cannot_escape_storage_dir(auth_headers):
    resp = client.post(
        "/videos/upload",
        files={"file": ("../../../../etc/passwd.mp4", MP4_HEADER, "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    with SessionLocal() as session:
        row = session.get(Video, resp.json()["id"])
        stored_path = Path(row.path).resolve()
        storage_dir = Path(settings.video_storage_path).resolve()
        assert stored_path.parent == storage_dir
        assert storage_dir in stored_path.parents


def test_txt_renamed_to_mp4_is_rejected(auth_headers):
    resp = client.post(
        "/videos/upload",
        files={"file": ("notes.mp4", b"just some plain text, not a video", "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == videos_module.NOT_A_VIDEO_MESSAGE

    with SessionLocal() as session:
        assert session.query(Video).count() == 0


def test_oversized_file_is_rejected_with_size_message(auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    oversized = MP4_HEADER + b"\x00" * (2 * 1024 * 1024)

    resp = client.post(
        "/videos/upload",
        files={"file": ("big.mp4", oversized, "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 413
    assert "1 MB" in resp.json()["detail"]

    with SessionLocal() as session:
        assert session.query(Video).count() == 0
    # no orphan .part file left behind either
    leftovers = list(Path(settings.video_storage_path).glob("*.part"))
    assert leftovers == []


def test_upload_requires_auth():
    resp = client.post("/videos/upload", files={"file": ("clip.mp4", MP4_HEADER, "video/mp4")})
    assert resp.status_code == 401
