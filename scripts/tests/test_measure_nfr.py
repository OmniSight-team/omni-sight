"""OMNI-714: the arithmetic of the NFR-1 and NFR-2 measuring scripts, on made-up rows."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    importlib.sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


nfr1 = _load("measure_nfr1")
nfr2 = _load("measure_nfr2")


def _search_row(**kw) -> dict:
    return {
        "mode": "fused", "pass": "first", "status": 200, "client_ms": 2500.0, "elapsed_ms": 2480.0, "encode_ms": 2400.0,
        "search_ms": 40.0, "fusion_ms": 0.5, "join_ms": 5.0, "encode_cached": False, **kw,
    }


def test_the_combined_figure_replaces_the_laptops_encode_with_the_gpus():
    assert nfr2.combined_ms(_search_row()) == pytest.approx(2500 - 2400 + 20)
    assert nfr2.combined_ms(_search_row(mode="frame")) == pytest.approx(2500 - 2400 + 13)
    assert nfr2.combined_ms(_search_row(mode="clip")) == pytest.approx(2500 - 2400 + 7)


def test_a_cached_query_keeps_its_own_time():
    assert nfr2.combined_ms(_search_row(encode_cached=True, encode_ms=0.1, client_ms=80.0)) == 80.0


def test_nfr2_fails_on_any_request_over_the_target_or_any_error():
    assert nfr2.passed([_search_row()])["passed"] is True
    slow = nfr2.passed([_search_row(), _search_row(client_ms=5500.0)])
    assert slow["passed"] is False
    assert slow["combined_over_target"] == 1
    failed = nfr2.passed([_search_row(), {"status": 503, "mode": "fused", "pass": "first", "client_ms": 30000.0}])
    assert failed["passed"] is False
    assert failed["errors"] == 1


def test_the_cpu_count_is_kept_apart():
    verdict = nfr2.passed([_search_row(client_ms=3100.0)])
    assert verdict["cpu_over_target"] == 1
    assert verdict["combined_over_target"] == 0


def test_nfr2_percentiles_and_a_summary_per_mode_and_pass():
    assert nfr2.stats([1.0, 2.0, 3.0, 4.0, 5.0]) == {"n": 5, "p50": 3.0, "p95": 5.0, "max": 5.0}
    assert nfr2.stats([]) == {"n": 0}
    summary = nfr2.summarise([_search_row(), _search_row(mode="clip", **{"pass": "repeat"})])
    assert summary["fused/first"]["requests"] == 1
    assert summary["clip/repeat"]["requests"] == 1
    assert summary["frame/first"]["requests"] == 0


def _control(*rows) -> dict:
    return {"rows": list(rows), "stats": {"dropped": 0}, "seen": {}}


def _record(capture: float, *, batched: float, upsert_start: float, upserted: float) -> dict:
    return {"capture": capture, "batched": batched, "upsert_start": upsert_start, "upserted": upserted, "batch_size": 1}


def test_nfr1_splits_each_frames_time_into_its_stages():
    report = nfr1.gpu_report(
        _control({"id": 1, "capture": 100.0, "stored": 100.25, "reason": "motion"}),
        {"records": {"1": _record(100.0, batched=100.75, upsert_start=100.875, upserted=101.0)}, "dead_lettered": 0},
    )
    assert report["capture_to_stored_s"]["max"] == 0.25
    assert report["stored_to_batched_s"]["max"] == 0.5
    assert report["batched_to_upsert_s"]["max"] == 0.125
    assert report["upsert_s"]["max"] == 0.125
    assert report["capture_to_searchable_s"]["max"] == 1.0
    assert report["passed"] is True


def test_nfr1_fails_a_frame_over_the_target_or_a_frame_with_no_point():
    late = nfr1.gpu_report(
        _control({"id": 1, "capture": 100.0, "stored": 100.2, "reason": "motion"}),
        {"records": {"1": _record(100.0, batched=104.0, upsert_start=105.0, upserted=105.0)}, "dead_lettered": 0},
    )
    assert late["passed"] is False
    assert late["over_target"] == 1
    missing = nfr1.gpu_report(
        _control({"id": 1, "capture": 100.0, "stored": 100.2, "reason": "motion"}, {"id": 2, "capture": 101.0, "stored": 101.2, "reason": "motion"}),
        {"records": {"1": _record(100.0, batched=100.5, upsert_start=100.6, upserted=100.7)}, "dead_lettered": 0},
    )
    assert missing["frames_with_a_point"] == 1
    assert missing["passed"] is False


def test_nfr1_separates_the_two_halves_so_a_trend_shows():
    rows = [{"id": i, "capture": 100.0 + i, "stored": 100.1 + i, "reason": "motion"} for i in range(4)]
    records = {str(i): _record(100.0 + i, batched=100.2 + i, upsert_start=100.3 + i, upserted=100.0 + i + (1.0 if i < 2 else 3.0)) for i in range(4)}
    report = nfr1.gpu_report(_control(*rows), {"records": records, "dead_lettered": 0})
    assert report["first_half_s"]["max"] == pytest.approx(1.0)
    assert report["second_half_s"]["max"] == pytest.approx(3.0)


def test_the_cpu_report_counts_a_frame_when_its_point_was_first_seen():
    control = _control({"id": 1, "capture": 100.0, "stored": 100.1, "reason": "motion"}, {"id": 2, "capture": 101.0, "stored": 101.1, "reason": "heartbeat"})
    control["seen"] = {"1": 112.0}
    report = nfr1.cpu_report(control)
    assert report["frames_stored"] == 2
    assert report["frames_with_a_point"] == 1
    assert report["capture_to_searchable_s"]["max"] == 12.0
