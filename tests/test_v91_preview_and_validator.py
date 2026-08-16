"""v9.1:素材质检 (asset_validator) 与 15s 先导样片 (preview gate) 测试。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from hevi.explainer.assembly import _truncate_to_preview
from hevi.explainer.contracts import ExplainerCue
from hevi.sourcing.asset_validator import _validate_bytes, validate_presenter_bytes


def _jpeg_bytes(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


# ── 素材质检 ───────────────────────────────────────────────────────────


def test_valid_image_passes_without_cv2_face_check() -> None:
    verdict = _validate_bytes(_jpeg_bytes((800, 1200)), min_face_ratio=0.05, max_face_ratio=0.6)
    assert verdict.valid is True
    assert verdict.face_check == "unavailable"  # 无 opencv 时降级不阻断


def test_oversized_image_rejected() -> None:
    verdict = _validate_bytes(_jpeg_bytes((9000, 9000)), min_face_ratio=0.05, max_face_ratio=0.6)
    assert verdict.valid is False
    assert "过大" in verdict.reason


def test_tiny_image_rejected() -> None:
    verdict = _validate_bytes(_jpeg_bytes((64, 64)), min_face_ratio=0.05, max_face_ratio=0.6)
    assert verdict.valid is False


def test_bad_bytes_rejected() -> None:
    verdict = _validate_bytes(b"not-an-image", min_face_ratio=0.05, max_face_ratio=0.6)
    assert verdict.valid is False
    assert "无法解析" in verdict.reason


def test_validate_presenter_bytes_public_api(tmp_path: Path) -> None:
    """上传接口走公共字节校验:合法图通过,超大图拒绝,无 opencv 时降级不阻断。"""
    ok = validate_presenter_bytes(_jpeg_bytes((800, 1200)))
    assert ok.valid is True
    assert ok.face_check == "unavailable"

    oversized = validate_presenter_bytes(_jpeg_bytes((9000, 9000)))
    assert oversized.valid is False
    assert "过大" in oversized.reason


def test_validate_local_path_reads_from_disk(tmp_path: Path) -> None:
    """上传接口落盘后的相对路径可直接校验(不走网络)。"""
    import asyncio

    from hevi.sourcing.asset_validator import validate_presenter_image

    target = tmp_path / "presenter.jpg"
    target.write_bytes(_jpeg_bytes((800, 1200)))

    verdict = asyncio.run(validate_presenter_image(str(target)))
    assert verdict.valid is True

    missing = asyncio.run(validate_presenter_image(str(tmp_path / "nope.jpg")))
    assert missing.valid is False
    assert "不存在" in missing.reason


def test_upload_presenter_image_endpoint_accepts_valid_jpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上传接口:合法底图 → 落盘并返回可读回路径;无脸/坏字节 → 422。"""
    import asyncio

    from fastapi import UploadFile
    from fastapi.exceptions import HTTPException as FastAPIHTTPException

    from hevi.api.routers import explainer as router

    # 落盘目录指向 tmp(避免污染 output/reference_images)。
    monkeypatch.setenv("HEVI_REFERENCE_DIR", str(tmp_path / "refs"))

    user = {"id": "u-1"}

    async def run_upload(data: bytes, filename: str):
        return await router.upload_presenter_image_endpoint(
            user,
            UploadFile(file=io.BytesIO(data), filename=filename),
        )

    # 合法图 → valid + 路径可读回。
    resp = asyncio.run(run_upload(_jpeg_bytes((800, 1200)), "presenter.jpg"))
    assert resp.valid is True
    assert resp.face_check == "unavailable"  # 无 cv2 时降级,不阻断
    saved = tmp_path / "refs" / "presenter-*".replace("*", "")  # 只断言目录存在
    assert saved.parent.exists()
    assert (tmp_path / "refs").is_dir()
    assert resp.reason and resp.reason.startswith(str(tmp_path / "refs"))

    # 坏字节 → 422。
    try:
        asyncio.run(run_upload(b"not-an-image", "bad.jpg"))
        raise AssertionError("bad image should be rejected")
    except FastAPIHTTPException as exc:
        assert exc.status_code == 422


# ── 15 秒先导样片 ──────────────────────────────────────────────────────


def test_preview_truncates_to_15_seconds_budget() -> None:
    cues = [ExplainerCue(text=f"cue{i}", time_estimate_s=8) for i in range(4)]
    kept = _truncate_to_preview(cues)
    assert 2 <= len(kept) <= 3  # 8+8=16 跨过 15s 边界保留跨线那条


def test_preview_keeps_single_short_cue() -> None:
    cues = [ExplainerCue(text="one", time_estimate_s=3)]
    assert len(_truncate_to_preview(cues)) == 1


def test_preview_empty_input_returns_empty() -> None:
    assert _truncate_to_preview([]) == []
