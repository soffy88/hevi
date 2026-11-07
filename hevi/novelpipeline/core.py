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
* :func:`write_chapter` — 写前分析 → 生成正文 → 多轮治理 (偏离目标 ±20%
  以上、或对白占比不在目标区间、或节拍缺失时自动分段扩写 / 缩减 / 修补,
  最多 ``DEFAULT_MAX_GOVERNANCE_ROUNDS`` 轮; 触顶仍不达标则打回, 不静默
  交出不合格章节, 旧章不受影响) → 落盘 + 更新进度。
  分段扩写 (本轮结构修复的核心): 本章按节拍切段, 每段给字数预算并强制
  扩写到预算 (逐段扩写、不是全文改写一遍); 段落级篇幅合同: 每段预算有
  aimLow–target 区间与参考上限 maximum, 低于 minimum 的段不做全文改写、
  只做一次向前续写补足 (推进下一事件 / 动作 / 对话、禁复述末尾、新增不
  超 ceiling、收束停在完整句段末); 长度已在带内但对白不足的段走段落级
  改成对话; 扩写后重组并全量复核 (章幅、对白比、节拍实质、禁语、标题
  场景)。节拍核对容忍自然改写 (去助词 / 近义 / 分词覆盖 / 有序窗口),
  但容忍后仍须章幅 + 对白双过才算过关。
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
    "DEFAULT_DIALOGUE_RATIO_RANGE",
    "DEFAULT_GOVERNANCE_DELTA",
    "DEFAULT_LLM_ATTEMPTS",
    "DEFAULT_MAX_GOVERNANCE_ROUNDS",
    "LlmFn",
    "char_count",
    "check_chapter",
    "continue_work",
    "create_novel",
    "dialogue_stats",
    "load_book",
    "normalize_beats",
    "save_book",
    "split_chapter_by_beats",
    "split_imported_text",
    "verify_book",
    "write_chapter",
]

# llm_fn(prompt, kind) -> str ; kind is one of:
#   "book_outline" | "chapter_body" | "expand" | "shrink" | "summary" |
#   "continue_setup" | "repair" | "segment_expand" | "segment_dialogue" |
#   "segment_continue"
# ("repair" is the blocker-only full rewrite: it deletes forbidden
#  revelations / fixes title-scene mismatch, used only when blockers are
#  present.  Every other governance need — too short, low dialogue, or
#  missing beats — goes through segmented expansion: "segment_expand"
#  expands / condenses one beat segment to its budget, "segment_dialogue"
#  converts one length-OK but dialogue-poor segment into dialogue, and
#  "segment_continue" is the single forward-continuation top-up for a
#  segment still below its minimum after expansion.  There is no
#  full-rewrite growth kind any more: a full rewrite is exactly the
#  failure mode the reprobe diagnosed (repair rounds added ~40 chars
#  each instead of growing to target).)
LlmFn = Callable[[str, str], str]

DEFAULT_GOVERNANCE_DELTA = 0.2
DEFAULT_MAX_GOVERNANCE_ROUNDS = 3
DEFAULT_DIALOGUE_RATIO_RANGE = (0.45, 0.58)
DEFAULT_LLM_ATTEMPTS = 3
_MIN_TARGET_CHARS = 100
_MAX_TARGET_CHARS = 20000
_MAX_GOVERNANCE_ROUNDS = 5
_MAX_LLM_ATTEMPTS = 5


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


