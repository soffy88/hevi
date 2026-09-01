"""Deterministic conversational editing for a Hevi timeline.

This is the FireRed-style interaction boundary: natural language is converted
to a small, inspectable edit command, applied to the canonical timeline, and
optionally sent through the existing FFmpeg exporter.  It deliberately keeps
the mutation surface narrow so a preview is safe and auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.studio.timeline import Timeline, TimelineClip, export_timeline, get_timeline, ripple

_ORDINAL = r"(?:第\s*(?P<index>[0-9一二三四五六七八九十百]+)\s*(?:个)?\s*(?:镜头|镜|片段)|(?P<index2>[0-9]+)\s*(?:号)?\s*(?:镜头|镜|片段))"
_CHINESE_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}


@dataclass(frozen=True)
class EditCommand:
    operation: str
    clip_index: int | None = None
    value: Any = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "clip_index": self.clip_index,
            "value": self.value,
            "description": self.description,
        }


def _ordinal(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[value]
    if value.startswith("十"):
        return 10 + (_CHINESE_DIGITS.get(value[1:], 0) if len(value) > 1 else 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return _CHINESE_DIGITS.get(left, 1) * 10 + _CHINESE_DIGITS.get(right, 0)
    if "百" in value:
        left, right = value.split("百", 1)
        return _CHINESE_DIGITS.get(left, 1) * 100 + _CHINESE_DIGITS.get(right, 0)
    raise ValueError(f"无法识别镜头序号: {value}")


def _clip_index(text: str) -> int | None:
    match = re.search(_ORDINAL, text)
    if not match:
        return None
    return _ordinal(match.group("index") or match.group("index2"))


def parse_edit_command(text: str) -> EditCommand:
    """Parse common Chinese edit requests into an explicit command."""

    message = " ".join(text.strip().split())
    if not message:
        raise ValueError("编辑指令不能为空")
    index = _clip_index(message)
    if re.search(r"(?:背景音乐|BGM|bgm).*(?:换成|改成|设置为|设为)", message, re.I):
        value = re.split(r"(?:换成|改成|设置为|设为)", message, maxsplit=1)[-1].strip(" ：:。")
        if not value:
            raise ValueError("请提供新的背景音乐路径或 URL")
        return EditCommand("set_bgm", value=value, description=f"背景音乐改为 {value}")
    if index is None:
        raise ValueError("请明确要操作第几个镜头，例如“删除第2镜”或“把第1镜字幕改成……”")
    if re.search(r"恢复|保留|撤销删除|取消删除", message):
        return EditCommand("keep", clip_index=index, description=f"恢复第 {index} 个镜头")
    if re.search(r"删除|删掉|去掉|移除|不要", message):
        return EditCommand("drop", clip_index=index, description=f"删除第 {index} 个镜头")
    duration = re.search(r"(?:时长|长度).{0,8}?([0-9]+(?:\.[0-9]+)?)\s*(?:秒|s)?", message, re.I)
    if duration:
        seconds = float(duration.group(1))
        if seconds <= 0:
            raise ValueError("镜头时长必须大于 0")
        return EditCommand("duration", clip_index=index, value=seconds, description=f"第 {index} 个镜头改为 {seconds:g} 秒")
    caption = re.search(r"(?:字幕|台词|文案).{0,12}?(?:改成|替换为|换成|设置为)\s*[‘'\"“]?(.+?)[’'\"”]?$", message)
    if caption:
        value = caption.group(1).strip(" 。")
        if value:
            return EditCommand("caption", clip_index=index, value=value, description=f"第 {index} 个镜头字幕改为“{value}”")
    if re.search(r"移到.*(?:最后|片尾|结尾)", message):
        return EditCommand("move_end", clip_index=index, description=f"第 {index} 个镜头移到最后")
    if re.search(r"移到.*(?:最前|开头|片头)", message):
        return EditCommand("move_start", clip_index=index, description=f"第 {index} 个镜头移到开头")
    raise ValueError("我识别到了镜头，但没有识别出动作；支持删除、恢复、改时长、改字幕、重排和换 BGM")


def _video_clips(timeline: Timeline) -> list[TimelineClip]:
    return sorted((c for c in timeline.clips if c.track == "video"), key=lambda c: c.start_s)


def _related_clips(timeline: Timeline, index: int) -> list[TimelineClip]:
    videos = _video_clips(timeline)
    if index < 1 or index > len(videos):
        raise ValueError(f"时间线只有 {len(videos)} 个视频镜头，找不到第 {index} 个")
    video = videos[index - 1]
    related = [video]
    # timeline_from_edit_plan uses vN/aN/cN; split clips have a generated suffix.
    stem = video.clip_id[1:].split("s", 1)[0]
    related.extend(
        clip
        for clip in timeline.clips
        if clip is not video and clip.clip_id[1:].split("s", 1)[0] == stem and clip.track in {"audio", "captions"}
    )
    # Imported timelines may not use matching IDs; time overlap is a safe fallback.
    if len(related) == 1:
        related.extend(
            clip
            for clip in timeline.clips
            if clip.track in {"audio", "captions"}
            and abs(clip.start_s - video.start_s) < 0.01
            and abs(clip.duration_s - video.duration_s) < 0.01
        )
    return related


def _move(timeline: Timeline, index: int, *, to_end: bool) -> None:
    videos = _video_clips(timeline)
    if index < 1 or index > len(videos):
        raise ValueError(f"时间线只有 {len(videos)} 个视频镜头，找不到第 {index} 个")
    chosen = videos[index - 1]
    groups = [_related_clips(timeline, position) for position in range(1, len(videos) + 1)]
    ordered = [group for group in groups if chosen not in group]
    chosen_group = next(group for group in groups if chosen in group)
    if to_end:
        ordered.append(chosen_group)
    else:
        ordered.insert(0, chosen_group)
    cursor = 0.0
    for group in ordered:
        duration = max((clip.duration_s for clip in group), default=0.0)
        for clip in group:
            clip.start_s = round(cursor, 3)
        cursor += duration


def apply_edit_command(timeline: Timeline, command: EditCommand) -> Timeline:
    if command.operation == "set_bgm":
        timeline.bgm = str(command.value)
        return timeline
    if command.clip_index is None:
        raise ValueError("该编辑动作缺少镜头序号")
    clips = _related_clips(timeline, command.clip_index)
    if command.operation in {"drop", "keep"}:
        for clip in clips:
            clip.action = "drop" if command.operation == "drop" else "keep"
    elif command.operation == "duration":
        for clip in clips:
            clip.duration_s = max(0.4, float(command.value))
    elif command.operation == "caption":
        caption_clips = [clip for clip in clips if clip.track == "captions"]
        if not caption_clips:
            raise ValueError("该镜头没有字幕轨")
        for clip in caption_clips:
            clip.text = str(command.value)
            clip.label = str(command.value)[:18]
    elif command.operation == "move_end":
        _move(timeline, command.clip_index, to_end=True)
    elif command.operation == "move_start":
        _move(timeline, command.clip_index, to_end=False)
    else:
        raise ValueError(f"不支持的编辑动作: {command.operation}")
    return timeline


def execute_edit(
    timeline_id: str,
    text: str,
    *,
    preview: bool = False,
    render: bool = False,
    output_path: str | None = None,
) -> dict[str, Any]:
    timeline = get_timeline(timeline_id)
    if timeline is None:
        raise KeyError(f"unknown timeline: {timeline_id}")
    command = parse_edit_command(text)
    before = timeline.to_dict()
    if not preview:
        apply_edit_command(timeline, command)
        if command.operation == "drop":
            ripple(timeline_id)
    after = timeline.to_dict()
    result: dict[str, Any] = {
        "status": "preview" if preview else "applied",
        "intent": command.operation,
        "command": command.to_dict(),
        "before": before,
        "timeline": after,
        "rerendered": False,
    }
    if render and not preview:
        destination = output_path or f"output/nle/{timeline_id}.mp4"
        result["render"] = export_timeline(timeline_id, Path(destination))
        result["rerendered"] = result["render"].get("status") == "ok"
    return result


__all__ = ["EditCommand", "apply_edit_command", "execute_edit", "parse_edit_command"]
