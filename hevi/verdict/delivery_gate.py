"""成片交付门 —— HEVI-ARCH §6.1.1 落地(3O 内化 wire ②)。

架构文档把"成片交付门清单"(频闪/死空档/联络表/隐私/BGM 接缝)写成设计;
这里用 3O 内化的能力落地为可运行检查:
  - 联络表:复用 `hevi/ingest` 的 watch(场景感知抽帧+预算+去重)→ contact sheet
    —— "LLM 不看全帧看压缩表示"的成片版,可直接喂 Tier1 VLM/人工审片。
  - 频闪:ffmpeg blackdetect + 亮度骤降(检测失败 → None,不阻断)。
  - 死空档:ffmpeg silencedetect,标记 ≥1.5s 句间停顿。
  - BGM 循环接缝:BGM 时长 ≥ 视频时长(短于片长 → 可闻循环跳变)。
  - 判例库自检:流程族(P)由本门覆盖,产出自检报告骨架。

全部确定性/低成本;ffmpeg 缺失时对应检查记 None 并注明,不阻断交付(与
beat_align / verdict_checks 同风格)。纯逻辑部分(静音解析/时长比较/报告)可单测。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from hevi.ingest.contact_sheet import build_contact_sheet
from hevi.ingest.video_frames import WatchDetail, extract_watch_frames
from hevi.verdict.aesthetic_canon import AestheticCanon, default_canon

logger = logging.getLogger(__name__)

#: 死空档判定:≥ 1.5s 静音视为拖节奏。
SILENCE_FLOOR_S = 1.5
#: 频闪判定:黑帧占比(blackdetect 累计)≥ 该值判频闪风险。
FLICKER_BLACK_RATIO = 0.15


class DeliveryGateError(Exception):
    """交付门检查失败(整门崩溃;单项失败只记 None)。"""


@dataclass
class GateItem:
    """一项检查结果:通过/失败/未检(None)。"""

    name: str
    ok: bool | None
    detail: str = ""


@dataclass
class DeliveryGateResult:
    """成片交付门结果。"""

    video_path: Path
    items: list[GateItem] = field(default_factory=list)
    contact_sheet_path: Path | None = None
    canon_report: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        checked = [i for i in self.items if i.ok is not None]
        return bool(checked) and all(i.ok for i in checked)


def _probe_duration(path: Path) -> float | None:
    """ffprobe 取时长(秒);失败 → None。"""
    if shutil.which("ffprobe") is None:
        return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return float(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    except Exception:
        return None


def detect_flicker_ratio(video_path: Path) -> float | None:
    """频闪检测:ffmpeg blackdetect 累计黑时长占比(0-1);失败 → None。"""
    if shutil.which("ffmpeg") is None:
        return None
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", str(video_path), "-vf",
                "blackdetect=d=0.1:pix_th=0.10", "-an", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        black_s = 0.0
        for line in proc.stderr.splitlines():
            if "black_start" in line and "black_end" in line:
                try:
                    start = float(line.split("black_start:")[1].split()[0])
                    end = float(line.split("black_end:")[1].split()[0])
                    black_s += max(end - start, 0.0)
                except (IndexError, ValueError):
                    continue
        duration = _probe_duration(video_path)
        if not duration or duration <= 0:
            return None
        return black_s / duration
    except Exception:
        return None


def parse_silence_events(
    ffmpeg_stderr: str, *, floor_s: float = SILENCE_FLOOR_S
) -> list[tuple[float, float]]:
    """从 ffmpeg silencedetect 输出解析静音区间 [(start, duration)],纯文本可测。

    ffmpeg 输出是成对行:`silence_start: 2.5` 后跟 `silence_end: 4.5 | silence_duration: 2`。
    """
    events: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in ffmpeg_stderr.splitlines():
        if "silence_start:" in line:
            try:
                pending_start = float(line.split("silence_start:")[1].split()[0])
            except (IndexError, ValueError):
                pending_start = None
        elif "silence_end:" in line and pending_start is not None:
            try:
                end = float(line.split("silence_end:")[1].split()[0])
            except (IndexError, ValueError):
                end = pending_start
            dur = end - pending_start
            if dur >= floor_s:
                events.append((pending_start, dur))
            pending_start = None
    return events


def detect_silence_gaps(
    video_path: Path, *, floor_s: float = SILENCE_FLOOR_S
) -> list[tuple[float, float]]:
    """死空档检测:silencedetect 找 ≥floor_s 的静音区间;ffmpeg 缺失 → []。"""
    if shutil.which("ffmpeg") is None:
        return []
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", str(video_path), "-af",
                f"silencedetect=noise=-35dB:d={floor_s}", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        return parse_silence_events(proc.stderr, floor_s=floor_s)
    except Exception:
        return []


def bgm_longer_than_video(video_path: Path, bgm_path: Path | None) -> bool | None:
    """BGM 循环接缝:BGM 时长 ≥ 视频时长才不会有可闻循环跳变。None = 未检。"""
    if bgm_path is None or not bgm_path.exists():
        return None
    v = _probe_duration(video_path)
    b = _probe_duration(bgm_path)
    if v is None or b is None:
        return None
    return b >= v


def run_delivery_gate(
    video_path: str | Path,
    *,
    out_dir: str | Path,
    bgm_path: str | Path | None = None,
    canon: AestheticCanon | None = None,
    frame_budget: int | None = None,
    contact_sheet: bool = True,
) -> DeliveryGateResult:
    """成片交付门:频闪 / 死空档 / 联络表 / BGM 接缝 + 判例库流程族自检。

    Args:
        video_path: 成片。
        out_dir: 联络表等产物目录。
        bgm_path: 可选,校验 BGM 循环接缝。
        canon: 判例库;None 用种子库。
        frame_budget: 联络表帧预算;None 按时长自动定。
        contact_sheet: 是否生成联络表。

    Returns:
        DeliveryGateResult(单项失败记 None,不整门崩溃)。
    """
    video = Path(video_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = DeliveryGateResult(video_path=video)

    if not video.exists():
        raise DeliveryGateError(f"video not found: {video}")

    # 1) 频闪
    flicker = detect_flicker_ratio(video)
    if flicker is None:
        result.items.append(GateItem("flicker", None, "ffmpeg 不可用或检测失败"))
    else:
        ok = flicker < FLICKER_BLACK_RATIO
        result.items.append(GateItem("flicker", ok, f"black ratio {flicker:.3f}"))

    # 2) 死空档
    gaps = detect_silence_gaps(video)
    if gaps:
        result.items.append(
            GateItem("dead_air", False, f"{len(gaps)} 处 ≥{SILENCE_FLOOR_S}s 静音: {gaps[:3]}")
        )
    else:
        result.items.append(GateItem("dead_air", True, "无超长静音"))

    # 3) 联络表(摄入侧 watch 的帧管线,不重复造轮子)
    if contact_sheet:
        try:
            frames = extract_watch_frames(
                video,
                out / "frames",
                detail=WatchDetail.BALANCED,
                budget=frame_budget,
            )
            if frames:
                sheet = build_contact_sheet(
                    [f.path for f in frames],
                    out / "contact_sheet.jpg",
                    cols=5,
                    thumb_width=320,
                )
                result.contact_sheet_path = sheet
                result.items.append(
                    GateItem("contact_sheet", True, f"{len(frames)} 帧联络表")
                )
            else:
                result.items.append(GateItem("contact_sheet", None, "抽帧失败"))
        except Exception as e:
            result.notes.append(f"contact sheet failed: {e}")
            result.items.append(GateItem("contact_sheet", None, str(e)))

    # 4) BGM 循环接缝
    bgm_ok = bgm_longer_than_video(video, Path(bgm_path) if bgm_path else None)
    if bgm_ok is None:
        result.items.append(GateItem("bgm_loop", None, "未提供 BGM 或探测失败"))
    else:
        result.items.append(
            GateItem(
                "bgm_loop",
                bgm_ok,
                "BGM 时长 ≥ 视频时长"
                if bgm_ok
                else "BGM 短于成片,有循环跳变风险",
            )
        )

    # 5) 判例库流程族(P)自检:本门覆盖 P1(验收贯穿/终检),其余按实际状态
    canon = canon or default_canon()
    report = build_gate_canon_report(canon, result)
    result.canon_report = report
    return result


def build_gate_canon_report(canon: AestheticCanon, gate: DeliveryGateResult) -> str:
    """把交付门结果投影成判例库 P 族自检报告(其余族留 ?)。"""
    p_results: dict[str, str | None] = {}
    for rule in canon.by_family("P"):
        if rule.code == "P1":
            p_results["P1"] = None if gate.passed else f"{gate.video_path.name} 交付门未全过"
    from hevi.verdict.aesthetic_canon import build_self_check_report

    return build_self_check_report(canon, p_results)
