"""hevi 摄入侧(ingest)—— "看懂视频"能力域,3O 内化 Phase A。

来源: bradautomates/claude-video(`/watch`)—— Hevi 此前完全缺失输入侧:
  fetch(yt-dlp)→ 场景感知抽帧(预算/去重/联络表)→ 转写(字幕/Whisper 兜底)。

3O 归属(待上游):
  - `oprim.video_fetch` / `oprim.video_frames_extract`(场景感知+去重+预算)
  - `oprim.video_transcript`(字幕→Whisper 兜底)/ `oprim.build_contact_sheet`
  - `oskill.video_watch`(编排: fetch→frames→transcript→结构结果)

Hevi 侧 wire: 成片 QA(verdict 联络表)、StylePack 参考视频拆解(HEVI-ARCH §5.3.7)、
竞品/素材研究。裁决与消费策略留 hevi(护城河)。
"""

from hevi.ingest.contact_sheet import ContactSheetError, build_contact_sheet
from hevi.ingest.frame_budget import FRAME_BUDGET_TABLE, frame_budget_for_duration
from hevi.ingest.frame_dedup import dedupe_frames, frame_delta
from hevi.ingest.preflight import PreflightReport, check_env
from hevi.ingest.video_fetch import FetchError, fetch_video
from hevi.ingest.video_frames import (
    FramesError,
    WatchDetail,
    extract_watch_frames,
)
from hevi.ingest.video_localize import LocalizePlan, plan_localize
from hevi.ingest.video_transcript import (
    TranscriptError,
    TranscriptSegment,
    WordSpan,
    fetch_transcript,
)
from hevi.ingest.video_watch import WatchResult, watch_video

__all__ = [
    "FRAME_BUDGET_TABLE",
    "ContactSheetError",
    "FetchError",
    "FramesError",
    "PreflightReport",
    "TranscriptError",
    "TranscriptSegment",
    "WordSpan",
    "LocalizePlan",
    "WatchDetail",
    "WatchResult",
    "build_contact_sheet",
    "check_env",
    "dedupe_frames",
    "extract_watch_frames",
    "fetch_transcript",
    "fetch_video",
    "plan_localize",
    "frame_budget_for_duration",
    "frame_delta",
    "watch_video",
]
