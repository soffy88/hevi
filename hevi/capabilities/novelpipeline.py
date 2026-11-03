"""Long-form serial novel capabilities (file-based, no database).

Registers three ``hevi.capabilities`` entries so every product line can run
the novel pipeline by dotted name (CAPABILITY_CONTRACT.md; precedent:
``.multimodel`` / ``.storyfilm``):

* ``novel.create`` — 创作简报 (题材/主角/核心冲突/目标章数/单章目标字数)
  → book directory with book.json (世界观、角色档案、卷纲/章节大纲).
* ``novel.write_chapter`` — 写前分析 (本章意图 + 上章摘要 + 正史要点) →
  正文生成 → 多轮治理 (偏离目标 ±20% 以上、对白占比不在目标区间、
  节拍缺失或节拍段无对话场景时自动分段扩写 / 段落级改成对话 /
  缩减 / 修补, 最多 3 轮; 触顶仍不达标则打回, 旧章与进度不动;
  生成前先备份旧章) → 章节落盘 + book.json 进度更新.
* ``novel.continue_work`` — 导入已有作品纯文本 → 章节切分 → 续写上下文
  (末章摘要 + 人物表, continuation.json) → 从断点产出新章.

LLM access is injectable: the core pipeline takes an ``llm_fn(prompt, kind)``
callable.  For the capability surface, install one process-wide with
:func:`set_llm_fn`.  Backend resolution order: an explicitly injected
``llm_fn`` wins; otherwise the default Monid backend
(:mod:`hevi.llm.monid_chat`, gpt-4o-mini via blockrun — the same route and
the same ``MONID_API_KEY`` env key as ``story.film_from_prompt``, billed
per Monid call at a small per-call rate) is used when the key is
resolvable; with neither available every render raises ``CapabilityError``
explaining both the injection point and the missing key — never a fake
success.
"""

from __future__ import annotations

import json
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

_LLM_FN: Any = None


def set_llm_fn(fn: Any) -> None:
    """Install (or clear, with ``None``) the process-wide novel LLM callable."""
    global _LLM_FN
    _LLM_FN = fn


def get_llm_fn() -> Any:
    """Return the explicitly injected llm_fn (``None`` if none installed).

    Note this does not reflect the default Monid backend; renders resolve
    the effective backend via :func:`_require_llm`.
    """
    return _LLM_FN


def _default_llm_fn(prompt: str, kind: str) -> str:
    """Default backend: Monid gpt-4o-mini chat (see hevi.llm.monid_chat).

    Synchronous facade — safe inside or outside a running event loop.
    """
    from hevi.llm import monid_chat

    return monid_chat.chat_for_kind_sync(prompt, kind)


def _resolve_llm_fn() -> Any:
    """Effective llm_fn: injected > default Monid (key resolvable) > None."""
    if _LLM_FN is not None:
        return _LLM_FN
    from hevi.llm import monid_chat

    if monid_chat.monid_key_available():
        return _default_llm_fn
    return None


def _require_llm(name: str) -> Any:
    fn = _resolve_llm_fn()
    if fn is None:
        from hevi.llm import monid_chat

        raise CapabilityError(
            f"{name}: no LLM configured — inject one via "
            "hevi.capabilities.novelpipeline.set_llm_fn(llm_fn) or call "
            "hevi.novelpipeline.core directly with llm_fn=...; and "
            f"{monid_chat.missing_key_hint()}"
        )
    return fn


