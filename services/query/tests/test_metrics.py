"""OMNI-713: `GET /metrics/sm1` reads the result file; it measures nothing."""

import json

import pytest
from fastapi.testclient import TestClient

from app import metrics
from app.deps import get_current_user
from app.main import app

client = TestClient(app)

RESULT = {
    "recall_at_5": 0.72,
    "baseline": 0.6,
    "n_queries": 50,
    "by_kind": {
        "scene": {"frame": 0.8, "clip": 0.5, "fused": 0.8, "fused_equal": 0.76, "chance": 0.385, "n_queries": 25},
        "action": {"frame": 0.4, "clip": 0.6, "fused": 0.64, "fused_equal": 0.6, "chance": 0.117, "n_queries": 25},
    },
    "measured_at": "2026-10-31T12:00:00+00:00",
    "queries": [{"query_id": "a01"}],
}


@pytest.fixture
def logged_in():
    app.dependency_overrides[get_current_user] = lambda: object()
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_the_result_file_is_answered_as_written(logged_in, tmp_path, monkeypatch):
    path = tmp_path / "sm1_result.json"
    path.write_text(json.dumps(RESULT))
    monkeypatch.setattr(metrics, "SM1_RESULT", path)

    response = client.get("/metrics/sm1")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"recall_at_5", "baseline", "n_queries", "by_kind", "measured_at"}
    assert body["recall_at_5"] == 0.72
    assert body["baseline"] == 0.6
    assert body["n_queries"] == 50
    assert body["by_kind"]["action"]["fused"] == 0.64
    assert body["by_kind"]["scene"]["chance"] == 0.385


def test_before_it_is_measured_it_says_so(logged_in, tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "SM1_RESULT", tmp_path / "missing.json")

    response = client.get("/metrics/sm1")

    assert response.status_code == 404
    assert response.json()["detail"] == metrics.NOT_MEASURED


def test_it_needs_a_login():
    assert client.get("/metrics/sm1").status_code == 401
