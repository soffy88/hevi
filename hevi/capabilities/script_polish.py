"""剧本打磨门 — ``story.script_polish``。

夜班笔记 E1 的教训：画面（清晰度/连贯性/人物一致性）可以过关，剧本却讲不清
故事——关键信息全压在观众看不见的纸条内容上、揭晓拖到下一集，台词只剩碎片，
夜次还会跳号。本门就是在剧本进分镜/生成之前，把这类问题拦下来。

注册一个能力 ``story.script_polish``（CAPABILITY_CONTRACT.md；先例
``.storybible`` / ``.novelpipeline``），输入一份单集剧本（结构化 ``scenes``
优先，Markdown ``screenplay`` 亦可），输出打磨报告（``polish_report.json``）
＋放行 verdict：**任一 blocker 存在即 ``passed=false``，不许进分镜**。

四项检查（``mode``）：

* ``info_audit``（信息层审计，核心）：作者在 ``intent.must_know`` 里列出本集
  必须向观众交付的关键事实（每条配关键词）。确定性部分：全集动作＋对白文本
  里一个关键词都搜不到 → blocker（缺席是硬证据；出现仅代表提及，不等于
  交付成立）。``full`` 模式追加冷读：LLM 只读剧本（不给前提/意图）复述故事，
  复述里缺失的 must_know 事实 → major；冷读提出的未解问题按重要性计入。
* ``dialogue``（对白打磨）：空对白 blocker；对白人物不在本场人物表 major；
  纯应答词（嗯/啊/哦/好/行…）minor；跨场逐字重复对白 minor。``full`` 模式
  追加 LLM 逐条功能判定（争取/回避/试探/施压/告知/揭示/无功能）＋口语度＋
  改写建议，无功能或不口语 → major。
* ``continuity``（逻辑连续性）：夜次标记（第 X 夜，取自 ``time_marker`` 或
  动作文本）按场次顺序出现跳号（如第二夜→第四夜）或倒退 → major；无动作
  无对白的空场 major；动作文本高度相似的 routine 在非连续场重复出现
  （SequenceMatcher ≥ 0.5）→ minor（重复未升级）。
* ``silent``（静音可懂，Soffy 永久标准在剧本层的对应门）：去掉对白后，动作
  描述过短（<12 字）或不含人物动作字 → minor。``full`` 模式追加 LLM 逐场
  静音复述：去掉对白就看不懂的场 → major。

``mode="deterministic"``（默认，零成本）：只跑确定性部分，LLM 检查记入
``skipped``，verdict 只对确定性 blocker 负责——报告里明示覆盖范围，绝不
把“没查”说成“通过”。``mode="full"`` 需要 LLM：优先注入的 ``llm_fn``，
否则默认 Monid 后端（``hevi.llm.monid_chat``，与 ``.novelpipeline`` 同路，
按次计费）；两者皆无 → :class:`CapabilityError`，绝不假装成功。LLM 输出
无法解析成约定 JSON → 同样抛错，不把糊涂账记成通过。

LLM 契约：``llm_fn(prompt, kind) -> str``，kind 取
``script_polish_cold_reader`` / ``script_polish_silent`` /
``script_polish_dialogue``；测试用注入的假函数，离线零成本。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
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
_llm_fn: Any = None


def set_llm_fn(fn: Any) -> None:
    """Install a process-wide ``llm_fn(prompt, kind) -> str`` for full mode."""
    global _llm_fn
    _llm_fn = fn


def _default_llm_fn(prompt: str, kind: str) -> str:
    """Default backend: Monid chat (same route as novelpipeline)."""
    from hevi.llm import monid_chat

    return monid_chat.chat_for_kind_sync(prompt, kind)


def _resolve_llm_fn() -> Any:
    """Injected fn wins; else Monid when its key resolves; else refuse."""
    if _llm_fn is not None:
        return _llm_fn
    from hevi.llm import monid_chat

    if monid_chat.monid_key_available():
        return _default_llm_fn
    raise CapabilityError(
        "story.script_polish: full mode needs an LLM: install one with "
        "hevi.capabilities.script_polish.set_llm_fn(llm_fn) or set "
        f"MONID_API_KEY ({monid_chat.missing_key_hint()})"
    )
# ---------------------------------------------------------------------------
# Finding helpers + text utils
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"blocker": 3, "major": 2, "minor": 1}


def _finding(
    check: str,
    severity: str,
    issue: str,
    suggestion: str,
    scene_id: str | None = None,
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "scene_id": scene_id,
        "issue": issue,
        "suggestion": suggestion,
    }


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_NIGHT_RE = re.compile(r"第([一二三四五六七八九十\d]+)夜")


def _night_numbers(text: str) -> list[int]:
    """Extract night numbers (in order) from a text, e.g. 第二夜 → 2."""
    out = []
    for m in _NIGHT_RE.finditer(text or ""):
        tok = m.group(1)
        if tok.isdigit():
            out.append(int(tok))
        elif tok in _CN_NUM:
            out.append(_CN_NUM[tok])
        elif tok == "十一":
            out.append(11)
        elif tok == "十二":
            out.append(12)
    return out


_PUNCT = "，。、；：？！·…—「」『』（）《》\"' \t\n"


def _norm_text(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch not in _PUNCT)


# 动词词表（子串匹配）：单字动词＋常见双字动词。确定性代理宁可放过（漏报）
# 也不要冤枉正常场面——“来了/整理/完成”这类日常动作必须算动作。
_VERB_WORDS = (
    "看", "走", "拿", "放", "开", "合", "推", "拉", "递", "擦", "读", "写",
    "站", "坐", "转", "望", "停", "追", "跑", "跳", "喊", "抱", "扶", "摸",
    "点", "翻", "倒", "躺", "靠", "摇", "摆", "舞", "唱", "吃", "喝", "睡",
    "醒", "出", "入", "回", "过", "到", "向", "对", "给", "跟", "随", "扔",
    "塞", "捡", "挂", "摘", "来", "去", "笑", "哭", "揉", "敲",
    "推门", "进门", "出门", "离开", "回来", "抬头", "低头", "抬眼", "望向",
    "看向", "走向", "跑向", "坐下", "站起", "起身", "转身", "回头", "点头",
    "摇头", "摆手", "招手", "挥手", "整理", "收拾", "完成", "出现", "发生",
    "注视", "取出", "放回", "展开", "折好", "合上", "打开", "推开", "递给",
    "接过", "靠在", "出神", "目送", "敲着", "揉了",
)

_BACKCHANNELS = {"嗯", "啊", "哦", "好", "行", "是", "对", "喂", "呀", "哎"}


def _full_script_text(scenes: list[dict[str, Any]]) -> str:
    parts = []
    for sc in scenes:
        parts.append(sc.get("action", ""))
        for line in sc.get("dialogue", []):
            parts.append(line.get("text", ""))
    return "\n".join(p for p in parts if p)


def _render_scenes_text(scenes: list[dict[str, Any]], *, with_dialogue: bool) -> str:
    """Render scenes as plain text for LLM prompts."""
    blocks = []
    for sc in scenes:
        lines = [f"[{sc.get('scene_id', '?')}] {sc.get('header', '')}"]
        if sc.get("action"):
            lines.append(f"画面：{sc['action']}")
        if with_dialogue:
            for line in sc.get("dialogue", []):
                lines.append(f"{line.get('speaker', '')}：{line.get('text', '')}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
# ---------------------------------------------------------------------------
# Scene normalization + best-effort Markdown parser
# ---------------------------------------------------------------------------

_SCENE_HEAD_RE = re.compile(
    r"^(?:#{1,3}\s*)?(?:INT|EXT|内景|外景|内\.|外\.|第[一二三四五六七八九十\d]+场).*$"
)
_DIALOGUE_RE = re.compile(r"^([^，。、；：？！·…—\s]{1,8})[：:]\s*(.+)$")
# Lines like 画面：/动作： are stage directions, not spoken lines.
_NON_SPEAKER_PREFIXES = {"画面", "动作", "场景", "转场"}


def _normalize_scene(raw: dict[str, Any], idx: int) -> dict[str, Any]:
    scene_id = str(raw.get("scene_id") or f"S{idx + 1:02d}")
    dialogue = []
    for line in raw.get("dialogue", []) or []:
        if isinstance(line, dict):
            dialogue.append(
                {"speaker": str(line.get("speaker", "")), "text": str(line.get("text", ""))}
            )
    return {
        "scene_id": scene_id,
        "header": str(raw.get("header", raw.get("scene", ""))),
        "time_marker": str(raw.get("time_marker", "")),
        "characters": [str(c) for c in (raw.get("characters", []) or [])],
        "action": str(raw.get("action", "")),
        "dialogue": dialogue,
    }


def _parse_markdown_screenplay(text: str) -> list[dict[str, Any]]:
    """Best-effort Markdown → scenes. Structured ``scenes`` input is preferred.

    Splits on INT/EXT-style headers or ``第X场`` markers; within a scene,
    ``Name：text`` lines become dialogue, everything else accumulates as action.
    """
    scenes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def _flush() -> None:
        if current is not None:
            current["action"] = " ".join(current["_action_parts"]).strip()
            del current["_action_parts"]
            scenes.append(current)

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SCENE_HEAD_RE.match(line):
            _flush()
            current = {
                "scene_id": f"S{len(scenes) + 1:02d}",
                "header": line,
                "time_marker": "",
                "characters": [],
                "action": "",
                "dialogue": [],
                "_action_parts": [],
            }
            continue
        if current is None:
            current = {
                "scene_id": "S01",
                "header": "",
                "time_marker": "",
                "characters": [],
                "action": "",
                "dialogue": [],
                "_action_parts": [],
            }
        m = _DIALOGUE_RE.match(line)
        if m and len(m.group(1)) <= 8 and m.group(1) not in _NON_SPEAKER_PREFIXES:
            current["dialogue"].append({"speaker": m.group(1), "text": m.group(2)})
            if m.group(1) not in current["characters"]:
                current["characters"].append(m.group(1))
        else:
            current["_action_parts"].append(line)
    _flush()
    return scenes


def _scenes_from_params(params: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = params.get("scenes")
    if scenes:
        if not isinstance(scenes, list):
            raise CapabilityError("story.script_polish: 'scenes' must be a list")
        return [_normalize_scene(s, i) for i, s in enumerate(scenes)]
    screenplay = params.get("screenplay")
    if screenplay:
        scenes = _parse_markdown_screenplay(str(screenplay))
        if not scenes:
            raise CapabilityError(
                "story.script_polish: could not parse any scene from 'screenplay'"
            )
        return scenes
    raise CapabilityError(
        "story.script_polish: provide 'scenes' (structured) or 'screenplay' (Markdown)"
    )


# ---------------------------------------------------------------------------
# Check 1 — information-layer audit
# ---------------------------------------------------------------------------


def _check_info(
    scenes: list[dict[str, Any]],
    intent: dict[str, Any],
    *,
    llm_fn: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Deterministic must_know keyword audit + (full mode) cold-reader audit."""
    findings: list[dict[str, Any]] = []
    skipped: list[str] = []
    full_text = _full_script_text(scenes)
    must_know = intent.get("must_know", []) or []
    for fact in must_know:
        text = str(fact.get("fact", ""))
        keywords = [str(k) for k in fact.get("keywords", []) or []]
        if not keywords:
            findings.append(
                _finding(
                    "info_audit",
                    "major",
                    f"关键事实未配关键词，无法审计：{text}",
                    "给这条事实配 1–3 个观众应在对白/动作里听到的关键词（如人名、数字、关系词）。",
                )
            )
            continue
        if not any(kw and kw in full_text for kw in keywords):
            findings.append(
                _finding(
                    "info_audit",
                    "blocker",
                    f"本集未向观众交付关键信息：{text}（关键词 {keywords} 全集未出现）",
                    "要么在本集用对白/旁白/字幕/看得见的行动把这条信息交代出来，要么"
                    "在本集先立一个观众可感知的钩子（明确“有个未解之谜”），不能让"
                    "观众在完全不知道这条信息存在的情况下看完本集。",
                )
            )
    if llm_fn is None:
        skipped.append("cold_reader")
        return findings, skipped
    prompt = (
        "你是第一次读这个剧本的观众，没有看过任何梗概、前情或作者意图。\n"
        "只根据下面剧本复述这个故事，并列出你无法回答的关键问题。\n"
        "只输出 JSON，不要多余文字：\n"
        '{"retelling": "一句话到一段话复述：主角是谁、想要什么、发生了什么、为什么重要", '
        '"unanswered": [{"question": "问题", "importance": "high|low"}]}\n\n'
        + _render_scenes_text(scenes, with_dialogue=True)
    )
    raw = llm_fn(prompt, "script_polish_cold_reader")
    try:
        data = json.loads(raw)
        retelling = str(data.get("retelling", ""))
        unanswered = data.get("unanswered", []) or []
    except (ValueError, AttributeError) as exc:
        raise CapabilityError(
            "story.script_polish: cold-reader LLM output is not valid JSON: "
            f"{exc}; raw excerpt: {raw[:300]!r}"
        ) from exc
    for fact in must_know:
        keywords = [str(k) for k in fact.get("keywords", []) or []]
        if keywords and not any(kw and kw in retelling for kw in keywords):
            findings.append(
                _finding(
                    "info_audit",
                    "major",
                    f"冷读复述缺失关键信息：{fact.get('fact', '')}",
                    "冷读观众复述不出这条信息，说明它在本集没有真正落地（只提及"
                    "关键词不算交付）；用对白或看得见的行动在本集交代它。",
                )
            )
    for q in unanswered:
        if not isinstance(q, dict):
            continue
        importance = str(q.get("importance", "low"))
        findings.append(
            _finding(
                "info_audit",
                "major" if importance == "high" else "minor",
                f"冷读未解问题（{importance}）：{q.get('question', '')}",
                "在剧本里给这个问题一个本集内的着落（回答、或明确立为钩子），"
                "不要让观众带着无从追问的困惑看完。",
            )
        )
    return findings, skipped


