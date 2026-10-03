"""OMNI-510a: a camera's worker in a process of its own.

Each scenario runs in `process_worker_driver.py`, a separate Python process with
services/ingestion on its path (ingestion's and query's code are both a package
called `app`, and one test session holds only one), and that process spawns the
camera's worker process, as ingestion does. The worker is a real `LiveWorker` over
a scripted stream (`process_worker_fixtures.py`); the real stack ran too
(docs/context/week-05.md, OMNI-510a).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
INGESTION = TESTS.parent


def _scenario(name: str) -> dict:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(INGESTION), str(TESTS)])}
    done = subprocess.run(
        [sys.executable, str(TESTS / "process_worker_driver.py"), name],
        cwd=INGESTION, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_worker_in_its_own_process_runs_reports_and_stops():
    out = _scenario("run")

    assert out["start_state"] == "running" and out["worker_id"]
    assert out["alive_while_running"] is True and out["status_while_running"] == "running"
    assert out["grabbed"][1] > out["grabbed"][0] > 0  # the reports keep coming
    assert out["gated"] > 0
    assert out["stopped"] is True and out["state_after_stop"] == "stopped" and out["alive_after_stop"] is False
    captured, gated, dropped, admitted, discarded = out["final_balance"]
    # The child's last report, after the stop: every frame gated or dropped, as in-process.
    assert captured == gated + dropped and gated == admitted + discarded


def test_a_stream_that_cannot_be_opened_fails_the_start_with_its_reason():
    out = _scenario("fail")

    assert out["start_state"] == "failed"
    assert out["error"] == "could not open the stream"
    assert out["alive_after"] is False


def test_a_worker_process_that_dies_reads_as_failed():
    out = _scenario("kill")

    assert out["state_after_kill"] == "failed"
    assert "ended unexpectedly" in out["error"]


def test_the_registry_still_allows_one_worker_per_camera():
    out = _scenario("registry")

    assert out["first_state"] == "running"
    assert out["second_start"] == "AlreadyRunning"
    assert out["snapshots"] == 1
    assert out["alive_after_stop_all"] is False
