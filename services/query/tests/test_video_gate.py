"""OMNI-306: POST /videos/{id}/gate — re-running Algorithm 1 in place.

Requires Postgres to be up with `alembic upgrade head` applied. Ingestion is
faked at the client boundary (`extraction.ingestion_extract_file`), same
approach as test_video_extract.py — this proves query's own logic (matching
existing rows by frame_index, updating them in place, the video's status and
recorded gate parameters, the failure paths that revert rather than fail).
The real re-decode is ingestion's own `extract_file`, already covered by
services/ingestion/tests/test_extraction_pipeline.py and test_motion_gate.py;
nothing about re-gating changes what happens on that side, only how query
uses the response.
"""

from pathlib import Path

import pytest
from app import extraction as extraction_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import AdmissionReason, Role, SegmentSourceType, VideoSource, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni306Pass!"
OPERATOR_EMAIL = "omni306-operator@omnisight.local"
NAME_PREFIX = "omni306-"


@pytest.fixture(scope="module", autouse=True)
def omni306_user():
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
def headers():
    resp = client.post("/auth/login", json={"email": OPERATOR_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(autouse=True)
def isolated_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frames_path", str(tmp_path / "frames"))
    monkeypatch.setattr(settings, "thumbs_path", str(tmp_path / "thumbs"))
    yield
    with SessionLocal() as session:
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(
            synchronize_session=False
        )
        session.commit()


def _make_video_with_segments(
    tmp_path, frame_count=10, *, status=VideoStatus.READY, admitted_indices=frozenset()
):
    """A `ready` video with `frame_count` existing segment rows (frame_index
    0..frame_count-1), some already admitted — the state a real prior
    extraction would have left it in."""
    path = tmp_path / f"{NAME_PREFIX}clip.mp4"
    path.write_bytes(b"video bytes")
    with SessionLocal() as session:
        video = Video(
            filename=path.name,
            path=str(path),
            source=VideoSource.UPLOAD,
            size_bytes=path.stat().st_size,
            status=status,
            gate_stride_s=0.5,
            gate_grid_size=8,
            gate_cell_threshold=25.0,
            gate_min_active_cells=3,
        )
        session.add(video)
        session.commit()
        video_id = video.id

        for i in range(frame_count):
            admitted = i in admitted_indices
            session.add(
                Segment(
                    video_id=video_id,
                    frame_index=i,
                    timestamp_s=float(i),
                    frame_path=f"/data/frames/{video_id}/{i:06d}.jpg" if admitted else None,
                    thumb_path=f"/data/thumbs/{video_id}/{i:06d}.jpg" if admitted else None,
                    motion_score=10.0 if admitted else 0.0,
                    admitted=admitted,
                    source_type=SegmentSourceType.UPLOAD,
                    admission_reason=AdmissionReason.MOTION if admitted else None,
                )
            )
        session.commit()
        return video_id


def _fake_gate_ingestion(admitted_indices, *, frame_count=10, seen=None):
    """A stand-in for ingestion's /extract/file, used for re-gating: returns
    a full re-computation for every existing frame_index, with the requested
    subset admitted."""

    def fake(video_id, path, source_type, camera_id, *, stride_s=None, grid_size=None, cell_threshold=None, min_active_cells=None):
        if seen is not None:
            seen["kwargs"] = {
                "stride_s": stride_s,
                "grid_size": grid_size,
                "cell_threshold": cell_threshold,
                "min_active_cells": min_active_cells,
            }
        segments = []
        for i in range(frame_count):
            admitted = i in admitted_indices
            segments.append(
                {
                    "video_id": video_id,
                    "camera_id": camera_id,
                    "frame_index": i,
                    "timestamp_s": float(i),
                    "frame_path": f"/data/frames/{video_id}/{i:06d}.jpg" if admitted else None,
                    "thumb_path": f"/data/thumbs/{video_id}/{i:06d}.jpg" if admitted else None,
                    "motion_score": 42.0 if admitted else 1.0,
                    "admitted": admitted,
                    "source_type": source_type,
                    "clip_start_s": max(0.0, i - 1.0) if admitted else None,
                    "clip_end_s": float(i) if admitted else None,
                    "admission_reason": "motion" if admitted else None,
                }
            )
        return {
            "ok": True,
            "segments": segments,
            "error": None,
            "stride_s": stride_s if stride_s is not None else 0.5,
            "grid_size": grid_size if grid_size is not None else 8,
            "cell_threshold": cell_threshold if cell_threshold is not None else 25.0,
            "min_active_cells": min_active_cells if min_active_cells is not None else 3,
        }

    return fake


def _detail(headers, video_id):
    resp = client.get(f"/videos/{video_id}", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def _rows(video_id):
    with SessionLocal() as session:
        return {
            r.frame_index: r
            for r in session.query(Segment).filter_by(video_id=video_id).all()
        }


def test_gate_updates_existing_rows_and_creates_none(tmp_path, headers, monkeypatch):
    video_id = _make_video_with_segments(tmp_path, frame_count=10, admitted_indices=set())
    before = _rows(video_id)
    before_ids = {i: row.id for i, row in before.items()}
    before_created_at = {i: row.created_at for i, row in before.items()}

    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion({2, 5, 8}, frame_count=10)
    )

    resp = client.post(f"/videos/{video_id}/gate", json={"min_active_cells": 2}, headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"admitted": 3, "discarded": 7}

    after = _rows(video_id)
    assert set(after) == set(before)  # same frame_indices
    for i, row in after.items():
        assert row.id == before_ids[i]  # same row identity — never recreated
        assert row.created_at == before_created_at[i]  # never touched by an UPDATE
    assert len({row.id for row in after.values()}) == 10  # still exactly 10 rows, no new ones


def test_two_runs_at_different_thresholds_give_different_counts_and_no_new_rows(
    tmp_path, headers, monkeypatch
):
    video_id = _make_video_with_segments(tmp_path, frame_count=10)

    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion(set(range(2)), frame_count=10)
    )
    strict = client.post(f"/videos/{video_id}/gate", json={"min_active_cells": 10}, headers=headers)

    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion(set(range(8)), frame_count=10)
    )
    lenient = client.post(f"/videos/{video_id}/gate", json={"min_active_cells": 1}, headers=headers)

    assert strict.json() == {"admitted": 2, "discarded": 8}
    assert lenient.json() == {"admitted": 8, "discarded": 2}
    with SessionLocal() as session:
        assert session.query(Segment).filter_by(video_id=video_id).count() == 10  # still 10, after two runs


