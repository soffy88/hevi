"""File-based long-form serial novel pipeline (clean-room, original design).

A *book* is a plain directory on disk — no database:

    <book_dir>/
        book.json               世界观 / 角色档案 / 卷纲章节大纲 / 进度台账
        continuation.json       (仅导入续写) 断点上下文: 末章摘要 + 人物表
        chapters/
            chapter_001.md      正文 (带字数治理头注)
            chapter_001.analysis.json   写前分析证据
            ...

Three operations (see ``hevi.capabilities.novelpipeline`` for the
registered capability wrappers):

* :func:`create_novel` — 创作简报 → book.json (世界观、角色档案、章节大纲)。
* :func:`write_chapter` — 写前分析 → 生成正文 → 字数治理 (偏离目标 ±20%
  以上时自动扩写或缩减, 只一轮) → 落盘 + 更新进度。
* :func:`continue_work` — 导入已有纯文本 → 按章节标记切分 → 续写上下文
  (末章摘要 + 人物表) → 从断点产出新章 (走 write_chapter 同一路径)。

Every LLM call goes through an injectable ``llm_fn(prompt, kind) -> str`` so
tests (and alternative providers) can substitute a deterministic fake with
zero network and zero spend.  With no ``llm_fn`` configured the functions
raise :class:`CapabilityError` — never a fabricated success.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError

__all__ = [
    "DEFAULT_GOVERNANCE_DELTA",
    "LlmFn",
    "char_count",
    "continue_work",
    "create_novel",
    "load_book",
    "save_book",
    "split_imported_text",
    "verify_book",
    "write_chapter",
]

# llm_fn(prompt, kind) -> str ; kind is one of:
#   "book_outline" | "chapter_body" | "expand" | "shrink" | "summary" |
#   "continue_setup"
LlmFn = Callable[[str, str], str]

DEFAULT_GOVERNANCE_DELTA = 0.2
_MIN_TARGET_CHARS = 100
_MAX_TARGET_CHARS = 20000


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def char_count(text: str) -> int:
    """生成侧字数: 非空白字符数 (中文正文的通行计法)。"""
    return len(re.sub(r"\s+", "", text or ""))


def _require_llm(llm_fn: LlmFn | None, op: str) -> LlmFn:
    if llm_fn is None:
        raise CapabilityError(
            f"novel.{op}: no llm_fn configured — inject one via the llm_fn "
            "parameter (core API) or hevi.capabilities.novelpipeline."
            "set_llm_fn(...) (capability API); the default deployment ships "
            "without an LLM backend"
        )
    return llm_fn


def _call_llm(llm_fn: LlmFn, prompt: str, kind: str, op: str) -> str:
    try:
        out = llm_fn(prompt, kind)
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"novel.{op}: llm_fn(kind={kind!r}) failed: {exc}") from exc
    if not isinstance(out, str) or not out.strip():
        raise CapabilityError(f"novel.{op}: llm_fn(kind={kind!r}) returned empty output")
    return out


def _parse_llm_json(text: str, op: str, kind: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise CapabilityError(
            f"novel.{op}: llm_fn(kind={kind!r}) did not return valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise CapabilityError(f"novel.{op}: llm_fn(kind={kind!r}) JSON must be an object")
    return data


def _validate_target_chars(value: Any, op: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"novel.{op}: chapter_target_chars must be an integer") from exc
    if not _MIN_TARGET_CHARS <= n <= _MAX_TARGET_CHARS:
        raise CapabilityError(
            f"novel.{op}: chapter_target_chars must be between "
            f"{_MIN_TARGET_CHARS} and {_MAX_TARGET_CHARS}, got {n}"
        )
    return n


def _chapter_rel_path(chapter: int) -> str:
    return f"chapters/chapter_{chapter:03d}.md"


def _chapter_path(book_dir: Path, chapter: int) -> Path:
    return book_dir / _chapter_rel_path(chapter)


def save_book(book_dir: Path, book: dict[str, Any]) -> Path:
    book_dir.mkdir(parents=True, exist_ok=True)
    path = book_dir / "book.json"
    path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_book(book_dir: Path | str, op: str = "write_chapter") -> dict[str, Any]:
    path = Path(book_dir) / "book.json"
    if not path.is_file():
        raise CapabilityError(f"novel.{op}: book.json not found under {book_dir}")
    try:
        book = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilityError(f"novel.{op}: book.json is corrupt: {exc}") from exc
    if not isinstance(book, dict):
        raise CapabilityError(f"novel.{op}: book.json must contain a JSON object")
    return book


def verify_book(book_dir: Path | str) -> dict[str, Any]:
    """Check that every artefact book.json claims actually exists on disk."""
    book_dir = Path(book_dir)
    book = load_book(book_dir, op="verify")
    missing: list[str] = []
    for entry in book.get("chapters", []):
        rel = entry.get("file")
        if rel and not (book_dir / rel).is_file():
            missing.append(rel)
    if missing:
        raise CapabilityError(
            f"novel.verify: book at {book_dir} is missing chapter artefacts: {missing}"
        )
    return {"ok": True, "book_dir": str(book_dir), "chapters": len(book.get("chapters", []))}


# ---------------------------------------------------------------------------
# novel.create
# ---------------------------------------------------------------------------

_OUTLINE_PROMPT = """你是一部长篇小说的总策划。根据下面的创作简报, 产出全书规划。
只输出 JSON, 不要 markdown 包裹。

