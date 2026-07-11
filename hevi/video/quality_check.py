"""RFC-002 item 13: 成片质量回归基线。

提供确定性的成片体检: ①ffprobe 规格(时长/分辨率/帧率/音轨) ②关键帧感知哈希
(average-hash, 供回归比对) ③镜头连续性打分(相邻采样帧 phash 汉明距离的反向归一)
④响度(LUFS,ffmpeg ebur128,纯确定性无 ML)⑤字幕对齐率(HEVI 路线图 Phase1 Tier0
补全:重新对成片音轨跑一遍 ASR,和烧录用的 subtitles.srt 时间码比对重叠率——不是
"配没配字幕",是"字幕时间码有没有跟实际说话对上",catches 装配阶段悄悄引入的漂移)。
纯 PIL + ffmpeg/ffprobe(+ faster-whisper 做字幕对齐,复用 hevi.assembly.subtitle_align
已有的 ASR 调用,不重新接模型), 不需 GPU —— 可纳入 E2E 断言与回归对比。
"""

from __future__ import annotations

import asyncio
import re
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
    # None = 没跑(无音轨/无字幕文件/ASR 失败等,best-effort 跳过,不是测出来的 0)。
    loudness_lufs: float | None = None
    subtitle_alignment_rate: float | None = None


def probe_stats(path: Path) -> VideoStats:
    """ffprobe 取成片规格。"""

    def _q(stream: str, entries: str) -> str:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                stream,
                "-show_entries",
                entries,
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        return r.stdout.strip()

    dur = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
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
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{ts:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(frame),
                ],
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


_LUFS_RE = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", re.IGNORECASE)


def measure_loudness(path: Path) -> float | None:
    """ffmpeg ebur128 滤镜量测整体响度(积分 LUFS)。无音轨/量测失败 → None(不是 0,
    0 LUFS 是"震耳欲聋",跟"没测出来"含义完全相反,不能混为一谈)。"""
    r = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=none", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    m = _LUFS_RE.search(r.stderr)
    return float(m.group(1)) if m else None


def _parse_srt_windows(srt_text: str) -> list[tuple[float, float]]:
    """SRT → [(start_s, end_s), ...]。只要时间码,不关心字幕文字内容对不对。"""

    def _ts(s: str) -> float:
        h, m, rest = s.split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000

    windows: list[tuple[float, float]] = []
    for line in srt_text.splitlines():
        if "-->" not in line:
            continue
        a, b = (p.strip() for p in line.split("-->"))
        try:
            windows.append((_ts(a), _ts(b.split()[0])))
        except ValueError, IndexError:
            continue
    return windows


def subtitle_alignment_rate(
    video_path: Path, subtitle_path: Path, *, overlap_tolerance: float = 0.5
) -> float | None:
    """重新对成片音轨跑一遍 ASR,和 subtitles.srt 的时间码窗口比对——每条字幕窗口只要
    跟任意一段 ASR 检测到的语音有重叠(容差内),就算对上。返回对上的比例(0..1)。

    ASR/字幕文件缺失或转写失败 → None(best-effort,不阻断体检,也不是测出对齐率=0)。
    """
    from hevi.assembly.subtitle_align import transcribe_to_cues

    if not subtitle_path.exists():
        return None
    windows = _parse_srt_windows(subtitle_path.read_text(encoding="utf-8", errors="ignore"))
    if not windows:
        return None
    try:
        asr_cues = transcribe_to_cues(video_path)
    except Exception:
        return None
    if not asr_cues:
        return None

    def _overlaps(a: tuple[float, float], b_start: float, b_end: float) -> bool:
        return a[0] - overlap_tolerance <= b_end and a[1] + overlap_tolerance >= b_start

    hits = sum(1 for w in windows if any(_overlaps(w, c.start, c.end) for c in asr_cues))
    return hits / len(windows)


async def quality_report(
    path: Path,
    *,
    expected_duration: float | None = None,
    expected_resolution: tuple[int, int] | None = None,
    duration_tol: float = 1.0,
    require_audio: bool = False,
    n_samples: int = 8,
    subtitle_path: Path | None = None,
    check_loudness: bool = True,
    min_loudness_lufs: float = -45.0,
    max_loudness_lufs: float = -5.0,
    min_subtitle_alignment_rate: float = 0.5,
) -> QualityReport:
    """成片体检: 规格断言 + 关键帧哈希 + 连续性打分 + 响度 + 字幕对齐率。

    在线程池跑(ffprobe/ffmpeg/faster-whisper 同步), 不阻塞事件循环。响度/字幕对齐
    都是 best-effort:量不出来(无音轨/无字幕文件/ASR 失败)→ 对应字段 None,不计入
    违规——区分"没测"和"测出来不合格"。响度阈值故意放得很宽(不是专业混音的 -23 LUFS
    目标),Tier0 的职责是拦"几乎无声/严重削波"这类 bug,不是做母带质量把关。
    """
    stats = await asyncio.to_thread(probe_stats, path)
    phashes = await asyncio.to_thread(sample_phashes, path, n_samples)
    cons = consistency_score(phashes)

    violations: list[str] = []
    if stats.duration <= 0:
        violations.append("成片时长为 0 / 无法探测")
    if expected_duration is not None and abs(stats.duration - expected_duration) > duration_tol:
        violations.append(
            f"时长 {stats.duration:.2f}s 偏离预期 {expected_duration:.2f}s (容差 {duration_tol}s)"
        )
    if expected_resolution is not None and (stats.width, stats.height) != expected_resolution:
        violations.append(f"分辨率 {stats.width}x{stats.height} != 预期 {expected_resolution}")
    if require_audio and not stats.has_audio:
        violations.append("缺音轨")

    loudness: float | None = None
    if check_loudness and stats.has_audio:
        loudness = await asyncio.to_thread(measure_loudness, path)
        if loudness is not None and not (min_loudness_lufs <= loudness <= max_loudness_lufs):
            violations.append(
                f"响度 {loudness:.1f} LUFS 超出合理范围 [{min_loudness_lufs}, {max_loudness_lufs}]"
            )

    alignment: float | None = None
    if subtitle_path is not None:
        alignment = await asyncio.to_thread(subtitle_alignment_rate, path, subtitle_path)
        if alignment is not None and alignment < min_subtitle_alignment_rate:
            violations.append(
                f"字幕对齐率 {alignment:.0%} < {min_subtitle_alignment_rate:.0%}(疑似装配阶段漂移)"
            )

    return QualityReport(
        stats=stats,
        phashes=phashes,
        consistency=cons,
        passed=not violations,
        violations=violations,
        loudness_lufs=loudness,
        subtitle_alignment_rate=alignment,
    )