def test_a_discarded_frame_can_become_admitted_something_a_files_only_regate_could_never_do(
    tmp_path, headers, monkeypatch
):
    """The exact case the ticket flags: proving re-gating actually re-decodes
    rather than only ever being able to narrow an already-admitted set."""
    video_id = _make_video_with_segments(tmp_path, frame_count=5, admitted_indices=set())  # none admitted
    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion({1, 3}, frame_count=5)
    )

    resp = client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    assert resp.json() == {"admitted": 2, "discarded": 3}
    rows = _rows(video_id)
    assert rows[1].admitted is True and rows[1].frame_path is not None
    assert rows[3].admitted is True


def test_admission_reason_clip_window_and_files_are_all_updated_in_place(tmp_path, headers, monkeypatch):
    video_id = _make_video_with_segments(tmp_path, frame_count=5, admitted_indices={0})  # frame 0 admitted
    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion({4}, frame_count=5)
    )  # now only frame 4 is admitted

    client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    rows = _rows(video_id)
    # frame 0: was admitted, no longer is — everything about the old admission is cleared
    assert rows[0].admitted is False
    assert rows[0].frame_path is None and rows[0].thumb_path is None
    assert rows[0].admission_reason is None
    assert rows[0].clip_start_s is None and rows[0].clip_end_s is None
    # frame 4: newly admitted — everything about a real admission is present
    assert rows[4].admitted is True
    assert rows[4].frame_path is not None
    assert rows[4].admission_reason == AdmissionReason.MOTION
    assert rows[4].clip_end_s == 4.0


def test_the_overrides_are_passed_through_to_ingestion_and_omitted_ones_are_none(
    tmp_path, headers, monkeypatch
):
    video_id = _make_video_with_segments(tmp_path, frame_count=3)
    seen = {}
    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion(set(), frame_count=3, seen=seen)
    )

    client.post(f"/videos/{video_id}/gate", json={"cell_threshold": 40.0}, headers=headers)

    assert seen["kwargs"] == {
        "stride_s": None,
        "grid_size": None,
        "cell_threshold": 40.0,
        "min_active_cells": None,
    }


def test_the_resolved_parameters_are_recorded_on_the_video(tmp_path, headers, monkeypatch):
    video_id = _make_video_with_segments(tmp_path, frame_count=3)
    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion(set(), frame_count=3)
    )

    client.post(f"/videos/{video_id}/gate", json={"stride_s": 0.8, "min_active_cells": 5}, headers=headers)

    with SessionLocal() as session:
        video = session.get(Video, video_id)
        assert video.gate_stride_s == 0.8
        assert video.gate_min_active_cells == 5
        assert video.gate_grid_size == 8  # resolved default, echoed back by the fake