简报:
- 题材: {genre}
- 主角: {protagonist}
- 核心冲突: {conflict}
- 目标章数 TOTAL_CHAPTERS={total_chapters}
- 单章目标字数 TARGET_CHARS={chapter_target_chars}

输出 JSON 字段:
{{
  "title": "书名",
  "setting": {{"world": "世界观一句话", "rules": ["世界规则/设定要点"]}},
  "characters": [
    {{"name": "名字", "role": "主角/配角/反派", "profile": "人物小传(一两句)"}}
  ],
  "outline": [
    {{"title": "章标题", "summary": "本章大纲(一两句)"}}
  ]
}}
约束: outline 恰好 TOTAL_CHAPTERS 条; characters 至少包含主角本人; 每章 summary 要推进核心冲突。"""


def create_novel(
    *,
    book_dir: Path | str,
    genre: str,
    protagonist: str,
    conflict: str,
    total_chapters: int,
    chapter_target_chars: int = 2000,
    title: str | None = None,
    llm_fn: LlmFn | None = None,
) -> dict[str, Any]:
    """Create a book directory (book.json + chapters/) from a creative brief."""
    op = "create"
    for field_name, value in (
        ("genre", genre),
        ("protagonist", protagonist),
        ("conflict", conflict),
    ):
        if not isinstance(value, str) or not value.strip():
            raise CapabilityError(f"novel.{op}: {field_name!r} must be a non-empty string")
    try:
        total = int(total_chapters)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"novel.{op}: total_chapters must be an integer") from exc
    if not 1 <= total <= 200:
        raise CapabilityError(f"novel.{op}: total_chapters must be between 1 and 200, got {total}")
    target = _validate_target_chars(chapter_target_chars, op)
    llm = _require_llm(llm_fn, op)

    prompt = _OUTLINE_PROMPT.format(
        genre=genre.strip(),
        protagonist=protagonist.strip(),
        conflict=conflict.strip(),
        total_chapters=total,
        chapter_target_chars=target,
    )
    draft = _parse_llm_json(_call_llm(llm, prompt, "book_outline", op), op, "book_outline")

    setting = draft.get("setting")
    if setting is None:
        raise CapabilityError(f"novel.{op}: outline JSON is missing 'setting'")
    characters = draft.get("characters")
    if not isinstance(characters, list) or not characters:
        raise CapabilityError(f"novel.{op}: outline JSON 'characters' must be a non-empty list")
    norm_characters: list[dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise CapabilityError(f"novel.{op}: every character needs a non-empty 'name'")
        norm_characters.append(
            {
                "name": str(item["name"]).strip(),
                "role": str(item.get("role") or "配角"),
                "profile": str(item.get("profile") or ""),
            }
        )
    if not any(c["name"] == protagonist.strip() for c in norm_characters):
        norm_characters.insert(0, {"name": protagonist.strip(), "role": "主角", "profile": ""})

    raw_outline = draft.get("outline")
    if not isinstance(raw_outline, list) or not raw_outline:
        raise CapabilityError(f"novel.{op}: outline JSON 'outline' must be a non-empty list")
    outline: list[dict[str, Any]] = []
    for i in range(total):
        item = raw_outline[i] if i < len(raw_outline) and isinstance(raw_outline[i], dict) else {}
        outline.append(
            {
                "chapter": i + 1,
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or "（待规划）"),
            }
        )

    book: dict[str, Any] = {
        "schema": "hevi.novel/1",
        "title": (title or str(draft.get("title") or "")).strip() or "未命名长篇",
        "genre": genre.strip(),
        "protagonist": protagonist.strip(),
        "conflict": conflict.strip(),
        "setting": setting,
        "characters": norm_characters,
        "total_chapters": total,
        "chapter_target_chars": target,
        "outline": outline,
        # 正史要点占位: 后续章节沉淀的不可违背事实 (本期只建结构, 不做追踪逻辑)
        "continuity": {"facts": []},
        "progress": {"completed": [], "next_chapter": 1, "status": "created"},
        "chapters": [],
        "created_from": "brief",
    }
    book_dir = Path(book_dir)
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    save_book(book_dir, book)
    return book


# ---------------------------------------------------------------------------
# novel.write_chapter (含生成侧字数治理)
# ---------------------------------------------------------------------------

_BODY_PROMPT = """写长篇小说的第 {chapter} 章正文。只输出正文, 不要标题, 不要解释。

