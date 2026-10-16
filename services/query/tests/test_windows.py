"""OMNI-609: the sampled windows, and the hand check's verdicts.

Requires Postgres (`docker compose up -d`); runs on the test database (conftest). A tiny
dataset with its own sample file: two sampled clips, one not sampled; a negative window and
a 60 s window that must not be listed.
"""

import pytest
from app import datasets as datasets_module
from app.db import SessionLocal
from app.main import app
from app.models import DatasetManifest, EventWindow, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Domain, Role, VideoSource, VideoStatus
from omnisight_common.datasets import AnnotationSource

client = TestClient(app)

TEST_PASSWORD = "Omni609Pass!"
EMAILS = {Role.ADMIN: "omni609-admin@omnisight.local", Role.OPERATOR: "omni609-operator@omnisight.local"}


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
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def windows(tmp_path, monkeypatch):
    sample = tmp_path / "sample.csv"
    sample.write_text(
        "dataset,clip_key,video_relpath,event_class,annotation_source,split\n"
        "ucf_crime,omni609_a.mp4,v/a.mp4,Robbery,uca,train\n"
        "ccd,omni609/000001,v/1.mp4,Crash,ccd_binlabels,held_out\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "hand_check_sample_path", str(sample))
    ids = {}
    with SessionLocal() as s:
        video = Video(filename="a.mp4", path="/data/videos/a.mp4", source=VideoSource.DATASET, size_bytes=1,
                      status=VideoStatus.READY, duration_s=90.0)
        s.add(video)
        s.flush()
        clips = {
            "a": DatasetManifest(dataset="ucf_crime", clip_key="omni609_a.mp4", domain=Domain.SURVEILLANCE,
                                 event_class="Robbery", event_start_s=40.0, event_end_s=55.0,
                                 annotation_source=AnnotationSource.UCA, split="train", video_relpath="v/a.mp4",
                                 video_id=video.id),
            "c": DatasetManifest(dataset="ccd", clip_key="omni609/000001", domain=Domain.TRAFFIC, event_class="Crash",
                                 event_start_s=3.2, event_end_s=5.0, annotation_source=AnnotationSource.CCD_BINLABELS,
                                 split="held_out", video_relpath="v/1.mp4"),
            "x": DatasetManifest(dataset="ucf_crime", clip_key="omni609_x.mp4", domain=Domain.SURVEILLANCE,
                                 event_class="Robbery", event_start_s=40.0, annotation_source=AnnotationSource.UCA,
                                 split="train", video_relpath="v/x.mp4"),
        }
        s.add_all(clips.values())
        s.flush()

        def win(clip, kind, nominal, start, end, cls):
            w = EventWindow(manifest_id=clips[clip].id, kind=kind, nominal_length_s=nominal, window_start_s=start,
                            window_end_s=end, length_s=end - start, event_class=cls, domain=clips[clip].domain,
                            split=clips[clip].split)
            s.add(w)
            s.flush()
            return w.id

        ids["a30"] = win("a", "positive", 30.0, 10.0, 40.0, "Robbery")
        ids["a60"] = win("a", "positive", 60.0, 0.0, 40.0, "Robbery")
        ids["c"] = win("c", "positive", None, 0.0, 3.2, "Crash")
        ids["x30"] = win("x", "positive", 30.0, 10.0, 40.0, "Robbery")
        s.commit()
        manifest_ids = [c.id for c in clips.values()]
        video_id = video.id
    monkeypatch.setattr(datasets_module, "_refused", {})
    yield ids
    with SessionLocal() as s:
        s.query(EventWindow).filter(EventWindow.manifest_id.in_(manifest_ids)).delete(synchronize_session=False)
        s.query(DatasetManifest).filter(DatasetManifest.id.in_(manifest_ids)).delete(synchronize_session=False)
        s.query(Video).filter_by(id=video_id).delete(synchronize_session=False)
        s.commit()


def test_lists_one_checked_window_per_sampled_clip(windows):
    resp = client.get("/windows", headers=_headers(Role.OPERATOR))
    assert resp.status_code == 200
    assert sorted(w["id"] for w in resp.json()) == sorted([windows["a30"], windows["c"]])


def test_detail_carries_the_event_and_the_video(windows):
    d = client.get(f"/windows/{windows['a30']}", headers=_headers(Role.OPERATOR)).json()
    assert (d["window_start_s"], d["window_end_s"], d["event_start_s"], d["event_end_s"]) == (10.0, 40.0, 40.0, 55.0)
    assert d["annotation_source"] == "uca" and d["video_duration_s"] == 90.0 and d["playback_url"].startswith("/media/")
    ccd = client.get(f"/windows/{windows['c']}", headers=_headers(Role.OPERATOR)).json()
    assert ccd["video_id"] is None and ccd["playback_url"] is None  # not loaded: no player


def test_unsampled_or_unchecked_windows_are_not_found(windows):
    for key in ("x30", "a60"):
        assert client.get(f"/windows/{windows[key]}", headers=_headers(Role.ADMIN)).status_code == 404


def test_verdicts_are_stored_with_who_and_when_and_can_be_replaced(windows):
    url = f"/windows/{windows['a30']}/verdict"
    d = client.post(url, json={"correct": False, "reason": "ends too late: robbery visible at 35 s"},
                    headers=_headers(Role.ADMIN)).json()
    assert d["verified"] is False and d["verify_reason"].startswith("ends too late")
    assert d["verified_by"] == EMAILS[Role.ADMIN] and d["verified_at"] is not None
    d = client.post(url, json={"correct": True, "reason": "ignored"}, headers=_headers(Role.ADMIN)).json()
    assert d["verified"] is True and d["verify_reason"] is None


def test_wrong_needs_a_reason_and_operators_cannot_judge(windows):
    url = f"/windows/{windows['a30']}/verdict"
    assert client.post(url, json={"correct": False, "reason": " "}, headers=_headers(Role.ADMIN)).status_code == 422
    assert client.post(url, json={"correct": True}, headers=_headers(Role.OPERATOR)).status_code == 403
    assert client.post(url, json={"correct": True}).status_code == 401
