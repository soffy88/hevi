"""小说 / 长文导入：把章节正文切成剧集的确定性入口。

只做切分与校验，不改写、不概括、不生成剧情：每章正文按段落
边界切成若干集，每集的 synopsis 只取该集首个非空段落（超长时
截断并加标记），绝不编造概括。纯标准库、确定性、离线。
"""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

__all__ = ["parse_chapters", "map_to_episodes"]

_SYNOPSIS_LIMIT = 200
_SYNOPSIS_MARKER = "……"
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_DIALOGUE_RE = re.compile(r"“([^”]*)”")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _split_paragraphs(text: str) -> list[str]:
    """按空行分段，丢弃全空白段，段落内容本身不改写。"""
    return [para for para in _PARAGRAPH_SPLIT_RE.split(text.strip()) if para.strip()]


def parse_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验章节列表并原样规范化，按章号升序返回。

    以下情况一律 raise CapabilityError，绝不静默丢章：
    章节列表为空；chapter_no 不是 int 或重复；章号不从 1 起连续；
    title 为空；text 为空或全空白。
    """
    if not isinstance(chapters, list) or not chapters:
        raise CapabilityError("章节列表为空：至少需要一章才能导入。")

    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            raise CapabilityError(f"第 {index + 1} 项不是章节对象（应为 dict）。")
        chapter_no = chapter.get("chapter_no")
        if not _is_int(chapter_no):
            raise CapabilityError(
                f"章节 chapter_no 必须是 int，得到 {chapter_no!r}。"
            )
        if chapter_no in seen:
            raise CapabilityError(f"章节号重复：第 {chapter_no} 章出现多次。")
        seen.add(chapter_no)
        title = chapter.get("title")
        if not isinstance(title, str) or not title.strip():
            raise CapabilityError(f"第 {chapter_no} 章标题为空。")
        text = chapter.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CapabilityError(f"第 {chapter_no} 章正文为空。")
        normalized.append(
            {"chapter_no": chapter_no, "title": title, "text": text}
        )

    expected = list(range(1, len(normalized) + 1))
    actual = sorted(seen)
    if actual != expected:
        highest = max(seen)
        missing = sorted(set(range(1, highest + 1)) - seen)
        extra = sorted(no for no in seen if no < 1 or no > len(normalized))
        detail = f"缺失的章号：{missing}。" if missing else ""
        if extra:
            detail += f"超出 1..{len(normalized)} 范围的章号：{extra}。"
        raise CapabilityError(
            f"章节号不从 1 起连续（现有章号：{actual}）。{detail}"
        )

    normalized.sort(key=lambda item: item["chapter_no"])
    return normalized


def _balanced_cuts(lengths: list[int], parts: int) -> list[int]:
    """把段落序列切成 parts 份，使各份字符数尽量接近均分。

    确定性动态规划：最小化各份长度与均值之差的平方和（分数精确
    运算，无浮点 tie 歧义）；代价相等时取先遇到的切法。返回每份
    所含段落数的列表。
    """
    total = sum(lengths)
    mean = Fraction(total, parts)
    prefix = [0]
    for length in lengths:
        prefix.append(prefix[-1] + length)

    count = len(lengths)
    infinity = Fraction(10**18)
    # dp[j][i]：前 i 段切成 j 份的最小代价；cut[j][i]：第 j 份的起点。
    dp: list[list[Fraction]] = [[infinity] * (count + 1) for _ in range(parts + 1)]
    cut: list[list[int]] = [[0] * (count + 1) for _ in range(parts + 1)]
    dp[0][0] = Fraction(0)
    for j in range(1, parts + 1):
        for i in range(j, count - (parts - j) + 1):
            for prev in range(j - 1, i):
                if dp[j - 1][prev] == infinity:
                    continue
                group_len = prefix[i] - prefix[prev]
                cost = dp[j - 1][prev] + (Fraction(group_len) - mean) ** 2
                if cost < dp[j][i]:
                    dp[j][i] = cost
                    cut[j][i] = prev
    sizes: list[int] = []
    end = count
    for j in range(parts, 0, -1):
        start = cut[j][end]
        sizes.append(end - start)
        end = start
    sizes.reverse()
    return sizes


def _synopsis(first_paragraph: str) -> str:
    if len(first_paragraph) > _SYNOPSIS_LIMIT:
        return first_paragraph[:_SYNOPSIS_LIMIT] + _SYNOPSIS_MARKER
    return first_paragraph


def _dialogue_char_count(text_slice: str) -> int:
    return sum(len(match) for match in _DIALOGUE_RE.findall(text_slice))


def map_to_episodes(
    chapters: list[dict[str, Any]], *, episodes_per_chapter: int = 2
) -> list[dict[str, Any]]:
    """把校验后的章节按段落边界切成剧集。

    每章切成 episodes_per_chapter 集，切分点取段落边界、使各份
    字符数尽量接近；段落数不足时对该章 raise CapabilityError。
    集号按章顺序、章内按 part 顺序从 1 起连续编号，总集数恒为
    章数 x episodes_per_chapter。
    """
    if not _is_int(episodes_per_chapter) or episodes_per_chapter < 1:
        raise CapabilityError(
            "episodes_per_chapter 必须是大于等于 1 的 int，"
            f"得到 {episodes_per_chapter!r}。"
        )
    parsed = parse_chapters(chapters)

    episodes: list[dict[str, Any]] = []
    episode_no = 0
    for chapter in parsed:
        paragraphs = _split_paragraphs(chapter["text"])
        if len(paragraphs) < episodes_per_chapter:
            raise CapabilityError(
                f"第 {chapter['chapter_no']} 章（{chapter['title']}）段落数 "
                f"{len(paragraphs)} 少于每章集数 {episodes_per_chapter}，"
                "无法按段落边界切分。"
            )
        sizes = _balanced_cuts(
            [len(paragraph) for paragraph in paragraphs], episodes_per_chapter
        )
        offset = 0
        for part, size in enumerate(sizes, start=1):
            chunk = paragraphs[offset : offset + size]
            offset += size
            text_slice = "\n\n".join(chunk)
            episode_no += 1
            episodes.append(
                {
                    "episode_no": episode_no,
                    "chapter_no": chapter["chapter_no"],
                    "part": part,
                    "title": f"{chapter['title']}（第{part}部分）",
                    "source_chapter_title": chapter["title"],
                    "synopsis": _synopsis(chunk[0]),
                    "text_slice": text_slice,
                    "char_count": len(text_slice),
                    "dialogue_char_count": _dialogue_char_count(text_slice),
                }
            )
    return episodes


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chapters": {"type": "array"},
        "episodes_per_chapter": {"type": "integer", "minimum": 1, "default": 2},
    },
    "required": ["chapters"],
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "novel_import.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    # Report capability: aspect is declared but ignored (S-03).
    # Naming division (S-02): novel.* (novelpipeline) CREATES a book;
    # story.novel_import only MAPS a finished book's chapters to
    # episode inputs (split + synopsis-from-first-paragraph only).
    episodes = map_to_episodes(
        params["chapters"],
        episodes_per_chapter=params.get("episodes_per_chapter", 2),
    )
    payload = {"episodes": episodes, "episode_count": len(episodes)}
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_novel_import_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.novel_import",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "成书→分集输入映射：把已成书的章节正文按段落边界切成"
                "剧集（每集梗概只取首段、超长截断标记），不改写、不概括、"
                "不创作。与 novel.* 家族分工：novel.* 负责成书创作，"
                "本能力只负责成书到分集的确定性映射。报告类能力："
                "产物为 episodes JSON（aspects 仅声明，渲染忽略）。"
            ),
            line="novel_import",
            has_media_output=False,
        )
    )
    return ["story.novel_import"]


register_novel_import_capabilities_once()
