"""OMNI-308: the playback-copy wiring on upload, and the playback_url field.

Requires Postgres to be up. Both `ingestion_probe_file` and
`ingestion_ensure_playback` are monkeypatched at the client boundary, same
approach as test_video_probe.py — this proves query's own logic (when
playback generation is even attempted, how its result is stored, that a
failure never touches the video's own `ready`/`failed` status). The real
ffmpeg behavior is covered by services/ingestion/tests/test_playback.py.
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
from omnisight_common import Role, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni308Pass!"
OPERATOR_EMAIL = "omni308-operator@omnisight.local"

MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 12
GOOD_PROBE = {"ok": True, "duration_s": 5.0, "fps": 10.0, "width": 320, "height": 240}


@pytest.fixture(scope="module", autouse=True)
def omni308_user():
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


def _upload(auth_headers, filename="clip.mp4"):
    resp = client.post(
        "/videos/upload",
        files={"file": (filename, MP4_HEADER, "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


def _detail(auth_headers, video_id):
    # POST /videos/upload returns VideoUploadResponse, a smaller shape with
    # no playback_url — that field only exists on the full detail record.
    resp = client.get(f"/videos/{video_id}", headers=auth_headers)
    assert resp.status_code == 200
    return resp.json()


def test_a_playback_copy_is_recorded_and_reflected_in_playback_url(auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(videos_module, "ingestion_probe_file", lambda path: GOOD_PROBE)
    copy_path = str(tmp_path / "abc_playback.mp4")
    monkeypatch.setattr(
        videos_module, "ingestion_ensure_playback", lambda path: {"ok": True, "playback_path": copy_path}
    )

    body = _upload(auth_headers)
    detail = _detail(auth_headers, body["id"])

    assert detail["playback_url"] == settings.video_url_prefix + copy_path.removeprefix(str(tmp_path))
    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        assert row.playback_path == copy_path


def test_an_already_h264_source_needs_no_copy_and_url_falls_back_to_the_original(
    auth_headers, monkeypatch
):
    monkeypatch.setattr(videos_module, "ingestion_probe_file", lambda path: GOOD_PROBE)
    monkeypatch.setattr(
        videos_module, "ingestion_ensure_playback", lambda path: {"ok": True, "playback_path": None}
    )

    body = _upload(auth_headers)
    detail = _detail(auth_headers, body["id"])

    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        assert row.playback_path is None
        expected = settings.video_url_prefix + row.path.removeprefix(settings.video_storage_path)
    assert detail["playback_url"] == expected


def test_a_failed_playback_attempt_leaves_the_video_ready_with_no_playback_path(auth_headers, monkeypatch):
    monkeypatch.setattr(videos_module, "ingestion_probe_file", lambda path: GOOD_PROBE)
    monkeypatch.setattr(
        videos_module,
        "ingestion_ensure_playback",
        lambda path: {"ok": False, "error": "ffmpeg failed: unsupported codec"},
    )

    body = _upload(auth_headers)

    assert body["status"] == VideoStatus.READY.value  # the probe's own success still stands
    assert body["error"] is None  # a playback failure is not what `error` means
    with SessionLocal() as session:
        assert session.get(Video, body["id"]).playback_path is None


def test_ingestion_unavailable_during_playback_also_leaves_the_video_ready(auth_headers, monkeypatch):
    monkeypatch.setattr(videos_module, "ingestion_probe_file", lambda path: GOOD_PROBE)

    def down(path):
        raise IngestionUnavailableError("connection refused")

    monkeypatch.setattr(videos_module, "ingestion_ensure_playback", down)

    body = _upload(auth_headers)

    assert body["status"] == VideoStatus.READY.value
    with SessionLocal() as session:
        assert session.get(Video, body["id"]).playback_path is None


def test_playback_is_never_attempted_when_the_probe_itself_fails(auth_headers, monkeypatch):
    monkeypatch.setattr(
        videos_module, "ingestion_probe_file", lambda path: {"ok": False, "error": "could not open file"}
    )
    calls = []
    monkeypatch.setattr(
        videos_module, "ingestion_ensure_playback", lambda path: calls.append(path) or {"ok": True}
    )

    body = _upload(auth_headers)

    assert body["status"] == VideoStatus.FAILED.value
    assert calls == []  # a file that couldn't even be probed gets no playback attempt


def test_playback_url_is_always_present_even_before_any_probe_result(auth_headers, monkeypatch):
    """The field is non-optional in the schema — even a video whose probe
    never ran (ingestion down) still gets a URL, pointing at the original
    file, which is the only one that could possibly be right at that point."""
    monkeypatch.setattr(
        videos_module,
        "ingestion_probe_file",
        lambda path: (_ for _ in ()).throw(IngestionUnavailableError("down")),
    )

    body = _upload(auth_headers)
    detail = _detail(auth_headers, body["id"])

    assert body["status"] == VideoStatus.UPLOADED.value
    assert detail["playback_url"]  # present and non-empty
    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        expected = settings.video_url_prefix + row.path.removeprefix(settings.video_storage_path)
    assert detail["playback_url"] == expected


def test_deleting_a_video_removes_its_playback_copy_too(auth_headers, monkeypatch, tmp_path):
    """A gap this ticket found in its own new code: DELETE /videos/{id}
    predates playback_path and only ever knew about the original file."""
    monkeypatch.setattr(videos_module, "ingestion_probe_file", lambda path: GOOD_PROBE)
    copy_path = tmp_path / "abc_playback.mp4"
    copy_path.write_bytes(b"fake transcoded bytes")
    monkeypatch.setattr(
        videos_module, "ingestion_ensure_playback", lambda path: {"ok": True, "playback_path": str(copy_path)}
    )

    body = _upload(auth_headers)
    with SessionLocal() as session:
        original_path = session.get(Video, body["id"]).path
    assert Path(original_path).is_file()
    assert copy_path.is_file()

    resp = client.delete(f"/videos/{body['id']}", headers=auth_headers)

    assert resp.status_code == 200
    assert not Path(original_path).exists()
    assert not copy_path.exists()
    with SessionLocal() as session:
        assert session.get(Video, body["id"]) is None
