"""preflight capabilities —— 接进 hevi 统一能力注册表。

注册（与 stickman 同模式，见 hevi/stickman/capabilities.py）：
- preflight.gate：对一个 beat 跑生成前门禁，写 gate_report.json。
- preflight.compile：编译一个 beat 的模型 prompt，写 compiled_prompt.json/txt。
- preflight.passrate：对一本通过率台账出统计＋反哺报告。

门禁与编译是纯本地离线操作：不登录谷歌、不调 Flow/Gemini API。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities import Capability, CapabilityError, CapabilityResult, register
from hevi.preflight.beats import Beat, CharacterRef, DialogueLine
from hevi.preflight.compiler import compile_beat
from hevi.preflight.gate import run_gate
from hevi.preflight.passrate import PassRateLedger

_PREFLIGHT_ASPECTS = ["16:9", "9:16"]


def _beat_from_params(params: dict[str, Any]) -> Beat:
    raw = params.get("beat") or {}
    if not isinstance(raw, dict):
        raise CapabilityError("preflight: params.beat must be an object")
    characters = []
    for ch in raw.get("characters", []):
        if isinstance(ch, dict):
            characters.append(CharacterRef(
                char_id=str(ch.get("char_id", "")),
                sheet_path=ch.get("sheet_path"),
                description=str(ch.get("description", "")),
            ))
    lines = []
    for ln in raw.get("dialogue_lines", []):
        if isinstance(ln, dict):
            lines.append(DialogueLine(
                speaker=str(ln.get("speaker", "")),
                text=str(ln.get("text", "")),
            ))
    return Beat(
        beat_id=str(raw.get("beat_id", "")),
        kind=str(raw.get("kind", "dialogue")),
        scene=str(raw.get("scene", "")),
        text=str(raw.get("text", "")),
        characters=characters,
        dialogue_lines=lines,
        first_frame=raw.get("first_frame"),
        duration_s=float(raw.get("duration_s", 8.0)),
        aspect=str(raw.get("aspect", "16:9")),
        style_lock=str(raw.get("style_lock", "")),
        on_screen_text=bool(raw.get("on_screen_text", False)),
    )


def _render_gate(params, out_dir, *, duration, aspect, seed):
    beat = _beat_from_params(params)
    model = str(params.get("model", "veo_fast"))
    report = run_gate(
        beat, model,
        prompt_text=str(params.get("prompt_text", "")),
        ledger=params.get("ledger"),
        character_sheets=params.get("character_sheets"),
        allow_override=bool(params.get("allow_override", False)),
        override_reason=str(params.get("override_reason", "")),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return CapabilityResult(
        duration_s=duration,
        qa={
            "beat_id": beat.beat_id,
            "model": model,
            "verdict": report.verdict,
            "blocked": report.blocked,
            "fail_count": sum(1 for f in report.findings if f.level == "FAIL"),
            "warn_count": sum(1 for f in report.findings if f.level == "WARN"),
            "estimated_cost": report.estimated_cost,
        },
    )


def _render_compile(params, out_dir, *, duration, aspect, seed):
    beat = _beat_from_params(params)
    model = str(params.get("model", "veo_fast"))
    compiled = compile_beat(beat, model)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compiled_prompt.json").write_text(
        json.dumps(compiled.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "compiled_prompt.txt").write_text(compiled.prompt_text, encoding="utf-8")
    return CapabilityResult(
        duration_s=duration,
        qa={
            "beat_id": beat.beat_id,
            "model": model,
            "estimated_cost": compiled.estimated_cost,
            "warnings": compiled.warnings,
        },
    )


def _render_passrate(params, out_dir, *, duration, aspect, seed):
    ledger_file = params.get("ledger_file", "")
    if not ledger_file:
        raise CapabilityError("preflight.passrate: params.ledger_file is required")
    ledger = PassRateLedger(ledger_file)
    stats = ledger.stats()
    report = ledger.feedback_report()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "passrate_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "feedback_report.md").write_text(report, encoding="utf-8")
    return CapabilityResult(duration_s=duration, qa=stats)


_REGISTERED = False


def register_preflight_capabilities_once() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True
    register(Capability(
        name="preflight.gate", kind="line", aspects=_PREFLIGHT_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "beat": {"type": "object"},
                "model": {"type": "string"},
                "prompt_text": {"type": "string"},
                "allow_override": {"type": "boolean"},
                "override_reason": {"type": "string"},
            },
            "required": ["beat"],
        },
        cpu_cost_hint=0.01, render=_render_gate,
        description="生成前门禁：prompt 审计＋首帧验真＋对白适配＋预算门，FAIL 拦住不烧 credits",
        line="preflight",
    ))
    register(Capability(
        name="preflight.compile", kind="shot", aspects=_PREFLIGHT_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {
                "beat": {"type": "object"},
                "model": {"type": "string"},
            },
            "required": ["beat"],
        },
        cpu_cost_hint=0.01, render=_render_compile,
        description="分镜节拍 → 各模型专用 prompt（Veo／Omni／SVI-Film），结构化 JSON＋可读文本",
        line="preflight",
    ))
    register(Capability(
        name="preflight.passrate", kind="line", aspects=_PREFLIGHT_ASPECTS,
        params_schema={
            "type": "object",
            "properties": {"ledger_file": {"type": "string"}},
            "required": ["ledger_file"],
        },
        cpu_cost_hint=0.01, render=_render_passrate,
        description="一次通过率统计＋失败模式→模板修正反哺报告",
        line="preflight",
    ))
