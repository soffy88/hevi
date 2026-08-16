"""环境预检 —— 零配置首跑状态机(3O 内化 Round 3c,来源 claude-video setup.py)。

claude-video 的 setup.py 模式:首跑做结构化预检(silent 成功 / exit code 区分
缺二进制 / 缺 key),`can_proceed` 是操作门 —— 只要二进制齐就能跑,key 可选。
hevi/ingest 此前只有"用到时优雅降级",没有显式预检层。

本模块为 hevi 暂驻(待上游 `obase.env_preflight`):确定性检查 ffmpeg/ffprobe/
yt-dlp/faster-whisper,产出 PreflightReport(可 JSON 序列化,供 agent 分支)。
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PreflightReport:
    """环境预检结果。"""

    can_proceed: bool
    missing_binaries: list[str] = field(default_factory=list)
    whisper_available: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "can_proceed": self.can_proceed,
            "missing_binaries": self.missing_binaries,
            "whisper_available": self.whisper_available,
            "notes": self.notes,
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


#: 必需二进制:本地文件路径直通只需要 av/PIL(都在依赖里);URL/字幕需要这些。
REQUIRED_BINARIES: tuple[str, ...] = ("ffmpeg", "ffprobe", "yt-dlp")


def check_env(
    *,
    require_url_tools: bool = False,
    check_whisper: bool = True,
) -> PreflightReport:
    """确定性环境检查。

    Args:
        require_url_tools: True 时 yt-dlp 缺失判为不可 proceed(URL 摄入);False 时
            yt-dlp 仅进 missing 列表不阻断(本地文件摄入仍可跑,与 /watch keyless 同哲学)。
        check_whisper: 是否探测 faster-whisper 兜底能力。

    Returns:
        PreflightReport(can_proceed 为操作门)。
    """
    missing: list[str] = [
        binary for binary in REQUIRED_BINARIES if shutil.which(binary) is None
    ]

    whisper_ok = False
    if check_whisper:
        try:
            import faster_whisper  # type: ignore[import-untyped] # noqa: F401

            whisper_ok = True
        except ImportError:
            whisper_ok = False

    notes: list[str] = []
    if "yt-dlp" in missing:
        notes.append("yt-dlp 缺失:URL 摄入/字幕拉取不可用;本地文件路径不受影响")
    if "ffmpeg" in missing or "ffprobe" in missing:
        notes.append("ffmpeg/ffprobe 缺失:联络表/频闪/静音检测不可用;PyAV 抽帧不受影响")
    if not whisper_ok:
        notes.append("faster-whisper 缺失:无字幕时兜底转写不可用")

    blocking = missing if require_url_tools else [b for b in missing if b != "yt-dlp"]
    return PreflightReport(
        can_proceed=not blocking,
        missing_binaries=missing,
        whisper_available=whisper_ok,
        notes=notes,
    )