def _resolve_book_dir(params: dict[str, Any], out_dir: Path, *, name: str) -> Path:
    """Resolve ``book_dir`` for a file-type capability (C-05).

    Contract rule (see CAPABILITY_CONTRACT.md): ``book_dir`` is the
    caller-confirmed write root for the book, NOT an ignored hint —
    but it is validated, never taken on faith:

    * a relative ``book_dir`` resolves under ``out_dir`` (out_dir is
      the default write root, so the preview endpoint's temp dir and
      the real write location cannot silently diverge);
    * an absolute ``book_dir`` is kept (existing callers and tests
      address books outside the job dir), but it is rejected when it
      resolves to the filesystem root, the user's home directory, or
      an existing non-directory — i.e. it may not point at an
      arbitrary unvalidated path;
    * ``write_chapter`` renders that need an existing book additionally
      require ``book.json`` to exist (checked by the caller before the
      core call).

    Every render also writes a receipt into ``out_dir`` naming the
    resolved book dir, so the job dir always records where the book
    actually went even when the book itself lives elsewhere.
    """
    raw = str(params["book_dir"])
    candidate = Path(raw)
    if not candidate.is_absolute():
        resolved = (Path(out_dir) / candidate).resolve()
    else:
        resolved = candidate.resolve()
    home = Path.home().resolve()
    if resolved == Path("/") or resolved == home:
        raise CapabilityError(
            f"{name}: book_dir must not be the filesystem root or the "
            f"home directory, got {raw!r}"
        )
    if resolved.exists() and not resolved.is_dir():
        raise CapabilityError(
            f"{name}: book_dir exists but is not a directory: {resolved}"
        )
    return resolved


