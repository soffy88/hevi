"""watch —— 摄入侧编排技能:fetch → frames → transcript → 结构结果(3O 内化 Phase A)。

来源: bradautomates/claude-video(`/watch`)的编排:一个字幕优先、按需下载、
场景感知抽帧、去重去预算、时间戳转写,最后把"帧路径 + 转写"交给 LLM 回答。

这里是 3O 内化的 `oskill.video_watch` 的 hevi 暂驻实现:返回结构化 WatchResult,
由调用方(agent / verdict QA / StylePack 拆解)消费。消费策略留 hevi(护城河)。

3O 归属(待上游): `oskill.video_watch`。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from hevi.ingest.video_frames import ExtractedFrame, WatchDetail, extract_watch_frames
from hevi.ingest.video_transcript import TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass
class WatchResult:
    """一次 watch 的完整结果:帧 + 转写 + 元信息,可直接喂 LLM。"""

    source: str
    frames: list[ExtractedFrame] = field(default_factory=list)
    transcript: list[TranscriptSegment] = field(default_factory=list)
    duration_s: float = 0.0
    detail: WatchDetail = WatchDetail.BALANCED
    notes: list[str] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def transcript_text(self) -> str:
        """时间戳文本拼接(供 LLM 上下文/检索)。"""
        return "\n".join(
            f"[{s.start:07.2f}-{s.end:07.2f}] {s.text}" for s in self.transcript
        )


def watch_video(
    source: str | Path,
    work_dir: Path,
    *,
    detail: WatchDetail | str = WatchDetail.BALANCED,
    budget: int | None = None,
    resolution_width: int = 512,
    whisper_fallback: bool = False,
    language: str | None = None,
    start_s: float | None = None,
    end_s: float | None = None,
) -> WatchResult:
    """看一条视频:URL/本地路径 → 帧 + 时间戳转写。

    Args:
        source: URL 或本地路径。
        work_dir: 下载/抽帧/字幕落地目录。
        detail: 抽帧档位(transcript 档只取转写,零下载帧成本)。
        budget: 帧预算;None 按时长自动定。
        resolution_width: 帧输出宽度(默认 512)。
        whisper_fallback: 无字幕时是否走 faster-whisper 兜底。
        language: 兜底转写语言。
        start_s / end_s: 聚焦窗口。

    Returns:
        WatchResult:frames 按时间升序;transcript 可能为空
        (无字幕且未启用/未成功兜底时,notes 会注明)。
    """
    from hevi.ingest.video_fetch import fetch_video
    from hevi.ingest.video_frames import FramesError
    from hevi.ingest.video_transcript import TranscriptError, fetch_transcript

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    detail_enum = WatchDetail(detail)

    # 1) fetch(本地路径直通;URL 下载;transcript 档若 URL 可跳过下载)
    video: Path
    try:
        video = fetch_video(source, work_dir)
    except Exception:
        # transcript 档的 URL 不下载也能拉字幕;下载失败不阻断转写尝试
        if detail_enum == WatchDetail.TRANSCRIPT and str(source).startswith(("http://", "https://")):
            video = Path(str(source))
        else:
            raise

    # 2) 转写
    transcript: list[TranscriptSegment] = []
    notes: list[str] = []
    try:
        transcript = fetch_transcript(
            source,
            whisper_fallback=whisper_fallback,
            language=language,
            work_dir=work_dir,
        )
    except TranscriptError as e:
        notes.append(f"transcript unavailable: {e}")
        logger.warning("watch: %s", e)

    # 3) 抽帧(transcript 档跳过)
    frames: list[ExtractedFrame] = []
    duration_s = 0.0
    if detail_enum != WatchDetail.TRANSCRIPT and not str(source).startswith(("http://", "https://")):
        try:
            frames = extract_watch_frames(
                video,
                work_dir / "frames",
                detail=detail_enum,
                budget=budget,
                resolution_width=resolution_width,
                start_s=start_s,
                end_s=end_s,
            )
        except FramesError as e:
            notes.append(f"frames unavailable: {e}")
            logger.warning("watch: %s", e)
        if frames:
            duration_s = frames[-1].timestamp_s - frames[0].timestamp_s

    return WatchResult(
        source=str(source),
        frames=frames,
        transcript=transcript,
        duration_s=duration_s,
        detail=detail_enum,
        notes=notes,
    )
