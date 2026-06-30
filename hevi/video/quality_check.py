"""RFC-002 item 13: 成片质量回归基线。

提供确定性的成片体检: ①ffprobe 规格(时长/分辨率/帧率/音轨) ②关键帧感知哈希
(average-hash, 供回归比对) ③镜头连续性打分(相邻采样帧 phash 汉明距离的反向归一)。
纯 PIL + ffmpeg/ffprobe, 无新依赖, 不需 GPU —— 可纳入 E2E 断言与回归对比。
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VideoStats:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    nb_frames: int


@dataclass
class QualityReport:
    stats: VideoStats
    phashes: list[str]
    consistency: float  # 0..1, 越高镜头越连续(相邻帧越相似)
    passed: bool
    violations: list[str] = field(default_factory=list)


def probe_stats(path: Path) -> VideoStats:
    """ffprobe 取成片规格。"""
    def _q(stream: str, entries: str) -> str:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", stream,
             "-show_entries", entries, "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True,
        )
        return r.stdout.strip()

    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    vlines = _q("v:0", "stream=width,height,r_frame_rate,nb_read_frames").splitlines()
    w = int(vlines[0]) if len(vlines) > 0 and vlines[0].isdigit() else 0
    h = int(vlines[1]) if len(vlines) > 1 and vlines[1].isdigit() else 0
    fps = 0.0
    if len(vlines) > 2 and "/" in vlines[2]:
        num, den = vlines[2].split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    has_audio = "audio" in _q("a:0", "stream=codec_type")
    try:
        duration = float(dur)
    except ValueError:
        duration = 0.0
    nb = 0
    if len(vlines) > 3 and vlines[3].isdigit():
        nb = int(vlines[3])
    return VideoStats(duration, w, h, fps, has_audio, nb)


def average_hash(img: object, hash_size: int = 8) -> str:
    """average-hash(aHash): 缩到 hash_size² 灰度, 与均值比较得位串(十六进制)。"""
    from PIL import Image

    assert isinstance(img, Image.Image)
    small = img.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    px = list(small.tobytes())  # L 模式: 每像素 1 字节灰度
    avg = sum(px) / len(px)
    bits = "".join("1" if p >= avg else "0" for p in px)
    return f"{int(bits, 2):0{hash_size * hash_size // 4}x}"


def hamming(a: str, b: str) -> int:
    """两个等长十六进制哈希的汉明距离(bit 差异数)。"""
    if len(a) != len(b):
        return max(len(a), len(b)) * 4
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def sample_phashes(path: Path, n: int = 8) -> list[str]:
    """均匀采样 n 帧, 各算 average-hash。"""
    from PIL import Image

    stats = probe_stats(path)
    dur = stats.duration or 1.0
    hashes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="qc_") as td:
        for i in range(n):
            ts = dur * (i + 0.5) / n
            frame = Path(td) / f"f{i}.png"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(path),
                 "-frames:v", "1", "-q:v", "3", str(frame)],
                capture_output=True,
            )
            if frame.exists():
                with Image.open(frame) as im:
                    hashes.append(average_hash(im))
    return hashes


def consistency_score(phashes: list[str], hash_size: int = 8) -> float:
    """相邻采样帧 phash 汉明距离的反向归一 → 0..1 连续性分(越高越连续)。"""
    if len(phashes) < 2:
        return 1.0
    bits = hash_size * hash_size
    dists = [hamming(phashes[i], phashes[i + 1]) / bits for i in range(len(phashes) - 1)]
    return max(0.0, 1.0 - sum(dists) / len(dists))


async def quality_report(
    path: Path,
    *,
    expected_duration: float | None = None,
    expected_resolution: tuple[int, int] | None = None,
    duration_tol: float = 1.0,
    require_audio: bool = False,
    n_samples: int = 8,
) -> QualityReport:
    """成片体检: 规格断言 + 关键帧哈希 + 连续性打分。

    在线程池跑(ffprobe/ffmpeg 同步), 不阻塞事件循环。
    """
    stats = await asyncio.to_thread(probe_stats, path)
    phashes = await asyncio.to_thread(sample_phashes, path, n_samples)
    cons = consistency_score(phashes)

    violations: list[str] = []
    if stats.duration <= 0:
        violations.append("成片时长为 0 / 无法探测")
    if expected_duration is not None and abs(stats.duration - expected_duration) > duration_tol:
        violations.append(
            f"时长 {stats.duration:.2f}s 偏离预期 {expected_duration:.2f}s "
            f"(容差 {duration_tol}s)"
        )
    if expected_resolution is not None and (stats.width, stats.height) != expected_resolution:
        violations.append(
            f"分辨率 {stats.width}x{stats.height} != 预期 {expected_resolution}"
        )
    if require_audio and not stats.has_audio:
        violations.append("缺音轨")

    return QualityReport(
        stats=stats, phashes=phashes, consistency=cons,
        passed=not violations, violations=violations,
    )