- 书名: {book_title} (题材: {genre})
- 本章标题: {chapter_title}
- 本章意图: {intent}
- 主要人物: {character_names}
- 上一章摘要: {prev_summary}
- 正史要点 (不可违背): {continuity_facts}
- 目标字数 TARGET_CHARS={target_chars} (允许 ±20%)

要求: 开头承接上一章, 本章内推进冲突, 结尾留钩子。"""

_EXPAND_PROMPT = """下面这一章太短了。在不改动情节走向与人物设定的前提下扩写: 补场景细节、
人物反应与对话, 把正文扩写到目标字数附近。只输出扩写后的完整正文, 不要解释。

- 目标字数 TARGET_CHARS={target_chars}
- 当前字数: {actual_chars}

原文:
{draft}"""

_SHRINK_PROMPT = """下面这一章太长了。在不丢失关键情节与结尾钩子的前提下缩减: 删冗余描写、
合并重复信息, 把正文缩减到目标字数附近。只输出缩减后的完整正文, 不要解释。

- 目标字数 TARGET_CHARS={target_chars}
- 当前字数: {actual_chars}

原文:
{draft}"""

_SUMMARY_PROMPT = """用 3-5 句话概括下面这一章: 发生了什么、人物状态有什么变化、留下了什么悬念。
只输出摘要本身。