# ---------------------------------------------------------------------------
# Check 2 — dialogue polish (deterministic part)
# ---------------------------------------------------------------------------


def _check_dialogue_deterministic(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen_lines: dict[str, str] = {}
    for sc in scenes:
        sid = sc["scene_id"]
        characters = set(sc["characters"])
        for line in sc["dialogue"]:
            speaker = line.get("speaker", "")
            text = line.get("text", "")
            norm = _norm_text(text)
            if not norm:
                findings.append(
                    _finding(
                        "dialogue",
                        "blocker",
                        "空对白：有说话人但无台词文本。",
                        "补写台词，或删掉这条对白。",
                        sid,
                    )
                )
                continue
            if characters and speaker and speaker not in characters:
                findings.append(
                    _finding(
                        "dialogue",
                        "major",
                        f"对白人物未列入本场人物表：{speaker} 说“{text}”，"
                        f"但本场人物表为 {sorted(characters)}。",
                        "把说话人补进本场人物表，或检查这句是否放错了场。",
                        sid,
                    )
                )
            if norm in _BACKCHANNELS:
                findings.append(
                    _finding(
                        "dialogue",
                        "minor",
                        f"纯应答词，无信息/关系推进：{speaker}“{text}”",
                        "除非是刻意停顿的节拍，否则让这句带上信息、态度或关系变化。",
                        sid,
                    )
                )
            if norm in seen_lines and seen_lines[norm] != sid:
                findings.append(
                    _finding(
                        "dialogue",
                        "minor",
                        f"跨场逐字重复对白：“{text}”（首见 {seen_lines[norm]}，重现 {sid}）",
                        "重复若非刻意回环/母题，应改写或删掉。",
                        sid,
                    )
                )
            else:
                seen_lines.setdefault(norm, sid)
    return findings


def _check_dialogue_llm(
    scenes: list[dict[str, Any]], llm_fn: Any
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = []
    for sc in scenes:
        for line in sc["dialogue"]:
            lines.append(
                {"scene_id": sc["scene_id"], "speaker": line.get("speaker", ""),
                 "text": line.get("text", "")}
            )
    if not lines:
        return findings
    prompt = (
        "你是剧本打磨师。逐条判定下面对白的功能与口语度，只输出 JSON：\n"
        '{"lines": [{"scene_id": "", "speaker": "", "text": "", '
        '"function": "争取|回避|试探|施压|告知|揭示|无功能", '
        '"speakable": true|false, "rewrite": "改写建议，无问题则为空"}]}\n\n'
        + json.dumps(lines, ensure_ascii=False, indent=1)
    )
    raw = llm_fn(prompt, "script_polish_dialogue")
    try:
        data = json.loads(raw)
        judged = data.get("lines", []) or []
    except (ValueError, AttributeError) as exc:
        raise CapabilityError(
            "story.script_polish: dialogue LLM output is not valid JSON: "
            f"{exc}; raw excerpt: {raw[:300]!r}"
        ) from exc
    for item in judged:
        if not isinstance(item, dict):
            continue
        func = str(item.get("function", ""))
        speakable = item.get("speakable", True)
        rewrite = str(item.get("rewrite", "") or "")
        if func == "无功能" or speakable is False:
            findings.append(
                _finding(
                    "dialogue",
                    "major",
                    f"对白无功能或不口语：{item.get('speaker', '')}“{item.get('text', '')}”"
                    f"（功能={func}，口语={speakable}）",
                    f"改写建议：{rewrite}" if rewrite else
                    "让这句带上争取/回避/试探/施压/告知/揭示中的至少一种功能，并改成人物会说出口的话。",
                    str(item.get("scene_id", "")) or None,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Check 3 — continuity
# ---------------------------------------------------------------------------


def _check_continuity(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    # Night-marker sequence (from time_marker or action text).
    night_seq: list[tuple[str, int]] = []
    for sc in scenes:
        nums = _night_numbers(sc.get("time_marker", ""))
        if not nums:
            nums = _night_numbers(sc.get("action", ""))
        if nums:
            night_seq.append((sc["scene_id"], nums[0]))
    prev_sid, prev_n = None, None
    for sid, n in night_seq:
        if prev_n is not None:
            if n < prev_n:
                findings.append(
                    _finding(
                        "continuity",
                        "major",
                        f"夜次倒退：{prev_sid} 为第 {prev_n} 夜，{sid} 却为第 {n} 夜。",
                        "检查夜次标注是否写错，或补一场交代时间回溯的戏。",
                        sid,
                    )
                )
            elif n > prev_n + 1:
                missing = "、".join(f"第 {m} 夜" for m in range(prev_n + 1, n))
                findings.append(
                    _finding(
                        "continuity",
                        "major",
                        f"夜次跳号：{prev_sid}（第 {prev_n} 夜）后直接是 {sid}（第 {n} 夜），"
                        f"缺 {missing}。",
                        "要么补上缺失夜次的戏，要么在跳号处给观众一个明确的时间标记"
                        "（字幕/对白/钟表），否则重复动作看起来像重复而非推进。",
                        sid,
                    )
                )
        prev_sid, prev_n = sid, n
    # Empty scenes + routine repetition without escalation.
    actions: list[tuple[str, str]] = []
    for sc in scenes:
        sid = sc["scene_id"]
        action = sc.get("action", "")
        if not _norm_text(action) and not sc["dialogue"]:
            findings.append(
                _finding(
                    "continuity",
                    "major",
                    "空场：无动作描述也无对白。",
                    "补一场有可拍动作或叙事事实的戏，或删掉本场。",
                    sid,
                )
            )
        actions.append((sid, _norm_text(action)))
    for i in range(len(actions)):
        for j in range(i + 2, len(actions)):
            a_sid, a_text = actions[i]
            b_sid, b_text = actions[j]
            if len(a_text) < 12 or len(b_text) < 12:
                continue
            ratio = difflib.SequenceMatcher(None, a_text, b_text).ratio()
            if ratio >= 0.6:
                findings.append(
                    _finding(
                        "continuity",
                        "minor",
                        f"routine 重复未升级：{a_sid} 与 {b_sid} 动作文本相似度 {ratio:.2f}，"
                        "两次出现但无明确新信息/情绪递进。",
                        "让后一次出现带上变化（夜次、情绪、关系、风险任一递进），"
                        "或合并/删掉其中一次。",
                        b_sid,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Check 4 — silent legibility (deterministic proxy; LLM in full mode)
# ---------------------------------------------------------------------------


def _check_silent_deterministic(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sc in scenes:
        sid = sc["scene_id"]
        action = sc.get("action", "")
        norm = _norm_text(action)
        if len(norm) < 12:
            findings.append(
                _finding(
                    "silent",
                    "minor",
                    "动作描述过短，静音下无叙事信息。",
                    "把这场戏的叙事动作写进画面（人物＋动作＋变化），不要只写氛围。",
                    sid,
                )
            )
        elif not any(w in norm for w in _VERB_WORDS):
            findings.append(
                _finding(
                    "silent",
                    "minor",
                    "纯氛围/状态描述，无人物动作，静音下不推进故事。",
                    "给这场戏一个看得见的动作或变化，否则静音观众只能看到一张氛围图。",
                    sid,
                )
            )
    return findings


def _check_silent_llm(
    scenes: list[dict[str, Any]], llm_fn: Any
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    prompt = (
        "你是静音验片员。下面每场戏只给动作描述（已去掉对白）。逐场判断："
        "只看画面能否看懂这场戏在讲什么。只输出 JSON：\n"
        '{"scenes": [{"scene_id": "", "understandable_without_dialogue": true|false, '
        '"missing": "看不懂时缺失的关键信息，无问题则为空"}]}\n\n'
        + _render_scenes_text(scenes, with_dialogue=False)
    )
    raw = llm_fn(prompt, "script_polish_silent")
    try:
        data = json.loads(raw)
        judged = data.get("scenes", []) or []
    except (ValueError, AttributeError) as exc:
        raise CapabilityError(
            "story.script_polish: silent LLM output is not valid JSON: "
            f"{exc}; raw excerpt: {raw[:300]!r}"
        ) from exc
    for item in judged:
        if not isinstance(item, dict):
            continue
        if item.get("understandable_without_dialogue") is False:
            findings.append(
                _finding(
                    "silent",
                    "major",
                    f"静音下看不懂：{item.get('missing', '')}",
                    "把缺失的信息放进画面（动作、道具、调度）或补一句交代性对白/旁白，"
                    "不要只靠对白或后续集揭晓。",
                    str(item.get("scene_id", "")) or None,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Render + registration
# ---------------------------------------------------------------------------

_SCENE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene_id": {"type": "string"},
        "header": {"type": "string"},
        "scene": {"type": "string"},
        "time_marker": {"type": "string"},
        "characters": {"type": "array", "items": {"type": "string"}},
        "action": {"type": "string"},
        "dialogue": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
    },
}

_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "premise": {"type": "string"},
        "intent": {
            "type": "object",
            "properties": {
                "must_know": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string"},
                            "keywords": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["fact"],
                    },
                },
            },
        },
        "scenes": {"type": "array", "items": _SCENE_SCHEMA},
        "screenplay": {"type": "string"},
        "mode": {"type": "string", "enum": ["deterministic", "full"]},
    },
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "polish_report.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    mode = params.get("mode", "deterministic")
    if mode not in ("deterministic", "full"):
        raise CapabilityError(f"story.script_polish: unsupported mode: {mode!r}")
    scenes = _scenes_from_params(params)
    intent = params.get("intent", {}) or {}
    llm_fn = _resolve_llm_fn() if mode == "full" else None

    findings: list[dict[str, Any]] = []
    skipped: list[str] = []
    checks: dict[str, Any] = {}

    info_findings, info_skipped = _check_info(scenes, intent, llm_fn=llm_fn)
    findings.extend(info_findings)
    skipped.extend(info_skipped)
    checks["info_audit"] = {
        "passed": not any(f["severity"] == "blocker" for f in info_findings),
        "skipped": info_skipped,
    }

    dlg_findings = _check_dialogue_deterministic(scenes)
    if llm_fn is not None:
        dlg_findings.extend(_check_dialogue_llm(scenes, llm_fn))
    else:
        skipped.append("dialogue_llm")
    findings.extend(dlg_findings)
    checks["dialogue"] = {
        "passed": not any(f["severity"] == "blocker" for f in dlg_findings),
        "skipped": ["dialogue_llm"] if llm_fn is None else [],
    }

    cont_findings = _check_continuity(scenes)
    findings.extend(cont_findings)
    checks["continuity"] = {
        "passed": not any(f["severity"] == "blocker" for f in cont_findings),
        "skipped": [],
    }

    silent_findings = _check_silent_deterministic(scenes)
    if llm_fn is not None:
        silent_findings.extend(_check_silent_llm(scenes, llm_fn))
    else:
        skipped.append("silent_llm")
    findings.extend(silent_findings)
    checks["silent"] = {
        "passed": not any(f["severity"] == "blocker" for f in silent_findings),
        "skipped": ["silent_llm"] if llm_fn is None else [],
    }

    counts = {"blocker": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    passed = counts["blocker"] == 0

    payload = {
        "title": params.get("title", ""),
        "premise": params.get("premise", ""),
        "mode": mode,
        "scene_count": len(scenes),
        "passed": passed,
        "counts": counts,
        "checks": checks,
        "skipped": sorted(set(skipped)),
        "findings": findings,
    }
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_script_polish_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.script_polish",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,  # audit call only; LLM cost is per-call (full mode)
            render=_render,
            has_media_output=False,
            description=(
                "剧本打磨门：单集剧本进分镜/生成之前的四项检查——信息层审计"
                "（本集必须交付的关键事实是否真落地，缺席即 blocker）、对白打磨"
                "（空对白/人物未列入/纯应答词/重复）、逻辑连续性（夜次跳号或倒退、"
                "空场、routine 重复未升级）、静音可懂（去掉对白后画面是否仍讲故事）。"
                "任一 blocker 即 passed=false，不许进分镜。deterministic 模式零成本；"
                "full 模式追加 LLM 冷读/静音复述/对白功能判定（可注入 llm_fn，"
                "否则走 Monid 后端，无 LLM 时直接报错不假装成功）。"
            ),
            line="script_polish",
        )
    )
    return ["story.script_polish"]


register_script_polish_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.script_polish on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--mode", default=None, help="override params mode")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.mode:
        params["mode"] = args.mode
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
