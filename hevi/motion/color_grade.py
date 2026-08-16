"""色彩分级/LUT —— 预设模型 + 校验 + ffmpeg filter 链(3O 内化 Round 3,补"色彩分级"缺口)。

HyperFrames 有完整 colorGrading + LUT;hevi 只有 assembly.color_normalize(跨 provider
调色归一化,单参数)。这里补**分级预设模型**(曝光/对比/饱和/暖度/暗角)+ **LUT 校验**
(.cube 解析)+ **ffmpeg filter 链构建**(调色应用,缺 ffmpeg 时降级)。

确定性部分(可测):预设 → 参数表;.cube 解析;filter 链字符串构建。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GradePreset:
    """一个分级预设:一组确定性调色参数。"""

    name: str
    exposure: float = 0.0  # EV
    contrast: float = 1.0  # 1 = 原始
    saturation: float = 1.0
    warmth: float = 0.0  # 正 = 暖
    vignette: float = 0.0  # 0-1 暗角强度

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "exposure": self.exposure,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "warmth": self.warmth,
            "vignette": self.vignette,
        }


#: 内置分级预设(hyperframes Media Treatments 参考起步,可追加)。
GRADE_PRESETS: tuple[GradePreset, ...] = (
    GradePreset(name="neutral", exposure=0.0, contrast=1.0, saturation=1.0),
    GradePreset(name="warm_film", exposure=0.08, contrast=1.06, saturation=1.12, warmth=0.10),
    GradePreset(name="cool_tech", exposure=-0.04, contrast=1.12, saturation=0.92, warmth=-0.12),
    GradePreset(
        name="retro_dv", exposure=0.12, contrast=0.9,
        saturation=0.85, warmth=0.16, vignette=0.18,
    ),
    GradePreset(name="bw_cinema", exposure=0.02, contrast=1.18, saturation=0.0),
)


def grade_preset_by_name(name: str) -> GradePreset:
    for preset in GRADE_PRESETS:
        if preset.name == name:
            return preset
    raise KeyError(f"unknown grade preset {name!r}")


def build_ffmpeg_grade_filter(preset: GradePreset) -> str:
    """分级 → ffmpeg filter 链(确定性字符串;空 = 无需调色)。"""
    parts: list[str] = []
    if abs(preset.exposure) > 0.001:
        parts.append(f"eq=brightness={preset.exposure:.3f}")
    if abs(preset.contrast - 1.0) > 0.001:
        parts.append(f"eq=contrast={preset.contrast:.3f}")
    if abs(preset.saturation - 1.0) > 0.001:
        parts.append(f"eq=saturation={preset.saturation:.3f}")
    if abs(preset.warmth) > 0.001:
        r, b = 1.0 + preset.warmth, 1.0 - preset.warmth
        parts.append(f"colorbalance=rs={r:.3f}:bs={b:.3f}:gs=1.0")
    if preset.vignette > 0.001:
        parts.append(f"vignette=PI/{4.0 + (1.0 - preset.vignette) * 6.0:.3f}")
    return ",".join(parts)


#: .cube LUT 解析:LUT_3D_SIZE / DOMAIN_MIN/MAX / 数据行(RGB 每通道 0-1)。
_CUBE_SIZE_RE = re.compile(r"LUT_3D_SIZE\s+(\d+)")
_CUBE_DATA_LINE = re.compile(r"^\s*([0-9.+-]+)\s+([0-9.+-]+)\s+([0-9.+-]+)\s*$")


@dataclass
class Lut3D:
    """解析后的 .cube LUT。"""

    path: Path
    size: int
    table: list[tuple[float, float, float]]

    @property
    def valid(self) -> bool:
        return self.size > 0 and len(self.table) == self.size**3


def parse_cube_lut(path: str | Path) -> Lut3D:
    """解析 .cube 文件(标准 3D LUT);格式不符抛 ValueError。"""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"lut not found: {p}")
    size = 0
    table: list[tuple[float, float, float]] = []
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            continue
        m = _CUBE_SIZE_RE.search(line)
        if m:
            size = int(m.group(1))
            continue
        if line.upper().startswith("DOMAIN"):
            continue
        dm = _CUBE_DATA_LINE.match(line)
        if dm:
            table.append(
                (float(dm.group(1)), float(dm.group(2)), float(dm.group(3)))
            )
    lut = Lut3D(path=p, size=size, table=table)
    if not lut.valid:
        raise ValueError(
            f"invalid .cube: size={size}, rows={len(table)} (期望 {size**3})"
        )
    return lut


def grade_ffmpeg_command(input_path: Path, output_path: Path, lut: Lut3D) -> list[str]:
    """LUT 应用命令(ffmpeg lut3d filter);纯构建,不执行。"""
    return [
        "ffmpeg", "-i", str(input_path),
        "-vf", f"lut3d='{lut.path}':interp=tetrahedral",
        "-c:a", "copy", str(output_path),
    ]
