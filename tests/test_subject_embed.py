"""C1: subject_embed — pure-function + error-path tests (no model needed) plus a
gated real-embed check. The real create_subject round-trip is verified manually."""

from __future__ import annotations

import importlib.util

import pytest

from hevi.subjects.subject_embed import (
    SubjectEmbedError,
    _crop_face_region,
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


# 多区域 embedding(HEVI 路线图 Phase2 #34):kind="face" 几何裁剪启发式。


def test_crop_face_region_takes_top_center_portion():
    from PIL import Image

    img = Image.new("RGB", (200, 300))
    cropped = _crop_face_region(img)
    # 高度 = 55%(_FACE_CROP_TOP_RATIO),宽度 = 居中 70%(_FACE_CROP_WIDTH_RATIO)
    assert cropped.size == (140, 165)


def test_crop_face_region_is_centered_horizontally():
    from PIL import Image

    img = Image.new("RGB", (100, 100))
    cropped = _crop_face_region(img)
    # 左右各切掉 15%(= (1-0.7)/2),裁剪结果水平居中
    left_margin = int(100 * (1 - 0.7) / 2)
    assert cropped.size == (100 - 2 * left_margin, 55)


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


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="transformers not installed",
)
def test_kind_face_actually_crops_end_to_end(tmp_path):
    """多区域 embedding(#34):kind="face" 要真的把 kind="style"(全图)排除掉的
    下半部分内容排除在外——上下两半用差异悬殊的纯色拼图,face 向量应该更贴近
    只用上半部分算出来的向量,而不是跟全图向量完全一致(证明真的裁剪了,不是
    labels 摆设)。"""
    from PIL import Image

    img = Image.new("RGB", (100, 100))
    top = Image.new("RGB", (100, 55), (255, 0, 0))
    bottom = Image.new("RGB", (100, 45), (0, 0, 255))
    img.paste(top, (0, 0))
    img.paste(bottom, (0, 55))
    p = tmp_path / "split.png"
    img.save(p)

    top_only = tmp_path / "top_only.png"
    top.save(top_only)

    face_vec = subject_embed(image_path=p, kind="face")
    whole_vec = subject_embed(image_path=p, kind="style")
    top_vec = subject_embed(image_path=top_only, kind="style")

    assert face_vec != whole_vec
    assert cosine_similarity(face_vec, top_vec) > cosine_similarity(whole_vec, top_vec)


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