def _call_llm_with_attempts(
    llm_fn: LlmFn, prompt: str, kind: str, op: str, attempts: int = DEFAULT_LLM_ATTEMPTS
) -> tuple[str, int]:
    """Call ``llm_fn`` with transient-error retries.

    A timed-out client read (the probe's chapter_body failure: the server
    run still completed but no text landed) surfaces here as an exception
    from ``llm_fn``; retrying re-issues the call while nothing has been
    written to disk yet, so a failed attempt can never leave a partial
    chapter behind.  ``CapabilityError`` raised by ``llm_fn`` itself is
    permanent and is never retried.  Returns ``(text, attempts_used)``.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            out = llm_fn(prompt, kind)
        except CapabilityError:
            raise
        except Exception as exc:  # transient: timeout / transport / 5xx
            last_exc = exc
            if attempt >= attempts:
                raise CapabilityError(
                    f"novel.{op}: llm_fn(kind={kind!r}) failed after "
                    f"{attempts} attempts: {exc}"
                ) from exc
            continue
        if not isinstance(out, str) or not out.strip():
            last_exc = ValueError("empty output")
            if attempt >= attempts:
                raise CapabilityError(
                    f"novel.{op}: llm_fn(kind={kind!r}) returned empty output "
                    f"after {attempts} attempts"
                )
            continue
        return out, attempt
    raise CapabilityError(  # pragma: no cover - loop always returns/raises
        f"novel.{op}: llm_fn(kind={kind!r}) failed: {last_exc}"
    )


def _call_llm(llm_fn: LlmFn, prompt: str, kind: str, op: str) -> str:
    text, _attempts = _call_llm_with_attempts(llm_fn, prompt, kind, op)
    return text


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


def _norm_text(text: str) -> str:
    """Text with all whitespace removed (the probe's char-count basis)."""
    return re.sub(r"\s+", "", text or "")


def dialogue_stats(text: str) -> dict[str, Any]:
    """Dialogue share of a chapter body.

    Probe convention: dialogue = characters inside Chinese (“”) or ASCII
    ("") quotes; total = non-whitespace characters (quotes included).
    """
    total = char_count(text)
    dialogue = 0
    for match in re.finditer(r"“([^”]*)”|\"([^\"]*)\"", text or ""):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        dialogue += char_count(inner)
    return {
        "dialogue_chars": dialogue,
        "total_chars": total,
        "ratio": (dialogue / total) if total else 0.0,
    }


_STOP_CHARS = set("的地得了着过在和与或但而就才也都还把被对为从向以及之乎者也")


def _beat_grams(beat_text: str) -> list[str]:
    """Distinctive 2-char grams of a beat string (Chinese paraphrase check).

    A beat given as plain prose cannot be matched verbatim — the model
    paraphrases.  Coverage of its 2-char grams is the deterministic
    proxy: a chapter that never delivers the beat contains ~none of
    them, while a paraphrase (“手稿上的三处线条对不上”) keeps most.
    Grams made only of stop characters are dropped.
    """
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", beat_text or "")
    grams: list[str] = []
    for i in range(len(cleaned) - 1):
        gram = cleaned[i : i + 2]
        if any(ch not in _STOP_CHARS for ch in gram) and gram not in grams:
            grams.append(gram)
    return grams


def normalize_beats(beats: Any) -> list[dict[str, Any]]:
    """Normalize caller-supplied beats to ``{text, anchors, required}``.

    Accepts a plain string (anchor = its 2-char grams, required = 30%
    coverage) or a dict ``{"beat": str, "anchors": [...],
    "min_anchors": int}`` (explicit anchors, required defaults to half
    the anchors, at least one).
    """
    normalized: list[dict[str, Any]] = []
    if not beats:
        return normalized
    if isinstance(beats, (str, dict)):
        beats = [beats]
    for item in beats:
        if isinstance(item, dict):
            if "anchors" in item and "required" in item:
                # Already normalized (e.g. re-measured inside write_chapter).
                text = str(item.get("beat") or item.get("text") or "")
                anchors = [_norm_text(str(a)) for a in item["anchors"]]
                anchors = [a for a in anchors if a]
                if text and anchors:
                    normalized.append(
                        {"text": text, "anchors": anchors,
                         "required": max(1, int(item["required"]))}
                    )
                continue
            text = str(item.get("beat") or item.get("text") or "")
            anchors = [_norm_text(str(a)) for a in (item.get("anchors") or [])]
            anchors = [a for a in anchors if a]
            if not text or not anchors:
                continue
            required = item.get("min_anchors")
            try:
                required = int(required) if required is not None else max(1, len(anchors) // 2)
            except (TypeError, ValueError):
                required = max(1, len(anchors) // 2)
            normalized.append(
                {"text": text, "anchors": anchors, "required": max(1, required)}
            )
        elif isinstance(item, str) and item.strip():
            grams = _beat_grams(item)
            if not grams:
                continue
            normalized.append(
                {
                    "text": item.strip(),
                    "anchors": grams,
                    "required": max(1, -(-len(grams) * 3 // 10)),  # ceil(30%)
                    "gram_coverage": True,
                }
            )
    return normalized


# Beat matching tolerates natural paraphrase (the reprobe's lesson: a beat
# that is substantively present must not be failed because the model
# rewrote its anchor — "签约夜的前夜" for "签约夜前夜", "缺失的碎钻" for
# "缺钻", "协议的终稿" for "协议终稿", "线条不符" for "线条对不上").
# Tolerance is deliberately layered and still conservative: an anchor hits
# on (a) exact substring, (b) the anchor with particles 的/之 removed,
# (c) synonym-normalized substring, (d) >= 50% 2-char-gram coverage for
# anchors of >= 4 chars, or (e) for 2-char anchors, both chars (with 缺
# synonyms 少/丢) appearing in order within a 10-char window.  The
# forbidden-phrase check is NOT loosened this way — it stays strict.
_PARTICLE_CHARS = set("的之")
_SYNONYM_PHRASES = (
    ("不符", "对不上"),
    ("不一致", "对不上"),
    ("对不拢", "对不上"),
    ("不吻合", "对不上"),
)
_SYNONYM_CHARS = {"缺": {"缺", "少", "丢"}}


def _strip_particles(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch not in _PARTICLE_CHARS)


def _normalize_synonyms(text: str) -> str:
    out = text or ""
    for src, dst in _SYNONYM_PHRASES:
        out = out.replace(src, dst)
    return out


def _anchor_hit(
    body_ns: str, body_stripped: str, body_syn: str, anchor: str
) -> bool:
    if not anchor:
        return False
    if anchor in body_ns:
        return True
    stripped = _strip_particles(anchor)
    if stripped and stripped in body_stripped:
        return True
    syn = _normalize_synonyms(anchor)
    if syn and syn in body_syn:
        return True
    if len(anchor) >= 4:
        for source, target in ((syn, body_syn), (stripped, body_stripped)):
            if len(source) < 2:
                continue
            grams = [source[i : i + 2] for i in range(len(source) - 1)]
            if grams and sum(1 for g in grams if g in target) / len(grams) >= 0.5:
                return True
    if len(anchor) == 2:
        first_options = _SYNONYM_CHARS.get(anchor[0], {anchor[0]})
        for haystack in (body_syn, body_ns):
            for i, ch in enumerate(haystack):
                if ch in first_options and anchor[1] in haystack[i + 1 : i + 11]:
                    return True
    return False


def _check_beats(body: str, beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body_ns = _norm_text(body)
    body_stripped = _strip_particles(body_ns)
    body_syn = _normalize_synonyms(body_ns)
    results: list[dict[str, Any]] = []
    for beat in beats:
        found = [
            a for a in beat["anchors"] if _anchor_hit(body_ns, body_stripped, body_syn, a)
        ]
        missing = [
            a
            for a in beat["anchors"]
            if not _anchor_hit(body_ns, body_stripped, body_syn, a)
        ]
        results.append(
            {
                "beat": beat["text"],
                "ok": len(found) >= beat["required"],
                "found": found,
                "missing": missing,
                "found_count": len(found),
                "required": beat["required"],
            }
        )
    return results


def _check_forbidden(body: str, phrases: Any) -> list[dict[str, Any]]:
    """Substring hits for forbidden phrases (full truths / invented events).

    Checked only in code, never injected into a generation prompt (the
    full truths must not reach the model, or it may leak them).  A hit is
    the whole phrase, or any of its clauses of >= 6 chars — so a
    paraphrased revelation still trips the check.
    """
    body_ns = _norm_text(body)
    hits: list[dict[str, Any]] = []
    if not phrases:
        return hits
    if isinstance(phrases, str):
        phrases = [phrases]
    for phrase in phrases:
        phrase_ns = _norm_text(str(phrase))
        if not phrase_ns:
            continue
        if phrase_ns in body_ns:
            hits.append({"phrase": str(phrase), "matched": str(phrase)})
            continue
        clauses = [
            c for c in re.split(r"[，。；：、！？,.!?;:\s]+", str(phrase)) if len(c) >= 6
        ]
        for clause in clauses:
            if _norm_text(clause) in body_ns:
                hits.append({"phrase": str(phrase), "matched": clause})
                break
    return hits


def _check_title_scene(body: str, scene_keywords: Any) -> dict[str, Any]:
    """Is the chapter's main scene where its title says it is?

    Heuristic, documented as such: at least one scene keyword must first
    appear in the opening 60% of the body.  A keyword mentioned only in
    a closing line (the probe's chapter 2: 鉴定室 named only at the end)
    is a mismatch, not a main scene.  With no keywords supplied the
    check is skipped (``checked: False``) rather than guessed.
    """
    if not scene_keywords:
        return {"checked": False, "ok": True, "detail": "no scene keywords supplied"}
    if isinstance(scene_keywords, str):
        scene_keywords = [scene_keywords]
    body_ns = _norm_text(body)
    total = len(body_ns) or 1
    for keyword in scene_keywords:
        kw = _norm_text(str(keyword))
        if not kw:
            continue
        pos = body_ns.find(kw)
        if pos >= 0 and pos <= 0.6 * total:
            return {"checked": True, "ok": True, "keyword": str(keyword),
                    "first_pos_ratio": round(pos / total, 3)}
        return {"checked": True, "ok": False, "keyword": str(keyword),
                "first_pos_ratio": (round(pos / total, 3) if pos >= 0 else None),
                "detail": "scene keyword absent or first appears after 60% of the chapter"}
    return {"checked": False, "ok": True, "detail": "no usable scene keywords"}


def check_chapter(
    body: str,
    *,
    target: int,
    governance_delta: float = DEFAULT_GOVERNANCE_DELTA,
    beats: Any = None,
    forbidden_phrases: Any = None,
    scene_keywords: Any = None,
    dialogue_ratio_range: tuple[float, float] | None = DEFAULT_DIALOGUE_RATIO_RANGE,
) -> dict[str, Any]:
    """Measure one draft against every author gate.

    ``passed`` is True only when length is in tolerance, dialogue share
    is in range (when a range is given), every beat is present, and no
    blocker exists.  Blockers (forbidden revelation, title/scene
    mismatch) are distinguished from fixable failures so callers can
    refuse delivery rather than pass a contaminated chapter on.
    """
    stats = dialogue_stats(body)
    chars = stats["total_chars"]
    lo = target * (1 - governance_delta)
    hi = target * (1 + governance_delta)
    in_tolerance = lo <= chars <= hi
    if dialogue_ratio_range is None:
        dialogue_in_range = True
    else:
        dialogue_in_range = dialogue_ratio_range[0] <= stats["ratio"] <= dialogue_ratio_range[1]
    beat_results = _check_beats(body, normalize_beats(beats))
    missing_beats = [b["beat"] for b in beat_results if not b["ok"]]
    forbidden_hits = _check_forbidden(body, forbidden_phrases)
    title_scene = _check_title_scene(body, scene_keywords)
    blockers: list[str] = []
    for hit in forbidden_hits:
        blockers.append(f"forbidden phrase revealed: {hit['matched']}")
    if title_scene["checked"] and not title_scene["ok"]:
        blockers.append(
            f"title/scene mismatch: main scene keyword "
            f"{title_scene.get('keyword')!r} {title_scene.get('detail')}"
        )
    failures: list[str] = []
    if not in_tolerance:
        failures.append(f"length {chars} outside {int(lo)}-{int(hi)} (target {target})")
    if not dialogue_in_range:
        failures.append(
            f"dialogue ratio {stats['ratio']:.1%} outside "
            f"{dialogue_ratio_range[0]:.0%}-{dialogue_ratio_range[1]:.0%}"
            if dialogue_ratio_range
            else "dialogue ratio out of range"
        )
    if missing_beats:
        failures.append(f"missing beats: {missing_beats}")
    return {
        "chars": chars,
        "dialogue_chars": stats["dialogue_chars"],
        "dialogue_ratio": stats["ratio"],
        "in_tolerance": in_tolerance,
        "dialogue_in_range": dialogue_in_range,
        "beats": beat_results,
        "missing_beats": missing_beats,
        "forbidden_hits": forbidden_hits,
        "title_scene": title_scene,
        "failures": failures,
        "blockers": blockers,
        "passed": in_tolerance and dialogue_in_range and not missing_beats and not blockers,
    }


# ---------------------------------------------------------------------------
# Segmented governance (structure fix for the reprobe failure)
#
# The reprobe proved a full-rewrite governance round cannot grow a chapter:
# repair rounds returned same-length rewrites (+~40 chars each).  A
# governance round therefore works paragraph by paragraph instead:
# split_chapter_by_beats cuts the draft at its beats, each segment gets a
# numeric budget, and each segment is expanded / condensed / converted to
# dialogue on its own.  A small segment with an explicit budget is a task
# the model can actually hit; a 4500-char "revise to near target" is not.
#
# Segment length contract (Pagekin method, mapped onto this pipeline's
# ±20% band; the chapter-level hard gate keeps the probe's char counting
# so the 4500±20% standard is unchanged):
#   budget  = the segment's share of the chapter target (shares sum to it)
#   minimum = ceil(0.8 * budget)  — below this the segment is sent back
#   maximum = floor(1.2 * budget) — reference ceiling only: an over-max
#             segment is kept whole, never truncated at segment level;
#             the chapter-level gate still applies on reassembly.
# Below minimum after one expansion, the segment is NOT rewritten again:
# it gets exactly one forward continuation (segment_continue) that advances
# the next event / action / dialogue, never restates the segment's tail,
# adds about the deficit and never more than the ceiling headroom, and
# closes on a complete sentence / paragraph.
# ---------------------------------------------------------------------------


def _dialogue_in_text(text: str) -> bool:
    for match in re.finditer(r"“([^”]*)”|\"([^\"]*)\"", text or ""):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        if inner and inner.strip():
            return True
    return False


def split_chapter_by_beats(body: str, beats: Any) -> list[dict[str, Any]]:
    """Split a chapter body into beat segments (paragraph level).

    Each segment is ``{"beats": [normalized beat dicts], "text": str,
    "missing": bool}``.  Paragraphs are walked in order; a paragraph that
    first delivers a beat starts a new segment, later paragraphs join the
    current segment, and paragraphs before the first beat form an intro
    segment.  Beats the whole body fails (tolerant check) get a fresh
    ``missing`` segment inserted after the previous beat's segment (or at
    the front when the beat is first) so the expansion round creates them
    instead of re-proving beats that are already present.  Beats the whole
    body passes but no single paragraph delivers are attached to the
    segment holding most of their anchors, never recreated.
    """
    norm = normalize_beats(beats)
    if not norm:
        return [{"beats": [], "text": body or "", "missing": False}]
    paragraphs = [p.strip() for p in re.split(r"\n+", body or "") if p.strip()]
    if not paragraphs:
        return [
            {"beats": [b], "text": "", "missing": True} for b in norm
        ]
    whole = _check_beats(body, norm)
    ok_whole = [c["ok"] for c in whole]
    segments: list[dict[str, Any]] = []
    assigned: set[int] = set()
    current: dict[str, Any] | None = None
    for para in paragraphs:
        checks = _check_beats(para, norm)
        # A paragraph starts a new segment only when it DELIVERS the beat
        # (ok threshold), not on any single shared anchor hit — a shared
        # name gram ("林晚") must not pull two beats into one segment.
        new_beats = [i for i, c in enumerate(checks) if c["ok"] and i not in assigned]
        if new_beats and current is not None:
            current = {"beat_idxs": [], "texts": []}
            segments.append(current)
        if current is None:
            current = {"beat_idxs": [], "texts": []}
            segments.append(current)
        for i in new_beats:
            current["beat_idxs"].append(i)
            assigned.add(i)
        current["texts"].append(para)
    for i, ok in enumerate(ok_whole):
        if ok and i not in assigned:
            best: dict[str, Any] | None = None
            best_count = 0
            for seg in segments:
                cnt = sum(
                    _check_beats(t, [norm[i]])[0]["found_count"] for t in seg["texts"]
                )
                if cnt > best_count:
                    best_count, best = cnt, seg
            target_seg = best if best is not None else segments[-1]
            target_seg["beat_idxs"].append(i)
            assigned.add(i)
    seg_for_beat: dict[int, dict[str, Any]] = {}
    for seg in segments:
        for i in seg["beat_idxs"]:
            seg_for_beat[i] = seg
    final: list[dict[str, Any]] = list(segments)
    for i, ok in enumerate(ok_whole):
        if not ok:
            missing_seg: dict[str, Any] = {"beat_idxs": [i], "texts": [], "missing": True}
            pos: int | None = None
            for j in range(i - 1, -1, -1):
                if j in seg_for_beat:
                    pos = final.index(seg_for_beat[j]) + 1
                    break
            if pos is None:
                final.insert(0, missing_seg)
            else:
                final.insert(pos, missing_seg)
            seg_for_beat[i] = missing_seg
    out: list[dict[str, Any]] = []
    for seg in final:
        idxs = sorted(set(seg["beat_idxs"]))
        out.append(
            {
                "beats": [norm[i] for i in idxs],
                "text": "\n\n".join(seg["texts"]),
                "missing": bool(seg.get("missing", False)),
            }
        )
    return out


def _allocate_segment_budgets(segments: list[dict[str, Any]], target: int) -> list[int]:
    """Equal shares of the chapter target; shares sum to exactly target."""
    n = max(1, len(segments))
    base = target // n
    budgets = [base] * n
    budgets[-1] += target - base * n
    return budgets


def _segment_minimum(budget: int) -> int:
    return -(-4 * budget // 5)  # ceil(0.8 * budget)


def _segment_maximum(budget: int) -> int:
    return 6 * budget // 5  # floor(1.2 * budget), reference ceiling only


def _segments_without_dialogue(body: str, norm_beats: list[dict[str, Any]]) -> list[str]:
    """Beat texts whose segment holds no quoted dialogue scene.

    Only enforced when a dialogue range is set (measure-only callers with
    range None skip it).  A segment with beats but no quoted dialogue is
    a governance failure even when the chapter-level ratio passes: the
    per-beat dialogue-scene rule is paragraph level, not chapter average.
    """
    if not norm_beats:
        return []
    missing: list[str] = []
    for seg in split_chapter_by_beats(body, norm_beats):
        if seg["beats"] and not _dialogue_in_text(seg["text"]):
            missing.extend(b["text"] for b in seg["beats"])
    return missing


def _ends_at_sentence(text: str) -> bool:
    s = (text or "").rstrip()
    if not s:
        return False
    if s[-1] in "。！？…":
        return True
    return len(s) >= 2 and s[-1] in "”\"'" and s[-2] in "。！？…"


def _trim_to_sentence_end(text: str) -> tuple[str, bool]:
    """Cut a continuation after its last sentence terminator, if dangling.

    A continuation that ends mid-sentence is cut back to the last complete
    sentence (keeping a closing quote that follows it).  No terminator at
    all: keep the text whole — trimming to nothing would be worse.
    """
    s = text or ""
    if _ends_at_sentence(s):
        return s, False
    idx = max(s.rfind("。"), s.rfind("！"), s.rfind("？"), s.rfind("…"))
    if idx < 0:
        return s, False
    cut = s[: idx + 1]
    if idx + 1 < len(s) and s[idx + 1] in "”\"":
        cut += s[idx + 1]
    return cut, True


def _truncate_to_chars(text: str, limit: int) -> str:
    """Keep a prefix of ``text`` with at most ``limit`` non-whitespace chars."""
    kept: list[str] = []
    count = 0
    for ch in text or "":
        if count >= limit:
            break
        kept.append(ch)
        if not ch.isspace():
            count += 1
    return "".join(kept)


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
- 目标字数 TARGET_CHARS={target_chars} (允许 ±20%); 必须写满目标字数附近,
  不得提前收尾; 按节拍逐项展开, 每项节拍至少一个对话场景。
- 篇幅合同: 蓝图必需事件全部落实, 不得删除、改写、截断; 篇幅紧张时压缩
  描写与过渡、减少场景数量, 而不是删必需事件; 不得为凑字数增加无关内容。

本章必含节拍 (逐项交付, 缺一不可, 写完自查每一项是否在正文出现):
{beats_section}

对白要求:
{dialogue_section}

防编造 (硬约束):
{fabrication_section}

主场景要求:
{scene_section}

要求: 开头承接上一章, 本章内推进冲突, 结尾留钩子。"""

_SHRINK_PROMPT = """下面这一章太长了。在不丢失关键情节与结尾钩子的前提下缩减: 删冗余描写、
合并重复信息, 把正文缩减到目标字数附近。只输出缩减后的完整正文, 不要解释。

- 目标字数 TARGET_CHARS={target_chars}
- 当前字数: {actual_chars}
{dialogue_note}
原文:
{draft}"""

_REPAIR_PROMPT = """下面这一章未通过成稿检查。请按检查清单逐项修订, 只输出修订后的完整正文,
不要解释。修订不得新增事件与人物关系, 不得提前揭示完整真相, 结尾留钩子。

- 目标字数 TARGET_CHARS={target_chars}; 当前字数: {actual_chars}
- 当前对白占比: {dialogue_ratio:.1%}; 目标对白占比: {dialogue_target}
- 缺失节拍 (必须补进正文, 每项至少一个对话场景): {missing_beats}
- 须删除的揭示内容 (只用于删除, 不得在新稿中复述): {forbidden_hits}
- 主场景要求: {scene_requirement}

原文:
{draft}"""

_SEGMENT_CONTEXT = """本章: {chapter_title}; 本章意图: {intent}; 人物: {character_names}。
只按本章蓝图与上述人物写作, 不新增事件与人物关系, 不提前揭示完整真相。"""

_SEGMENT_EXPAND_PROMPT = """你是长篇小说编辑。只扩写或精简下面这一段正文, 不要标题, 不要解释。
{segment_context}

- 本段节拍: {beats_text}
- 本段原文 (当前 {current_chars} 字):
{segment}

- 本段字数预算 SEGMENT_TARGET_CHARS={budget}; 篇幅合同: 写到
  SEGMENT_MIN_CHARS={minimum}–SEGMENT_TARGET_CHARS={budget} 区间,
  SEGMENT_MAX_CHARS={maximum} 只是参考上限; 少于 minimum 会被退回续写,
  超出 maximum 保留全文但须在下一轮处理; 篇幅紧张时压缩描写与过渡、
  减少场景数量, 而不是删必需事件; 蓝图全部作者任务和必需事件都要落实,
  不得删除、改写、截断, 也不要为凑字数增加无关内容。
- 对白: 本段必须含至少一个对话场景 (引号对话推进情节), 本段对白占比
  尽量接近 {dialogue_mid}; 把心理叙述改成人物对话与动作, 不得交回同等
  篇幅的改写——当前 {current_chars} 字与预算 {budget} 字的差额必须补足或删足。
- 只输出本段正文。"""

_SEGMENT_CREATE_PROMPT = """你是长篇小说作者。只新写下面这一段正文, 不要标题, 不要解释。
{segment_context}

- 本段必须完整交付的节拍: {beats_text}
- 本段字数预算 SEGMENT_TARGET_CHARS={budget}; 篇幅合同: 写到
  SEGMENT_MIN_CHARS={minimum}–SEGMENT_TARGET_CHARS={budget} 区间,
  SEGMENT_MAX_CHARS={maximum} 只是参考上限; 篇幅紧张时压缩描写与过渡、
  减少场景数量, 而不是删必需事件; 不要为凑字数增加无关内容。
- 对白: 本段必须含至少一个对话场景 (引号对话推进情节), 本段对白占比
  尽量接近 {dialogue_mid}; 让冲突在对话里推进。
- 只输出本段正文, 不得新增本节拍之外的事件与人物关系, 不提前揭示完整真相。"""

_SEGMENT_DIALOGUE_PROMPT = """你是长篇小说编辑。把下面这一段的叙述改成对话, 不要标题, 不要解释。
{segment_context}

- 本段节拍: {beats_text}
- 本段原文 (当前 {current_chars} 字):
{segment}

- 本段字数预算 SEGMENT_TARGET_CHARS={budget}; 字数保持在
  SEGMENT_MIN_CHARS={minimum}–SEGMENT_TARGET_CHARS={budget} 区间,
  不得大删大增; 篇幅合同: 必需事件全部落实, 不得删除、改写、截断,
  不得为凑字数增加无关内容。
- 改成对话: 把心理叙述与旁白改成人物对话与动作, 本段必须含至少一个
  对话场景, 本段对白占比尽量接近 {dialogue_mid}; 冲突在对话里推进。
- 只输出本段正文。"""

_SEGMENT_CONTINUE_PROMPT = """你是长篇小说编辑。只输出下面这一段的续写新增部分, 不要重复原文, 不要解释。
{segment_context}

- 已写本段 (当前 {current_chars} 字, 预算 {budget} 字, minimum {minimum} 字,
  maximum {maximum} 字):
{segment}

- 续写补足: 续写约 CONTINUE_NEED_CHARS={need} 字, 新增部分绝不超过
  CONTINUE_CEILING_CHARS={ceiling} 字; 直接向前推进下一事件、动作或对话,
  禁止复述已写末尾 (不得重复最后一句、最后一幕); 收束停在完整句子和
  自然段落末尾; 不得增加无关内容, 不得提前揭示完整真相。"""

_SUMMARY_PROMPT = """用 3-5 句话概括下面这一章: 发生了什么、人物状态有什么变化、留下了什么悬念。
只输出摘要本身。

章节正文 (节选):
{text}"""


def _summarize_text(llm: LlmFn, text: str, op: str) -> str:
    excerpt = text[:4000]
    return _call_llm(llm, _SUMMARY_PROMPT.format(text=excerpt), "summary", op).strip()


def _backup_existing_chapter(book_dir: Path, n: int) -> str | None:
    """Back up the on-disk chapter before it is overwritten, if any.

    Numbered backups under ``chapters/backups/`` (``chapter_XXX.bak-K.md``)
    so rewriting a chapter can never destroy the previous good version
    the way the probe's first chapter 1 draft was lost to an overwrite.
    Returns the backup path, or ``None`` when nothing existed to back up.
    """
    chapter_file = _chapter_path(book_dir, n)
    if not chapter_file.is_file():
        return None
    backup_dir = book_dir / "chapters" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(backup_dir.glob(f"chapter_{n:03d}.bak-*.md"))
    k = len(existing) + 1
    backup_path = backup_dir / f"chapter_{n:03d}.bak-{k}.md"
    backup_path.write_bytes(chapter_file.read_bytes())
    analysis_file = book_dir / "chapters" / f"chapter_{n:03d}.analysis.json"
    if analysis_file.is_file():
        (backup_dir / f"chapter_{n:03d}.analysis.bak-{k}.json").write_bytes(
            analysis_file.read_bytes()
        )
    return str(backup_path)


def write_chapter(
    *,
    book_dir: Path | str,
    llm_fn: LlmFn | None = None,
    chapter: int | None = None,
    target_chars: int | None = None,
    governance_delta: float = DEFAULT_GOVERNANCE_DELTA,
    beats: Any = None,
    forbidden_phrases: Any = None,
    scene_keywords: Any = None,
    max_governance_rounds: int = DEFAULT_MAX_GOVERNANCE_ROUNDS,
    dialogue_ratio_range: tuple[float, float] | None = DEFAULT_DIALOGUE_RATIO_RANGE,
    llm_attempts: int = DEFAULT_LLM_ATTEMPTS,
) -> dict[str, Any]:
    """Write one chapter: pre-write analysis → draft → multi-round governance.

    Governance loop (up to ``max_governance_rounds``): after every draft
    :func:`check_chapter` measures length, dialogue share, beat coverage,
    forbidden revelations and title/scene consistency, and each beat
    segment is checked for at least one dialogue scene (when a dialogue
    range is set).  The loop stops early when every gate passes.
    Blockers (forbidden revelation / title-scene mismatch) get a repair
    round (deletion-focused full rewrite); a pure too-long deviation
    with everything else passing gets a shrink round; every other failure
    — too short, low dialogue, missing beats, or a beat segment without a
    dialogue scene — gets a segmented-expansion round (see
    ``split_chapter_by_beats``): per-segment budgets, per-segment dialogue
    conversion where length is already in band, and a single forward
    continuation per segment still below its minimum.  A full-rewrite
    repair round is never used to grow a chapter: the reprobe proved it
    returns same-length rewrites instead of growing to target.

    Delivery contract: this function returns only a chapter that passes
    every gate.  If the loop caps out with any gate still failing, the
    draft is saved to ``chapters/chapter_XXX.quarantine.md`` (for author
    inspection), the existing chapter file and book progress are left
    untouched, and a :class:`CapabilityError` reports the failures —
    never a silently sub-standard chapter, never continuity pollution.
    Before any generation, an existing chapter is backed up under
    ``chapters/backups/`` so a rewrite can never destroy the previous
    good version, blocked attempt or not.  ``forbidden_phrases`` are
    checked in code only and are never put in a generation prompt; a
    repair prompt names only phrases the model itself already generated,
    marked for deletion.
    """
    op = "write_chapter"
    book_dir = Path(book_dir)
    book = load_book(book_dir, op=op)
    llm = _require_llm(llm_fn, op)
    if not 0 < float(governance_delta) < 0.5:
        raise CapabilityError(
            f"novel.{op}: governance_delta must be in (0, 0.5), got {governance_delta}"
        )
    try:
        max_rounds = int(max_governance_rounds)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"novel.{op}: max_governance_rounds must be an integer") from exc
    if not 1 <= max_rounds <= _MAX_GOVERNANCE_ROUNDS:
        raise CapabilityError(
            f"novel.{op}: max_governance_rounds must be between 1 and "
            f"{_MAX_GOVERNANCE_ROUNDS}, got {max_rounds}"
        )
    try:
        attempts = int(llm_attempts)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"novel.{op}: llm_attempts must be an integer") from exc
    if not 1 <= attempts <= _MAX_LLM_ATTEMPTS:
        raise CapabilityError(
            f"novel.{op}: llm_attempts must be between 1 and {_MAX_LLM_ATTEMPTS}, got {attempts}"
        )
    if dialogue_ratio_range is not None:
        try:
            d_lo, d_hi = float(dialogue_ratio_range[0]), float(dialogue_ratio_range[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise CapabilityError(
                f"novel.{op}: dialogue_ratio_range must be (min, max)"
            ) from exc
        if not (0 <= d_lo <= d_hi <= 1):
            raise CapabilityError(
                f"novel.{op}: dialogue_ratio_range must satisfy 0 <= min <= max <= 1, "
                f"got {dialogue_ratio_range}"
            )
        dialogue_ratio_range = (d_lo, d_hi)
    norm_beats = normalize_beats(beats)
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
    if norm_beats:
        beats_section = "\n".join(
            f"{i}. {b['text']}" for i, b in enumerate(norm_beats, start=1)
        )
    else:
        beats_section = "（按大纲意图推进; 本章意图中的每一项情节都必须在正文出现）"
    if dialogue_ratio_range is not None:
        d_lo, d_hi = dialogue_ratio_range
        dialogue_section = (
            f"本章对白字数 (引号内) 须占全章 {d_lo:.0%}-{d_hi:.0%}"
            f"(约 {int(target * d_lo)}-{int(target * d_hi)} 字); "
            f"把心理叙述改成人物对话与动作, 让冲突在对话里推进, "
            f"不得用大段叙述凑字数或提前收尾。"
        )
        dialogue_note = (
            f"- 扩写/缩减后对白占比仍须落在 {d_lo:.0%}-{d_hi:.0%} 之间; "
            f"扩写优先新增对话场景, 缩减优先删叙述、保留对白与节拍。"
        )
        dialogue_target_text = f"{d_lo:.0%}-{d_hi:.0%}"
    else:
        dialogue_section = "对白与叙事兼顾, 冲突尽量在对话里推进。"
        dialogue_note = ""
        dialogue_target_text = "（不设区间, 仅实测记录）"
    fabrication_section = (
        f"只许使用下列事实与人物, 不得新增事件、不得新增人物关系、"
        f"不得让未登场人物提前登场、不得写出表层说法之外的完整真相。"
        f"人物: {character_names or '（见角色档案）'};"
        f"正史要点: {'；'.join(continuity_facts) or '（暂无）'};"
        f"本章意图与节拍见上。"
    )
    if scene_keywords:
        scene_list = scene_keywords if isinstance(scene_keywords, (list, tuple)) else [scene_keywords]
        scene_section = (
            f"本章主场景必须是: {'、'.join(str(s) for s in scene_list)};"
            f"章标题《{chapter_title}》的主场景与正文主场景一致, 主场景须在开篇即出现"
            f"并贯穿本章, 不得把主场景只放在结尾一笔带过。"
        )
        scene_requirement = f"主场景: {'、'.join(str(s) for s in scene_list)} (开篇即出现并贯穿本章)"
    else:
        scene_section = "（按章标题与大纲意图确定主场景, 全章主场景一致, 不得偏离）"
        scene_requirement = "（按章标题, 主场景一致）"
    analysis = {
        "chapter": n,
        "intent": intent,
        "prev_chapter_summary": prev_summary,
        "continuity_facts": continuity_facts,
        "characters": character_names,
        "target_chars": target,
        "beats": [b["text"] for b in norm_beats],
        "forbidden_phrases": list(forbidden_phrases or []),
        "scene_keywords": list(scene_keywords or []),
        "dialogue_ratio_range": list(dialogue_ratio_range) if dialogue_ratio_range else None,
        "max_governance_rounds": max_rounds,
    }
    (book_dir / "chapters").mkdir(parents=True, exist_ok=True)
    # Back up BEFORE any generation overwrites anything: a blocked or
    # crashed rewrite must still leave the previous good chapter recoverable
    # (the probe's chapter 1 first draft was lost to an overwrite).
    backup_path = _backup_existing_chapter(book_dir, n)
    analysis_path = book_dir / "chapters" / f"chapter_{n:03d}.analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=1), encoding="utf-8")

    def _measure(body_text: str) -> dict[str, Any]:
        return check_chapter(
            body_text,
            target=target,
            governance_delta=governance_delta,
            beats=norm_beats,
            forbidden_phrases=forbidden_phrases,
            scene_keywords=scene_keywords,
            dialogue_ratio_range=dialogue_ratio_range,
        )

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
        beats_section=beats_section,
        dialogue_section=dialogue_section,
        fabrication_section=fabrication_section,
        scene_section=scene_section,
    )
    body, body_attempts = _call_llm_with_attempts(
        llm, body_prompt, "chapter_body", op, attempts=attempts
    )
    body = body.strip()
    checks = _measure(body)
    rounds: list[dict[str, Any]] = [
        {
            "kind": "draft",
            "chars": checks["chars"],
            "dialogue_ratio": round(checks["dialogue_ratio"], 4),
            "attempts": body_attempts,
        }
    ]

    # --- 多轮治理: 逐轮实测, 直至全部门禁通过或触顶 --------------------------
    lo = target * (1 - governance_delta)
    hi = target * (1 + governance_delta)

    def _dialogue_missing(body_text: str) -> list[str]:
        if dialogue_ratio_range is None:
            return []
        return _segments_without_dialogue(body_text, norm_beats)

    def _run_segment_round(current_body: str) -> tuple[str, dict[str, Any]]:
        """One segmented-expansion round: per-segment budget + dialogue
        conversion + at most one forward continuation per short segment."""
        segments = split_chapter_by_beats(current_body, norm_beats)
        budgets = _allocate_segment_budgets(segments, target)
        segment_context = _SEGMENT_CONTEXT.format(
            chapter_title=chapter_title,
            intent=intent or "（按大纲推进）",
            character_names=character_names or "（见角色档案）",
        )
        dialogue_mid = (
            f"{(dialogue_ratio_range[0] + dialogue_ratio_range[1]) / 2:.0%}"
            if dialogue_ratio_range is not None
            else "（不设区间）"
        )
        parts: list[str] = []
        segment_kinds: list[str] = []
        continuations: list[dict[str, Any]] = []
        total_attempts = 0
        for seg, budget in zip(segments, budgets):
            minimum = _segment_minimum(budget)
            maximum = _segment_maximum(budget)
            seg_text = seg["text"]
            seg_chars = char_count(seg_text)
            seg_dialogue = dialogue_stats(seg_text)["ratio"] if seg_text else 0.0
            beats_text = (
                "；".join(b["text"] for b in seg["beats"])
                if seg["beats"]
                else "（无固定节拍, 按上下文推进）"
            )
            if seg["missing"]:
                kind = "segment_expand"
                prompt = _SEGMENT_CREATE_PROMPT.format(
                    segment_context=segment_context,
                    beats_text=beats_text,
                    budget=budget,
                    minimum=minimum,
                    maximum=maximum,
                    dialogue_mid=dialogue_mid,
                )
            elif (
                dialogue_ratio_range is not None
                and minimum <= seg_chars <= maximum
                and seg_dialogue < dialogue_ratio_range[0]
            ):
                kind = "segment_dialogue"
                prompt = _SEGMENT_DIALOGUE_PROMPT.format(
                    segment_context=segment_context,
                    beats_text=beats_text,
                    segment=seg_text,
                    current_chars=seg_chars,
                    budget=budget,
                    minimum=minimum,
                    maximum=maximum,
                    dialogue_mid=dialogue_mid,
                )
            else:
                kind = "segment_expand"
                prompt = _SEGMENT_EXPAND_PROMPT.format(
                    segment_context=segment_context,
                    beats_text=beats_text,
                    segment=seg_text,
                    current_chars=seg_chars,
                    budget=budget,
                    minimum=minimum,
                    maximum=maximum,
                    dialogue_mid=dialogue_mid,
                )
            out, call_attempts = _call_llm_with_attempts(
                llm, prompt, kind, op, attempts=attempts
            )
            total_attempts += call_attempts
            segment_kinds.append(kind)
            out = out.strip()
            out_chars = char_count(out)
            # 续写补足 (唯一一次): 仍低于 minimum 时不全文改写, 只向前续写。
            if out_chars < minimum:
                need = budget - out_chars
                ceiling = maximum - out_chars
                if ceiling > 0:
                    cont_prompt = _SEGMENT_CONTINUE_PROMPT.format(
                        segment_context=segment_context,
                        segment=out,
                        current_chars=out_chars,
                        budget=budget,
                        minimum=minimum,
                        maximum=maximum,
                        need=need,
                        ceiling=ceiling,
                    )
                    cont, cont_attempts = _call_llm_with_attempts(
                        llm, cont_prompt, "segment_continue", op, attempts=attempts
                    )
                    total_attempts += cont_attempts
                    cont = cont.strip()
                    truncated = False
                    if char_count(cont) > ceiling:
                        cont = _truncate_to_chars(cont, ceiling)
                        truncated = True
                    cont, trimmed = _trim_to_sentence_end(cont)
                    before_chars = out_chars
                    if cont:
                        out = (out + "\n\n" + cont).strip()
                    out_chars = char_count(out)
                    continuations.append(
                        {
                            "segment": len(parts),
                            "before_chars": before_chars,
                            "need_chars": need,
                            "ceiling_chars": ceiling,
                            "after_chars": out_chars,
                            "truncated": truncated,
                            "trimmed_to_sentence": trimmed,
                        }
                    )
            parts.append(out)
        return "\n\n".join(p for p in parts if p), {
            "segment_kinds": segment_kinds,
            "segment_budgets": budgets,
            "continuations": continuations,
            "attempts": total_attempts,
        }

    gov_rounds = 0
    while (
        not checks["passed"] or _dialogue_missing(body)
    ) and gov_rounds < max_rounds:
        gov_rounds += 1
        dialogue_missing = _dialogue_missing(body)
        only_too_long = (
            checks["chars"] > hi
            and checks["dialogue_in_range"]
            and not checks["missing_beats"]
            and not checks["blockers"]
            and not dialogue_missing
        )
        if checks["blockers"]:
            kind = "repair"
            prompt = _REPAIR_PROMPT.format(
                target_chars=target,
                actual_chars=checks["chars"],
                dialogue_ratio=checks["dialogue_ratio"],
                dialogue_target=dialogue_target_text,
                missing_beats="；".join(checks["missing_beats"]) or "（无）",
                forbidden_hits="；".join(
                    h["matched"] for h in checks["forbidden_hits"]
                ) or "（无）",
                scene_requirement=scene_requirement,
                draft=body,
            )
            body, call_attempts = _call_llm_with_attempts(
                llm, prompt, kind, op, attempts=attempts
            )
            body = body.strip()
            checks = _measure(body)
            rounds.append(
                {
                    "kind": kind,
                    "chars": checks["chars"],
                    "dialogue_ratio": round(checks["dialogue_ratio"], 4),
                    "attempts": call_attempts,
                }
            )
        elif only_too_long:
            kind = "shrink"
            prompt = _SHRINK_PROMPT.format(
                target_chars=target,
                actual_chars=checks["chars"],
                dialogue_note=dialogue_note,
                draft=body,
            )
            body, call_attempts = _call_llm_with_attempts(
                llm, prompt, kind, op, attempts=attempts
            )
            body = body.strip()
            checks = _measure(body)
            rounds.append(
                {
                    "kind": kind,
                    "chars": checks["chars"],
                    "dialogue_ratio": round(checks["dialogue_ratio"], 4),
                    "attempts": call_attempts,
                }
            )
        else:
            body, seg_info = _run_segment_round(body)
            body = body.strip()
            checks = _measure(body)
            rounds.append(
                {
                    "kind": "segment_expand",
                    "chars": checks["chars"],
                    "dialogue_ratio": round(checks["dialogue_ratio"], 4),
                    "attempts": seg_info["attempts"],
                    "segments": len(seg_info["segment_budgets"]),
                    "segment_budgets": seg_info["segment_budgets"],
                    "segment_kinds": seg_info["segment_kinds"],
                    "continuations": seg_info["continuations"],
                }
            )

    gov_kinds = {r["kind"] for r in rounds[1:]}
    if not gov_kinds:
        governance = "none"
    elif gov_kinds == {"segment_expand"}:
        governance = "segment_expanded"
    elif gov_kinds == {"shrink"}:
        governance = "shrunk"
    elif gov_kinds == {"repair"}:
        governance = "repaired"
    else:
        governance = "governed"
    final_chars = checks["chars"]

    # --- 触顶仍不达标: 隔离 + 打回, 绝不静默交付、不污染进度 ------------------
    # A chapter that passes the chapter-level gates but still leaves a beat
    # segment without a dialogue scene is blocked too: the per-beat
    # dialogue rule is paragraph level, not chapter average.
    dialogue_missing_final = _dialogue_missing(body)
    if not checks["passed"] or dialogue_missing_final:
        quarantine_path = book_dir / "chapters" / f"chapter_{n:03d}.quarantine.md"
        quarantine_path.write_text(
            f"<!-- BLOCKED chapter: {n}; target_chars: {target}; "
            f"final_chars: {final_chars}; governance: {governance}; "
            f"failures: {checks['failures']}; blockers: {checks['blockers']} -->\n\n"
            + body
            + "\n",
            encoding="utf-8",
        )
        analysis["checks"] = checks
        analysis["rounds"] = rounds
        analysis["status"] = "blocked"
        analysis["quarantine_path"] = str(quarantine_path)
        analysis["backup_path"] = backup_path
        analysis_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        raise CapabilityError(
            f"novel.{op}: chapter {n} blocked after {gov_rounds} governance "
            f"round(s) (cap {max_rounds}): failures={checks['failures']}; "
            f"beats_without_dialogue={dialogue_missing_final}; "
            f"blockers={checks['blockers']}; draft saved to {quarantine_path}; "
            f"existing chapter and book progress untouched — fix the beats / "
            f"prompts / forbidden list and retry this chapter"
        )

    # --- 落盘章节 (旧章已在生成前备份, 见上) + 更新 book.json 进度 --------------
    chapter_file = _chapter_path(book_dir, n)
    header = (
        f"# 第{n}章 {chapter_title}\n\n"
        f"<!-- chapter: {n}; target_chars: {target}; final_chars: {final_chars}; "
        f"governance: {governance}; dialogue_ratio: {checks['dialogue_ratio']:.3f}; "
        f"beats_ok: {len(checks['beats']) - len(checks['missing_beats'])}/{len(checks['beats'])} -->\n\n"
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
            "checks": checks,
            "backup_path": backup_path,
            "in_tolerance": True,
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
        "dialogue_ratio": checks["dialogue_ratio"],
        "dialogue_chars": checks["dialogue_chars"],
        "checks": checks,
        "backup_path": backup_path,
        "in_tolerance": True,
        "status": "ok",
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
    beats: Any = None,
    forbidden_phrases: Any = None,
    scene_keywords: Any = None,
    max_governance_rounds: int = DEFAULT_MAX_GOVERNANCE_ROUNDS,
    dialogue_ratio_range: tuple[float, float] | None = DEFAULT_DIALOGUE_RATIO_RANGE,
    llm_attempts: int = DEFAULT_LLM_ATTEMPTS,
) -> dict[str, Any]:
    """Import an existing work, build continuation context, write the next chapter.

    The imported chapters are preserved verbatim under ``chapters/`` and
    recorded in book.json; the continuation context (last-chapter summary +
    character table) lands in ``continuation.json``; the new chapter is then
    produced through :func:`write_chapter` — the same path as a from-scratch
    book, including multi-round governance and its delivery contract.
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
        book_dir=book_dir,
        llm_fn=llm,
        chapter=imported + 1,
        target_chars=target,
        beats=beats,
        forbidden_phrases=forbidden_phrases,
        scene_keywords=scene_keywords,
        max_governance_rounds=max_governance_rounds,
        dialogue_ratio_range=dialogue_ratio_range,
        llm_attempts=llm_attempts,
    )
    return {
        "book_dir": str(book_dir),
        "book_json": str(book_dir / "book.json"),
        "imported_chapters": imported,
        "continuation_path": str(continuation_path),
        "continuation": continuation,
        "new_chapter": new_chapter,
    }
