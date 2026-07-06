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
    text_embed,
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


def test_text_embed_empty_raises():
    with pytest.raises(SubjectEmbedError):
        text_embed("")


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="transformers not installed",
)
def test_real_text_embed_is_normalized_512_and_matches_image(tmp_path):
    """tongjian L6 G6 门要的是文本-图像跨模态相似度:同一 CLIP 空间下,
    红色方块图应该跟"红色"文本比"蓝色"文本更相似——不只是维度/归一化对,
    真的要能分辨。"""
    from PIL import Image

    v = text_embed("a solid red square")
    assert len(v) == 512
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-4)

    red_path = tmp_path / "red.png"
    Image.new("RGB", (64, 64), (220, 20, 20)).save(red_path)
    red_img_vec = subject_embed(image_path=red_path, kind="style")

    red_text_vec = text_embed("a photo of a red square")
    blue_text_vec = text_embed("a photo of a blue square")
    assert cosine_similarity(red_img_vec, red_text_vec) > cosine_similarity(
        red_img_vec, blue_text_vec
    )
