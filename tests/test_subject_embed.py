"""C1: subject_embed — pure-function + error-path tests (no model needed) plus a
gated real-embed check. The real create_subject round-trip is verified manually."""

from __future__ import annotations

import importlib.util

import pytest

from hevi.subjects.subject_embed import (
    SubjectEmbedError,
    cosine_similarity,
    embedding_distance,
    subject_embed,
)


def test_cosine_and_distance_math():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    assert embedding_distance(a, b) == pytest.approx(0.0)
    assert cosine_similarity(a, c) == pytest.approx(0.0)
    assert embedding_distance(a, c) == pytest.approx(1.0)


def test_cosine_handles_empty_and_mismatched():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0
    assert embedding_distance([], []) == 1.0  # 1 - 0


def test_missing_file_raises_before_loading_model(tmp_path):
    # exists() guard fires first → no CLIP load (keeps fake-path unit tests fast/offline)
    with pytest.raises(SubjectEmbedError):
        subject_embed(image_path=tmp_path / "nope.png", kind="face")


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="transformers not installed",
)
def test_real_embed_is_normalized_512(tmp_path):
    from PIL import Image

    p = tmp_path / "img.png"
    Image.new("RGB", (64, 64), (200, 40, 40)).save(p)
    v = subject_embed(image_path=p, kind="face")
    assert len(v) == 512
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-4)  # L2-normalized
