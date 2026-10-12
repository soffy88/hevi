"""Backlot REPLAY —— 把一次 run 的分镜 + 裁决回放成一条可播放的时间线。

审批门回答"这条镜头要不要", REPLAY 回答"这条片子**是怎么**长出来的": 哪个镜头
先来、当时花了多少、谁在什么时候批的、后来哪一格被否掉了改了什么。回放清单由
**实测时长**排布(ffprobe 探真实时长, 不拿配置里的名义值充数), 所以前端可以
真的按时间轴跳。

三层产物:
  1. ``build_replay``      纯函数: 板 + 事件流 → 回放清单(片段、时长、决策注解)
  2. ``render_replay_video``  真 ffmpeg 拼接: 把选中的镜头按顺序拼成一条 mp4
  3. 两者都把"没量到"显式写出来 —— 没有真实媒体就不给视频, 不给占位。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hevi.backlot.storyboard import (
    SHOT_APPROVED,
    SHOT_REJECTED,
    StoryboardBoard,
)

logger = logging.getLogger(__name__)

#: 裁决注解在回放时间线上的默认停留时长(秒)。
DECISION_CARD_S = 1.5


def _probe_duration(path: Path) -> float | None:
    try:
        from hevi.layer4_legacy.review.oprim_impl.media import MediaError, probe_media

        info = probe_media(path)
    except (MediaError, OSError) as exc:
        logger.warning("replay probe failed (%s): %s", path, exc)
        return None
    return round(float(info.duration_s), 3)


def build_replay(
    board: StoryboardBoard,
    *,
    events: list[dict[str, Any]] | None = None,
    include: str = SHOT_APPROVED,
    decision_card_s: float = DECISION_CARD_S,
) -> dict[str, Any]:
    """Build the replay timeline. Pure over the board + event list.

    Args:
        board: the storyboard board for the run.
        events: backlot events for the run (newest-last), used to annotate the
            timeline with what the pipeline was doing at each point.
        include: which shots make the cut — ``approved`` (default, what ships),
            ``rejected`` (what got thrown away), or ``all``.
        decision_card_s: hold time for a decision card between shots.

    ``duration_s`` on each segment is measured with ffprobe; a shot with no
    readable media lands in ``unmeasured`` instead of getting a made-up length.
    """
    wanted = {
        SHOT_APPROVED: lambda s: s.status == SHOT_APPROVED,
        SHOT_REJECTED: lambda s: s.status == SHOT_REJECTED,
        "all": lambda s: True,
    }.get(include)
    if wanted is None:
        raise ValueError(f"include must be approved|rejected|all, got {include!r}")

    segments: list[dict[str, Any]] = []
    unmeasured: list[dict[str, Any]] = []
    cursor = 0.0
    for shot in board.shots():
        if not wanted(shot):
            continue
        media = Path(shot.source_path) if shot.source_path else None
        duration = _probe_duration(media) if media and media.is_file() else None
        entry: dict[str, Any] = {
            "scene_id": shot.scene_id,
            "index": shot.index,
            "title": shot.title,
            "status": shot.status,
            "source_path": shot.source_path,
            "thumbnail": shot.thumbnail,
            "cost_usd": shot.cost_usd,
            "quality_score": (shot.quality or {}).get("score"),
            "decisions": [d.to_dict() for d in shot.decisions],
        }
        if duration is None or duration <= 0:
            unmeasured.append({"scene_id": shot.scene_id, "reason": "no readable media"})
            entry.update({"kind": "unmeasured", "at_s": round(cursor, 3), "duration_s": None})
            segments.append(entry)
            continue
        entry.update({"kind": "shot", "at_s": round(cursor, 3), "duration_s": duration})
        segments.append(entry)
        cursor += duration
        # 裁决注解: 被否的镜头在回放里留一张"停"卡, 说明为什么。
        last = shot.decisions[-1] if shot.decisions else None
        if last is not None:
            segments.append(
                {
                    "kind": "decision_card",
                    "scene_id": shot.scene_id,
                    "decision": last.decision,
                    "reason": last.reason,
                    "reviewer": last.reviewer,
                    "ts": last.ts,
                    "at_s": round(cursor, 3),
                    "duration_s": round(float(decision_card_s), 3),
                }
            )
            cursor += float(decision_card_s)

    return {
        "run_id": board.run_id,
        "include": include,
        "segments": segments,
        "total_s": round(cursor, 3),
        "segment_count": len(segments),
        "unmeasured": unmeasured,
        "summary": board.summary(),
        "events": list(events or []),
        "renderable": not unmeasured and any(s["kind"] == "shot" for s in segments),
    }


def render_replay_video(
    replay: dict[str, Any],
    output_path: str | Path,
    *,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Concatenate the measured shot segments into one real mp4 with ffmpeg.

    Returns ``{ok, path, duration_s, sha256, ...}``.  Refuses (ok=False) when the
    replay has unmeasured segments or no shots — an honest no beats a video with
    fabricated padding.
    """
    from hevi.layer4_legacy.enhance.oprim_impl.media import MediaError, run_ffmpeg
    from hevi.layer4_legacy.review.oprim_impl.media import probe_media

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not replay.get("renderable"):
        return {
            "ok": False,
            "path": None,
            "reason": (f"回放不可渲染: {len(replay.get('unmeasured') or [])} 个片段没量到真实媒体"),
            "unmeasured": replay.get("unmeasured") or [],
        }

    shots = [s for s in replay["segments"] if s.get("kind") == "shot" and s.get("source_path")]
    missing = [s for s in shots if not Path(str(s["source_path"])).is_file()]
    if missing:
        return {"ok": False, "path": None, "reason": f"源文件缺失: {missing[0]['source_path']}"}

    work = Path(work_dir) if work_dir else out.parent / f".{out.stem}_replay"
    work.mkdir(parents=True, exist_ok=True)
    concat_file = work / "concat.txt"

    def _concat_entry(shot: dict[str, Any]) -> str:
        # ffmpeg resolves concat entries relative to the list file, and the
        # single-quote/backslash escaping is its own little language.
        raw = str(Path(str(shot["source_path"])).resolve()).replace("\\", "/")
        return "file '" + raw.replace("'", "'\\''") + "'\n"

    concat_file.write_text("".join(_concat_entry(s) for s in shots), encoding="utf-8")

    cmd = [
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(out),
    ]
    try:
        run_ffmpeg(cmd)
        info = probe_media(out, with_sha256=True)
    except (MediaError, OSError) as exc:
        return {"ok": False, "path": None, "reason": f"ffmpeg 拼接失败: {exc}"}

    return {
        "ok": True,
        "path": str(out),
        "duration_s": info.duration_s,
        "resolution": f"{info.width}x{info.height}",
        "has_audio": info.has_audio,
        "size_bytes": info.size_bytes,
        "sha256": info.sha256,
        "shots": [s["scene_id"] for s in shots],
        "concat_file": str(concat_file),
    }


def save_replay(replay: dict[str, Any], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


__all__ = [
    "DECISION_CARD_S",
    "build_replay",
    "render_replay_video",
    "save_replay",
]
