"""OMNI-301: every new upload gets a retention date, from settings.

Requires Postgres to be up (`docker compose up -d`). Same setup as
test_video_upload.py: storage is a pytest tmp_path, and probing is stubbed to
"ingestion unavailable" because only the row's retention_until matters here.
"""

from datetime import timedelta

import pytest
from app import videos as videos_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Role

client = TestClient(app)

TEST_PASSWORD = "Omni301Pass!"
OPERATOR_EMAIL = "omni301-operator@omnisight.local"

MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 12


@pytest.fixture(scope="module", autouse=True)
def omni301_user():
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
        raise IngestionUnavailableError("stubbed unavailable for retention tests")

    monkeypatch.setattr(videos_module, "ingestion_probe_file", _unavailable)


def _upload(auth_headers) -> int:
    resp = client.post(
        "/videos/upload",
        files={"file": ("clip.mp4", MP4_HEADER, "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_upload_sets_retention_until_created_at_plus_configured_days(auth_headers):
    video_id = _upload(auth_headers)

    with SessionLocal() as session:
        row = session.get(Video, video_id)
        assert row.retention_until is not None
        assert row.retention_until == row.created_at + timedelta(days=settings.video_retention_days)


def test_retention_period_comes_from_settings_not_a_literal(auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "video_retention_days", 7)

    video_id = _upload(auth_headers)

    with SessionLocal() as session:
        row = session.get(Video, video_id)
        assert row.retention_until == row.created_at + timedelta(days=7)


def test_retention_until_is_returned_by_the_api(auth_headers):
    video_id = _upload(auth_headers)

    resp = client.get(f"/videos/{video_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["retention_until"] is not None
