"""OMNI-706: the InternVideo2 clip and text encoder.

`app` is loaded as a package under another name (query and ingestion also have a top-level
package called `app`), so clip_encoder.py's relative import of the copied model code works.

The tests need the pinned checkpoint in `models/pretrained/internvideo2-clip-s/` (never
committed; ai_workers downloads it on its first start). Without it they are skipped. The
sampling tests need no model. The text side is small (63M parameters) and always runs; the
video side loads the whole model (about 3 GB of memory, half a minute a clip on this CPU),
so those tests are marked `model`:

    uv run pytest services/ai_workers/tests -m model
"""

import importlib
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
APP = Path(__file__).resolve().parents[1] / "app"
_spec = importlib.util.spec_from_file_location(
    "omnisight_ai_workers_app", APP / "__init__.py", submodule_search_locations=[str(APP)]
)
_package = importlib.util.module_from_spec(_spec)
importlib.sys.modules["omnisight_ai_workers_app"] = _package
_spec.loader.exec_module(_package)
clip_encoder = importlib.import_module("omnisight_ai_workers_app.clip_encoder")

CHECKPOINT = ROOT / "models" / "pretrained" / "internvideo2-clip-s"
needs_checkpoint = pytest.mark.skipif(
    not (CHECKPOINT / "model.safetensors").is_file(), reason="the InternVideo2 checkpoint is not in models/pretrained/"
)


@pytest.fixture(scope="module")
def text_only():
    if not (CHECKPOINT / "model.safetensors").is_file():
        pytest.skip("the InternVideo2 checkpoint is not in models/pretrained/")
    return clip_encoder.ClipTextEncoder(CHECKPOINT, video=False)


@pytest.fixture(scope="module")
def model():
    if not (CHECKPOINT / "model.safetensors").is_file():
        pytest.skip("the InternVideo2 checkpoint is not in models/pretrained/")
    return clip_encoder.ClipTextEncoder(CHECKPOINT)


# --- uniform_subsample ----------------------------------------------------------------------


def test_eight_frames_are_spread_evenly_over_the_span():
    # The middle of each eighth of frames 0..79.
    assert clip_encoder.uniform_indices(0, 79) == [4, 14, 24, 34, 44, 54, 64, 74]


def test_the_frames_stay_inside_the_span():
    for start, end in [(100, 107), (2489, 2577), (5, 1000), (0, 8)]:
        indices = clip_encoder.uniform_indices(start, end)

        assert len(indices) == 8
        assert indices == sorted(indices)
        assert start <= indices[0] and indices[-1] <= end


def test_a_span_shorter_than_eight_frames_repeats_its_last_frame():
    assert clip_encoder.uniform_indices(10, 13) == [10, 11, 12, 13, 13, 13, 13, 13]


def test_an_empty_span_is_refused():
    with pytest.raises(ValueError):
        clip_encoder.uniform_indices(10, 9)


# --- the text side (the laptop's part, D-32) ------------------------------------------------


@needs_checkpoint
def test_text_encodes_to_unit_512_vectors(text_only):
    vectors = text_only.encode_texts(["a person opening the trunk of a car", "a car"])

    assert vectors.shape == (2, 512)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


@needs_checkpoint
def test_text_is_lowercased_by_the_tokenizer(text_only):
    upper, lower = text_only.encode_texts(["A Person Running", "a person running"])

    assert np.allclose(upper, lower, atol=1e-6)


@needs_checkpoint
def test_the_text_only_encoder_has_no_video_side(text_only):
    assert text_only.vision is None
    with pytest.raises(RuntimeError):
        text_only.encode_clips([[np.zeros((224, 224, 3), np.uint8)] * 8])


@needs_checkpoint
def test_every_weight_of_the_checkpoint_has_a_place_in_the_copied_code():
    # Strict loading refuses a missing or extra key within each part (the text side in
    # every run, the video side in the model tests); this checks that no whole part of
    # the checkpoint is left out (only the training temperature is unused).
    from safetensors import safe_open

    with safe_open(str(CHECKPOINT / "model.safetensors"), "pt") as source:
        prefixes = {key.split(".")[0] for key in source.keys()}

    assert prefixes == {"text_encoder", "vision_encoder", "vision_align", "temp"}


# --- the video side -------------------------------------------------------------------------


def _clip(seed: int) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [rng.integers(0, 256, (360, 640, 3), dtype=np.uint8) for _ in range(8)]


@pytest.mark.model
@needs_checkpoint
def test_a_clip_encodes_to_a_unit_512_vector(model):
    vectors = model.encode_clips([_clip(1)])

    assert vectors.shape == (1, 512)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


@pytest.mark.model
@needs_checkpoint
def test_a_batch_gives_the_same_vectors_as_one_at_a_time(model):
    clips = [_clip(1), _clip(2)]

    together = model.encode_clips(clips)
    alone = np.vstack([model.encode_clips([c]) for c in clips])

    assert np.allclose(together, alone, atol=1e-4)


@pytest.mark.model
@needs_checkpoint
def test_frame_order_matters(model):
    # The encoder sees time: the same frames reversed are a different clip.
    frames = _clip(3)
    forward, backward = model.encode_clips([frames, frames[::-1]])

    assert not np.allclose(forward, backward, atol=1e-3)


@pytest.mark.model
@needs_checkpoint
def test_a_clip_is_eight_frames(model):
    with pytest.raises(ValueError):
        model.encode_clips([_clip(1)[:7]])
