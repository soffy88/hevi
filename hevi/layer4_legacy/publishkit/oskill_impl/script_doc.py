"""文稿解析（oskill 层）：把成片对应的文稿变成逐句 ScriptDoc。

支持上游产线的三种真实文稿形态，全部来自输入文件本身：

* talkcraft ``work/timestamps.json`` —— 带 start_s/end_s 的逐句旁白（成片真实时间戳）；
* 白板 ``scenes/script.json`` —— 场景 + 每场 ``segments``（beat）旁白；
* 分镜 JSON / Markdown / 纯文本 —— 一行一句。

明确**不**接受二进制或视频文件当文稿：读不出文字就报错，不把源码/字节流
当成"正文"塞进文案。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.publishkit.oprim_impl.contracts import (
    ScriptDoc,
    ScriptError,
    ScriptLine,
)

_TEXT_SUFFIXES = {".json", ".md", ".txt", ".srt", ".vtt"}
_BINARY_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".wav", ".mp3", ".m4a",
    ".jpg", ".jpeg", ".png", ".webp", ".ttf", ".otf", ".woff", ".woff2",
}
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")
_SKIP_LINE = re.compile(r"^\s*(?://|/\*|#\s*|第\s*\d+\s*段)")


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _BINARY_SUFFIXES:
        raise ScriptError(f"NOT_A_SCRIPT: {path.name} 是媒体/字体文件，不能当文稿用")
    if suffix not in _TEXT_SUFFIXES:
        raise ScriptError(f"NOT_A_SCRIPT: 不支持的文稿扩展名 {suffix or '(无)'}（{path.name}）")
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ScriptError(f"NOT_A_SCRIPT: {path.name} 含二进制字节，不是文稿")
    text = raw.decode("utf-8", errors="strict")
    if not text.strip():
        raise ScriptError(f"EMPTY_SCRIPT: {path.name} 是空文件")
    return text


def _lines_from_sentences(text: str) -> list[str]:
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _SKIP_LINE.match(line):
            continue
        for piece in _SENTENCE_SPLIT.split(line):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def _from_talkcraft_timings(data: dict[str, Any]) -> tuple[str, list[ScriptLine], str]:
    """talkcraft work/timestamps.json：逐句旁白 + 成片真实起止时间。"""

    timings = data.get("timings")
    if not isinstance(timings, list) or not timings:
        raise ScriptError("TIMINGS_EMPTY: timestamps.json 里没有 timings")
    lines: list[ScriptLine] = []
    for item in timings:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        lines.append(
            ScriptLine(
                index=len(lines),
                text=text,
                start_s=float(item["start_s"]) if item.get("start_s") is not None else None,
                end_s=float(item["end_s"]) if item.get("end_s") is not None else None,
            )
        )
    if not lines:
        raise ScriptError("TIMINGS_EMPTY: timestamps.json 的 timings 全是空文本")
    topic = lines[0].text.rstrip("？?。.")
    return topic, lines, "talkcraft_timestamps"


def _from_scene_script(data: Any) -> tuple[str, list[ScriptLine], str]:
    """白板 scenes/script.json：场景数组，每场 segments 是 beat 旁白。"""

    scenes = data if isinstance(data, list) else data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ScriptError("SCRIPT_EMPTY: script.json 里没有 scenes")
    lines: list[ScriptLine] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        segments = scene.get("segments") or []
        for seg in segments:
            text = str(seg).strip()
            if text:
                lines.append(ScriptLine(index=len(lines), text=text))
    if not lines:
        raise ScriptError("SCRIPT_EMPTY: script.json 的 scenes 里没有旁白")
    first_name = str(scenes[0].get("name") or "") if isinstance(scenes[0], dict) else ""
    # 场景名形如 "00-intro" 是内部 id，不能当标题——改用首句旁白
    topic = lines[0].text.rstrip("？?。.") if not first_name or re.fullmatch(r"\d+-\w+", first_name) else first_name
    return topic, lines, "scene_script"


def _from_storyboard(data: dict[str, Any]) -> tuple[str, list[ScriptLine], str, str]:
    """分镜 JSON：topic + segments[].narration（`|` 分 beat）。"""

    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ScriptError("STORYBOARD_EMPTY: 分镜里没有 segments")
    lines: list[ScriptLine] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        narration = str(seg.get("narration") or seg.get("text") or "")
        for beat in narration.split("|"):
            beat = beat.strip()
            if beat:
                lines.append(ScriptLine(index=len(lines), text=beat))
    if not lines:
        raise ScriptError("STORYBOARD_EMPTY: 分镜的 narration 全是空文本")
    brand = data.get("brand")
    brand_name = brand.get("name", "") if isinstance(brand, dict) else str(brand or "")
    return str(data.get("topic") or lines[0].text), lines, "storyboard_json", str(brand_name or "")


def parse_script(path: Path) -> ScriptDoc:
    """读取文稿 → ScriptDoc。文稿不可用时抛 ScriptError（绝不降级成占位正文）。"""

    path = Path(path)
    if not path.is_file():
        raise ScriptError(f"SCRIPT_MISSING: {path}")
    text = _read_text(path)

    topic = ""
    brand = ""
    account = ""
    lines: list[ScriptLine] = []
    kind = ""

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScriptError(f"SCRIPT_NOT_JSON: {path.name} 解析失败：{exc}") from exc
        if isinstance(data, dict) and isinstance(data.get("timings"), list):
            topic, lines, kind = _from_talkcraft_timings(data)
        elif isinstance(data, dict) and isinstance(data.get("segments"), list):
            topic, lines, kind, brand = _from_storyboard(data)
        elif isinstance(data, list | dict):
            topic, lines, kind = _from_scene_script(data)
        else:
            raise ScriptError(f"SCRIPT_SHAPE_UNKNOWN: {path.name} 不是可识别的文稿 JSON")
    else:
        raw_lines = _lines_from_sentences(text)
        if not raw_lines:
            raise ScriptError(f"SCRIPT_EMPTY: {path.name} 没有可用的旁白句")
        lines = [ScriptLine(index=i, text=t) for i, t in enumerate(raw_lines)]
        topic = lines[0].text.rstrip("？?。.")
        kind = path.suffix.lstrip(".") or "text"

    if not lines:
        raise ScriptError(f"SCRIPT_EMPTY: {path.name} 没有解析出旁白句")

    chapters = _chapters_from_lines(lines)
    return ScriptDoc(
        path=str(path),
        topic=topic or lines[0].text,
        lines=tuple(lines),
        chapters=chapters,
        brand=brand,
        account=account,
        source_kind=kind,
    )


def _chapters_from_lines(lines: list[ScriptLine]) -> tuple[tuple[str, float], ...]:
    """章节 = 有真实时间戳的句子；没有时间戳就不编章节（不伪造时间码）。"""

    if not lines or lines[0].start_s is None:
        return ()
    out: list[tuple[str, float]] = []
    for line in lines:
        if line.start_s is None:
            continue
        title = _chapter_title(line.text)
        if title:
            out.append((title, float(line.start_s)))
    return tuple(out)


def _chapter_title(text: str, limit: int = 14) -> str:
    """把一句旁白压成章节名（截到第一个标点，最多 limit 字）。"""

    head = re.split(r"[，。？！；：、,]", text.strip())[0].strip()
    head = head.rstrip("？?。.")
    if len(head) > limit:
        head = head[:limit]
    return head