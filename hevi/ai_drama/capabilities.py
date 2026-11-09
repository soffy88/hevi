"""Capability-registry surface for the ai_drama line.

Names are registered under the existing ``drama`` line:
``drama.ai_script``, ``drama.ai_storyboard``, ``drama.ai_assets``,
``drama.ai_voice``, ``drama.ai_segments``, ``drama.ai_edit``,
``drama.ai_episode``, ``drama.game_pov_ui``, ``drama.game_pov_dialogue_box``,
``drama.provider_status``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_REPORT_SCHEMA = {
    "type": "object",
    "properties": {"episode": {"type": "object"}, "out_dir": {"type": "string"}},
    "additionalProperties": True,
}

_EPISODE_SCHEMA = {
    "type": "object",
    "properties": {
        "episode": {"type": "object"},
        "theme": {"type": "string"},
        "style": {"type": "string"},
        "out_dir": {"type": "string"},
        "episode_id": {"type": "string"},
        "budget_cny": {"type": "number"},
        "provider": {"type": "string"},
        "seed": {"type": "integer"},
        "render_images": {"type": "boolean"},
        "lipsync": {"type": "boolean"},
    },
    "additionalProperties": True,
}


def _report_result(report: dict[str, Any], out_dir: Path, name: str, *, png: str | None = None,
                   mp4: str | None = None) -> CapabilityResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        mp4=mp4,
        png=png,
        sha256=compute_sha256(path),
        qa={"report_json": str(path), "passed": bool(report.get("passed", True))},
    )


def _render_script(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .compile import draft_script_from_theme
    from .rules import check_script, summarise
    from .schema import normalize_script

    if params.get("script"):
        script = normalize_script(params["script"])
    else:
        script = normalize_script(draft_script_from_theme(
            str(params.get("theme") or "一个日常里的异常"), style=str(params.get("style") or "live_action")))
    findings = check_script(script)
    report = {"passed": summarise(findings)["passed"], "script": script, "checks": summarise(findings)}
    return _report_result(report, out_dir, "ai_script")


def _render_storyboard(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .compile import compile_storyboard
    from .rules import check_storyboard, summarise
    from .schema import normalize_script, normalize_storyboard

    if params.get("storyboard"):
        sb = normalize_storyboard(params["storyboard"])
    elif params.get("script"):
        sb = normalize_storyboard(compile_storyboard(normalize_script(params["script"])))
    else:
        raise CapabilityError("drama.ai_storyboard 需要 script 或 storyboard")
    findings = check_storyboard(sb, normalize_script(params["script"]) if params.get("script") else None)
    report = {"passed": summarise(findings)["passed"], "storyboard": sb, "checks": summarise(findings)}
    return _report_result(report, out_dir, "ai_storyboard")


def _render_assets(params: dict, out_dir: Path, *, seed: int = 42, **_: Any) -> CapabilityResult:
    from .assets import build_assets, render_assets
    from .rules import check_assets, summarise
    from .schema import normalize_script, normalize_storyboard

    script = normalize_script(params["script"])
    assets = build_assets(script)
    paths = render_assets(assets, out_dir / "assets", seed=seed) if params.get("render_images", True) else {}
    findings = check_assets(assets, script, normalize_storyboard(params.get("storyboard") or {"segments": []}))
    report = {"passed": summarise(findings)["passed"], "assets": assets, "paths": paths,
              "checks": summarise(findings)}
    return _report_result(report, out_dir, "ai_assets")


def _render_voice(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .rules import check_script, summarise
    from .schema import normalize_script
    from .voice import attach_references, build_voice_plan

    script = normalize_script(params["script"])
    plan = build_voice_plan(script, out_dir / "voice")
    plan = attach_references(plan, out_dir / "voice" / "references")
    findings = check_script(script)
    report = {"passed": summarise(findings)["passed"], "voice_plan": plan,
              "references": {cid: c.get("reference") for cid, c in plan["characters"].items()},
              "checks": summarise(findings)}
    return _report_result(report, out_dir, "ai_voice")


def _render_segments(params: dict, out_dir: Path, *, seed: int = 42, **_: Any) -> CapabilityResult:
    from .assets import build_assets, render_assets
    from .credits import CreditLedger
    from .render import render_segments, render_shots
    from .schema import normalize_script, normalize_storyboard
    from .voice import attach_references, build_voice_plan, fit_storyboard_to_audio

    script = normalize_script(params["script"])
    sb = normalize_storyboard(params["storyboard"])
    assets = build_assets(script)
    paths = render_assets(assets, out_dir / "assets", seed=seed) if params.get("render_images", True) else {}
    plan = attach_references(build_voice_plan(script, out_dir / "voice"), out_dir / "voice" / "references")
    fit_storyboard_to_audio(sb, plan)
    ledger = CreditLedger(out_dir / "credit_ledger.jsonl", episode_id=str(params.get("episode_id") or ""),
                          cap_cny=params.get("budget_cny"))
    shots = render_shots(sb, script, assets, paths, plan, out_dir, ledger=ledger,
                         prefer_provider=params.get("provider"), lipsync=params.get("lipsync"), seed=seed)
    segments = render_segments(sb, shots["clips"], out_dir)
    report = {"passed": True, "provider": shots["provider"], "providers": shots["providers"],
              "shots": shots["clips"], "segments": segments, "ledger": ledger.report()}
    return _report_result(report, out_dir, "ai_segments", mp4=next(iter(segments.values()), None))


def _render_edit(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .edit import build_edit, export_fcpxml, export_jianying_plan
    from .rules import check_edit, check_game_pov, summarise
    from .schema import normalize_script, normalize_storyboard

    script = normalize_script(params["script"])
    sb = normalize_storyboard(params["storyboard"])
    edit = build_edit(sb, script, params.get("voice_plan") or {"lines": {}}, out_dir)
    findings = check_edit(edit, script, sb)
    if script.get("style") == "game_pov":
        findings += check_game_pov(script, sb, edit)
    export_fcpxml(edit, out_dir / "timeline.fcpxml")
    export_jianying_plan(edit, out_dir / "jianying_plan.json")
    report = {"passed": summarise(findings)["passed"], "edit": edit, "checks": summarise(findings)}
    return _report_result(report, out_dir, "ai_edit")


def _render_episode(params: dict, out_dir: Path, *, seed: int = 42, **_: Any) -> CapabilityResult:
    from .pipeline import Pipeline

    episode = params.get("episode")
    if not episode:
        episode = {"theme": params.get("theme"), "style": params.get("style", "live_action")}
    report = Pipeline(
        out_dir,
        episode_id=str(params.get("episode_id") or "ai_drama_episode"),
        budget_cny=params.get("budget_cny"),
        prefer_provider=params.get("provider"),
        seed=seed,
        lipsync=params.get("lipsync"),
        render_images=bool(params.get("render_images", True)),
    ).run(episode)
    deliverable = report.get("delivery", {}).get("deliverable")
    return _report_result(report, out_dir, "ai_episode", mp4=deliverable)


def _render_game_ui(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .game_pov import FONT_LICENSE, make_ui_png

    text = str(params.get("text") or "继续")
    png = make_ui_png(text, out_dir / "ui_overlay.png")
    report = {"passed": True, "text": text, "png": str(png), "font_license": FONT_LICENSE}
    return _report_result(report, out_dir, "game_pov_ui", png=str(png))


def _render_game_box(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .game_pov import game_dialogue_box

    video = Path(str(params["video"]))
    if not video.is_file():
        raise CapabilityError(f"drama.game_pov_dialogue_box: video 不存在: {video}")
    result = game_dialogue_box(video, params.get("edit") or {"subtitles": []}, out_dir / "dialogue_box.mp4")
    report = {"passed": True, **result}
    return _report_result(report, out_dir, "game_pov_dialogue_box", mp4=result["video"])


def _render_provider_status(params: dict, out_dir: Path, **_: Any) -> CapabilityResult:
    from .credits import budget_cap, price_for
    from .providers import select_provider

    selected, status = select_provider(prefer=params.get("provider"))
    report = {
        "passed": True,
        "selected": selected.name,
        "providers": status,
        "budget_cap_cny": budget_cap(),
        "prices": {name: price_for(name, 5.0) for name in ("offline", "runninghub_h3", "minimax_h3_api", "wan")},
        "note": "价格是计划用估算，不是供应商报价；付费前先跑 1 段 5s 预览实测。",
    }
    return _report_result(report, out_dir, "provider_status")


def register_ai_drama_capabilities_once() -> None:
    global _Registered
    if _Registered:
        return
    common = {"aspects": ["9:16"], "line": "ai_drama", "has_media_output": False}
    register(Capability(name="drama.ai_script", kind="line", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=0.0, render=_render_script, description="主题/剧本 -> 结构化短剧剧本 + 自检", **common))
    register(Capability(name="drama.ai_storyboard", kind="line", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=0.0, render=_render_storyboard, description="剧本 -> 段/镜头分镜 + 切镜规则", **common))
    register(Capability(name="drama.ai_assets", kind="line", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=2.0, render=_render_assets, description="资产身份板/场景空镜/道具 + @图片N", **common))
    register(Capability(name="drama.ai_voice", kind="line", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=1.0, render=_render_voice, description="每角色固定音色 + 3-8s 音频参考", **common))
    register(Capability(name="drama.ai_segments", kind="shot", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=8.0, render=_render_segments, description="镜头 -> 视频段（provider 抽象）", **{**common, "has_media_output": True}))
    register(Capability(name="drama.ai_edit", kind="line", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=0.0, render=_render_edit, description="剪辑单/字幕/FCPXML/剪映 plan", **common))
    register(Capability(name="drama.ai_episode", kind="shot", params_schema=_EPISODE_SCHEMA,
                        cpu_cost_hint=20.0, render=_render_episode, description="主题/剧本 -> 9:16 成片（离线可出片）", **{**common, "has_media_output": True}))
    register(Capability(name="drama.game_pov_ui", kind="overlay", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=0.1, render=_render_game_ui, description="game_pov 透明交互提示 PNG", **{**common, "has_media_output": True}))
    register(Capability(name="drama.game_pov_dialogue_box", kind="overlay", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=1.0, render=_render_game_box, description="游戏对话框字幕（蒙版+羽化+模糊+像素字）", **{**common, "has_media_output": True}))
    register(Capability(name="drama.provider_status", kind="line", params_schema=_REPORT_SCHEMA,
                        cpu_cost_hint=0.0, render=_render_provider_status, description="H3 provider 可用性/价格/预算", **common))
    _Registered = True
