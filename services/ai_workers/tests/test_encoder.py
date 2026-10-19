"""OMNI-704: the SigLIP 2 frame and text encoder.

encoder.py is loaded by file path under its own name, because query and ingestion also
have a top-level package called `app` (the same trick as ingestion's tests).

The tests need the pinned checkpoint in `models/pretrained/` (never committed; ai_workers
downloads it on its first start). Without it they are skipped, not failed. The text tests
read only the tokenizer and always run; the encoding tests load the whole model (about 4.5 GB
of memory, minutes on this CPU), so they are marked `model` and run only when asked:

    uv run pytest services/ai_workers/tests -m model
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "omnisight_ai_workers_encoder", Path(__file__).resolve().parents[1] / "app" / "encoder.py"
)
encoder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(encoder)

CHECKPOINT = ROOT / "models" / "pretrained" / "siglip2-so400m-patch14-384"
needs_checkpoint = pytest.mark.skipif(
    not (CHECKPOINT / "model.safetensors").is_file(), reason="the SigLIP 2 checkpoint is not in models/pretrained/"
)


@pytest.fixture(scope="module")
def processor():
    if not (CHECKPOINT / "tokenizer.json").is_file():
        pytest.skip("the SigLIP 2 tokenizer is not in models/pretrained/")
    from transformers import AutoProcessor

    return AutoProcessor.from_pretrained(CHECKPOINT)


@pytest.fixture(scope="module")
def model():
    if not (CHECKPOINT / "model.safetensors").is_file():
        pytest.skip("the SigLIP 2 checkpoint is not in models/pretrained/")
    return encoder.FrameTextEncoder(CHECKPOINT)


# --- the text trap --------------------------------------------------------------------------


def test_text_is_padded_to_64_tokens(processor):
    inputs = encoder.text_inputs(processor, ["a person", "a red car parked next to a building at night"])

    assert inputs["input_ids"].shape == (2, 64)


def test_the_processor_alone_does_not_pad_to_64(processor):
    # Why text_inputs exists: called with its defaults, the processor gives a short
    # sequence, which the model still encodes, only worse.
    plain = processor(text=["a person"], return_tensors="pt")

    assert plain["input_ids"].shape[1] < 64


def test_text_is_lowercased(processor):
    upper = encoder.text_inputs(processor, ["A Person Running"])["input_ids"]
    lower = encoder.text_inputs(processor, ["a person running"])["input_ids"]

    assert upper.tolist() == lower.tolist()


def test_long_text_is_truncated_to_64_tokens(processor):
    inputs = encoder.text_inputs(processor, ["a person walking " * 100])

    assert inputs["input_ids"].shape == (1, 64)


# --- encoding -------------------------------------------------------------------------------


def _solid(tmp_path: Path, name: str, rgb: tuple[int, int, int]) -> Path:
    path = tmp_path / f"{name}.jpg"
    Image.new("RGB", (640, 360), rgb).save(path, quality=90)
    return path


@pytest.mark.model
@needs_checkpoint
def test_frames_encode_to_unit_1152_vectors(model, tmp_path):
    paths = [_solid(tmp_path, "red", (220, 20, 20)), _solid(tmp_path, "green", (20, 200, 40))]

    vectors = model.encode_images(paths)

    assert vectors.shape == (2, 1152)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


@pytest.mark.model
@needs_checkpoint
def test_a_batch_gives_the_same_vectors_as_one_at_a_time(model, tmp_path):
    paths = [_solid(tmp_path, "red", (220, 20, 20)), _solid(tmp_path, "blue", (20, 40, 220))]

    together = model.encode_images(paths)
    alone = np.vstack([model.encode_images([p]) for p in paths])

    assert np.allclose(together, alone, atol=1e-4)


@pytest.mark.model
@needs_checkpoint
def test_text_encodes_to_a_unit_1152_vector(model):
    vectors = model.encode_texts(["a person walking", "a car"])

    assert vectors.shape == (2, 1152)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


@pytest.mark.model
@needs_checkpoint
def test_text_and_frames_share_one_space(model, tmp_path):
    images = model.encode_images([_solid(tmp_path, "red", (220, 20, 20)), _solid(tmp_path, "green", (20, 200, 40))])
    texts = model.encode_texts(["a plain red image", "a plain green image"])

    similarity = texts @ images.T

    assert similarity[0, 0] > similarity[0, 1]
    assert similarity[1, 1] > similarity[1, 0]


# --- the checkpoint -------------------------------------------------------------------------


def test_a_checkpoint_at_the_pinned_revision_is_not_downloaded_again(tmp_path, monkeypatch):
    import huggingface_hub

    (tmp_path / encoder.REVISION_FILE).write_text("abc\n")
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: pytest.fail("downloaded again"))

    assert encoder.ensure_checkpoint("google/x", "abc", tmp_path) == tmp_path


def test_a_checkpoint_at_another_revision_is_replaced(tmp_path, monkeypatch):
    import huggingface_hub

    calls = []
    (tmp_path / encoder.REVISION_FILE).write_text("old\n")
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: calls.append((a, k)))

    encoder.ensure_checkpoint("google/x", "new", tmp_path)

    assert calls[0][1]["revision"] == "new"
    assert (tmp_path / encoder.REVISION_FILE).read_text().strip() == "new"
