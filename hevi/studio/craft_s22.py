"""S22 出片方法 —— 镜头路线、报价、阶段闸门、自检、审稿、声音、许可、栏目模板。

只借一篇文章的方法，不抄提示词原文。所有能力都做成“节点 + 自检”：

* 镜头路线：每镜先判 代码 / Blender / 生成 / 用户素材，代码能做好就优先代码；
  每镜给出模型、秒数、金额与预计渲染时间，全片报价和成本账本一起落盘。
* 阶段闸门：一句话主旨 → 脚本分镜（事实带出处）→ 出样 → 最难一镜低清试做 →
  整片 → 交付清单；每道闸门都可“一键跳过”，但跳过会写进审稿记录。
* 独立审稿：脚本与成片单独一次 LLM 调用（与写稿不同的 system prompt/上下文），
  只列问题；没有免费通道时退回确定性规则，不假装已经审过。
* 规则自检：画面文字后期叠加；生成提示词避开易误解颜色词；同类图表 ≤3 次；
  一句一个主视觉；代码动画先低帧率试跑；3D 一次只跑一个渲染。
* 声音：无旁白先定整首配乐再按拍点剪；前 1 秒必须有声；音乐撑到黑场淡出；
  TTS 后用 faster-whisper 回转对稿；额外导出无 BGM 版。
* 许可审计：把线上实际在用的 TTS / 配乐 / 模型列清楚，无法确认商用的标红并给替换。
* 栏目模板：知识讲解固定底色/光效/字体/字幕速度（每秒 6–7 字），只换标题、比喻、标签。
* 标题/封面：标题必须回答“看完得到什么”，给 3 个候选；封面单独生成，不截帧。

本模块默认零网络、零付费、零新依赖；``allow_llm=True`` 才可能走既有免费 LLM 通道。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 镜头路线
# ---------------------------------------------------------------------------

ROUTE_META: dict[str, dict[str, Any]] = {
    "code": {
        "label": "代码动画",
        "model": "hevi-code/ffmpeg",
        "render_s_per_shot": 8.0,
        "note": "图形、图表、文字动效都在代码里画，零 API 成本。",
    },
    "blender": {
        "label": "Blender",
        "model": "blender/eevee",
        "render_s_per_shot": 45.0,
        "note": "3D 拆解、场景复原、地图路线；一次只跑一个渲染。",
    },
    "generation": {
        "label": "生成",
        "model": "",
        "render_s_per_shot": 22.0,
        "note": "写实人脸、动物、真实运镜；先定妆图再关键帧。",
    },
    "user_media": {
        "label": "用户素材",
        "model": "user-upload",
        "render_s_per_shot": 3.0,
        "note": "用户上传的实拍素材，只做剪辑与包装。",
    },
    "mixed": {
        "label": "代码 + 生成",
        "model": "mixed",
        "render_s_per_shot": 18.0,
        "note": "空镜生成、信息图代码；按镜拆开计价。",
    },
}

#: 形式默认生成模型（只用于报价；离线预览一律 ¥0）。
_FORMAT_GENERATION_MODEL: dict[str, str] = {
    "live_drama": "wan_2_7",
    "comic_drama": "wan_2_7",
    "history_scene": "wan_2_7",
    "digital_human": "h3_local",
    "animation": "h3_local",
    "explainer": "h3_local",
    "material_cut": "",
}

_3D_WORDS = ("3d", "3D", "blender", "拆解", "爆炸图", "建模", "场景复原", "地图路线")
_HUMAN_WORDS = ("人物", "主角", "人脸", "特写", "写实", "演员", "口播", "出镜", "动物")
_CHART_WORDS = ("时间线", "数字", "图表", "数据", "对比", "地图", "流程")


def usd_cny_rate() -> float:
    try:
        return float(os.environ.get("HEVI_USD_CNY", "7.2"))
    except ValueError:
        return 7.2


def model_price_cny_per_second(model: str) -> float:
    """从既有定价表取模型单价（美元/秒 → 人民币/秒）；未知模型按 0。"""
    if not model:
        return 0.0
    try:
        from hevi.cost.pricing_table import get_pricing_table

        row = get_pricing_table().get(model) or {}
    except Exception:
        return 0.0
    price = float(row.get("price_usd") or 0.0)
    unit = str(row.get("unit") or "per_second")
    if unit == "per_minute":
        price = price / 60.0
    return price * usd_cny_rate()


def classify_route(
    *,
    format_id: str,
    style_id: str,
    line: str,
    prompt: str = "",
    has_user_media: bool = False,
) -> str:
    """一个镜头走哪条路线。默认代码；只有代码做不好时才升级。"""
    text = f"{line} {prompt}"
    if format_id == "material_cut" or has_user_media:
        return "user_media"
    if style_id == "editorial_2d":
        return "code"
    if style_id in {"scene3d", "cutaway_3d", "world_3d"} or any(
        word in text for word in _3D_WORDS
    ):
        return "blender"
    if format_id in {"live_drama", "comic_drama"}:
        return "generation"
    if format_id == "digital_human":
        return "generation"
    if format_id == "history_scene":
        no_human = any(neg in text for neg in ("没有人物", "无人", "没有人"))
        if any(word in text for word in _HUMAN_WORDS) and not no_human:
            return "generation"
        if any(word in text for word in _CHART_WORDS):
            return "code"
        return "mixed"
    if format_id == "animation":
        return "code"
    if any(word in text for word in _HUMAN_WORDS):
        return "generation"
    return "code"


def _generation_model(format_id: str, model: str | None) -> str:
    if model:
        return model
    return _FORMAT_GENERATION_MODEL.get(format_id, "") or "wan_2_7"


def plan_shot(
    *,
    index: int,
    line: str,
    prompt: str,
    duration_s: float,
    format_id: str,
    style_id: str,
    has_user_media: bool = False,
    provider: str | None = None,
) -> dict[str, Any]:
    route = classify_route(
        format_id=format_id,
        style_id=style_id,
        line=line,
        prompt=prompt,
        has_user_media=has_user_media,
    )
    meta = ROUTE_META[route]
    seconds = max(1.0, round(float(duration_s or 5.0), 2))
    model = meta["model"]
    if route == "generation":
        model = _generation_model(format_id, provider)
    per_second = model_price_cny_per_second(model) if route == "generation" else 0.0
    cost_cny = round(per_second * seconds, 3)
    render_s = round(float(meta["render_s_per_shot"]) * (seconds / 5.0), 1)
    if route == "code":
        why = "代码能做好：图形/文字/图表零成本，先低帧率试跑。"
    elif route == "blender":
        why = "需要真实三维空间或拆解，代码做不好。"
    elif route == "generation":
        why = "需要人脸/动物/真实运镜，代码与 3D 都替代不了。"
    elif route == "user_media":
        why = "用户已给实拍素材，只做剪辑包装。"
    else:
        why = "信息图用代码，空镜生成；同一条片子按镜拆价。"
    return {
        "index": index,
        "line": line,
        "keyframe_prompt": prompt,
        "route": route,
        "route_label": meta["label"],
        "model": model,
        "duration_s": seconds,
        "cost_cny": cost_cny,
        "offline_cost_cny": 0.0,
        "render_s_est": render_s,
        "why": why,
        "note": meta["note"],
    }


def estimate_budget(shots: list[dict[str, Any]]) -> dict[str, Any]:
    total_cny = round(sum(float(s.get("cost_cny") or 0) for s in shots), 2)
    total_seconds = round(sum(float(s.get("duration_s") or 0) for s in shots), 2)
    total_render_s = round(sum(float(s.get("render_s_est") or 0) for s in shots), 1)
    overhead = 0.0  # 本地配音/字幕/合成，公测期零现金成本
    per_route: dict[str, int] = {}
    for shot in shots:
        route = str(shot.get("route") or "code")
        per_route[route] = per_route.get(route, 0) + 1
    routes = ", ".join(f"{ROUTE_META.get(k, {}).get('label', k)} {v} 镜" for k, v in per_route.items())
    quote = (
        f"全片 {len(shots)} 镜 · 约 {int(total_seconds)} 秒 · 报价 ¥{total_cny + overhead:.2f}"
        f"（{routes or '无镜头'}）；本地预览 ¥0。"
    )
    return {
        "currency": "CNY",
        "shots": len(shots),
        "total_seconds": total_seconds,
        "total_render_s_est": total_render_s,
        "total_cny": round(total_cny + overhead, 2),
        "overhead_cny": overhead,
        "per_route": per_route,
        "quote": quote,
        "disclaimer": "生成镜按公开单价估算；实际账单以下游 provider 为准，本地/离线一律 ¥0。",
    }


# ---------------------------------------------------------------------------
# 阶段闸门
# ---------------------------------------------------------------------------

GATE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "brief",
        "label": "一句话主旨",
        "require": "给谁看 / 看完得到什么 / 可转述金句",
        "skippable": True,
    },
    {
        "id": "script",
        "label": "逐句脚本 + 分镜",
        "require": "每句有作用；事实与数字必须带出处，查不到就删",
        "skippable": False,
    },
    {
        "id": "proof",
        "label": "出样",
        "require": "代码线每句一帧总览图；3D 低采样首中尾三帧；生成线定妆图 + 关键帧",
        "skippable": True,
    },
    {
        "id": "hardest",
        "label": "最难一镜低清试做",
        "require": "最低分辨率 / 最低采样跑通最难的镜头，再批量",
        "skippable": True,
    },
    {
        "id": "film",
        "label": "整片",
        "require": "按镜头路线渲染并合成，字幕与文字全部后期叠加",
        "skippable": True,
    },
    {
        "id": "delivery",
        "label": "交付清单",
        "require": "写明哪些画面没逐帧看、哪些声音需要人工听",
        "skippable": True,
    },
)

#: 每种路线的出样证据。
PROOF_BY_ROUTE = {
    "code": "每句一帧总览图（contact sheet），先看信息层级再看动效",
    "blender": "低采样首 / 中 / 尾三帧，确认空间与镜头运动",
    "generation": "定妆图 + 关键帧（先图后视频），确认身份与构图",
    "user_media": "素材清单 + 首尾帧，确认可用段与授权",
    "mixed": "代码帧 + 生成关键帧各一张，分开确认",
}


def _gate_state(gate_id: str, *, skip_gates: set[str]) -> tuple[str, str]:
    if gate_id in skip_gates:
        return "skipped", "熟练用户一键跳过；审稿记录会保留。"
    if gate_id == "brief":
        return "pending", "等用户确认主旨三件事。"
    if gate_id == "script":
        return "pending", "脚本与分镜确认后由系统检查事实出处。"
    return "pending", "上一道闸门通过后进入。"


def build_gates(
    *,
    topic: str,
    lines: list[str],
    shots: list[dict[str, Any]],
    brief: dict[str, Any] | None,
    skip_gates: list[str] | None = None,
) -> list[dict[str, Any]]:
    skips = {str(item) for item in (skip_gates or [])}
    proof = []
    for shot in shots:
        route = str(shot.get("route") or "code")
        if route not in proof:
            proof.append(route)
    proof_text = "；".join(PROOF_BY_ROUTE.get(route, "") for route in proof) or "先出总览图"
    gates: list[dict[str, Any]] = []
    for definition in GATE_DEFS:
        gate_id = definition["id"]
        status, detail = _gate_state(gate_id, skip_gates=skips)
        evidence: dict[str, Any] = {}
        if gate_id == "brief":
            evidence = brief or {}
            if evidence.get("audience") and evidence.get("payoff") and evidence.get("quotable"):
                status = "done" if status != "skipped" else status
                detail = "主旨三件事已齐。"
        elif gate_id == "script":
            evidence = {"lines": len(lines), "shots": len(shots)}
        elif gate_id == "proof":
            evidence = {"routes": proof, "instruction": proof_text}
        elif gate_id == "hardest":
            hardest = max(
                shots,
                key=lambda s: float(s.get("render_s_est") or 0),
                default={},
            ) or {}
            evidence = {
                "shot": hardest.get("index"),
                "route": hardest.get("route"),
                "instruction": "这一镜先用最低分辨率/最低采样试做，通过再批量。",
            }
        elif gate_id == "film":
            evidence = {"shots": len(shots), "text_overlay": "所有画面文字后期叠加"}
        elif gate_id == "delivery":
            evidence = {
                "unseen_frames": "逐帧看过的镜头列表之外的，全部写明",
                "manual_sound": "TTS 回转对稿里列出的读错字、配乐卡点，需人工听",
            }
        gates.append({**definition, "status": status, "detail": detail, "evidence": evidence})
    return gates


def find_gate(gates: list[dict[str, Any]], gate_id: str) -> dict[str, Any] | None:
    return next((gate for gate in gates if gate["id"] == gate_id), None)


def apply_gate_action(
    gates: list[dict[str, Any]], gate_id: str, action: str, *, detail: str = ""
) -> list[dict[str, Any]]:
    """一键跳过 / 标记完成 / 重新打开；返回新列表，不修改入参。"""
    if action not in {"skip", "done", "reopen"}:
        raise ValueError(f"unknown gate action: {action}")
    out = json.loads(json.dumps(gates, ensure_ascii=False))
    gate = find_gate(out, gate_id)
    if gate is None:
        raise ValueError(f"unknown gate: {gate_id}")
    if action == "reopen":
        gate["status"] = "pending"
    else:
        gate["status"] = "skipped" if action == "skip" else "done"
    gate["detail"] = detail or gate.get("detail", "")
    gate["acted_at"] = datetime.now(UTC).isoformat()
    return out


# ---------------------------------------------------------------------------
# 规则自检
# ---------------------------------------------------------------------------

#: 易误解颜色词 → 更稳的写法（生成模型会按字面把皮肤/天空画错）。
COLOR_REPLACEMENTS: dict[str, str] = {
    "通红": "肤色自然偏暖",
    "血红": "暗红色（非皮肤）",
    "惨白": "自然浅肤色",
    "苍白": "自然浅肤色",
    "漆黑": "低照度深色环境",
    "雪白": "中性白",
    "金黄": "暖黄色（不要高饱和）",
    "碧绿": "自然绿色",
    "死白": "中性灰白",
}

TEXT_WORDS = ("文字", "字幕", "标题", "招牌", "标语", "logo", "LOGO", "海报", "字卡", "大字")

_CHART_CANON = {
    "折线": "line",
    "柱状": "bar",
    "条形": "bar",
    "饼图": "pie",
    "圆环": "donut",
    "地图": "map",
    "流程": "flow",
    "时间线": "timeline",
    "散点": "scatter",
    "表格": "table",
}

_NUM_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|％|年|月|日|亿|万|千|百|倍|米|公里|人|元|美元|岁|秒|分钟|小时|次|个)?"
)


def sanitize_prompt(prompt: str) -> dict[str, Any]:
    """生成提示词自检：去颜色歧义词、禁止在画面里生成字。"""
    original = prompt or ""
    text = original
    changes: list[str] = []
    for bad, good in COLOR_REPLACEMENTS.items():
        if bad in text:
            text = text.replace(bad, good)
            changes.append(f"{bad} → {good}")
    # 画面文字一律后期叠加：把提示词里“文字/标题/招牌…”所在的短句整段删掉，
    # 只留“标题安全区”这种构图信息。
    clauses = re.split(r"(?<=[，,。；;])", text)
    kept = [part for part in clauses if not any(word in part for word in TEXT_WORDS)]
    if len(kept) != len(clauses):
        text = "".join(kept).strip()
        changes.append("删除画面内文字描述，文字改后期叠加")
        if not text:
            text = "干净背景，留出标题安全区"
    if len(kept) != len(clauses) and not any(
        stop in text for stop in ("不生成任何文字", "不要文字", "no text")
    ):
        text = text.rstrip("，,。.；; ") + "。画面内不生成任何文字、字幕、招牌或 logo，标题与字幕后期叠加。"
        changes.append("追加：画面不生成文字，文字后期叠加")
    if changes and "标题安全区" not in text:
        text = text.rstrip("。. ") + "。画面留出标题安全区。"
    return {"prompt": text, "changed": text != original, "changes": changes}


def _chart_types(text: str) -> list[str]:
    found: list[str] = []
    for word, canon in _CHART_CANON.items():
        if word in text and canon not in found:
            found.append(canon)
    return found


_SCAFFOLD_NUM = re.compile(r"(?:第\s*\d+\s*个关键点|第\s*[一二三四五六七八九十]+\s*个关键点)")


def _unsourced_numbers(line: str, facts: list[dict[str, Any]]) -> list[str]:
    """只把“像事实”的数字算数：1 位数和“第 1 个”这类 Scaffold 编号不算。"""
    text = _SCAFFOLD_NUM.sub("", line or "")
    tokens: list[str] = []
    for match in _NUM_TOKEN.finditer(text):
        token = match.group(0).strip()
        digits = re.match(r"\d+", token)
        if not digits:
            continue
        bare = digits.group(0)
        # “第 1 个/第 2 条”是编号，不是事实。
        prefix = text[: match.start()].rstrip()
        if prefix.endswith("第") and len(bare) <= 2:
            continue
        # 1 位数没有单位时多半是编号；2 位以上（72 法则/80 亿/2024）都要出处。
        if len(bare) < 2 and not re.search(r"[%％年月日亿万千百倍米人元岁秒次个]", token):
            continue
        tokens.append(token)
    if not tokens:
        return []
    haystack = " ".join(
        f"{fact.get('claim', '')} {fact.get('source', '')} {fact.get('numbers', '')}"
        for fact in facts
    )
    return [token for token in tokens if token and token not in haystack]


def self_check(
    *,
    format_id: str,
    lines: list[str],
    shots: list[dict[str, Any]],
    facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """规则自检。每条问题都带 level / rule / fix，方便画布直接显示。"""
    facts = facts or []
    issues: list[dict[str, Any]] = []
    prompt_fixes: list[dict[str, Any]] = []

    for shot in shots:
        index = shot.get("index")
        raw = str(shot.get("keyframe_prompt") or shot.get("prompt") or "")
        clean = sanitize_prompt(raw)
        if clean["changed"]:
            prompt_fixes.append({"shot": index, "changes": clean["changes"], "prompt": clean["prompt"]})
        if any(word in raw for word in TEXT_WORDS):
            issues.append(
                {
                    "level": "fail",
                    "rule": "text_in_image",
                    "shot": index,
                    "message": f"镜头 {index} 的提示词让模型画字：{raw[:40]}…",
                    "fix": "画面里的文字一律后期代码叠加；提示词只写“无文字画面”。",
                }
            )
        if any(word in raw for word in COLOR_REPLACEMENTS):
            issues.append(
                {
                    "level": "warn",
                    "rule": "color_words",
                    "shot": index,
                    "message": f"镜头 {index} 用了易误解颜色词。",
                    "fix": "按 prompt_fixes 替换成“肤色自然/中性色”等稳定写法。",
                }
            )
        clause_count = raw.count("，") + raw.count("、") + raw.count("；")
        if clause_count >= 3:
            issues.append(
                {
                    "level": "warn",
                    "rule": "one_visual_per_sentence",
                    "shot": index,
                    "message": f"镜头 {index} 一句里塞了 {clause_count + 1} 个分句/画面。",
                    "fix": "一句一个主视觉；拆成两镜，或删掉次要信息。",
                }
            )

    chart_counts: dict[str, int] = {}
    for shot in shots:
        text = f"{shot.get('line', '')} {shot.get('keyframe_prompt', '')}"
        for canon in _chart_types(text):
            chart_counts[canon] = chart_counts.get(canon, 0) + 1
    for canon, count in chart_counts.items():
        if count > 3:
            issues.append(
                {
                    "level": "warn",
                    "rule": "chart_repetition",
                    "shot": 0,
                    "message": f"同一种图表（{canon}）出现 {count} 次，超过 3 次。",
                    "fix": "换一种图表或换成口播/示意图，避免全片一个模板。",
                }
            )

    for index, line in enumerate(lines, start=1):
        missing = _unsourced_numbers(line, facts)
        if missing:
            issues.append(
                {
                    "level": "fail" if shots and shots[0].get("route") != "user_media" else "warn",
                    "rule": "fact_source",
                    "shot": index,
                    "message": f"第 {index} 句的数字/事实没有出处：{', '.join(missing)}",
                    "fix": "补出处；查不到就把该句删掉。",
                }
            )

    routes = {str(shot.get("route")) for shot in shots}
    if "code" in routes:
        issues.append(
            {
                "level": "info",
                "rule": "code_low_fps_probe",
                "shot": 0,
                "message": "代码动画要先低帧率试跑。",
                "fix": "预览 12fps，通过后再按 30fps 正式渲染（计划里已写入 first_pass_fps=12）。",
            }
        )
    blender_shots = [s for s in shots if s.get("route") == "blender"]
    if len(blender_shots) > 1:
        issues.append(
            {
                "level": "info",
                "rule": "blender_one_at_a_time",
                "shot": 0,
                "message": f"有 {len(blender_shots)} 个 Blender 镜头。",
                "fix": "3D 一次只跑一个渲染；按顺序排队，不要并行占显存。",
            }
        )
    if format_id in {"live_drama", "comic_drama", "digital_human"}:
        issues.append(
            {
                "level": "info",
                "rule": "identity_first",
                "shot": 0,
                "message": "生成线先出定妆图，再关键帧，再视频。",
                "fix": "身份板通过后再跑关键帧；关键帧通过后再跑视频。",
            }
        )

    fails = [i for i in issues if i["level"] == "fail"]
    warns = [i for i in issues if i["level"] == "warn"]
    return {
        "ok": not fails,
        "issues": issues,
        "counts": {"fail": len(fails), "warn": len(warns), "info": len(issues) - len(fails) - len(warns)},
        "prompt_fixes": prompt_fixes,
        "text_policy": "画面内不生成文字；标题、字幕、数据标签一律后期代码叠加。",
        "preview": {"code_first_pass_fps": 12, "final_fps": 30, "blender_serial": len(blender_shots) > 1},
    }


# ---------------------------------------------------------------------------
# 独立审稿
# ---------------------------------------------------------------------------

_LLM_REVIEW_COOLDOWN_S = float(os.getenv("HEVI_CRAFT_REVIEW_COOLDOWN_S", "600"))
_LLM_COOLDOWN_UNTIL = 0.0

_REVIEW_SYSTEM = (
    "你是独立审稿人，不参与写作。只输出严格 JSON；只列问题，不夸、不总结、不改写全文。"
)

_REVIEW_PROMPT = """审这段中文短视频脚本，逐项只列问题：
1) 每句作用（钩子/证据/转折/收束，重复或缺作用要指出）；
2) 事实与数字是否对得上出处（对不上就点名）；
3) 拍摄风险（一镜多动作、写实人脸、手靠近脸、画面有字）；
4) 如果只能留一半，保留哪几句、删哪几句。
只输出 JSON：
{{"issues":[{{"dimension":"role|fact|risk|half","shot":1,"message":"具体问题","fix":"可执行修改"}}],
 "keep_half":[1,2,3],"cut_half":[4,5]}}

