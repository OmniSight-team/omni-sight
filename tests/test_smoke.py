"""Smoke tests — verify every workspace package is importable."""

import importlib

import pytest

WORKSPACE_PACKAGES = [
    "omnisight_common",
    "omnisight_messaging",
    "ingestion",
    "ai_worker_frame",
    "ai_worker_temporal",
    "query_service",
    "pfm",
    "verification",
    "rag_forensics",
]


@pytest.mark.parametrize("package", WORKSPACE_PACKAGES)
def test_package_importable(package: str) -> None:
    mod = importlib.import_module(package)
    assert mod is not None
