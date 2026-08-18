"""从 OpenMontage 700 skill 精选、落到可调用函数的制片手艺。

只内化 Hevi 原先缺、且两条主用法(日更成片 / Veya 调成品)会用到的:
5 面分镜词、B-roll 决策、口味盘、静帧幻灯风险、源片审查、变体检查、调色计划、
网站转视频计划、Seedance 八段提示。不搬 700 份 markdown。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


def compile_shot_spec(payload: dict[str, Any]) -> dict[str, Any]:
    """Subject / Motion / Scene / Spatial / Camera 五面词。"""
    text = str(payload.get("text") or payload.get("topic") or "").strip()
    subject = str(payload.get("subject") or _first_clause(text) or "主体")
    motion = str(payload.get("motion") or "缓慢推进,保留呼吸感")
    scene = str(payload.get("scene") or "与选题相符的实景/资料空间")
    spatial = str(payload.get("spatial") or "中近景,主体居中偏左")
    camera = str(payload.get("camera") or "稳定机,微推")
    spec = {
        "subject": subject,
        "motion": motion,
        "scene": scene,
        "spatial": spatial,
        "camera": camera,
    }
    prompt = (
        f"{spec['subject']}。{spec['motion']}。"
        f"场景:{spec['scene']}。空间:{spec['spatial']}。机位:{spec['camera']}。"
    )
    return {"status": "ok", "spec": spec, "prompt": prompt}


def seedance_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """Seedance 八段结构(题材/主体/动作/场景/镜头/光线/风格/对白)。"""
    spec = compile_shot_spec(payload)["spec"]
    quote = str(payload.get("quote") or payload.get("dialogue") or "").strip()
    parts = {
        "theme": str(payload.get("topic") or spec["subject"]),
        "subject": spec["subject"],
        "action": spec["motion"],
        "scene": spec["scene"],
        "camera": spec["camera"],
        "light": str(payload.get("light") or "自然光,轮廓清楚"),
        "style": str(payload.get("style") or "写实纪录"),
        "dialogue": quote,
    }
    prompt = " / ".join(f"{k}:{v}" for k, v in parts.items() if v)
    return {"status": "ok", "components": parts, "prompt": prompt}


def plan_broll(payload: dict[str, Any]) -> dict[str, Any]:
    """stock vs generate:有可检索关键词走语料库,抽象概念才生成。"""
    text = str(payload.get("text") or payload.get("topic") or "")
    abstract = bool(
        re.search(r"概念|定理|制度|抽象|公式|原则", text)
        or payload.get("force_generate")
    )
    query = _first_clause(text) or text[:24]
    return {
        "status": "ok",
        "mode": "generate" if abstract else "stock",
        "query": query,
        "reason": "abstract-concept" if abstract else "searchable-footage",
        "sources": ["pexels", "archive", "wikimedia"] if not abstract else ["manim", "hyperframes"],
    }


def taste_dials(payload: dict[str, Any]) -> dict[str, Any]:
    """brief → 口味盘 + 反模式,给提案/构图用。"""
    brief = str(payload.get("brief") or payload.get("topic") or "")
    formal = bool(re.search(r"史|课|教材|制度|盐税|通鉴", brief))
    dials = {
        "pace": "measured" if formal else "punchy",
        "palette": "ink-paper" if formal else "high-contrast",
        "type": "serif-title" if formal else "bold-sans",
        "voice": "narration-first" if formal else "hook-first",
    }
    anti = ["圣斗士肩甲", "大头念稿", "无出处金句", "幻灯片硬切"]
    return {"status": "ok", "dials": dials, "anti_patterns": anti, "brief": brief[:200]}


def slideshow_risk(payload: dict[str, Any]) -> dict[str, Any]:
    """静帧幻灯风险:运动比过低则停交付。"""
    shots = payload.get("shots") or payload.get("cuts") or []
    still = 0
    total = 0
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        total += 1
        motion = float(shot.get("motion_ratio") or shot.get("min_motion_ratio") or 0)
        if motion < 0.08 or shot.get("kind") == "still":
            still += 1
    ratio = (still / total) if total else 0.0
    risky = total >= 3 and ratio >= 0.7
    return {
        "status": "ok",
        "still_ratio": round(ratio, 3),
        "risky": risky,
        "halt": risky,
        "reason": "slideshow" if risky else "ok",
    }


def source_review(payload: dict[str, Any]) -> dict[str, Any]:
    """源片能不能用:时长/有声/许可。"""
    duration = float(payload.get("duration_s") or 0)
    has_audio = bool(payload.get("has_audio", True))
    license_ok = bool(payload.get("license_ok", True))
    issues: list[str] = []
    if duration and duration < 4:
        issues.append("too_short")
    if not has_audio:
        issues.append("no_audio")
    if not license_ok:
        issues.append("license")
    return {
        "status": "ok" if not issues else "blocked",
        "ok": not issues,
        "issues": issues,
    }


def variation_check(payload: dict[str, Any]) -> dict[str, Any]:
    """相邻镜文案/画面描述过近则标重复。"""
    items = payload.get("items") or payload.get("script_lines") or []
    texts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            texts.append(str(item.get("text") or item.get("prompt") or ""))
        else:
            texts.append(str(item))
    dups: list[dict[str, Any]] = []
    for i in range(1, len(texts)):
        a, b = _norm(texts[i - 1]), _norm(texts[i])
        if a and a == b:
            dups.append({"index": i, "reason": "identical"})
        elif a and b and (a in b or b in a) and min(len(a), len(b)) >= 8:
            dups.append({"index": i, "reason": "near-duplicate"})
    return {"status": "ok", "duplicates": dups, "ok": not dups}


def grade_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """ffmpeg 调色计划(LUT 名 + 滤镜串),不假装已上色。"""
    look = str(payload.get("look") or "neutral")
    luts = {
        "neutral": None,
        "ink": "ink_paper",
        "teal": "teal_orange",
        "night": "cool_night",
        "warm": "warm_key",
    }
    lut = luts.get(look)
    filt = "eq=contrast=1.05:saturation=1.02"
    if look == "ink":
        filt = "eq=contrast=1.12:saturation=0.7,unsharp=3:3:0.4"
    elif look == "night":
        filt = "eq=gamma=0.92:saturation=0.9,colorbalance=rs=-0.04:bs=0.06"
    return {"status": "ok", "look": look, "lut": lut, "vf": filt}


def site_to_video_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """网站/URL → 捕获计划(不真开浏览器)。"""
    url = str(payload.get("url") or payload.get("source") or "").strip()
    if not url:
        return {"status": "failed", "reason": "url required"}
    shots = [
        {"kind": "hero", "note": "首屏 3s"},
        {"kind": "scroll", "note": "关键段落 2 处"},
        {"kind": "cta", "note": "结尾标语"},
    ]
    return {"status": "ok", "url": url, "shots": shots, "runtime": "hyperframes"}


def fingerprint_brief(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _first_clause(text: str) -> str:
    parts = re.split(r"[。！？；\n]", text.strip())
    return (parts[0] if parts else text).strip()[:40]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).strip()
