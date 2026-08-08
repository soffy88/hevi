"""场景感知抽帧 —— 三档 detail + 去重 + 预算(3O 内化 Phase A)。

来源: bradautomates/claude-video 的三档抽帧设计(efficient/balanced/token-burner)
+ 帧预算 + 去重。基于 PyAV(自带 ffmpeg 库,不依赖系统 ffmpeg 二进制,与
hevi/verdict/frame_extract.py 同一策略)。

档位语义:
  transcript     —— 不抽帧(转写即可,见 video_transcript)
  efficient      —— 只取关键帧(keyframe),近实时(~0.5s 级)
  balanced       —— 场景切换候选 + 时长感知均匀采样,封顶 budget
  token-burner   —— 场景切换候选,不封顶(全部保留)

统一采样规则:候选在全范围检测,然后**均匀下采样到预算**(首帧+末帧必留)。
去重(16×16 均差)发生在预算封顶**之前**,预算花在真正不同的帧上。

3O 归属(待上游): `oprim.video_frames_extract`(场景感知+去重+预算)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class FramesError(Exception):
    """抽帧失败。"""


class WatchDetail(StrEnum):
    """抽帧档位(与来源 /watch --detail 对齐)。"""

    TRANSCRIPT = "transcript"
    EFFICIENT = "efficient"
    BALANCED = "balanced"
    TOKEN_BURNER = "token-burner"


@dataclass(frozen=True)
class ExtractedFrame:
    """一帧抽帧结果:时间戳(秒)+ 落盘路径。"""

    timestamp_s: float
    path: Path


#: 场景切换判定阈值:相邻帧 16×16 灰度均差超过该值视为切镜(近似 ffmpeg scene≈0.3)。
SCENE_THRESHOLD = 30.0
#: 默认输出宽度(JPEG 512px 宽,与来源一致;高按比例,上限 1998px 保证 Read 兼容)。
DEFAULT_WIDTH = 512
MAX_HEIGHT = 1998


def _gray16_thumb(frame_image: object) -> bytes:
    """把一帧转成 16×16 灰度字节(每字节一像素)。"""
    from PIL import Image

    img = frame_image
    if not isinstance(img, Image.Image):
        img = Image.fromarray(img)  # type: ignore[arg-type]
    return img.convert("L").resize((16, 16)).tobytes()


def _decode_frames(
    video_path: Path, *, scene_aware: bool
) -> tuple[list[float], list[object], list[bytes]]:
    """解码视频,返回 (时间戳列表, 帧图像列表, 16×16 灰度缩略图列表)。

    scene_aware=False → 只留关键帧(efficient 档)。
    scene_aware=True  → 相邻帧均差 > SCENE_THRESHOLD 视为切镜候选(balanced 档)。
    本函数不做预算/去重,只产出候选。
    """
    import av

    timestamps: list[float] = []
    images: list[object] = []
    thumbs: list[bytes] = []

    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate) if stream.average_rate else 30.0
        last_thumb: bytes | None = None
        frame_index = 0
        for frame in container.decode(video=0):
            if scene_aware is False and not getattr(frame, "key_frame", False):
                continue
            ts = (
                float(frame.pts * frame.time_base)
                if frame.pts is not None and frame.time_base is not None
                else frame_index / fps
            )
            thumb = _gray16_thumb(frame.to_image())  # type: ignore[no-untyped-call]
            if scene_aware:
                # 与上一个候选比较(非上一帧),与去重同思路,抓慢渐变
                if (
                    last_thumb is not None
                    and frame_delta_of(thumb, last_thumb) <= SCENE_THRESHOLD
                ):
                    continue
                last_thumb = thumb
            images.append(frame.to_image())  # type: ignore[no-untyped-call]
            thumbs.append(thumb)
            timestamps.append(ts)
            frame_index += 1
    return timestamps, images, thumbs


def frame_delta_of(a: bytes, b: bytes) -> float:
    """两缩略图均差(内部复用,避免循环导入)。"""
    from hevi.ingest.frame_dedup import frame_delta

    return frame_delta(a, b)


def _even_sample(
    indexes: list[int], budget: int, *, force_ends: bool = True
) -> list[int]:
    """在候选下标上均匀采样到 budget,首/末必留。"""
    n = len(indexes)
    if n <= budget:
        return indexes
    out: list[int] = []
    if force_ends:
        out.append(indexes[0])
        out.append(indexes[-1])
        if budget <= 2:
            return out
        step = (n - 1) / (budget - 1)
        picked = [indexes[min(n - 1, round(k * step))] for k in range(1, budget - 1)]
        out.extend(picked)
        # 去重 + 保序
        return sorted(set(out))
    step = n / budget
    return [indexes[min(n - 1, int(k * step))] for k in range(budget)]


def _save_jpeg(image: object, out_path: Path, *, width: int) -> None:
    """按宽度等比缩放(高封顶 MAX_HEIGHT)存 JPEG。"""
    from PIL import Image

    img = image if isinstance(image, Image.Image) else Image.fromarray(image)  # type: ignore[arg-type]
    w, h = img.size
    if w > width:
        ratio = width / w
        h = max(1, int(h * ratio))
        w = width
    if h > MAX_HEIGHT:
        ratio = MAX_HEIGHT / h
        w = max(1, int(w * ratio))
        h = MAX_HEIGHT
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    img.convert("RGB").save(out_path, "JPEG", quality=88)


def extract_watch_frames(
    video_path: str | Path,
    out_dir: Path,
    *,
    detail: WatchDetail | str = WatchDetail.BALANCED,
    budget: int | None = None,
    resolution_width: int = DEFAULT_WIDTH,
    start_s: float | None = None,
    end_s: float | None = None,
    dedup: bool = True,
    dedup_threshold: float = 2.0,
) -> list[ExtractedFrame]:
    """抽帧主入口:候选检测 → 去重 → 预算 → 落盘。

    Args:
        video_path: 本地视频路径(图片输入原样返回单帧)。
        out_dir: 输出目录(不存在则创建)。
        detail: 档位(transcript 档返回空列表 —— 转写即可)。
        budget: 帧预算;None 时按时长自动定(聚焦窗口另算)。
        resolution_width: 输出宽度像素(默认 512)。
        start_s / end_s: 聚焦窗口(秒);给定后预算按窗口密度取。
        dedup: 是否先做 16×16 均差去重(预算之前)。
        dedup_threshold: 去重阈值(默认 2.0)。

    Returns:
        按时间升序的 (timestamp_s, path) 列表。
    """
    from hevi.ingest.frame_budget import focused_budget, frame_budget_for_duration
    from hevi.ingest.frame_dedup import dedupe_frames

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = Path(video_path)
    if not src.exists():
        raise FramesError(f"video not found: {src}")

    detail_enum = WatchDetail(detail)
    if detail_enum == WatchDetail.TRANSCRIPT:
        return []

    # 图片输入 → 单帧直通
    if src.suffix.lower() in _IMAGE_SUFFIXES:
        return [ExtractedFrame(timestamp_s=0.0, path=src)]

    try:
        timestamps, images, thumbs = _decode_frames(
            src, scene_aware=detail_enum in (WatchDetail.BALANCED, WatchDetail.TOKEN_BURNER)
        )
    except Exception as e:
        raise FramesError(f"decode failed for {src}: {e}") from e

    if not images:
        raise FramesError(f"no frames decoded: {src}")

    if start_s is not None or end_s is not None:
        budget = budget or focused_budget(start_s, end_s)
    else:
        duration_s = timestamps[-1] - timestamps[0] if timestamps else 0.0
        budget = budget or frame_budget_for_duration(duration_s)

    # 1) 去重(预算之前)—— 预算花在真正不同的帧上
    keep_indexes = list(range(len(images)))
    if dedup:
        survivors, _dropped = dedupe_frames(thumbs, threshold=dedup_threshold)
        keep_indexes = survivors

    # 2) 预算均匀采样(首末必留;token-burner 不封顶)
    if detail_enum != WatchDetail.TOKEN_BURNER:
        keep_indexes = _even_sample(keep_indexes, budget)

    # 3) 落盘
    frames: list[ExtractedFrame] = []
    for i in keep_indexes:
        out_path = out_dir / f"frame_{i:05d}_t{timestamps[i]:07.2f}s.jpg"
        try:
            _save_jpeg(images[i], out_path, width=resolution_width)
        except Exception as e:
            raise FramesError(f"save failed for frame {i}: {e}") from e
        frames.append(ExtractedFrame(timestamp_s=timestamps[i], path=out_path))
    frames.sort(key=lambda f: f.timestamp_s)
    return frames