def test_the_video_detail_exposes_the_current_gate_parameters_and_follows_a_regate(
    tmp_path, headers, monkeypatch
):
    """OMNI-310's slider has to start at the video's real threshold, and stay
    truthful after a drag — so GET /videos/{id} reports what was recorded."""
    video_id = _make_video_with_segments(tmp_path, frame_count=3)

    detail = client.get(f"/videos/{video_id}", headers=headers).json()
    assert detail["gate_cell_threshold"] == 25.0
    assert detail["gate_min_active_cells"] == 3
    assert detail["gate_grid_size"] == 8
    assert detail["gate_stride_s"] == 0.5

    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion(set(), frame_count=3)
    )
    client.post(f"/videos/{video_id}/gate", json={"cell_threshold": 40.0}, headers=headers)

    assert client.get(f"/videos/{video_id}", headers=headers).json()["gate_cell_threshold"] == 40.0


def test_a_plain_extraction_also_records_its_own_gate_parameters(tmp_path, headers, monkeypatch):
    """Not just re-gating — a first extraction is also one run of Algorithm 1,
    at the configured defaults, and that should be reproducible too."""
    path = tmp_path / f"{NAME_PREFIX}fresh.mp4"
    path.write_bytes(b"video bytes")
    with SessionLocal() as session:
        video = Video(
            filename=path.name, path=str(path), source=VideoSource.UPLOAD,
            size_bytes=path.stat().st_size, status=VideoStatus.READY,
        )
        session.add(video)
        session.commit()
        video_id = video.id

    def fake_extract(video_id, path, source_type, camera_id):
        return {
            "ok": True,
            "segments": [],
            "error": None,
            "stride_s": 0.5,
            "grid_size": 8,
            "cell_threshold": 25.0,
            "min_active_cells": 3,
        }

    monkeypatch.setattr(extraction_module, "ingestion_extract_file", fake_extract)

    client.post(f"/videos/{video_id}/extract", headers=headers)

    with SessionLocal() as session:
        video = session.get(Video, video_id)
        assert video.gate_stride_s == 0.5
        assert video.gate_grid_size == 8


def test_gating_an_uploaded_video_is_refused(tmp_path, headers):
    video_id = _make_video_with_segments(tmp_path, frame_count=1, status=VideoStatus.UPLOADED)

    resp = client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    assert resp.status_code == 409
    assert "ready" in resp.json()["detail"]
    with SessionLocal() as session:
        assert session.get(Video, video_id).status == VideoStatus.UPLOADED  # untouched


def test_a_second_gate_while_one_is_running_is_refused(tmp_path, headers):
    video_id = _make_video_with_segments(tmp_path, frame_count=1, status=VideoStatus.EXTRACTING)

    resp = client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    assert resp.status_code == 409


def test_gating_a_missing_video_is_a_404(headers):
    assert client.post("/videos/99999999/gate", json={}, headers=headers).status_code == 404


def test_gate_requires_auth(tmp_path):
    video_id = _make_video_with_segments(tmp_path, frame_count=1)
    assert client.post(f"/videos/{video_id}/gate", json={}).status_code == 401


def test_ingestion_unavailable_reverts_to_ready_leaving_segments_untouched(tmp_path, headers, monkeypatch):
    video_id = _make_video_with_segments(tmp_path, frame_count=3, admitted_indices={1})
    before = _rows(video_id)

    def down(*args, **kwargs):
        raise IngestionUnavailableError("connection refused")

    monkeypatch.setattr(extraction_module, "ingestion_extract_file", down)

    resp = client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    assert resp.status_code == 502
    with SessionLocal() as session:
        assert session.get(Video, video_id).status == VideoStatus.READY  # reverted, not failed
    after = _rows(video_id)
    assert {i: (r.admitted, r.motion_score) for i, r in after.items()} == {
        i: (r.admitted, r.motion_score) for i, r in before.items()
    }


def test_a_reported_failure_also_reverts_to_ready_not_failed(tmp_path, headers, monkeypatch):
    video_id = _make_video_with_segments(tmp_path, frame_count=1)
    monkeypatch.setattr(
        extraction_module,
        "ingestion_extract_file",
        lambda *a, **kw: {"ok": False, "segments": [], "error": "could not decode frame 0"},
    )

    resp = client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    assert resp.status_code == 502
    assert resp.json()["detail"] == "could not decode frame 0"
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        assert video.status == VideoStatus.READY
        assert video.error is None  # a gate failure is not what `error` means


def test_a_frame_index_mismatch_is_refused_and_reverts_to_ready(tmp_path, headers, monkeypatch):
    video_id = _make_video_with_segments(tmp_path, frame_count=5)
    # the source file apparently changed shape since the last extraction
    monkeypatch.setattr(
        extraction_module, "ingestion_extract_file", _fake_gate_ingestion(set(), frame_count=7)
    )

    resp = client.post(f"/videos/{video_id}/gate", json={}, headers=headers)

    assert resp.status_code == 502
    with SessionLocal() as session:
        assert session.get(Video, video_id).status == VideoStatus.READY
        assert session.query(Segment).filter_by(video_id=video_id).count() == 5  # unchanged
