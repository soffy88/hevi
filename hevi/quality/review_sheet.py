"""Cross-line review sheet: structured review comments + frame grabs.

``qa.review_sheet`` 的核心实现（跨产品线通用，不属于任何一条线）：
把一组成片时间码上的审片评论规范化成结构化记录，在每条评论的
``timestamp_s`` 处抓一帧，最后组装成机器可读的 ``review_sheet.json``
与人可读的 ``review.md`` 审片单。

与既有近邻的分工（互补，不替代）：

* ``hevi.kids.annotation_revision`` —— kids 线专用：把画布上的图形标注
  （pin/arrow/rect…）确定性地翻成 ``ShotSpecPatch`` 去改 ShotSpec；
  它处理的是"在画面上画了什么"，不是自由文本评论，也不组装审片单。
* ``hevi.kids.review_sheet`` —— kids 线专用：按 manifest/ShotSpec 渲染
  一集一张的分镜网格 PNG，用于分镜展示；它没有评论、状态与 thread
  的概念，输入也不是成片文件。
* 本模块 —— 任意一条线在成片（或任意阶段的视频文件）上留下的
  自由文本审片评论的"记录 + 抓帧 + 成单"：评论有生命周期状态、
  有可追溯的 thread，审片单按评论时间点配帧图。

记录格式（一条评论）::

    {id, film, shot, timestamp_s, scene, element, comment, status}

``status`` ∈ ``pending | working | done | reopened | cancelled``，
缺省 ``pending``。``id`` 缺省时由
``sha256(f"{film}|{shot}|{timestamp_s}|{comment}")`` 的前 12 位
确定性生成：同一输入永远得到同一个 id，不含随机与时钟。

输入有两种形态：

(a) 评论列表 ``list[dict]`` —— 每条就是上面的记录格式，直接规范化；
(b) 事件日志 ``list[dict]`` —— 每条带 ``type`` ∈
    ``comment | claim | done | reopen | cancel``，按追加顺序折叠
    （fold）出每条评论的当前状态与其 ``thread``：

    - ``comment`` 新建一条评论（初始 ``pending``）；
    - ``claim``   → ``working``（认领）；
    - ``done``    → ``done``（处理完成）；
    - ``reopen``  → ``pending``（打回待办池；打回这一事实留在
      thread 里，不会丢，所以状态机里另外保留 ``reopened`` 供
      评论列表形态直接标注"曾被打回"的记录）；
    - ``cancel``  → ``cancelled``（作废）。

    每个事件的 ``note``（如 agent 的处理说明）按顺序追加进对应
    评论的 ``thread``，因此一条评论的完整来龙去脉可追溯。

    设计参考（仅借鉴思路、未复制代码）：huashu-motion 的 inbox
    事件折叠做法——外部输入先以只追加的事件流落盘，当前状态永远
    由事件按序重放折叠得出，而不是直接改写状态字段；本模块用
    自己的实现把同一思路落在审片评论上。出处：
    https://github.com/alchaincyf/huashu-art-motion

拒绝口径（与 ``hevi.kids.annotation_revision`` 一致，明确拒绝、
不静默）：非法 ``status``、缺 ``comment`` 文本、``timestamp_s < 0``
→ :class:`ReviewSheetError`；任一评论的 ``timestamp_s`` 超出成片
时长 → 报错并点名该评论 id、整单拒绝（一帧都不抓、一份文件都不写），
绝不静默钳制到片尾或跳过该条。
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from collections import Counter
from contextlib import suppress
from pathlib import Path
from typing import Any

__all__ = [
    "EVENT_TYPES",
    "VALID_STATUSES",
    "ReviewSheetError",
    "build_review_sheet",
    "fold_events",
    "format_timecode",
    "make_comment_id",
    "normalize_comments",
    "normalize_records",
]

VALID_STATUSES = ("pending", "working", "done", "reopened", "cancelled")
EVENT_TYPES = ("comment", "claim", "done", "reopen", "cancel")

# Non-comment event type -> status it folds the comment into.
_EVENT_STATUS = {
    "claim": "working",
    "done": "done",
    "reopen": "pending",
    "cancel": "cancelled",
}


class ReviewSheetError(Exception):
    """审片评论非法或审片单组装失败（能力层转 CapabilityError）。"""


# ---------------------------------------------------------------------------
# Deterministic id + timecode
# ---------------------------------------------------------------------------


def make_comment_id(
    film: Any, shot: Any, timestamp_s: Any, comment: str
) -> str:
    """Deterministic 12-hex id from ``film|shot|timestamp_s|comment``."""
    raw = f"{film or ''}|{shot if shot is not None else ''}|{float(timestamp_s)}|{comment}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def format_timecode(timestamp_s: float) -> str:
    """``HH:MM:SS.mmm`` timecode for a position in seconds."""
    total_ms = round(float(timestamp_s) * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_comment_fields(raw: dict[str, Any], where: str) -> dict[str, Any]:
    """Validate the fields a *new* comment must carry; return clean values."""
    comment = raw.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        raise ReviewSheetError(f"{where}: missing comment text")
    comment = comment.strip()

    if "timestamp_s" not in raw or raw.get("timestamp_s") is None:
        raise ReviewSheetError(f"{where}: missing timestamp_s")
    ts_raw = raw.get("timestamp_s")
    if isinstance(ts_raw, bool) or not isinstance(ts_raw, (int, float)):
        raise ReviewSheetError(f"{where}: timestamp_s must be a number, got {ts_raw!r}")
    timestamp_s = float(ts_raw)
    if not math.isfinite(timestamp_s):
        raise ReviewSheetError(f"{where}: timestamp_s must be finite, got {ts_raw!r}")
    if timestamp_s < 0:
        raise ReviewSheetError(f"{where}: timestamp_s < 0: {timestamp_s}")

    status = raw.get("status") or "pending"
    if status not in VALID_STATUSES:
        raise ReviewSheetError(
            f"{where}: invalid status {status!r}, expected one of {VALID_STATUSES}"
        )

    film = _clean_str(raw.get("film"))
    shot = raw.get("shot")
    if isinstance(shot, str):
        shot = _clean_str(shot)
    return {
        "film": film,
        "shot": shot,
        "timestamp_s": timestamp_s,
        "scene": _clean_str(raw.get("scene")),
        "element": _clean_str(raw.get("element")),
        "comment": comment,
        "status": status,
    }


def _record_from_validated(
    raw: dict[str, Any], fields: dict[str, Any], where: str
) -> dict[str, Any]:
    cid = _clean_str(raw.get("id"))
    if cid is None:
        cid = make_comment_id(
            fields["film"], fields["shot"], fields["timestamp_s"], fields["comment"]
        )
    thread = raw.get("thread")
    if thread is not None and not isinstance(thread, list):
        raise ReviewSheetError(f"{where}: thread must be a list")
    return {"id": cid, **fields, "thread": list(thread) if thread else []}


def normalize_comments(comments: Any) -> list[dict[str, Any]]:
    """Normalise comment-list form (a) into canonical records."""
    if not isinstance(comments, (list, tuple)):
        raise ReviewSheetError("comments must be a list of dicts")
    if not comments:
        raise ReviewSheetError("comments list is empty: nothing to review")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, raw in enumerate(comments):
        where = f"comment #{i}"
        if not isinstance(raw, dict):
            raise ReviewSheetError(f"{where}: must be a dict, got {type(raw).__name__}")
        fields = _validate_comment_fields(raw, where)
        record = _record_from_validated(raw, fields, where)
        if record["id"] in seen:
            raise ReviewSheetError(f"{where}: duplicate comment id {record['id']!r}")
        seen.add(record["id"])
        records.append(record)
    return records


def fold_events(events: Any) -> list[dict[str, Any]]:
    """Fold an append-only event log (form b) into canonical records.

    Events apply in append order; each event's ``note`` lands on the
    target comment's ``thread`` so the history is never overwritten.
    """
    if not isinstance(events, (list, tuple)):
        raise ReviewSheetError("events must be a list of dicts")
    if not events:
        raise ReviewSheetError("events list is empty: nothing to review")
    records: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(events):
        where = f"event #{i}"
        if not isinstance(raw, dict):
            raise ReviewSheetError(f"{where}: must be a dict, got {type(raw).__name__}")
        etype = raw.get("type")
        if etype not in EVENT_TYPES:
            raise ReviewSheetError(
                f"{where}: invalid event type {etype!r}, expected one of {EVENT_TYPES}"
            )
        note = raw.get("note")
        note_text = str(note) if note is not None else ""
        entry: dict[str, Any] = {"type": etype, "note": note_text}
        for key in ("actor", "by"):
            if raw.get(key) is not None:
                entry[key] = raw[key]

        if etype == "comment":
            fields = _validate_comment_fields(raw, where)
            record = _record_from_validated(raw, fields, where)
            if record["id"] in by_id:
                raise ReviewSheetError(
                    f"{where}: duplicate comment id {record['id']!r}"
                )
            if not note_text:
                entry["note"] = record["comment"]
            record["thread"].append(entry)
            by_id[record["id"]] = record
            records.append(record)
            continue

        cid = _clean_str(raw.get("id"))
        if cid is None:
            raise ReviewSheetError(f"{where}: {etype} event missing id")
        record = by_id.get(cid)
        if record is None:
            raise ReviewSheetError(f"{where}: {etype} event references unknown id {cid!r}")
        record["status"] = _EVENT_STATUS[etype]
        record["thread"].append(entry)
    return records


def normalize_records(comments_or_events: Any) -> list[dict[str, Any]]:
    """Accept either input form and return canonical records.

    A list whose items carry a ``type`` field is an event log; a list
    without is a comment list.  A dict wrapper ``{"comments": [...]}``
    or ``{"events": [...]}`` is also accepted.
    """
    if isinstance(comments_or_events, dict):
        has_comments = comments_or_events.get("comments") is not None
        has_events = comments_or_events.get("events") is not None
        if has_comments == has_events:
            raise ReviewSheetError(
                "provide exactly one of 'comments' / 'events'"
            )
        if has_events:
            return fold_events(comments_or_events["events"])
        return normalize_comments(comments_or_events["comments"])
    if isinstance(comments_or_events, (list, tuple)):
        if any(
            isinstance(item, dict) and "type" in item
            for item in comments_or_events
        ):
            return fold_events(comments_or_events)
        return normalize_comments(comments_or_events)
    raise ReviewSheetError(
        "comments_or_events must be a comment list, an event list, "
        "or a {'comments': [...]} / {'events': [...]} dict"
    )


# ---------------------------------------------------------------------------
# Media probe + frame grab
# ---------------------------------------------------------------------------


def _probe_media(media_path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(media_path),
            ],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReviewSheetError(f"ffprobe failed for {media_path}: {exc}") from exc
    if proc.returncode != 0:
        raise ReviewSheetError(
            f"ffprobe could not probe {media_path}: {proc.stderr.strip()[:300]}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewSheetError(f"ffprobe returned non-JSON for {media_path}") from exc

    fmt = data.get("format") or {}
    try:
        duration_s = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration_s = 0.0
    width = height = None
    fps: float | None = None
    for stream in data.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        width = stream.get("width")
        height = stream.get("height")
        raw_fps = str(stream.get("avg_frame_rate") or "")
        if "/" in raw_fps:
            num, _, den = raw_fps.partition("/")
            try:
                if float(den):
                    fps = float(num) / float(den)
            except ValueError:
                fps = None
        if duration_s <= 0:
            with suppress(TypeError, ValueError):
                duration_s = float(stream.get("duration") or 0.0)
        break
    if duration_s <= 0:
        raise ReviewSheetError(f"could not determine duration of {media_path}")
    return {
        "duration_s": duration_s,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else None,
        "fps": fps,
        "format": fmt.get("format_name"),
    }


def _grab_frame(
    ffmpeg: str, media_path: Path, timestamp_s: float, duration_s: float, out: Path
) -> None:
    # Seeking to exactly the duration yields no frame; for that edge
    # only, grab the last frame instead (the record keeps its true
    # timestamp_s, and timestamp_s > duration was already rejected).
    seek = timestamp_s
    if seek >= duration_s:
        seek = max(0.0, duration_s - 0.05)
    proc = subprocess.run(
        [
            ffmpeg, "-y", "-v", "error",
            "-ss", f"{seek:.3f}", "-i", str(media_path),
            "-frames:v", "1", "-q:v", "2", str(out),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise ReviewSheetError(
            f"ffmpeg frame grab failed at {timestamp_s:.3f}s for "
            f"{media_path}: {proc.stderr.strip()[:300]}"
        )


# ---------------------------------------------------------------------------
# Sheet assembly
# ---------------------------------------------------------------------------


def build_review_sheet(
    media_path: str | Path,
    comments_or_events: Any,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Build a review sheet for ``media_path`` from comments or events.

    Writes ``frames/review_<id>.png`` per comment, ``review_sheet.json``
    (probe + canonical records incl. frame path and status) and
    ``review.md`` (human sheet titled with the film name) under
    ``out_dir``; returns the report dict (the JSON content plus the
    sheet file paths).
    """
    media_path = Path(media_path)
    out_dir = Path(out_dir)
    if not media_path.is_file():
        raise ReviewSheetError(f"media file not found: {media_path}")

    records = normalize_records(comments_or_events)
    probe = _probe_media(media_path)
    duration_s = float(probe["duration_s"])

    # Whole-sheet rejection, annotation_revision口径: validate every
    # timestamp before grabbing a single frame or writing a file.
    for record in records:
        if record["timestamp_s"] > duration_s:
            raise ReviewSheetError(
                f"comment {record['id']}: timestamp_s {record['timestamp_s']} "
                f"exceeds media duration {duration_s:.3f}s; whole sheet rejected"
            )

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        frame_name = f"review_{record['id']}.png"
        _grab_frame(
            ffmpeg, media_path, record["timestamp_s"], duration_s,
            frames_dir / frame_name,
        )
        record["frame"] = f"frames/{frame_name}"
        record["timecode"] = format_timecode(record["timestamp_s"])

    film = next(
        (r["film"] for r in records if r.get("film")),
        media_path.stem,
    )
    by_status = {
        status: Counter(r["status"] for r in records).get(status, 0)
        for status in VALID_STATUSES
    }
    by_status = {k: v for k, v in by_status.items() if v}

    report: dict[str, Any] = {
        "film": film,
        "media_path": str(media_path),
        "probe": probe,
        "comments": records,
        "count": len(records),
        "by_status": by_status,
        "pass": True,
    }

    sheet_json = out_dir / "review_sheet.json"
    sheet_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    lines: list[str] = [f"# {film}", ""]
    lines.append(
        f"- 媒体：`{media_path.name}` · 时长 {duration_s:.2f}s"
        + (f" · 分辨率 {probe['resolution']}" if probe.get("resolution") else "")
        + f" · 评论 {len(records)} 条"
    )
    lines.append("")
    for record in records:
        shot_scene = " / ".join(
            str(part)
            for part in (
                f"镜 {record['shot']}" if record.get("shot") is not None else None,
                record.get("scene"),
            )
            if part
        )
        heading = f"## {record['timecode']}"
        if shot_scene:
            heading += f" · {shot_scene}"
        lines.append(heading)
        lines.append("")
        lines.append(f"- 时间码：{record['timecode']}（{record['timestamp_s']:.2f}s）")
        if shot_scene:
            lines.append(f"- 镜号/场景：{shot_scene}")
        if record.get("element"):
            lines.append(f"- 元素：{record['element']}")
        lines.append(f"- 评论：{record['comment']}")
        lines.append(f"- 状态：{record['status']}")
        lines.append(f"- 帧图：![{record['id']}]({record['frame']})")
        lines.append("")
    sheet_md = out_dir / "review.md"
    sheet_md.write_text("\n".join(lines), encoding="utf-8")

    report["sheet_json"] = str(sheet_json)
    report["sheet_md"] = str(sheet_md)
    report["frames_dir"] = str(frames_dir)
    return report