主旨：{topic}
事实与出处：{facts}
脚本（逐句）：
{lines}
分镜：
{shots}
"""


def _role_for(line: str) -> str:
    text = line or ""
    if "？" in text or "?" in text:
        return "问题/钩子"
    if _NUM_TOKEN.search(text):
        return "证据/数字"
    if any(word in text for word in ("但是", "然而", "可是", "其实", "反而")):
        return "转折"
    if any(word in text for word in ("所以", "因此", "记住", "这就是", "下次")):
        return "收束/行动"
    return "过渡"


def _keep_half(lines: list[str]) -> tuple[list[int], list[int]]:
    """只能留一半：保钩子 + 带数字/核心判断的句子，按原顺序。"""
    keep: list[int] = []
    if lines:
        keep.append(1)
    for index, line in enumerate(lines, start=1):
        if index in keep:
            continue
        if _NUM_TOKEN.search(line or "") or any(
            word in (line or "") for word in ("所以", "因此", "记住", "这就是")
        ):
            keep.append(index)
    target = max(1, (len(lines) + 1) // 2)
    for index in range(1, len(lines) + 1):
        if len(keep) >= target:
            break
        if index not in keep:
            keep.append(index)
    keep = sorted(keep[:target])
    cut = [index for index in range(1, len(lines) + 1) if index not in keep]
    return keep, cut


def review_script_offline(
    *,
    topic: str,
    lines: list[str],
    shots: list[dict[str, Any]],
    facts: list[dict[str, Any]] | None = None,
    skipped_gates: list[str] | None = None,
) -> dict[str, Any]:
    facts = facts or []
    issues: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    seen_roles: dict[str, int] = {}
    for index, line in enumerate(lines, start=1):
        role = _role_for(line)
        roles.append({"shot": index, "role": role, "line": line})
        seen_roles[role] = seen_roles.get(role, 0) + 1
        if len(line or "") > 42:
            issues.append(
                {
                    "dimension": "role",
                    "shot": index,
                    "message": f"第 {index} 句 {len(line)} 字，口播一口气读不完。",
                    "fix": "拆成两句，或删掉修饰。",
                }
            )
        missing = _unsourced_numbers(line, facts)
        if missing:
            issues.append(
                {
                    "dimension": "fact",
                    "shot": index,
                    "message": f"第 {index} 句的数字没有出处：{', '.join(missing)}",
                    "fix": "补出处；查不到就删。",
                }
            )
        prompt = str((shots[index - 1] if index - 1 < len(shots) else {}).get("keyframe_prompt") or "")
        if any(word in prompt for word in ("然后", "接着", "同时", "一边", "再")):
            issues.append(
                {
                    "dimension": "risk",
                    "shot": index,
                    "message": f"第 {index} 镜一镜多动作，视频模型容易崩。",
                    "fix": "拆成两镜，或只保留一个主动作。",
                }
            )
        if any(word in prompt for word in ("写实", "photo", "photorealistic", "人脸", "特写")):
            issues.append(
                {
                    "dimension": "risk",
                    "shot": index,
                    "message": f"第 {index} 镜是写实人脸，先定妆图再关键帧。",
                    "fix": "先出定妆图，锁定身份后再跑视频。",
                }
            )
        if any(word in prompt for word in ("手",)) and any(word in prompt for word in ("脸", "面部")):
            issues.append(
                {
                    "dimension": "risk",
                    "shot": index,
                    "message": f"第 {index} 镜手靠近脸，生成容易糊。",
                    "fix": "改成手在胸前/桌面，或拆成两个镜头。",
                }
            )
        if any(word in prompt for word in TEXT_WORDS):
            issues.append(
                {
                    "dimension": "risk",
                    "shot": index,
                    "message": f"第 {index} 镜画面里有字，模型会画错。",
                    "fix": "文字改后期叠加。",
                }
            )
        if seen_roles[role] > 2:
            issues.append(
                {
                    "dimension": "role",
                    "shot": index,
                    "message": f"第 {index} 句又是“{role}”，同类作用重复第 {seen_roles[role]} 次。",
                    "fix": "合并同类句子，换成推进信息。",
                }
            )
    issues.extend(
        {
            "dimension": "risk",
            "shot": 0,
            "message": f"闸门 {gate} 被跳过，没有留下证据。",
            "fix": "交付前补证据，或写明风险由谁承担。",
        }
        for gate in skipped_gates or []
    )
    keep, cut = _keep_half(lines)
    return {
        "mode": "offline_rules",
        "model": "hevi.studio.craft/review_rules",
        "issues": issues,
        "per_line": roles,
        "keep_half": keep,
        "cut_half": cut,
        "keep_half_text": [lines[i - 1] for i in keep if 0 < i <= len(lines)],
        "counts": {"total": len(issues)},
    }


def _review_sync(prompt: str, *, timeout: float = 12.0) -> tuple[str, str]:
    from hevi.providers.free_llm import available_channels, build_channel_caller

    names = available_channels()
    preferred = os.environ.get("HEVI_CANVAS_LLM_CHANNEL", "").strip()
    if preferred:
        names = [preferred] + [name for name in names if name != preferred]
    if not names:
        raise RuntimeError("没有可用的免费 LLM 通道")

    def factory(caller: Any) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            return await asyncio.wait_for(
                caller(
                    messages=[{"role": "user", "content": prompt}],
                    system=_REVIEW_SYSTEM,
                    max_tokens=2400,
                    temperature=0,
                ),
                timeout=timeout,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(run())).result(timeout=timeout + 5)

    last: Exception | None = None
    deadline = time.monotonic() + 25.0
    for name in names[:2]:  # 最多试两个通道，总预算 25 秒，避免审稿按钮卡住
        remaining = deadline - time.monotonic()
        if remaining <= 1.0:
            break
        caller = build_channel_caller(name)
        if caller is None:
            continue
        try:
            response = factory(caller)
        except Exception as exc:
            logger.warning("S22 review channel %s failed: %s", name, exc)
            last = exc
            continue
        content = str((response or {}).get("content") or "").strip()
        if content:
            return name, content
        last = RuntimeError(f"{name}: empty content")
    raise RuntimeError(f"所有免费 LLM 通道均失败：{last}")


def _parse_json(text: str) -> dict[str, Any] | None:
    clean = (text or "").strip()
    if clean.startswith("```"):
        match = re.search(r"```(?:json)?\n?(.*?)\n?```", clean, re.S)
        if match:
            clean = match.group(1).strip()
    match = re.search(r"\{.*\}", clean, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def review_script(
    *,
    topic: str,
    lines: list[str],
    shots: list[dict[str, Any]],
    facts: list[dict[str, Any]] | None = None,
    skipped_gates: list[str] | None = None,
    allow_llm: bool = False,
    llm_call: Any = None,
) -> dict[str, Any]:
    """独立审稿：先用确定性规则兜底，allow_llm 时再单独调一次 LLM。

    LLM 的 system prompt 与写稿/画布节点审稿不同，输入只有脚本、事实与分镜，
    不带写作上下文。失败时不假装审过：mode 保持 offline_rules 并写明原因。
    """
    baseline = review_script_offline(
        topic=topic,
        lines=lines,
        shots=shots,
        facts=facts,
        skipped_gates=skipped_gates,
    )
    global _LLM_COOLDOWN_UNTIL
    if not allow_llm:
        return baseline
    if time.monotonic() < _LLM_COOLDOWN_UNTIL:
        return {**baseline, "llm_error": "LLM 通道冷却中，本次用离线规则"}
    prompt = _REVIEW_PROMPT.format(
        topic=topic,
        facts=json.dumps(facts or [], ensure_ascii=False)[:2000],
        lines="\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1)),
        shots=json.dumps(shots, ensure_ascii=False)[:3000],
    )
    try:
        if llm_call is not None:
            channel, content = llm_call(prompt)
        else:
            channel, content = await asyncio.to_thread(_review_sync, prompt)
        data = _parse_json(content)
        if not data:
            raise RuntimeError("LLM 审稿返回非 JSON")
        llm_issues = []
        for item in data.get("issues") or []:
            if not isinstance(item, dict):
                continue
            llm_issues.append(
                {
                    "dimension": str(item.get("dimension") or "role"),
                    "shot": int(item.get("shot") or 0),
                    "message": str(item.get("message") or ""),
                    "fix": str(item.get("fix") or ""),
                    "source": "llm",
                }
            )
        merged = [dict(item, source=item.get("source") or "rules") for item in baseline["issues"]] + llm_issues
        keep = data.get("keep_half") if isinstance(data.get("keep_half"), list) else baseline["keep_half"]
        cut = data.get("cut_half") if isinstance(data.get("cut_half"), list) else baseline["cut_half"]
        keep = [int(x) for x in keep if isinstance(x, (int, float))]
        cut = [int(x) for x in cut if isinstance(x, (int, float))]
        return {
            **baseline,
            "mode": "llm",
            "model": f"hevi.studio.craft/{channel}",
            "issues": merged,
            "keep_half": keep,
            "cut_half": cut,
            "keep_half_text": [lines[i - 1] for i in keep if 0 < i <= len(lines)],
            "counts": {"total": len(merged)},
        }
    except Exception as exc:
        return {**baseline, "llm_error": f"{type(exc).__name__}: {exc}"[:300]}


def review_film_offline(qc: dict[str, Any] | None = None) -> dict[str, Any]:
    """成片 QC：只列问题。qc 来自真实探针（时长/响度/黑场/文字/无 BGM 版）。"""
    qc = qc or {}
    issues: list[dict[str, Any]] = []
    if not qc.get("exists", True):
        issues.append(
            {"dimension": "delivery", "shot": 0, "message": "成片文件不存在。", "fix": "重新导出成片。"}
        )
    duration = float(qc.get("duration_s") or 0)
    if duration and duration < 5:
        issues.append(
            {"dimension": "delivery", "shot": 0, "message": f"成片只有 {duration:.1f}s。", "fix": "确认是否漏合镜头。"}
        )
    if qc.get("has_audio") is False:
        issues.append(
            {"dimension": "sound", "shot": 0, "message": "成片没有音轨。", "fix": "重新混音；无旁白也要有配乐。"}
        )
    first = qc.get("first_second_lufs")
    if first is not None and float(first) < -50:
        issues.append(
            {
                "dimension": "sound",
                "shot": 0,
                "message": f"前 1 秒几乎无声（{first} LUFS）。",
                "fix": "配乐第一帧就要有声；把音乐整体前移或补 0.3s 起音。",
            }
        )
    if qc.get("fade_to_black") is False:
        issues.append(
            {"dimension": "sound", "shot": 0, "message": "音乐没有撑到黑场淡出。", "fix": "尾巴补 1.5–2s 淡出并停在黑场。"}
        )
    if qc.get("text_in_frame"):
        issues.append(
            {
                "dimension": "risk",
                "shot": 0,
                "message": f"画面里出现模型生成的文字：{qc.get('text_in_frame')}",
                "fix": "改成后期字幕；重跑该镜并在提示词里禁止文字。",
            }
        )
    if qc.get("no_bgm_export") is False:
        issues.append(
            {
                "dimension": "delivery",
                "shot": 0,
                "message": "没有导出无 BGM 版。",
                "fix": "额外导出保留旁白/对白/音效的版本，供抖音/视频号加曲库音乐。",
            }
        )
    if qc.get("misread"):
        issues.append(
            {
                "dimension": "sound",
                "shot": 0,
                "message": f"TTS 回转对稿发现读错：{qc.get('misread')}",
                "fix": "改字/加注音后重配这一句。",
            }
        )
    unseen = qc.get("unseen_frames") or []
    if unseen:
        issues.append(
            {
                "dimension": "half",
                "shot": 0,
                "message": f"这些镜头没有逐帧看：{', '.join(str(x) for x in unseen[:10])}",
                "fix": "交付清单里写明；关键镜补看。",
            }
        )
    return {
        "mode": "offline_rules",
        "model": "hevi.studio.craft/film_qc_rules",
        "issues": issues,
        "counts": {"total": len(issues)},
        "checked": sorted(qc.keys()),
    }


# ---------------------------------------------------------------------------
# 声音
# ---------------------------------------------------------------------------

SOUND_RULES: tuple[str, ...] = (
    "无旁白：先定整首配乐，再按节拍剪；切点对齐拍点。",
    "配乐第一帧必须有声：前 1 秒响度不低于 -24 LUFS。",
    "音乐撑到黑场，结尾 1.5–2 秒淡出。",
    "旁白 TTS 后用 faster-whisper 回转对稿，列出读错字。",
    "额外导出无 BGM 版，保留旁白/对白/音效。",
)


def build_sound_plan(
    *,
    has_narration: bool,
    total_s: float,
    shots: list[dict[str, Any]],
    mood: str = "calm",
    bpm: float | None = None,
) -> dict[str, Any]:
    total = max(1.0, round(float(total_s or 0), 2))
    if bpm is None:
        try:
            from hevi.audio.procedural_bgm import MOOD_PRESETS

            bpm = float((MOOD_PRESETS.get(mood) or {}).get("bpm") or 90.0)
        except Exception:
            bpm = 90.0
    period = 60.0 / max(1.0, float(bpm))
    beats = [round(i * period, 3) for i in range(int(total / period) + 2)]
    # 把每个镜头边界吸到最近的拍点；首尾不吸 0。
    boundaries: list[float] = []
    cursor = 0.0
    for shot in shots:
        cursor += float(shot.get("duration_s") or 0)
        if cursor <= 0:
            continue
        nearest = min(beats, key=lambda beat: abs(beat - cursor)) if beats else cursor
        boundaries.append(round(min(nearest, total), 3))
    no_bgm: dict[str, Any] = {
        "enabled": True,
        "keep": ["narration", "dialogue", "sfx"],
        "path_suffix": "_nobgm",
        "how": "用分轨（旁白/对白/音效）重新混，不要从成片里硬抠。",
    }
    roundtrip: dict[str, Any] = {
        "tool": "faster-whisper",
        "status": "pending" if has_narration else "not_needed",
        "compare": "逐字稿 vs 脚本，列出读错字与漏字",
        "function": "hevi.studio.craft.roundtrip_tts",
    }
    return {
        "has_narration": has_narration,
        "strategy": "narration_then_music" if has_narration else "music_first_beat_cut",
        "mood": mood,
        "bpm": round(float(bpm), 2),
        "beat_period_s": round(period, 4),
        "total_s": total,
        "cut_points_s": boundaries,
        "first_frame": {"must_have_sound": True, "first_second_lufs_min": -24.0},
        "fade_out": {"start_s": round(max(0.0, total - 2.0), 2), "end_s": total, "to_black": True},
        "loudnorm": {"target_lufs": -16.0, "true_peak_db": -1.5},
        "no_bgm_export": no_bgm,
        "tts_roundtrip": roundtrip,
        "rules": list(SOUND_RULES),
        "checks": [
            {"id": "music_first", "label": "配乐第一帧有声", "state": "todo"},
            {"id": "beat_cut", "label": "切点对齐拍点", "state": "todo"},
            {"id": "fade_black", "label": "音乐淡出到黑场", "state": "todo"},
            {"id": "tts_roundtrip", "label": "TTS 回转对稿", "state": "todo" if has_narration else "skip"},
            {"id": "no_bgm", "label": "导出无 BGM 版", "state": "todo"},
        ],
    }


def first_second_loudness(path: str) -> dict[str, Any]:
    """用 ffmpeg ebur128 量成片前 1 秒响度；失败返回 unavailable，不假装有声。"""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or not os.path.isfile(path):
        return {"status": "unavailable", "lufs": None}
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path, "-t", "1", "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    match = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", proc.stderr or "")
    if not match:
        return {"status": "unavailable", "lufs": None}
    return {"status": "ok", "lufs": float(match[-1])}


def export_no_bgm(*, narration_wav: str, sfx_wav: str | None, out_path: str) -> dict[str, Any]:
    """把旁白/对白与音效重新混成无 BGM 版；没有分轨就明确拒绝。"""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return {"ok": False, "reason": "ffmpeg missing"}
    if not os.path.isfile(narration_wav):
        return {"ok": False, "reason": "缺少旁白/对白分轨；不能从成片硬抠出无 BGM 版"}
    inputs = ["-i", narration_wav]
    if sfx_wav and os.path.isfile(sfx_wav):
        inputs += ["-i", sfx_wav]
        filt = "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0,alimiter=limit=0.95[a]"
    else:
        filt = "[0:a]alimiter=limit=0.95[a]"
    proc = subprocess.run(
        [ffmpeg, "-y", *inputs, "-filter_complex", filt, "-map", "[a]", out_path],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return {"ok": proc.returncode == 0, "path": out_path if proc.returncode == 0 else "", "stderr": (proc.stderr or "")[-500:]}


def roundtrip_tts(
    *,
    audio_path: str,
    script_text: str,
    transcriber: Any = None,
) -> dict[str, Any]:
    """TTS → faster-whisper 回转对稿：列出读错字/漏字。

    ``transcriber`` 可注入（测试用）；默认走本地 faster-whisper，模型不可用时
    返回 unavailable，不编造识别结果。
    """
    if not os.path.isfile(audio_path):
        return {"status": "unavailable", "reason": "audio missing", "misread": []}
    try:
        if transcriber is None:
            from hevi.audio.whisper_alignment import _transcribe_words

            words = _transcribe_words(audio_path)
        else:
            words = transcriber(audio_path)
        text = "".join(word[0] for word in words) if words else ""
    except Exception as exc:
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:200], "misread": []}
    if not text:
        return {"status": "unavailable", "reason": "识别为空", "misread": []}
    from hevi.audio.asr_verify import character_error_rate, critical_word_errors

    cer = round(character_error_rate(script_text, text), 4)
    critical = critical_word_errors(script_text, text)
    misread = [{"script": expected, "heard": actual} for expected, actual in _diff_pairs(script_text, text)]
    return {
        "status": "ok",
        "transcript": text,
        "cer": cer,
        "critical": critical,
        "misread": misread[:20],
    }


def _diff_pairs(expected: str, actual: str) -> list[tuple[str, str]]:
    import difflib

    pairs: list[tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(a=expected, b=actual)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            pairs.append((expected[i1:i2], actual[j1:j2]))
        elif tag == "delete":
            pairs.append((expected[i1:i2], ""))
    return pairs


# ---------------------------------------------------------------------------
# 许可审计
# ---------------------------------------------------------------------------

#: 线上实际出现过的 TTS / 配乐 / 模型。commercial: yes / unknown / no。
LICENSE_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "id": "edge-tts",
        "kind": "TTS",
        "license": "Microsoft Edge 朗读接口，无独立商用授权文本",
        "commercial": "unknown",
        "risk": "high",
        "used_by": "hevi/video/presets.py、tasks.py（默认 edge_tts）",
        "replacement": "piper（本地，MIT 引擎；音色需逐个核对）或 kokoro（Apache-2.0）",
        "action": "公测期继续用；对外商用前切本地/已授权引擎。",
    },
    {
        "id": "piper",
        "kind": "TTS",
        "license": "引擎 MIT；各 voice 模型许可不一（部分 CC BY-NC）",
        "commercial": "unknown",
        "risk": "medium",
        "used_by": "hevi/audio/piper_tts_service.py",
        "replacement": "只选 MIT/CC-BY 音色；记录 voice 来源",
        "action": "逐个音色登记许可，NC 音色不得商用。",
    },
    {
        "id": "kokoro",
        "kind": "TTS",
        "license": "Apache-2.0（代码与 82M 模型）",
        "commercial": "yes",
        "risk": "low",
        "used_by": "hevi/audio/kokoro_service.py",
        "replacement": "-",
        "action": "可作 edge-tts 的替换。",
    },
    {
        "id": "chatterbox",
        "kind": "TTS",
        "license": "Resemble AI Chatterbox，MIT（以仓库 LICENSE 为准）",
        "commercial": "yes",
        "risk": "low",
        "used_by": "hevi/audio/chatterbox_service.py",
        "replacement": "-",
        "action": "可用；声音克隆需取得被克隆人授权。",
    },
    {
        "id": "cosyvoice",
        "kind": "TTS",
        "license": "代码 Apache-2.0；模型权重许可随版本，需锁版本",
        "commercial": "unknown",
        "risk": "medium",
        "used_by": "hevi/audio/cosyvoice_service.py",
        "replacement": "kokoro / chatterbox",
        "action": "锁权重版本并保留 LICENSE 副本。",
    },
    {
        "id": "f5-tts",
        "kind": "TTS",
        "license": "代码 MIT；权重在 Emilia 数据集上训练（CC BY-NC 4.0）",
        "commercial": "unknown",
        "risk": "high",
        "used_by": "hevi/audio/f5_tts_service.py",
        "replacement": "kokoro / chatterbox / 商用授权 TTS",
        "action": "公测期可试；对外商用前替换。",
    },
    {
        "id": "fish-speech",
        "kind": "TTS",
        "license": "权重 CC BY-NC-SA（非商用）",
        "commercial": "no",
        "risk": "high",
        "used_by": "hevi/audio/fish_speech_service.py",
        "replacement": "kokoro / chatterbox / qwen_tts",
        "action": "不要用于对外商用成片。",
    },
    {
        "id": "indextts",
        "kind": "TTS",
        "license": "权重许可需随版本核对（常见为非商用）",
        "commercial": "unknown",
        "risk": "high",
        "used_by": "hevi/audio/indextts_service.py",
        "replacement": "kokoro / chatterbox",
        "action": "未确认前只做内部测试。",
    },
    {
        "id": "qwen-tts-maas",
        "kind": "TTS",
        "license": "阿里云百炼商用 API（按量付费）",
        "commercial": "yes",
        "risk": "low",
        "used_by": "hevi/audio/qwen_tts_maas.py",
        "replacement": "-",
        "action": "有预算时可替换 edge-tts。",
    },
    {
        "id": "procedural-bgm",
        "kind": "配乐",
        "license": "hevi 自己用 numpy 合成，无第三方素材",
        "commercial": "yes",
        "risk": "low",
        "used_by": "hevi/audio/procedural_bgm.py",
        "replacement": "-",
        "action": "默认配乐优先用它，自带拍点。",
    },
    {
        "id": "bgm-library",
        "kind": "配乐",
        "license": "assets/audio/bgm 下素材来源未逐条登记",
        "commercial": "unknown",
        "risk": "high",
        "used_by": "hevi/audio/bgm_library.py",
        "replacement": "procedural-bgm 或已登记 CC0 曲库",
        "action": "入库前必须登记来源与许可。",
    },
    {
        "id": "sdxl",
        "kind": "图像模型",
        "license": "CreativeML OpenRAIL-M",
        "commercial": "yes",
        "risk": "low",
        "used_by": "hevi/image/* sdxl worker",
        "replacement": "-",
        "action": "保留使用限制说明；不得用于违法内容。",
    },
    {
        "id": "sd-turbo",
        "kind": "图像模型",
        "license": "Stability AI Community License（年收入阈值内可商用）",
        "commercial": "yes",
        "risk": "medium",
        "used_by": "ai_drama 离线关键帧",
        "replacement": "-",
        "action": "超过营收阈值需企业授权。",
    },
    {
        "id": "wan-2.7",
        "kind": "视频模型",
        "license": "阿里 Wan 模型许可（以发布页为准）",
        "commercial": "unknown",
        "risk": "medium",
        "used_by": "hevi/cost/pricing_table.py（wan_2_7）",
        "replacement": "h3_local / ltx2_local",
        "action": "对外商用前锁许可版本。",
    },
    {
        "id": "h3-local",
        "kind": "视频模型",
        "license": "本地 ComfyUI H3，权重许可随来源",
        "commercial": "unknown",
        "risk": "medium",
        "used_by": "hevi/capabilities/fasth3_local.py",
        "replacement": "wan_local / ltx2_local",
        "action": "登记权重来源。",
    },
)


def license_audit() -> dict[str, Any]:
    entries = [dict(item) for item in LICENSE_ENTRIES]
    high = [item["id"] for item in entries if item["risk"] == "high"]
    unknown = [item["id"] for item in entries if item["commercial"] != "yes"]
    return {
        "entries": entries,
        "high_risk": high,
        "not_clearly_commercial": unknown,
        "policy": "公测期继续用；对外商用前把 high_risk 全部替换或拿到书面授权。",
        "note": "这是工程审计，不是法律意见；许可以各项目仓库 LICENSE 与官方发布页为准。",
        "updated_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# 栏目模板
# ---------------------------------------------------------------------------

SERIES_TEMPLATES: dict[str, dict[str, Any]] = {
    "explainer_standard": {
        "id": "explainer_standard",
        "format": "explainer",
        "label": "知识讲解 · 栏目模板",
        "fixed": {
            "background": "#0E1420 深蓝黑渐变",
            "light": "左上 5600K 柔光 + 右下冷色轮廓光",
            "font": "思源黑体 Bold（标题）/ 思源黑体 Regular（正文）",
            "subtitle": "底部安全区，白字 + 40% 黑底",
            "subtitle_chars_per_second": 6.5,
            "accent": "#F2B544 琥珀色",
        },
        "variables": ["标题", "核心比喻", "标签/关键词", "数据点"],
        "rules": [
            "固定底色、光效、字体与字幕速度，观众一眼认出栏目。",
            "只换标题、比喻、标签；结构不换。",
            "字幕每秒 6–7 字，单行不超过 16 字。",
        ],
        "speedup": "复用模板后，单条片的前期设计时间从 ~40 分钟降到 ~10 分钟。",
    },
}
SERIES_TEMPLATES["explainer_kinetic"] = {
    **SERIES_TEMPLATES["explainer_standard"],
    "id": "explainer_kinetic",
    "label": "动效标题 · 栏目模板",
    "fixed": {
        **SERIES_TEMPLATES["explainer_standard"]["fixed"],
        "background": "#101010 近黑 + 纸张纹理",
        "accent": "#FF5A36 橙红",
    },
}


def series_templates(format_id: str | None = None) -> list[dict[str, Any]]:
    items = list(SERIES_TEMPLATES.values())
    if format_id:
        items = [item for item in items if item.get("format") == format_id]
    return [json.loads(json.dumps(item, ensure_ascii=False)) for item in items]


def apply_series_template(
    template_id: str, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    template = SERIES_TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"unknown series template: {template_id}")
    values = {key: str((variables or {}).get(key) or "") for key in template["variables"]}
    missing = [key for key, value in values.items() if not value]
    return {
        "template": json.loads(json.dumps(template, ensure_ascii=False)),
        "variables": values,
        "missing": missing,
        "ready": not missing,
        "subtitle": {
            "chars_per_second": template["fixed"]["subtitle_chars_per_second"],
            "max_chars_per_line": 16,
        },
    }


# ---------------------------------------------------------------------------
# 标题 / 封面
# ---------------------------------------------------------------------------


def title_candidates(topic: str, lines: list[str] | None = None) -> list[dict[str, Any]]:
    """3 个标题，每个都回答“看完得到什么”，并说明理由。"""
    topic = (topic or "这条视频").strip().rstrip("。！？!?")
    core = topic[:24]
    lines = lines or []
    payoff = next(
        (
            line
            for line in lines
            if _NUM_TOKEN.search(line)
            and not any(bad in line for bad in ("关键点", "评论区", "接下来", "最后一点"))
        ),
        "",
    )
    middle = payoff[:18].strip("，。；:： ") if payoff else "一个反直觉的答案"
    return [
        {
            "title": f"看完这条，你会明白{core}",
            "gain": f"得到一个能转述的判断：{core}",
            "why": "直接承诺观看收益，不做悬念标题党。",
        },
        {
            "title": f"3 分钟讲清{core}",
            "gain": "用最短时间建立完整框架",
            "why": "时间承诺 + 知识交付，适合知识讲解。",
        },
        {
            "title": f"{core}：{middle}",
            "gain": f"记住一个具体结论：{middle}",
            "why": "主题 + 具体收益，封面可配一个数字或对比。",
        },
    ]


def cover_spec(topic: str, *, format_id: str = "explainer") -> dict[str, Any]:
    topic = (topic or "这条视频").strip()
    palette = {
        "explainer": ["#0E1420", "#F2B544", "#F5F1E8"],
        "history_scene": ["#1A1410", "#C9A227", "#E8DFD0"],
        "live_drama": ["#101820", "#D94F3D", "#F2E9E4"],
        "comic_drama": ["#1B1030", "#7C5CFF", "#F7E9FF"],
        "animation": ["#0F1B2D", "#2EC4B6", "#FFF3E0"],
        "digital_human": ["#121417", "#4DA3FF", "#F5F7FA"],
        "material_cut": ["#141414", "#FF7A00", "#F5F5F5"],
    }.get(format_id, ["#0E1420", "#F2B544", "#F5F1E8"])
    return {
        "separate_generation": True,
        "not_frame_grab": True,
        "aspect": "16:9",
        "prompt": (
            f"为“{topic}”单独设计一张封面：一个主视觉、留出标题安全区；"
            "画面内不生成任何文字，标题后期叠加；" + "、".join(palette)
        ),
        "palette": palette,
        "rules": [
            "封面单独生成，不要从成片截帧。",
            "封面只放一个视觉焦点，标题后期叠加。",
            "同一个栏目连续 5 条保持同一构图与配色。",
        ],
    }


# ---------------------------------------------------------------------------
# 一句话主旨
# ---------------------------------------------------------------------------


def brief_from_topic(topic: str, *, audience: str = "", payoff: str = "", quotable: str = "") -> dict[str, Any]:
    topic = (topic or "").strip()
    return {
        "topic": topic,
        "audience": audience,
        "payoff": payoff or (f"看完能讲清“{topic}”" if topic else ""),
        "quotable": quotable,
        "ready": bool(topic and audience and quotable),
        "questions": ["给谁看？", "看完得到什么？", "能转述的那句金句是什么？"],
    }


# ---------------------------------------------------------------------------
# 总装
# ---------------------------------------------------------------------------


def plan_id_for(format_id: str, style_id: str, topic: str, lines: list[str]) -> str:
    digest = hashlib.sha1(
        json.dumps([format_id, style_id, topic, lines], ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]
    return f"s22-{digest}"


def build_craft_plan(
    *,
    format_id: str,
    style_id: str,
    topic: str,
    lines: list[str],
    shots: list[dict[str, Any]],
    slots: dict[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
    skip_gates: list[str] | None = None,
    brief: dict[str, Any] | None = None,
    series_template_id: str | None = None,
) -> dict[str, Any]:
    """把脚本/分镜补成可执行、可报价、可审稿、可交付的出片计划。"""
    slots = slots or {}
    has_user_media = bool(slots.get("media_path") or slots.get("source_path") or slots.get("video_path"))
    provider = str(slots.get("provider") or "").strip() or None

    planned_shots: list[dict[str, Any]] = []
    for index, shot in enumerate(shots, start=1):
        planned = plan_shot(
            index=int(shot.get("index") or index),
            line=str(shot.get("line") or ""),
            prompt=str(shot.get("keyframe_prompt") or shot.get("prompt") or ""),
            duration_s=float(shot.get("duration_s") or 5.0),
            format_id=format_id,
            style_id=style_id,
            has_user_media=has_user_media,
            provider=provider,
        )
        planned_shots.append(planned)

    budget = estimate_budget(planned_shots)
    brief_data = brief or brief_from_topic(topic)
    gates = build_gates(
        topic=topic,
        lines=lines,
        shots=planned_shots,
        brief=brief_data,
        skip_gates=skip_gates,
    )
    rules = self_check(format_id=format_id, lines=lines, shots=planned_shots, facts=facts)
    sound = build_sound_plan(
        has_narration=bool(slots.get("narration", True)),
        total_s=budget["total_seconds"],
        shots=planned_shots,
        mood=str(slots.get("music_mood") or "calm"),
    )
    templates = series_templates(format_id)
    applied = None
    if series_template_id:
        applied = apply_series_template(series_template_id, slots.get("series_variables") or {})
    audit = license_audit()
    plan_id = plan_id_for(format_id, style_id, topic, lines)
    return {
        "plan_id": plan_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "format": format_id,
        "style": style_id,
        "brief": brief_data,
        "gates": gates,
        "shots": planned_shots,
        "budget": budget,
        "rules": rules,
        "sound": sound,
        "titles": title_candidates(topic, lines),
        "cover": cover_spec(topic, format_id=format_id),
        "series_templates": templates,
        "series_template": applied,
        "license": {
            "high_risk": audit["high_risk"],
            "not_clearly_commercial": audit["not_clearly_commercial"],
            "policy": audit["policy"],
        },
        "review": {"mode": "not_run", "issues": []},
    }