def _write_receipt(
    out_dir: Path, *, name: str, book_dir: Path, extra: dict[str, Any]
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt = out_dir / "novel_render_receipt.json"
    receipt.write_text(
        json.dumps(
            {"capability": name, "book_dir": str(book_dir), **extra},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return receipt


def _require_existing_book(book_dir: Path, *, name: str) -> None:
    if not (book_dir / "book.json").is_file():
        raise CapabilityError(
            f"{name}: book_dir has no book.json (not an existing book): "
            f"{book_dir}"
        )


def _render_create(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.novelpipeline.core import create_novel

    llm = _require_llm("novel.create")
    book_dir = _resolve_book_dir(params, out_dir, name="novel.create")
    book = create_novel(
        book_dir=book_dir,
        genre=str(params["genre"]),
        protagonist=str(params["protagonist"]),
        conflict=str(params["conflict"]),
        total_chapters=int(params["total_chapters"]),
        chapter_target_chars=int(params.get("chapter_target_chars") or 2000),
        title=str(params["title"]) if params.get("title") else None,
        llm_fn=llm,
    )
    book_json = book_dir / "book.json"
    receipt = _write_receipt(
        out_dir, name="novel.create", book_dir=book_dir,
        extra={"book_json": str(book_json)},
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(book_json),
        qa={
            "receipt_json": str(receipt),
            "book_json": str(book_json),
            "book_dir": str(book_dir),
            "title": book["title"],
            "total_chapters": book["total_chapters"],
            "chapter_target_chars": book["chapter_target_chars"],
            "characters": [c["name"] for c in book["characters"]],
            "outline_chapters": len(book["outline"]),
        },
    )


def _render_write_chapter(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.novelpipeline.core import write_chapter

    llm = _require_llm("novel.write_chapter")
    book_dir = _resolve_book_dir(params, out_dir, name="novel.write_chapter")
    _require_existing_book(book_dir, name="novel.write_chapter")
    # Capability default mirrors the core default (45-58%); the core API
    # still allows dialogue_ratio_range=None for measure-only callers.
    dialogue_range = (
        float(params.get("dialogue_min_ratio") or 0.45),
        float(params.get("dialogue_max_ratio") or 0.58),
    )
    result = write_chapter(
        book_dir=book_dir,
        llm_fn=llm,
        chapter=int(params["chapter"]) if params.get("chapter") else None,
        target_chars=(
            int(params["chapter_target_chars"]) if params.get("chapter_target_chars") else None
        ),
        governance_delta=float(params.get("governance_delta") or 0.2),
        beats=params.get("beats"),
        forbidden_phrases=params.get("forbidden_phrases"),
        scene_keywords=params.get("scene_keywords"),
        max_governance_rounds=int(params.get("max_governance_rounds") or 3),
        dialogue_ratio_range=dialogue_range,
    )
    chapter_path = Path(result["path"])
    receipt = _write_receipt(
        out_dir, name="novel.write_chapter", book_dir=book_dir,
        extra={"chapter_path": str(chapter_path)},
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(chapter_path),
        qa={
            "receipt_json": str(receipt),
            "chapter": result["chapter"],
            "title": result["title"],
            "chapter_path": str(chapter_path),
            "analysis_path": result["analysis_path"],
            "book_json": str(book_dir / "book.json"),
            "target_chars": result["target_chars"],
            "final_chars": result["final_chars"],
            "governance": result["governance"],
            "rounds": result["rounds"],
            "dialogue_ratio": result["dialogue_ratio"],
            "checks": result["checks"],
            "backup_path": result["backup_path"],
            "in_tolerance": result["in_tolerance"],
            "status": result["status"],
        },
    )


def _render_continue_work(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.novelpipeline.core import continue_work

    llm = _require_llm("novel.continue_work")
    book_dir = _resolve_book_dir(params, out_dir, name="novel.continue_work")
    result = continue_work(
        book_dir=book_dir,
        text=str(params["text"]),
        llm_fn=llm,
        title=str(params["title"]) if params.get("title") else None,
        chapter_target_chars=int(params.get("chapter_target_chars") or 2000),
        extra_chapters=int(params.get("extra_chapters") or 1),
        beats=params.get("beats"),
        forbidden_phrases=params.get("forbidden_phrases"),
        scene_keywords=params.get("scene_keywords"),
        max_governance_rounds=int(params.get("max_governance_rounds") or 3),
        dialogue_ratio_range=(
            float(params.get("dialogue_min_ratio") or 0.45),
            float(params.get("dialogue_max_ratio") or 0.58),
        ),
    )
    new_path = Path(result["new_chapter"]["path"])
    receipt = _write_receipt(
        out_dir, name="novel.continue_work", book_dir=book_dir,
        extra={"new_chapter_path": str(new_path)},
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(new_path),
        qa={
            "receipt_json": str(receipt),
            "book_json": result["book_json"],
            "book_dir": result["book_dir"],
            "imported_chapters": result["imported_chapters"],
            "continuation_json": result["continuation_path"],
            "continuation": json.loads(
                Path(result["continuation_path"]).read_text(encoding="utf-8")
            ),
            "new_chapter": result["new_chapter"],
        },
    )


def register_novelpipeline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="novel.create",
            kind="line",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "book_dir": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Book directory to create (holds book.json + chapters/); relative paths resolve under out_dir, absolute paths are validated (never root/home/a file)",
                    },
                    "genre": {"type": "string", "minLength": 1, "description": "题材"},
                    "protagonist": {"type": "string", "minLength": 1, "description": "主角"},
                    "conflict": {"type": "string", "minLength": 1, "description": "核心冲突"},
                    "total_chapters": {"type": "integer", "minimum": 1, "maximum": 200},
                    "chapter_target_chars": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": 20000,
                        "default": 2000,
                        "description": "单章目标字数 (生成侧字数治理的锚)",
                    },
                    "title": {"type": "string", "description": "书名 (缺省时由规划生成)"},
                },
                "required": ["book_dir", "genre", "protagonist", "conflict", "total_chapters"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,  # planning call only; LLM cost is per-call
            render=_render_create,
            has_media_output=False,
            description=(
                "Create a long-form serial novel from a creative brief "
                "(genre / protagonist / core conflict / chapter count / "
                "per-chapter target chars). Produces a file-based book "
                "directory: book.json with world setting, character "
                "profiles and a full chapter outline. LLM backend: an "
                "injected llm_fn (set_llm_fn) if installed, otherwise the "
                "default Monid gpt-4o-mini backend (per-call small fee, "
                "same MONID_API_KEY as story.film_from_prompt)."
            ),
            line="novel",
        )
    )
    registered.append("novel.create")

    register(
        Capability(
            name="novel.write_chapter",
            kind="line",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "book_dir": {"type": "string", "minLength": 1, "description": "Existing book directory (must contain book.json); relative paths resolve under out_dir"},
                    "chapter": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Chapter to write (default: next unwritten chapter)",
                    },
                    "chapter_target_chars": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": 20000,
                        "description": "Override the book's per-chapter target chars",
                    },
                    "governance_delta": {
                        "type": "number",
                        "minimum": 0.05,
                        "maximum": 0.49,
                        "default": 0.2,
                        "description": "Allowed length deviation before "
                        "governance rounds trigger",
                    },
                    "beats": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required beats for this chapter, "
                        "injected into the prompt and checked after each "
                        "draft; a missing beat triggers a repair round",
                    },
                    "forbidden_phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Phrases that must never appear "
                        "(full truths / invented events); checked in code "
                        "only, never sent in a generation prompt; a hit "
                        "after all repair rounds blocks the chapter",
                    },
                    "scene_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Main-scene keywords the title "
                        "promises; the first occurrence must fall in the "
                        "opening 60% of the chapter or it is blocked",
                    },
                    "max_governance_rounds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                        "description": "Governance rounds before a still-"
                        "failing chapter is blocked (quarantined, progress "
                        "untouched) instead of silently delivered",
                    },
                    "dialogue_min_ratio": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0.45,
                        "description": "Dialogue share floor (quoted chars / "
                        "total chars); narration is turned into dialogue "
                        "in prompts and repair rounds",
                    },
                    "dialogue_max_ratio": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0.58,
                        "description": "Dialogue share ceiling",
                    },
                },
                "required": ["book_dir"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_write_chapter,
            has_media_output=False,
            description=(
                "Write one chapter of an existing book: pre-write analysis "
                "(chapter intent + previous-chapter summary + continuity "
                "facts) → draft → multi-round governance (segmented "
                "expansion with per-segment budgets and a single forward "
                "continuation per short segment, paragraph-level dialogue "
                "conversion for dialogue-poor segments, shrink for a pure "
                "too-long deviation, repair only for blockers; up to 3 "
                "rounds, then the chapter is blocked and quarantined "
                "rather than silently delivered; the previous chapter is "
                "backed up before generation) → chapter file on disk and "
                "book.json progress updated. LLM backend: injected llm_fn "
                "(set_llm_fn) or the default Monid gpt-4o-mini backend "
                "(per-call small fee)."
            ),
            line="novel",
        )
    )
    registered.append("novel.write_chapter")

    register(
        Capability(
            name="novel.continue_work",
            kind="line",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "book_dir": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Fresh book directory for the imported work",
                    },
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Full plain text of the existing work",
                    },
                    "title": {"type": "string", "description": "书名 (缺省时由提炼生成)"},
                    "chapter_target_chars": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": 20000,
                        "default": 2000,
                    },
                    "extra_chapters": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 1,
                        "description": "How many new chapters the book plans "
                        "beyond the imported ones (the first is written now)",
                    },
                    "beats": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required beats for the new chapter "
                        "(see novel.write_chapter)",
                    },
                    "forbidden_phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Phrases that must never appear in "
                        "the new chapter (see novel.write_chapter)",
                    },
                    "scene_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Main-scene keywords for the new "
                        "chapter (see novel.write_chapter)",
                    },
                    "max_governance_rounds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                    },
                    "dialogue_min_ratio": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0.45,
                    },
                    "dialogue_max_ratio": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0.58,
                    },
                },
                "required": ["book_dir", "text"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_continue_work,
            has_media_output=False,
            description=(
                "Import an existing novel as plain text: split into "
                "chapters (第X章 / Chapter X markers), build the "
                "continuation context (last-chapter summary + character "
                "table in continuation.json), preserve the imported "
                "chapters on disk, then write the next chapter from the "
                "breakpoint through the same write_chapter path (with "
                "multi-round governance). LLM backend: injected llm_fn "
                "(set_llm_fn) or the default Monid gpt-4o-mini backend "
                "(per-call small fee)."
            ),
            line="novel",
        )
    )
    registered.append("novel.continue_work")

    return registered
