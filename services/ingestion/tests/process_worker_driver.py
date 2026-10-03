"""Runs one `ProcessWorker` scenario and prints what happened as JSON (OMNI-510a).

Started by `test_worker_process.py` as a separate Python process with
services/ingestion and this folder on its path, because ingestion's and query's
code are both a package called `app` and a test session holds only one.
"""

import json
import sys
import time

from app.live_capture import WorkerRegistry
from app.worker_process import ProcessWorker

# Under "spawn" every child re-imports this script; only the parent runs a scenario.
if __name__ == "__main__":
    scenario = sys.argv[1]
    out: dict = {}

    if scenario == "run":
        worker = ProcessWorker(7, "rtsp://unused", factory="process_worker_fixtures:steady_worker", report_interval_s=0.2)
        out["start_state"] = worker.start(20.0).value
        out["worker_id"] = worker.worker_id
        time.sleep(1.5)
        first = worker.snapshot()
        time.sleep(1.0)
        second = worker.snapshot()
        out["alive_while_running"] = worker.alive
        out["grabbed"] = [first["grabbed"], second["grabbed"]]
        out["gated"] = second["gated"]
        out["status_while_running"] = second["status"]
        out["stopped"] = worker.stop(10.0)
        out["state_after_stop"] = worker.state.value
        out["alive_after_stop"] = worker.alive
        final = worker.snapshot()
        out["final_balance"] = [final["captured"], final["gated"], final["dropped"], final["admitted"], final["discarded"]]

    elif scenario == "fail":
        worker = ProcessWorker(8, "rtsp://unused", factory="process_worker_fixtures:dead_stream_worker", report_interval_s=0.2)
        out["start_state"] = worker.start(20.0).value
        out["error"] = worker.error
        worker.stop(5.0)
        out["alive_after"] = worker.alive

    elif scenario == "kill":
        worker = ProcessWorker(9, "rtsp://unused", factory="process_worker_fixtures:steady_worker", report_interval_s=0.2)
        worker.start(20.0)
        worker._process.kill()  # the child dies without a word
        deadline = time.time() + 10
        while time.time() < deadline and worker.state.value != "failed":
            time.sleep(0.1)
        out["state_after_kill"] = worker.state.value
        out["error"] = worker.error

    elif scenario == "registry":
        registry = WorkerRegistry()
        factory = lambda: ProcessWorker(10, "rtsp://unused", factory="process_worker_fixtures:steady_worker", report_interval_s=0.2)
        first = registry.start(10, factory, 20.0)
        try:
            registry.start(10, factory, 20.0)
            out["second_start"] = "accepted"
        except Exception as exc:
            out["second_start"] = type(exc).__name__
        out["snapshots"] = len(registry.snapshots())
        out["first_state"] = first.state.value
        registry.stop_all(10.0)
        out["alive_after_stop_all"] = first.alive

    print(json.dumps(out))