章节正文 (节选):
{text}"""


def _summarize_text(llm: LlmFn, text: str, op: str) -> str:
    excerpt = text[:4000]
    return _call_llm(llm, _SUMMARY_PROMPT.format(text=excerpt), "summary", op).strip()


def write_chapter(
    *,
    book_dir: Path | str,
    llm_fn: LlmFn | None = None,
    chapter: int | None = None,
    target_chars: int | None = None,
    governance_delta: float = DEFAULT_GOVERNANCE_DELTA,
) -> dict[str, Any]:
    """Write one chapter: pre-write analysis → draft → word-count governance.

    Governance: if the draft's char count deviates from the target by more
    than ``governance_delta`` (default ±20%), exactly ONE corrective round
    runs — expand when too short, shrink when too long.  Never more.
    """
    op = "write_chapter"
    book_dir = Path(book_dir)
    book = load_book(book_dir, op=op)
    llm = _require_llm(llm_fn, op)
    if not 0 < float(governance_delta) < 0.5:
        raise CapabilityError(
            f"novel.{op}: governance_delta must be in (0, 0.5), got {governance_delta}"
        )
    total = int(book.get("total_chapters") or 0)
    if total < 1:
        raise CapabilityError(f"novel.{op}: book.json has no valid total_chapters")
    if chapter is None:
        n = int(book.get("progress", {}).get("next_chapter") or 1)
    else:
        try:
            n = int(chapter)
        except (TypeError, ValueError) as exc:
            raise CapabilityError(f"novel.{op}: chapter must be an integer") from exc
    if not 1 <= n <= total:
        raise CapabilityError(f"novel.{op}: chapter must be between 1 and {total}, got {n}")
    target = (
        _validate_target_chars(target_chars, op)
        if target_chars is not None
        else int(book.get("chapter_target_chars") or 2000)
    )

    outline = book.get("outline") or []
    outline_entry = outline[n - 1] if n - 1 < len(outline) else {}
    chapter_title = str(outline_entry.get("title") or f"第{n}章")
    intent = str(outline_entry.get("summary") or "")
    characters = book.get("characters") or []
    character_names = "、".join(str(c.get("name")) for c in characters if c.get("name"))
    continuity_facts = list((book.get("continuity") or {}).get("facts") or [])

    # --- 写前分析: 本章意图 + 上章摘要 + 正史要点 --------------------------
    prev_summary = ""
    if n > 1 and _chapter_path(book_dir, n - 1).is_file():
        prev_text = _chapter_path(book_dir, n - 1).read_text(encoding="utf-8")
        prev_summary = _summarize_text(llm, prev_text, op)
    analysis = {
        "chapter": n,
        "intent": intent,
        "prev_chapter_summary": prev_summary,
        "continuity_facts": continuity_facts,
        "characters": character_names,
        "target_chars": target,
    }
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    analysis_path = book_dir / "chapters" / f"chapter_{n:03d}.analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- 生成正文 -----------------------------------------------------------
    body_prompt = _BODY_PROMPT.format(
        chapter=n,
        book_title=book.get("title", ""),
        genre=book.get("genre", ""),
        chapter_title=chapter_title,
        intent=intent or "（按大纲推进）",
        character_names=character_names or "（见角色档案）",
        prev_summary=prev_summary or "（无, 本章为开篇或前章未导入）",
        continuity_facts="；".join(continuity_facts) or "（暂无）",
        target_chars=target,
    )
    body = _call_llm(llm, body_prompt, "chapter_body", op).strip()

    # --- 字数治理: 偏离 ±delta 以上只纠正一轮 ------------------------------
    rounds: list[dict[str, Any]] = [{"kind": "draft", "chars": char_count(body)}]
    actual = rounds[0]["chars"]
    governance = "none"
    lo = target * (1 - governance_delta)
    hi = target * (1 + governance_delta)
    if actual < lo:
        body = _call_llm(
            llm,
            _EXPAND_PROMPT.format(target_chars=target, actual_chars=actual, draft=body),
            "expand",
            op,
        ).strip()
        governance = "expanded"
        rounds.append({"kind": "expand", "chars": char_count(body)})
    elif actual > hi:
        body = _call_llm(
            llm,
            _SHRINK_PROMPT.format(target_chars=target, actual_chars=actual, draft=body),
            "shrink",
            op,
        ).strip()
        governance = "shrunk"
        rounds.append({"kind": "shrink", "chars": char_count(body)})
    final_chars = char_count(body)

    # --- 落盘章节 + 更新 book.json 进度 --------------------------------------
    chapter_file = _chapter_path(book_dir, n)
    header = (
        f"# 第{n}章 {chapter_title}\n\n"
        f"<!-- chapter: {n}; target_chars: {target}; final_chars: {final_chars}; "
        f"governance: {governance} -->\n\n"
    )
    chapter_file.write_text(header + body + "\n", encoding="utf-8")

    ledger = [e for e in book.get("chapters", []) if int(e.get("chapter") or 0) != n]
    ledger.append(
        {
            "chapter": n,
            "title": chapter_title,
            "file": _chapter_rel_path(n),
            "source": "generated",
            "target_chars": target,
            "rounds": rounds,
            "final_chars": final_chars,
            "governance": governance,
        }
    )
    ledger.sort(key=lambda e: int(e.get("chapter") or 0))
    book["chapters"] = ledger
    completed = sorted({int(e["chapter"]) for e in ledger})
    book["progress"] = {
        "completed": completed,
        "next_chapter": (max(completed) + 1) if completed else 1,
        "status": "complete" if len(completed) >= total else "writing",
    }
    save_book(book_dir, book)

    return {
        "chapter": n,
        "title": chapter_title,
        "path": str(chapter_file),
        "analysis_path": str(analysis_path),
        "target_chars": target,
        "final_chars": final_chars,
        "governance": governance,
        "rounds": rounds,
    }


# ---------------------------------------------------------------------------
# novel.continue_work (导入 → 切分 → 续写上下文 → 断点新章)
# ---------------------------------------------------------------------------


def split_imported_text(text: str) -> list[Any]:
    """Split imported prose into chapters.

    Reuses hevi's existing chapter-splitting convention
    (``hevi.storygraph.chapter_splitter.split_text_to_chapters``: explicit
    第X章 / Chapter X markers first, blank-line blocks as fallback).  If that
    module is unavailable, falls back to a local marker-only splitter with
    the same Chapter-shaped result (chapter_id / title / content).
    """
    try:
        from hevi.storygraph.chapter_splitter import split_text_to_chapters

        return split_text_to_chapters(text, source_name="import")
    except ImportError:  # pragma: no cover - storygraph is in-repo
        from dataclasses import dataclass

        @dataclass
        class _Chapter:
            chapter_id: str
            title: str
            content: str
            char_count: int

        marker = re.compile(r"^\s*(第[零一二三四五六七八九十百千万\d]+[章回节])\s*(.*)$")
        parts: list[tuple[str, str]] = []
        current_title, buf = "", []
        for line in text.splitlines():
            m = marker.match(line)
            if m:
                if buf:
                    parts.append((current_title, "\n".join(buf)))
                current_title, buf = line.strip(), [line]
            else:
                buf.append(line)
        if buf:
            parts.append((current_title, "\n".join(buf)))
        return [
            _Chapter(f"IMP_{i:03d}", t or c.strip()[:20], c.strip(), len(c))
            for i, (t, c) in enumerate(parts, start=1)
            if c.strip()
        ]


_CONTINUE_SETUP_PROMPT = """下面是一部未完长篇的导入信息。请提炼续写所需的作品档案。
只输出 JSON, 不要 markdown 包裹。

