"""AI short-drama screenwriter wrapper.

This is a product boundary around the existing director screenplay generator:
it adds the standalone short-drama contract, a script-only output mode, and a
review report that can be handed to storyboard production without pretending
that a script is already a shot list.
"""

from __future__ import annotations

from typing import Any

from hevi.director.pipeline_schemas import Screenplay


def review_screenplay(screenplay: Screenplay) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for scene in screenplay.scenes:
        if not scene.location:
            findings.append({"scene_no": scene.scene_no, "severity": "warning", "code": "missing_location", "message": "场景缺少地点，后续分镜需要人工确认。"})
        if not scene.visual_actions and not scene.narration:
            findings.append({"scene_no": scene.scene_no, "severity": "error", "code": "no_visual_action", "message": "场景没有可拍动作或叙述。"})
        if not scene.dialogue and not scene.narration:
            findings.append({"scene_no": scene.scene_no, "severity": "warning", "code": "silent_scene", "message": "场景没有对白或旁白。"})
        names = set(scene.characters_present)
        unknown = sorted({line.character_name for line in scene.dialogue if line.character_name and line.character_name not in names})
        if unknown:
            findings.append({"scene_no": scene.scene_no, "severity": "warning", "code": "character_not_present", "message": f"对白人物未列入出场表: {', '.join(unknown)}"})
    errors = sum(item["severity"] == "error" for item in findings)
    return {
        "passed": errors == 0 and bool(screenplay.scenes),
        "score": max(0, 100 - errors * 25 - sum(item["severity"] == "warning" for item in findings) * 5),
        "scene_count": len(screenplay.scenes),
        "findings": findings,
        "handoff": "storyboard/video-prompts" if errors == 0 else "screenplay-revision",
        "scope": "script-only; 不生成分镜或视频提示词",
    }


def screenplay_markdown(screenplay: Screenplay, *, title: str = "短剧单集") -> str:
    lines = [f"# {title}", ""]
    for scene in screenplay.scenes:
        slug = " · ".join(item for item in (scene.int_ext or "内", scene.location or "待定地点", scene.day_night or scene.time or "待定时间") if item)
        lines.extend([f"## SC{scene.scene_no:03d} {slug}", ""])
        if scene.event_summary:
            lines.append(scene.event_summary)
        if scene.narration:
            lines.append(scene.narration)
        lines.extend(action for action in scene.visual_actions if action and action != scene.narration)
        for line in scene.dialogue:
            speaker = line.character_name or "旁白"
            target = f" → {line.target_name}" if line.target_name else ""
            lines.append(f"{speaker}{target}：{line.text}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


__all__ = ["review_screenplay", "screenplay_markdown"]
