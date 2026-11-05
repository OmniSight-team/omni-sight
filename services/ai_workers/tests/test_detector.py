"""OMNI-X02 (D-42): YOLO-World's weights are used only at the pinned SHA-256, and boxes come
back per frame in fractions of the frame. The test marked `model` loads the real weights from
`models/pretrained/yolo-world` (downloaded there if missing: 25 MB, plus CLIP ViT-B/32's
338 MB): `uv run pytest services/ai_workers/tests -m model`.

detector.py is loaded by file path under its own name, as in test_encoder.py (query and
ingestion also have a package called `app`)."""

import hashlib
import importlib.util
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "omnisight_ai_workers_detector", Path(__file__).resolve().parents[1] / "app" / "detector.py"
)
detector_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detector_module)
BoxDetector, ensure_weights = detector_module.BoxDetector, detector_module.ensure_weights
MODEL_DIR = ROOT / "models" / "pretrained" / "yolo-world"


def _fake_download(content: bytes):
    def download(url, path):
        with open(path, "wb") as handle:
            handle.write(content)
    return download


def test_weights_with_the_pinned_hash_are_used_without_a_download(tmp_path, monkeypatch):
    content = b"pinned weights"
    (tmp_path / detector_module.WEIGHTS_FILE).write_bytes(content)
    monkeypatch.setattr(detector_module, "WEIGHTS_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(detector_module.urllib.request, "urlretrieve", lambda *a: pytest.fail("downloaded"))

    assert ensure_weights(tmp_path) == tmp_path / detector_module.WEIGHTS_FILE


def test_missing_or_altered_weights_are_downloaded_again(tmp_path, monkeypatch):
    content = b"pinned weights"
    (tmp_path / detector_module.WEIGHTS_FILE).write_bytes(b"altered")
    monkeypatch.setattr(detector_module, "WEIGHTS_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(detector_module.urllib.request, "urlretrieve", _fake_download(content))

    path = ensure_weights(tmp_path)

    assert path.read_bytes() == content


def test_a_download_with_another_hash_is_refused_and_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(detector_module, "WEIGHTS_SHA256", "0" * 64)
    monkeypatch.setattr(detector_module.urllib.request, "urlretrieve", _fake_download(b"something else"))

    with pytest.raises(RuntimeError, match="not the pinned"):
        ensure_weights(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.model
def test_boxes_per_frame_in_fractions_and_none_for_an_unreadable_frame(tmp_path):
    """A white car-like shape is not a test of quality, only of the format: whatever is found
    is at most 3 boxes, inside 0-1, each with a label from the prompts."""
    frame = tmp_path / "frame.jpg"
    image = Image.new("RGB", (1280, 720), "gray")
    ImageDraw.Draw(image).rectangle([400, 300, 800, 500], fill="white")
    image.save(frame)
    detector = BoxDetector(MODEL_DIR, 0.01, 3)

    [found, missing] = detector.detect([frame, tmp_path / "missing.jpg"], ["a white car", "car"])

    assert missing == []
    assert len(found) <= 3
    for box in found:
        assert box["label"] == "car"
        x1, y1, x2, y2 = box["box"]
        assert 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1
        assert 0.01 <= box["score"] <= 1