- 已有章节标题: {chapter_titles}
- 末章摘要: {last_summary}
- 末章正文节选:
{last_excerpt}

输出 JSON 字段:
{{
  "title": "书名 (无法判断时给一个贴切的暂定名)",
  "genre": "题材",
  "protagonist": "主角姓名",
  "conflict": "核心冲突 (一句话)",
  "characters": [
    {{"name": "名字", "role": "主角/配角/反派", "profile": "人物小传(一两句)"}}
  ]
}}
约束: characters 至少包含主角; 只依据原文, 不要编造原文没有的关键设定。"""


def continue_work(
    *,
    book_dir: Path | str,
    text: str,
    llm_fn: LlmFn | None = None,
    title: str | None = None,
    chapter_target_chars: int = 2000,
    extra_chapters: int = 1,
) -> dict[str, Any]:
    """Import an existing work, build continuation context, write the next chapter.

    The imported chapters are preserved verbatim under ``chapters/`` and
    recorded in book.json; the continuation context (last-chapter summary +
    character table) lands in ``continuation.json``; the new chapter is then
    produced through :func:`write_chapter` — the same path as a from-scratch
    book, including word-count governance.
    """
    op = "continue_work"
    if not isinstance(text, str) or not text.strip():
        raise CapabilityError(f"novel.{op}: 'text' must be a non-empty string")
    target = _validate_target_chars(chapter_target_chars, op)
    try:
        extra = int(extra_chapters)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"novel.{op}: extra_chapters must be an integer") from exc
    if not 1 <= extra <= 50:
        raise CapabilityError(f"novel.{op}: extra_chapters must be between 1 and 50, got {extra}")
    llm = _require_llm(llm_fn, op)
    book_dir = Path(book_dir)
    if (book_dir / "book.json").exists():
        raise CapabilityError(
            f"novel.{op}: {book_dir} already contains a book.json; refusing to overwrite"
        )

    chapters = split_imported_text(text)
    if not chapters:
        raise CapabilityError(f"novel.{op}: no chapters could be split from the imported text")
    imported = len(chapters)
    last = chapters[-1]

    # --- 续写上下文: 末章摘要 + 人物表 ---------------------------------------
    last_summary = _summarize_text(llm, str(last.content), op)
    setup = _parse_llm_json(
        _call_llm(
            llm,
            _CONTINUE_SETUP_PROMPT.format(
                chapter_titles="；".join(str(c.title) for c in chapters),
                last_summary=last_summary,
                last_excerpt=str(last.content)[:2000],
            ),
            "continue_setup",
            op,
        ),
        op,
        "continue_setup",
    )
    characters = setup.get("characters")
    if not isinstance(characters, list) or not characters:
        raise CapabilityError(f"novel.{op}: continue_setup JSON 'characters' must be non-empty")
    norm_characters: list[dict[str, Any]] = []
    for item in characters:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise CapabilityError(f"novel.{op}: every character needs a non-empty 'name'")
        norm_characters.append(
            {
                "name": str(item["name"]).strip(),
                "role": str(item.get("role") or "配角"),
                "profile": str(item.get("profile") or ""),
            }
        )
    protagonist = str(setup.get("protagonist") or "").strip()
    if protagonist and not any(c["name"] == protagonist for c in norm_characters):
        norm_characters.insert(0, {"name": protagonist, "role": "主角", "profile": ""})

    total = imported + extra
    outline: list[dict[str, Any]] = [
        {
            "chapter": i + 1,
            "title": str(c.title),
            "summary": "（导入章节）",
        }
        for i, c in enumerate(chapters)
    ] + [
        {
            "chapter": imported + j + 1,
            "title": "",
            "summary": "承接末章悬念续写, 推进核心冲突。",
        }
        for j in range(extra)
    ]
    book: dict[str, Any] = {
        "schema": "hevi.novel/1",
        "title": (title or str(setup.get("title") or "")).strip() or "导入作品续写",
        "genre": str(setup.get("genre") or ""),
        "protagonist": protagonist,
        "conflict": str(setup.get("conflict") or ""),
        "setting": setup.get("setting") or {},
        "characters": norm_characters,
        "total_chapters": total,
        "chapter_target_chars": target,
        "outline": outline,
        "continuity": {"facts": []},
        "progress": {
            "completed": list(range(1, imported + 1)),
            "next_chapter": imported + 1,
            "status": "writing",
        },
        "chapters": [],
        "created_from": "import",
    }

    # --- 导入章节原样落盘 -----------------------------------------------------
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    ledger: list[dict[str, Any]] = []
    for i, c in enumerate(chapters, start=1):
        content = str(c.content).strip()
        _chapter_path(book_dir, i).write_text(content + "\n", encoding="utf-8")
        ledger.append(
            {
                "chapter": i,
                "title": str(c.title),
                "file": _chapter_rel_path(i),
                "source": "imported",
                "target_chars": None,
                "rounds": [],
                "final_chars": char_count(content),
                "governance": "imported",
            }
        )
    book["chapters"] = ledger
    save_book(book_dir, book)

    continuation = {
        "imported_chapters": imported,
        "last_chapter": imported,
        "last_chapter_title": str(last.title),
        "last_chapter_summary": last_summary,
        "characters": norm_characters,
    }
    continuation_path = book_dir / "continuation.json"
    continuation_path.write_text(
        json.dumps(continuation, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # --- 从断点产出新章 (与从零写作同一路径) ----------------------------------
    new_chapter = write_chapter(
        book_dir=book_dir, llm_fn=llm, chapter=imported + 1, target_chars=target
    )
    return {
        "book_dir": str(book_dir),
        "book_json": str(book_dir / "book.json"),
        "imported_chapters": imported,
        "continuation_path": str(continuation_path),
        "continuation": continuation,
        "new_chapter": new_chapter,
    }
