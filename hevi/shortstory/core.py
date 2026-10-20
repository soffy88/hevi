"""Short-story one-stop package: idea -> outline -> draft -> review -> blurb -> cover.

Clean-room, original implementation. Pipeline (every stage writes evidence
into ``out_dir``; nothing is merely declared):

  outline.json / outline.md   大纲 (title / logline / characters / beats)
  story.txt / story.md        正文
  review.json / review.md     结构化自审: hook / conflict / ending checklist
                              with per-item scores (deterministic heuristics)
  blurb.json / blurb.md       简介卖点: title candidates + one-line pitch +
                              synopsis + selling points
  cover_prompt.txt            封面提示词 (always produced)
  cover.png                   封面图 (only when a cover generator succeeds)
  package.json                台账 manifest: files / review / cover status

LLM access is fully injectable: ``llm_fn(stage, payload) -> str | dict`` with
stages ``"outline"``, ``"draft"``, ``"blurb"``, ``"cover_prompt"``. The
capability layer supplies the production (Monid-backed) implementation;
tests pass fakes, so the whole chain runs offline at zero cost.

Cover policy: ``cover_fn(prompt, out_path)`` may be injected. When it is not,
the core tries the registered ``image.gpt_generate`` capability (looked up
by name via ``hevi.capabilities.get``). Any failure degrades gracefully:
only ``cover_prompt.txt`` is kept and the degradation is recorded in the
manifest / qa (``cover.degraded is True``) — never a fake cover image.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = [
    "ShortStoryError",
    "build_cover_prompt",
    "build_short_package",
    "review_story",
]

LlmFn = Callable[[str, dict[str, Any]], Any]
CoverFn = Callable[[str, Path], Any]


class ShortStoryError(RuntimeError):
    """A short-story package stage failed; no fake package is produced."""


# ---------------------------------------------------------------------------
# Parsing helpers (LLM outputs may be JSON strings, dicts, or plain text)
# ---------------------------------------------------------------------------


def _maybe_json(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _text_of(raw: Any, *keys: str) -> str:
    if isinstance(raw, dict):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    return str(raw or "").strip()


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [line.strip(" -\t") for line in value.splitlines() if line.strip()]
    return []


def _normalise_outline(raw: Any, *, premise: str, genre: str) -> dict[str, Any]:
    data = _maybe_json(raw)
    if data is not None:
        title = str(data.get("title") or "").strip() or premise[:20]
        beats = []
        for beat in data.get("beats") or data.get("outline") or []:
            if isinstance(beat, dict):
                beats.append(
                    {
                        "title": str(beat.get("title") or "").strip(),
                        "summary": str(
                            beat.get("summary") or beat.get("text") or ""
                        ).strip(),
                    }
                )
            elif str(beat).strip():
                beats.append({"title": "", "summary": str(beat).strip()})
        characters = []
        for ch in data.get("characters") or []:
            if isinstance(ch, dict):
                characters.append(
                    {
                        "name": str(ch.get("name") or "").strip(),
                        "role": str(ch.get("role") or "").strip(),
                        "description": str(
                            ch.get("description") or ch.get("appearance") or ""
                        ).strip(),
                    }
                )
            elif str(ch).strip():
                characters.append(
                    {"name": str(ch).strip(), "role": "", "description": ""}
                )
        logline = str(data.get("logline") or data.get("hook") or "").strip()
    else:
        text = _text_of(raw)
        lines = [ln.strip(" #-\t") for ln in text.splitlines() if ln.strip()]
        title = lines[0][:40] if lines else premise[:20]
        beats = [{"title": "", "summary": ln} for ln in lines[1:]] or [
            {"title": "", "summary": premise}
        ]
        characters = []
        logline = premise
    if not beats:
        raise ShortStoryError("outline stage produced no beats")
    return {
        "title": title,
        "genre": genre,
        "premise": premise,
        "logline": logline,
        "characters": characters,
        "beats": beats,
    }


def _normalise_blurb(
    raw: Any, *, outline: dict[str, Any], premise: str
) -> dict[str, Any]:
    data = _maybe_json(raw)
    if data is not None:
        titles = _str_list(
            data.get("title_candidates") or data.get("titles") or []
        )
        pitch = str(
            data.get("one_line_pitch")
            or data.get("pitch")
            or data.get("selling_point")
            or ""
        ).strip()
        synopsis = str(data.get("synopsis") or data.get("blurb") or "").strip()
        points = _str_list(data.get("selling_points") or [])
    else:
        text = _text_of(raw)
        lines = [ln.strip(" #-\t") for ln in text.splitlines() if ln.strip()]
        titles = lines[:3]
        pitch = lines[3] if len(lines) > 3 else ""
        synopsis = "\n".join(lines[4:]) if len(lines) > 4 else ""
        points = []
    if outline["title"] and outline["title"] not in titles:
        titles = [outline["title"], *titles]
    titles = titles[:5]
    if not titles:
        raise ShortStoryError("blurb stage produced no title candidates")
    if not pitch:
        pitch = outline.get("logline") or premise
    if not synopsis:
        synopsis = premise
    return {
        "title_candidates": titles,
        "one_line_pitch": pitch,
        "synopsis": synopsis,
        "selling_points": points,
    }


# ---------------------------------------------------------------------------
# Structured self-review (deterministic checklist scoring)
# ---------------------------------------------------------------------------

_HOOK_MARKERS = (
    "突然", "秘密", "消失", "深夜", "未知", "竟然", "为什么", "谁", "敲门",
    "电话", "信", "梦", "死", "血", "?", "？", "!", "！",
)
_CONFLICT_MARKERS = (
    "但是", "然而", "冲突", "对抗", "拒绝", "挣扎", "危险", "追", "逃",
    "失败", "必须", "不能", "不肯", "争吵", "威胁", "陷阱", "代价", "选择",
)
_ENDING_MARKERS = (
    "终于", "明白", "回家", "天亮", "笑了", "安静", "决定", "再也", "从此",
    "结束", "释然", "告别", "新生", "答案",
)


def _marker_score(text: str, markers: tuple[str, ...], *, base: int = 0) -> int:
    hits = sum(1 for m in markers if m in text)
    return max(0, min(5, base + hits))


def review_story(story_text: str, outline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score a draft against a hook / conflict / ending checklist.

    Deterministic heuristics (no LLM): each check is 0-5, ``ok`` at >= 3.
    The review is a report, not a gate — a weak draft still ships with its
    scores visible in ``review.json``.
    """
    text = (story_text or "").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs and text:
        paragraphs = [text]
    opening = text[:300]
    middle = text[len(text) // 4 : (len(text) * 3) // 4] if len(text) >= 200 else text
    closing = text[-300:]

    hook = _marker_score(opening, _HOOK_MARKERS)
    if paragraphs and len(paragraphs[0]) <= 120:
        hook = min(5, hook + 1)
    conflict = _marker_score(middle, _CONFLICT_MARKERS)
    ending = _marker_score(closing, _ENDING_MARKERS)
    if closing.rstrip().endswith(("。", "！", "？", ".", "!", "?", "”", '"')):
        ending = min(5, ending + 1)
    structure = 5 if len(paragraphs) >= 3 else (3 if len(paragraphs) == 2 else 1)
    length = 5 if len(text) >= 800 else (3 if len(text) >= 300 else 1)

    checks = [
        {"name": "hook", "score": hook, "max": 5, "ok": hook >= 3,
         "detail": "opening carries a question / shock / suspense marker"},
        {"name": "conflict", "score": conflict, "max": 5, "ok": conflict >= 3,
         "detail": "middle carries opposition, stakes or a hard choice"},
        {"name": "ending", "score": ending, "max": 5, "ok": ending >= 3,
         "detail": "closing lands with resolution markers + final punctuation"},
        {"name": "structure", "score": structure, "max": 5,
         "ok": structure >= 3, "detail": "at least three paragraphs / beats"},
        {"name": "length", "score": length, "max": 5, "ok": length >= 3,
         "detail": "draft length in the short-story band"},
    ]
    total = sum(c["score"] for c in checks)
    return {
        "checks": checks,
        "total_score": total,
        "max_score": sum(c["max"] for c in checks),
        "passed_checks": [c["name"] for c in checks if c["ok"]],
        "failed_checks": [c["name"] for c in checks if not c["ok"]],
        "word_count": len(text),
        "paragraph_count": len(paragraphs),
        "outline_beats": len((outline or {}).get("beats") or []),
    }


def build_cover_prompt(
    *, title: str, genre: str, premise: str, synopsis: str = ""
) -> str:
    """Deterministic fallback cover prompt (used when the LLM gives none)."""
    subject = synopsis.strip() or premise.strip()
    return (
        f"Book cover illustration for a short story titled '{title}', "
        f"genre: {genre or 'fiction'}. Scene: {subject}. "
        "Single striking composition, strong silhouette, cinematic light, "
        "space reserved at the top for the title text, no text, no watermark."
    )


# ---------------------------------------------------------------------------
# Cover generation (injected fn, else the image.gpt_generate capability)
# ---------------------------------------------------------------------------


def _try_cover(
    cover_prompt: str,
    out_dir: Path,
    *,
    cover_fn: CoverFn | None,
    attempt_cover: bool,
) -> dict[str, Any]:
    cover_path = out_dir / "cover.png"
    if cover_fn is not None:
        try:
            result = cover_fn(cover_prompt, cover_path)
        except Exception as exc:
            return {"status": "prompt_only", "degraded": True, "image": None,
                    "note": f"cover generation failed, degraded to prompt only: {exc}"}
        produced = Path(result) if isinstance(result, (str, Path)) else cover_path
        if isinstance(result, dict) and result.get("png"):
            produced = Path(str(result["png"]))
        if produced.is_file():
            if produced.resolve() != cover_path.resolve():
                shutil.copyfile(produced, cover_path)
            return {"status": "generated", "degraded": False,
                    "image": str(cover_path), "note": "cover generated via injected cover_fn"}
        return {"status": "prompt_only", "degraded": True, "image": None,
                "note": "cover_fn returned no image file, degraded to prompt only"}
    if not attempt_cover:
        return {"status": "prompt_only", "degraded": True, "image": None,
                "note": "cover generation not attempted (attempt_cover=False), prompt only"}
    try:
        from hevi.capabilities import get as _cap_get

        cap = _cap_get("image.gpt_generate")
    except Exception as exc:
        return {"status": "prompt_only", "degraded": True, "image": None,
                "note": f"image.gpt_generate unavailable, degraded to prompt only: {exc}"}
    try:
        gen_dir = out_dir / "_cover_gen"
        result = cap.render_safe(
            {"prompt": cover_prompt}, gen_dir,
            duration=0.0, aspect="9:16", seed=42,
        )
        produced = Path(result.png) if getattr(result, "png", None) else gen_dir / "image.png"
        if not produced.is_file():
            raise ShortStoryError("image.gpt_generate produced no png")
        shutil.copyfile(produced, cover_path)
    except Exception as exc:
        return {"status": "prompt_only", "degraded": True, "image": None,
                "note": f"image.gpt_generate failed, degraded to prompt only: {exc}"}
    return {"status": "generated", "degraded": False, "image": str(cover_path),
            "note": "cover generated via image.gpt_generate"}


# ---------------------------------------------------------------------------
# Main chain
# ---------------------------------------------------------------------------


def build_short_package(
    *,
    premise: str,
    genre: str = "",
    out_dir: str | Path,
    llm_fn: LlmFn | None,
    cover_fn: CoverFn | None = None,
    attempt_cover: bool = True,
    target_words: int | None = None,
) -> dict[str, Any]:
    """Run the full short-story chain and write every artifact to ``out_dir``.

    Returns the package manifest (also written to ``package.json``).
    Raises :class:`ShortStoryError` on invalid input or a failed stage.
    """
    premise = str(premise or "").strip()
    if not premise:
        raise ShortStoryError("premise is required (one-line idea / 题材创意)")
    if llm_fn is None or not callable(llm_fn):
        raise ShortStoryError("llm_fn is required and must be callable")
    if target_words is not None and not (200 <= int(target_words) <= 50000):
        raise ShortStoryError("target_words must be between 200 and 50000")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1) Outline -------------------------------------------------------------
    try:
        outline_raw = llm_fn(
            "outline",
            {
                "premise": premise,
                "genre": genre,
                "prompt": (
                    f"为短篇小说写大纲。题材：{genre or '不限'}。一句话创意：{premise}。"
                    "输出 JSON：title / logline / characters(name, role, description) / "
                    "beats(title, summary)，beats 3-7 个，含开端、冲突、高潮、结尾。"
                ),
            },
        )
    except ShortStoryError:
        raise
    except Exception as exc:
        raise ShortStoryError(f"outline stage failed: {exc}") from exc
    outline = _normalise_outline(outline_raw, premise=premise, genre=genre)

    # 2) Draft ---------------------------------------------------------------
    try:
        draft_raw = llm_fn(
            "draft",
            {
                "premise": premise,
                "genre": genre,
                "outline": outline,
                "prompt": (
                    f"按大纲写短篇小说正文。标题：{outline['title']}。创意：{premise}。"
                    f"大纲节拍：{json.dumps(outline['beats'], ensure_ascii=False)}。"
                    "开头即钩子，中段有冲突与代价，结尾有回落与收束。只输出正文。"
                    + (f"目标字数约 {target_words} 字。" if target_words else "")
                ),
            },
        )
    except ShortStoryError:
        raise
    except Exception as exc:
        raise ShortStoryError(f"draft stage failed: {exc}") from exc
    story_text = _text_of(draft_raw, "text", "story", "body", "content")
    if len(story_text) < 50:
        raise ShortStoryError("draft stage produced an unusably short story (<50 chars)")

    # 3) Structured self-review ----------------------------------------------
    review = review_story(story_text, outline)

    # 4) Blurb / selling points ----------------------------------------------
    try:
        blurb_raw = llm_fn(
            "blurb",
            {
                "premise": premise,
                "genre": genre,
                "outline": outline,
                "story_excerpt": story_text[:600],
                "prompt": (
                    f"为短篇《{outline['title']}》写简介卖点。输出 JSON："
                    "title_candidates(3-5 个) / one_line_pitch / synopsis / selling_points。"
                ),
            },
        )
    except ShortStoryError:
        raise
    except Exception as exc:
        raise ShortStoryError(f"blurb stage failed: {exc}") from exc
    blurb = _normalise_blurb(blurb_raw, outline=outline, premise=premise)

    # 5) Cover prompt + (best-effort) cover image ------------------------------
    cover_prompt = ""
    try:
        cover_raw = llm_fn(
            "cover_prompt",
            {
                "premise": premise,
                "genre": genre,
                "outline": outline,
                "blurb": blurb,
                "prompt": (
                    f"为短篇《{outline['title']}》写一条英文封面生成提示词："
                    "一个标志性画面、强构图、顶部留标题空间、无文字无水印。"
                ),
            },
        )
        cover_prompt = _text_of(cover_raw, "prompt", "cover_prompt", "text")
    except Exception:
        cover_prompt = ""
    if not cover_prompt:
        cover_prompt = build_cover_prompt(
            title=outline["title"], genre=genre,
            premise=premise, synopsis=blurb.get("synopsis", ""),
        )
    cover = _try_cover(cover_prompt, out, cover_fn=cover_fn, attempt_cover=attempt_cover)

    # 6) Write artifacts --------------------------------------------------------
    files: dict[str, str] = {}

    def _write(name: str, content: str) -> str:
        path = out / name
        path.write_text(content, encoding="utf-8")
        files[name] = str(path)
        return str(path)

    _write("outline.json", json.dumps(outline, ensure_ascii=False, indent=1))
    outline_md = [f"# 大纲：{outline['title']}", "", f"创意：{premise}",
                  f"一句话故事：{outline.get('logline', '')}", "", "## 人物"]
    outline_md.extend(
        f"- {ch['name']}（{ch.get('role', '')}）：{ch.get('description', '')}"
        for ch in outline["characters"]
    )
    outline_md += ["", "## 节拍"]
    for i, beat in enumerate(outline["beats"], 1):
        outline_md.append(f"{i}. {beat.get('title', '')} {beat.get('summary', '')}".strip())
    _write("outline.md", "\n".join(outline_md) + "\n")

    _write("story.txt", story_text + "\n")
    _write("story.md", f"# {outline['title']}\n\n{story_text}\n")

    _write("review.json", json.dumps(review, ensure_ascii=False, indent=1))
    review_md = [f"# 自审：{outline['title']}", "",
                 f"总分：{review['total_score']}/{review['max_score']}", ""]
    review_md.extend(
        f"- {c['name']}: {c['score']}/{c['max']} "
        f"{'OK' if c['ok'] else 'WEAK'} — {c['detail']}"
        for c in review["checks"]
    )
    _write("review.md", "\n".join(review_md) + "\n")

    _write("blurb.json", json.dumps(blurb, ensure_ascii=False, indent=1))
    blurb_md = [f"# 简介卖点：{outline['title']}", "", "## 标题候选"]
    blurb_md += [f"- {t}" for t in blurb["title_candidates"]]
    blurb_md += ["", f"一句话卖点：{blurb['one_line_pitch']}", "",
                 "## 简介", blurb["synopsis"], "", "## 卖点"]
    blurb_md += [f"- {p}" for p in blurb["selling_points"]] or ["- （无）"]
    _write("blurb.md", "\n".join(blurb_md) + "\n")

    _write("cover_prompt.txt", cover_prompt + "\n")
    if cover.get("image"):
        files["cover.png"] = str(cover["image"])

    manifest: dict[str, Any] = {
        "kind": "short_story_package",
        "title": outline["title"],
        "premise": premise,
        "genre": genre,
        "word_count": len(story_text),
        "files": files,
        "review": review,
        "blurb": blurb,
        "cover": {
            "status": cover["status"],
            "degraded": bool(cover["degraded"]),
            "prompt_file": files["cover_prompt.txt"],
            "image": cover.get("image"),
            "note": cover["note"],
        },
    }
    _write("package.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    manifest["files"] = files
    return manifest
