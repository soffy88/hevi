"""OMQUALITY 后期增强 —— 真解码 / 真 ffmpeg 的回归测试。

只测"量错了会被抓出来"的那几件事, 其余能力由 scripts/om_quality_e2e.py 在真实
成片上端到端跑一遍。图片夹具在 tmp 里现造(纯色块), 不是伪造的验收数据 ——
这里验的是**算子行为**, 验收数据一律来自 E2E。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageStat

from hevi.layer4_legacy.enhance.oprim_impl.lut import apply_lut
from hevi.layer4_legacy.enhance.oprim_impl.media import MediaError, run_ffmpeg
from hevi.layer4_legacy.enhance.oskill_impl.lut_math import cube_lines


def _rgb(path: Path) -> tuple[float, float, float]:
    with Image.open(path) as im:
        return tuple(round(float(v), 3) for v in ImageStat.Stat(im.convert("RGB")).mean)  # type: ignore[return-value]


@pytest.fixture()
def photo(tmp_path: Path) -> Path:
    """A flat mid-grey test image (not a measurement fixture — an input)."""
    src = tmp_path / "grey.png"
    Image.new("RGB", (64, 64), (128, 128, 128)).save(src)
    return src


# --- LUT: the intensity knob must mean what it says -----------------------


def test_intensity_zero_is_exactly_the_source(photo: Path, tmp_path: Path) -> None:
    """Regression: the blend used to put the SOURCE first, which inverted the
    knob — intensity 0 applied the full grade and 0.85 applied almost none."""
    out = tmp_path / "i0.png"
    apply_lut(photo, out, look="teal", lut_dir=tmp_path / "luts", intensity=0.0)
    assert _rgb(out) == pytest.approx(_rgb(photo), abs=0.01)


def test_intensity_one_is_the_full_look(photo: Path, tmp_path: Path) -> None:
    out = tmp_path / "i1.png"
    apply_lut(photo, out, look="teal", lut_dir=tmp_path / "luts", intensity=1.0)
    assert _rgb(out) != pytest.approx(_rgb(photo), abs=0.5)


def test_intensity_is_monotonic(photo: Path, tmp_path: Path) -> None:
    """越大的 intensity 必须越靠近满强度(与满强度的差距单调收敛)。"""
    full = tmp_path / "full.png"
    apply_lut(photo, full, look="teal", lut_dir=tmp_path / "luts", intensity=1.0)
    graded = _rgb(full)
    previous_gap = float("inf")
    for intensity in (0.0, 0.25, 0.5, 0.75, 1.0):
        out = tmp_path / f"m{intensity}.png"
        apply_lut(photo, out, look="teal", lut_dir=tmp_path / "luts", intensity=intensity)
        gap = abs(_rgb(out)[0] - graded[0])
        assert gap <= previous_gap + 1e-6, f"intensity={intensity} 没有单调靠近满强度"
        previous_gap = gap
    assert _rgb(photo) != graded


def test_unknown_look_is_refused(photo: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown look"):
        apply_lut(photo, tmp_path / "x.png", look="not_a_look", lut_dir=tmp_path / "luts")


def test_cube_has_the_right_shape(tmp_path: Path) -> None:
    lines = cube_lines("ink", size=17)
    header, body = lines[:4], lines[4:]
    assert header[1] == "LUT_3D_SIZE 17"
    assert len(body) == 17**3
    assert all(len(line.split()) == 3 for line in body)


def test_lut_rejects_non_media(photo: Path, tmp_path: Path) -> None:
    junk = tmp_path / "not_media.txt"
    junk.write_text("hello")
    with pytest.raises(ValueError):
        apply_lut(junk, tmp_path / "x.png", look="teal", lut_dir=tmp_path / "luts")


# --- ffmpeg error handling is honest --------------------------------------


def test_run_ffmpeg_raises_on_failure(tmp_path: Path) -> None:
    with pytest.raises(MediaError):
        run_ffmpeg(["-i", str(tmp_path / "does_not_exist.mp4"), str(tmp_path / "out.mp4")])
