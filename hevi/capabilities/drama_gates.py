"""Pre-generation gates for drama episodes -- ``story.drama_gates``.

Runs nine checks over a prompt package produced by ``story.episode_prompts``
before any generation credit is spent:

1. ``completeness`` -- every shot must carry characters, scene, action,
   dialogue (an explicitly empty dialogue list is a pure-visual shot and
   is allowed when action is present; a *missing* dialogue field is not),
   camera, style, duration, negatives and first frame. One blocker per
   missing item.
2. ``first_frame`` -- empty first-frame text is a blocker; first-frame
   text mentioning neither the shot's scene-name keywords nor any of the
   shot's character names is a major.
3. ``duration_dialogue`` -- total duration outside 240-360s is a blocker;
   total dialogue over 1300 chars is a blocker (cut scenes, do not speed
   up delivery); a single shot over 60s is a major.
4. ``budget`` -- ``est_credits = ceil(total_sec / 8) * credits_per_8s``;
   over ``max_credits`` is a fail-closed blocker.
5. ``script_polish`` -- hard gate: ``story.script_polish`` is invoked in
   deterministic mode via the registry (``render_safe``, so its schema
   is validated, not bypassed); any of its blockers becomes a blocker
   here, carrying the original blocker content. ``rewrite_round``
   over 2 is a stop-and-report blocker.
6. ``ledger`` -- every run appends one line to
   ``out_dir/drama_pass_ledger.jsonl`` with episode_no, passed, counts,
   failed_checks and timestamp; the report carries the ledger path.
7. ``action_nodes`` -- one action node per shot: 2 nodes is a major,
   3 or more is a blocker. A shot with no node information at all is a
   blocker (fail-closed: the compiler always emits nodes, so a package
   without them was not built by the compiler).
8. ``spatial_continuity`` -- a shot without a spatial layout is a
   blocker; within one scene, the static layout fields (door, table,
   light -- architecture and light do not move) must match the scene's
   first shot, field by field; any mismatch is a blocker. Key props and
   character positions move legitimately and are NOT continuity-checked.
9. ``edit_ready`` -- wired to ``story.edit_assemble``: when the caller
   passes an ``edit_report`` (the ``build_edl`` payload, with its
   ``edit_ready`` flag and ``findings``), a clean report passes this
   check and any blocker finding in the report becomes a blocker
   here (a report claiming ``edit_ready`` true while carrying a
   blocker is treated as a blocker, fail-closed). A clean report
   whose ``ffmpeg.status`` is ``"pending"`` stays pending, not
   passed: no executable assemble command exists yet. Without an
   ``edit_report`` the check stays ``pending`` (never a fake pass);
   a bare ``edl`` without a report does NOT pass it. Pending never
   affects ``passed`` and is counted separately under
   ``counts["pending"]``.

Verdict: ``passed`` is true only when there are zero blockers. Majors,
minors and pendings do not fail the gate. Fully offline and deterministic:
no Monid, no network -- script_polish runs in deterministic mode only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hevi.capabilities.script_polish  # noqa: F401 - import registers story.script_polish
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    get as _registry_get,
    register,
)

_Registered = False

MISSING = "[缺失]"

_SEGMENT_NAMES = [
    "角色锁定",
    "场景锁定",
    "动作",
    "对白",
    "镜头",
    "风格",
    "时长",
    "否定约束",
    "首帧参照",
]


def _finding(
    check: str,
    severity: str,
    issue: str,
    suggestion: str,
    shot_id: str | None = None,
    scene_id: str | None = None,
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "shot_id": shot_id,
        "scene_id": scene_id,
        "issue": issue,
        "suggestion": suggestion,
    }


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def _parse_prompt_segments(prompt_text: str) -> dict[str, str]:
    """Split a compiled prompt_text into its 9 named segments."""
    segments: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    def _flush() -> None:
        if current is not None:
            segments[current] = "\n".join(buf).strip()

    for line in (prompt_text or "").splitlines():
        stripped = line.strip()
        header = None
        if stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1]
            if inner in _SEGMENT_NAMES:
                header = inner
        if header is not None:
            _flush()
            current = header
            buf = []
        elif current is not None:
            buf.append(line)
    _flush()
    return segments


def _parse_layout_line(scene_text: str | None) -> dict[str, Any] | None:
    """Recover a spatial layout from a compiled [场景锁定] segment.

    The compiler appends a ``空间布局：门：…；桌：…；光源：…`` line; parse
    back only the static fields (door/table/light). Returns None when no
    layout line is present.
    """
    if not scene_text:
        return None
    labels = {"门": "door", "桌": "table", "光源": "light"}
    layout: dict[str, Any] = {}
    for line in scene_text.splitlines():
        if not line.startswith("空间布局"):
            continue
        body = line.split("：", 1)[-1] if "：" in line else line
        for part in re.split(r"[；;]", body):
            part = part.strip()
            if "：" in part:
                label, value = part.split("：", 1)
            elif ":" in part:
                label, value = part.split(":", 1)
            else:
                continue
            key = labels.get(label.strip())
            if key and value.strip():
                layout[key] = value.strip()
    return layout or None


def _parse_action_nodes_from_text(action_text: str | None) -> list[str] | None:
    """Count action-node lines in a compiled [动作] segment.

    Returns None when the segment carries no node lines at all (package
    predates the node contract); otherwise the node texts.
    """
    if not action_text:
        return None
    nodes: list[str] = []
    for line in action_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("动作节点"):
            text = stripped.split("：", 1)[-1].strip() if "：" in stripped else stripped
            nodes.append(text)
    return nodes or None


def _shot_fields(shot: dict[str, Any]) -> dict[str, Any]:
    """Normalize one package shot to gate-checkable fields.

    Blocks (from the compiler) are authoritative when present; otherwise
    the prompt_text segments are parsed, with a literal [缺失] segment
    meaning the field is missing.
    """
    blocks = shot.get("blocks") if isinstance(shot.get("blocks"), dict) else {}
    shot_id = _as_str(shot.get("shot_id", "")) or None
    if blocks:
        chars = blocks.get("characters")
        char_names: list[str] = []
        if isinstance(chars, list):
            for entry in chars:
                if isinstance(entry, dict):
                    char_names.append(_as_str(entry.get("name", entry.get("id", ""))))
                else:
                    char_names.append(_as_str(entry))
        elif isinstance(chars, str):
            char_names = [chars] if chars.strip() else []
        char_ids = blocks.get("character_ids")
        if not char_names and isinstance(char_ids, list):
            char_names = [_as_str(c) for c in char_ids]
        if not char_names and isinstance(blocks.get("character_names"), list):
            char_names = [_as_str(c) for c in blocks["character_names"]]
        dialogue = blocks.get("dialogue")
        nodes_raw = blocks.get("action_nodes")
        if isinstance(nodes_raw, list):
            action_nodes: list[Any] | None = nodes_raw
        else:
            action_nodes = None
        layout_raw = blocks.get("spatial_layout")
        spatial_layout = layout_raw if isinstance(layout_raw, dict) else None
        return {
            "shot_id": shot_id,
            "characters": char_names,
            "scene_id": _nonempty(blocks.get("scene_id")),
            "scene_name": _nonempty(blocks.get("scene_name")),
            "scene": _nonempty(blocks.get("scene")),
            "spatial_layout": spatial_layout,
            "action": _nonempty(blocks.get("action")),
            "action_nodes": action_nodes,
            "dialogue": dialogue,
            "camera": _nonempty(blocks.get("camera")),
            "style": _nonempty(blocks.get("style")),
            "duration_sec": blocks.get("duration_sec", blocks.get("duration")),
            "negatives": blocks.get("negatives"),
            "first_frame": _nonempty(blocks.get("first_frame")),
        }
    segments = _parse_prompt_segments(_as_str(shot.get("prompt_text", "")))

    def _seg(name: str) -> str | None:
        text = segments.get(name)
        if text is None or text == MISSING:
            return None
        return text

    dialogue_seg = segments.get("对白")
    if dialogue_seg is None or dialogue_seg == MISSING:
        dialogue: Any = None
    elif "纯视觉镜" in dialogue_seg:
        dialogue = []
    else:
        dialogue = [line for line in dialogue_seg.splitlines() if line.strip()]
    duration_text = _seg("时长")
    duration_sec: Any = None
    if duration_text:
        m = re.search(r"(\d+(?:\.\d+)?)", duration_text)
        if m:
            duration_sec = float(m.group(1))
    negatives_seg = _seg("否定约束")
    negatives = (
        [line[1:].strip() for line in negatives_seg.splitlines() if line.strip()]
        if negatives_seg
        else None
    )
    scene_seg = _seg("场景锁定")
    action_seg = _seg("动作")
    return {
        "shot_id": shot_id,
        "characters": [c for c in (_seg("角色锁定") or "").splitlines() if c.strip()],
        "scene_id": None,
        "scene_name": None,
        "scene": scene_seg,
        "spatial_layout": _parse_layout_line(scene_seg),
        "action": action_seg,
        "action_nodes": _parse_action_nodes_from_text(action_seg),
        "dialogue": dialogue,
        "camera": _seg("镜头"),
        "style": _seg("风格"),
        "duration_sec": duration_sec,
        "negatives": negatives,
        "first_frame": _seg("首帧参照"),
    }


def _check_completeness(fields_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for f in fields_list:
        sid = f["shot_id"]
        scene_id = f["scene_id"]
        if not f["characters"]:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺角色：未指定任何角色。",
                    "给本镜指定至少一个 bible 中的角色，或删掉本镜。",
                    sid, scene_id,
                )
            )
        if f["scene"] is None and f["scene_id"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺场景：未指定场景。",
                    "给本镜指定一个 bible 中的场景。",
                    sid, scene_id,
                )
            )
        elif f["scene"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺场景锁定块：场景已指定但无锁定场景块。",
                    "给该场景补锁定场景块，或换一个有锁定块的场景。",
                    sid, scene_id,
                )
            )
        if f["action"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺动作：动作描述为空。",
                    "补写本镜看得见的动作（带支撑点/方向幅度/停止位置），不要只写氛围。",
                    sid, scene_id,
                )
            )
        dialogue = f["dialogue"]
        if dialogue is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺对白字段：对白字段缺失（不是纯视觉镜）。",
                    "补写本镜对白，或明确把对白置为空列表声明为纯视觉镜。",
                    sid, scene_id,
                )
            )
        elif isinstance(dialogue, list) and dialogue:
            empty_lines = [
                d for d in dialogue
                if isinstance(d, dict) and not _as_str(d.get("text", "")).strip()
            ]
            if empty_lines:
                findings.append(
                    _finding(
                        "completeness", "blocker",
                        f"镜 {sid} 对白文本为空：有说话人但无台词文本。",
                        "补写台词，或删掉这条对白。",
                        sid, scene_id,
                    )
                )
        if f["camera"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺镜头描述。",
                    "补写本镜镜头（机位/运动/景别）。",
                    sid, scene_id,
                )
            )
        if f["style"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺风格描述。",
                    "补写本镜风格描述，与全集风格锁定一致。",
                    sid, scene_id,
                )
            )
        if f["duration_sec"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺时长（duration_sec）。",
                    "给本镜标时长（秒），并复核全集总时长在 240-360 秒内。",
                    sid, scene_id,
                )
            )
        negatives = f["negatives"]
        if negatives is None or (isinstance(negatives, list) and not negatives):
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺否定约束。",
                    "补否定约束，至少含四条默认否定：不换脸、不加无关人物、"
                    "不出文字 artifact、不出品牌 logo。",
                    sid, scene_id,
                )
            )
        if f["first_frame"] is None:
            findings.append(
                _finding(
                    "completeness", "blocker",
                    f"镜 {sid} 缺首帧参照文本。",
                    "补写本镜首帧参照文本，须提及本镜场景与人物。",
                    sid, scene_id,
                )
            )
    return findings


def _scene_keywords(scene_name: str | None, scene_id: str | None) -> list[str]:
    candidates: list[str] = []
    for raw in (scene_name, scene_id):
        if not raw:
            continue
        if raw not in candidates:
            candidates.append(raw)
        for part in re.split(r"[·、，, /()（）\s]+", raw):
            if len(part) >= 2 and part not in candidates:
                candidates.append(part)
    return candidates


def _check_first_frame(fields_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for f in fields_list:
        sid = f["shot_id"]
        scene_id = f["scene_id"]
        ff = f["first_frame"]
        if ff is None:
            findings.append(
                _finding(
                    "first_frame", "blocker",
                    f"镜 {sid} 首帧文本为空。",
                    "补写首帧参照文本，须提及本镜场景名关键词与本镜人物名。",
                    sid, scene_id,
                )
            )
            continue
        scene_hit = any(kw and kw in ff for kw in _scene_keywords(f["scene_name"], f["scene_id"]))
        char_hit = any(
            name and name in ff for name in (f["characters"] or [])
        )
        # Without a scene name or character names to check against, there is
        # nothing to verify -- do not invent a false major.
        if f["scene_name"] is None and f["scene_id"] is None and not f["characters"]:
            continue
        if not scene_hit and not char_hit:
            findings.append(
                _finding(
                    "first_frame", "major",
                    f"镜 {sid} 首帧未提及本镜场景名关键词，也未提及任一本镜人物名。",
                    "首帧文本里写明本镜场景与至少一位本镜人物，否则首帧验真无从对齐。",
                    sid, scene_id,
                )
            )
    return findings


def _check_duration_dialogue(
    fields_list: list[dict[str, Any]],
    total_sec: float | None,
    total_dialogue_chars: int | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if total_sec is not None and not (240 <= total_sec <= 360):
        findings.append(
            _finding(
                "duration_dialogue", "blocker",
                f"全集总时长 {total_sec:g} 秒，超出 240-360 秒范围。",
                "增删镜次或调整单镜时长，使总时长回到 240-360 秒。",
            )
        )
    if total_dialogue_chars is not None and total_dialogue_chars > 1300:
        findings.append(
            _finding(
                "duration_dialogue", "blocker",
                f"对白总字数 {total_dialogue_chars} 字，超出 1300 字上限。",
                "超了砍场景不加速念：删减镜次/台词，把对白压回 1300 字内，"
                "不要靠加快语速硬塞。",
            )
        )
    for f in fields_list:
        dur = f["duration_sec"]
        if isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur > 60:
            findings.append(
                _finding(
                    "duration_dialogue", "major",
                    f"镜 {f['shot_id']} 单镜时长 {dur:g} 秒，超过 60 秒。",
                    "把本镜拆成两镜，或压缩动作/对白到 60 秒内。",
                    f["shot_id"], f["scene_id"],
                )
            )
    return findings


def _check_budget(
    total_sec: float | None, budget: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], int | float | None]:
    if budget is None:
        return [], None
    findings: list[dict[str, Any]] = []
    max_credits = budget.get("max_credits")
    per_8s = budget.get("credits_per_8s")
    if not isinstance(max_credits, (int, float)) or isinstance(max_credits, bool):
        findings.append(
            _finding(
                "budget", "blocker",
                "预算缺少 max_credits（数字），无法做预算门。",
                "在 budget 里给出 max_credits（数字）。",
            )
        )
        return findings, None
    if not isinstance(per_8s, (int, float)) or isinstance(per_8s, bool):
        findings.append(
            _finding(
                "budget", "blocker",
                "预算缺少 credits_per_8s（数字），无法做预算门。",
                "在 budget 里给出 credits_per_8s（每 8 秒单价，数字）。",
            )
        )
        return findings, None
    if total_sec is None:
        return [], None
    est = math.ceil(total_sec / 8) * per_8s
    if est > max_credits:
        findings.append(
            _finding(
                "budget", "blocker",
                f"预估花费 {est:g} credits，超出预算上限 {max_credits:g} credits。",
                "降时长或降单价模型：缩短总时长，或换更低单价的生成模型，"
                "把预估压回预算内再生成。",
            )
        )
    return findings, est


def _check_action_nodes(fields_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for f in fields_list:
        sid = f["shot_id"]
        scene_id = f["scene_id"]
        nodes = f.get("action_nodes")
        if nodes is None:
            findings.append(
                _finding(
                    "action_nodes", "blocker",
                    f"镜 {sid} 缺动作节点信息：包里没有 action_nodes（非编译器产物）。",
                    "用 story.episode_prompts 重新编译本集，拿到每镜的动作节点后再跑门。",
                    sid, scene_id,
                )
            )
            continue
        count = len(nodes)
        if count == 0:
            findings.append(
                _finding(
                    "action_nodes", "blocker",
                    f"镜 {sid} 动作节点为空：本镜没有可执行的动作节点。",
                    "给本镜补一个动作节点，或删掉本镜。",
                    sid, scene_id,
                )
            )
        elif count == 2:
            findings.append(
                _finding(
                    "action_nodes", "major",
                    f"镜 {sid} 含 2 个动作节点，超过一镜一动作节点的约定。",
                    "把本镜拆成两镜，每镜只留一个动作节点；或删掉次要的那个节点。",
                    sid, scene_id,
                )
            )
        elif count >= 3:
            findings.append(
                _finding(
                    "action_nodes", "blocker",
                    f"镜 {sid} 含 {count} 个动作节点，超过一镜一动作节点的约定。",
                    "把本镜拆成多镜，每镜只留一个动作节点；不要靠压缩时长硬塞。",
                    sid, scene_id,
                )
            )
    return findings


SPATIAL_STATIC_FIELDS = ["door", "table", "light"]


def _static_value(layout: dict[str, Any] | None, field: str) -> str | None:
    if not isinstance(layout, dict):
        return None
    return _nonempty(layout.get(field))


def _check_spatial_continuity(fields_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    first_layout_by_scene: dict[str, dict[str, Any]] = {}
    for f in fields_list:
        sid = f["shot_id"]
        scene_id = f["scene_id"]
        layout = f.get("spatial_layout")
        if layout is None:
            findings.append(
                _finding(
                    "spatial_continuity", "blocker",
                    f"镜 {sid} 缺空间布局：没有 spatial_layout，无法做空间连续性检查。",
                    "给本镜补空间布局（门／桌／光源的相对位置与人物站位朝向），"
                    "或给场景补 layout，再重新编译。",
                    sid, scene_id,
                )
            )
            continue
        if scene_id is None:
            continue
        if scene_id not in first_layout_by_scene:
            first_layout_by_scene[scene_id] = layout
            continue
        reference = first_layout_by_scene[scene_id]
        for field in SPATIAL_STATIC_FIELDS:
            want = _static_value(reference, field)
            got = _static_value(layout, field)
            if want != got:
                label = {"door": "门", "table": "桌", "light": "光源"}[field]
                findings.append(
                    _finding(
                        "spatial_continuity", "blocker",
                        f"镜 {sid} 空间布局与同场景首镜不一致（{label}）："
                        f"首镜为 {want or '缺失'}，本镜为 {got or '缺失'}。",
                        "建筑与光源不随镜次移动：把本镜的门／桌／光源改回"
                        "同场景首镜的布局，或修正首镜布局后全集重编。",
                        sid, scene_id,
                    )
                )
    return findings


def _check_edit_ready(edl: Any, edit_report: Any = None) -> list[dict[str, Any]]:
    """Edit-assembly gate, wired to the ``story.edit_assemble`` report.

    Additive wiring only; the no-report semantics are unchanged:

    * No ``edit_report``: always pending, exactly as before. A bare
      ``edl`` without a report does not pass this check.
    * Clean report (``edit_ready`` true and no blocker finding):
      no finding at all, so the check passes.
    * Report carrying any blocker finding: one blocker finding per
      report blocker, re-issued under ``edit_ready`` with the
      original issue, suggestion, shot and scene carried over.
    * Contradiction, fail-closed: ``edit_ready`` true with a blocker
      finding, or ``edit_ready`` false with no blocker finding,
      both yield a blocker, never a silent pass.
    * C-08: a clean report whose ``ffmpeg.status`` is ``"pending"``
      (e.g. no subtitle_file, so no assemble command was generated)
      yields a pending finding, not a pass: "gates passed" must not
      hide "there is no executable assemble command yet".
    * Unusable report (not a dict, or ``edit_ready`` not a bool):
      pending, with the reason stated; never a fake pass.
    """
    if edit_report is None:
        if edl is None:
            issue = "剪辑就绪门未实现：EDL 缺失，状态 pending（占位，不伪造通过）。"
        else:
            issue = "剪辑就绪门未实现：EDL 已提供，但未传入 edit_assemble 报告，状态 pending。"
        return [
            _finding(
                "edit_ready", "pending",
                issue,
                "传入 story.edit_assemble 的 build_edl 报告（edit_report 参数）"
                "后再跑本门；在此之前不要把 pending 当成通过。",
            )
        ]
    if not isinstance(edit_report, dict) or not isinstance(
        edit_report.get("edit_ready"), bool
    ):
        return [
            _finding(
                "edit_ready", "pending",
                "剪辑就绪门无法判定：传入的 edit_report 不是可用的 "
                "edit_assemble 报告（须为含 edit_ready 布尔值的对象），状态 pending。",
                "传入 story.edit_assemble 的 build_edl 原样报告后再跑本门；"
                "不要把 pending 当成通过。",
            )
        ]
    raw_findings = edit_report.get("findings")
    report_findings = raw_findings if isinstance(raw_findings, list) else []
    blockers = [
        f for f in report_findings
        if isinstance(f, dict) and f.get("severity") == "blocker"
    ]
    if edit_report["edit_ready"] and not blockers:
        ffmpeg = edit_report.get("ffmpeg")
        if isinstance(ffmpeg, dict) and ffmpeg.get("status") == "pending":
            return [
                _finding(
                    "edit_ready", "pending",
                    "剪辑就绪门未通过：edit_assemble 报告 edit_ready 为 true，"
                    "但 ffmpeg 组装命令仍为 pending（未生成可执行命令，"
                    "如未提供 subtitle_file），状态 pending，不计入通过。",
                    "提供 subtitle_file 后重跑 story.edit_assemble，拿到"
                    " ffmpeg 命令后再跑本门；不要把 pending 当成通过。",
                )
            ]
        return []
    if blockers:
        return [
            _finding(
                "edit_ready", "blocker",
                f"edit_assemble 报告 blocker 透传：{f.get('issue', '')}",
                f"按 edit_assemble 建议处理：{f.get('suggestion', '')}",
                f.get("shot_id") if isinstance(f.get("shot_id"), str) else None,
                f.get("scene_id") if isinstance(f.get("scene_id"), str) else None,
            )
            for f in blockers
        ]
    return [
        _finding(
            "edit_ready", "blocker",
            "edit_assemble 报告 edit_ready 为 false，但未附 blocker 详情，"
            "fail-closed 拦住。",
            "检查 edit_assemble 报告的 findings 与 counts，修好剪辑问题后再跑本门。",
        )
    ]


def _check_script_polish(
    title: str,
    must_know: list[dict[str, Any]],
    episode_scenes: Any,
    rewrite_round: int,
    out_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    info: dict[str, Any] = {"passed": True, "blocker_count": 0}
    if not isinstance(episode_scenes, list) or not episode_scenes:
        findings.append(
            _finding(
                "script_polish", "blocker",
                "无法运行 script_polish 硬门：episode_scenes 为空或缺失。",
                "传入供 script_polish 用的结构化场 episode_scenes（scene_id、"
                "header、characters、action、dialogue），再跑本门。",
            )
        )
        info["passed"] = False
        info["blocker_count"] = 1
        return findings, info
    sp_params = {
        "title": title,
        "intent": {"must_know": must_know},
        "scenes": episode_scenes,
        "mode": "deterministic",
    }
    try:
        # S-05: go through the registry (render_safe = schema validation
        # + render), never the private _render — so script_polish schema
        # or registration changes are felt here instead of bypassed.
        result = _registry_get("story.script_polish").render_safe(
            sp_params, Path(out_dir), duration=0.0, aspect="16:9", seed=42
        )
        sp_payload = result.qa
        sp_blockers = [
            f for f in sp_payload.get("findings", []) if f.get("severity") == "blocker"
        ]
        info["passed"] = len(sp_blockers) == 0
        info["blocker_count"] = len(sp_blockers)
        info["report_json"] = sp_payload.get("report_json")
        for orig in sp_blockers:
            scene_ref = orig.get("scene_id") or ""
            findings.append(
                _finding(
                    "script_polish", "blocker",
                    f"script_polish blocker 透传（{scene_ref}）：{orig.get('issue', '')}",
                    f"按 script_polish 建议处理：{orig.get('suggestion', '')}",
                    None,
                    scene_ref or None,
                )
            )
    except CapabilityError as exc:
        info["passed"] = False
        info["blocker_count"] = 1
        findings.append(
            _finding(
                "script_polish", "blocker",
                f"script_polish 硬门运行失败（fail-closed）：{exc}",
                "修好剧本输入（scenes/intent 结构）后再跑本门，不要绕过硬门生成。",
            )
        )
    if isinstance(rewrite_round, int) and rewrite_round > 2:
        findings.append(
            _finding(
                "script_polish", "blocker",
                f"改写轮次 rewrite_round={rewrite_round}，已超过 2 轮上限。",
                "停下报用户：改写已超 2 轮，停止自动改写，把本集问题与改写记录"
                "报给用户定夺，不要继续静默改写。",
            )
        )
        info["passed"] = False
        info["blocker_count"] = info.get("blocker_count", 0) + 1
    return findings, info


def _append_ledger(
    out_dir: Path, payload: dict[str, Any]
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = out_dir / "drama_pass_ledger.jsonl"
    entry = {
        "episode_no": payload.get("episode_no"),
        "passed": payload.get("passed"),
        "counts": payload.get("counts"),
        "failed_checks": payload.get("failed_checks"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return ledger


def run_drama_gates(params: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """Pure gate logic except the ledger append and report write (via _render)."""
    pkg = params.get("prompt_package") or params.get("package")
    if not isinstance(pkg, dict) and isinstance(params.get("shots"), list):
        pkg = params
    if not isinstance(pkg, dict):
        raise CapabilityError(
            "story.drama_gates: provide 'prompt_package' (story.episode_prompts output)"
        )
    shots = pkg.get("shots", []) or []
    if not isinstance(shots, list):
        raise CapabilityError("story.drama_gates: 'prompt_package.shots' must be a list")
    fields_list = []
    for shot in shots:
        if not isinstance(shot, dict):
            raise CapabilityError("story.drama_gates: each shot must be an object")
        fields_list.append(_shot_fields(shot))

    total_sec = pkg.get("total_duration_sec")
    if not isinstance(total_sec, (int, float)) or isinstance(total_sec, bool):
        durations = [
            f["duration_sec"] for f in fields_list
            if isinstance(f["duration_sec"], (int, float))
        ]
        total_sec = sum(durations) if durations else None
    else:
        total_sec = float(total_sec)
    total_dialogue_chars = pkg.get("total_dialogue_chars")
    if not isinstance(total_dialogue_chars, int) or isinstance(total_dialogue_chars, bool):
        total_dialogue_chars = None
        for f in fields_list:
            dlg = f["dialogue"]
            if isinstance(dlg, list):
                for d in dlg:
                    if isinstance(d, dict):
                        total_dialogue_chars = (total_dialogue_chars or 0) + len(
                            _as_str(d.get("text", ""))
                        )
                    else:
                        total_dialogue_chars = (total_dialogue_chars or 0) + len(
                            _as_str(d)
                        )

    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    comp = _check_completeness(fields_list)
    findings.extend(comp)
    checks["completeness"] = {
        "passed": not any(f["severity"] == "blocker" for f in comp),
    }

    ff = _check_first_frame(fields_list)
    findings.extend(ff)
    checks["first_frame"] = {
        "passed": not any(f["severity"] == "blocker" for f in ff),
    }

    dd = _check_duration_dialogue(fields_list, total_sec, total_dialogue_chars)
    findings.extend(dd)
    checks["duration_dialogue"] = {
        "passed": not any(f["severity"] == "blocker" for f in dd),
    }

    budget = params.get("budget")
    if budget is not None and not isinstance(budget, dict):
        raise CapabilityError("story.drama_gates: 'budget' must be an object")
    budget_findings, est_credits = _check_budget(total_sec, budget)
    findings.extend(budget_findings)
    checks["budget"] = {
        "passed": not any(f["severity"] == "blocker" for f in budget_findings),
        "est_credits": est_credits,
    }

    rewrite_round = params.get("rewrite_round", 0)
    if not isinstance(rewrite_round, int) or isinstance(rewrite_round, bool):
        try:
            rewrite_round = int(rewrite_round)
        except (TypeError, ValueError):
            rewrite_round = 0
    must_know = pkg.get("must_know", []) or []
    sp_findings, sp_info = _check_script_polish(
        _as_str(pkg.get("title", "")),
        must_know,
        params.get("episode_scenes"),
        rewrite_round,
        Path(out_dir),
    )
    findings.extend(sp_findings)
    checks["script_polish"] = sp_info

    an = _check_action_nodes(fields_list)
    findings.extend(an)
    checks["action_nodes"] = {
        "passed": not any(f["severity"] == "blocker" for f in an),
    }

    sc = _check_spatial_continuity(fields_list)
    findings.extend(sc)
    checks["spatial_continuity"] = {
        "passed": not any(f["severity"] == "blocker" for f in sc),
    }

    edl = params.get("edl", pkg.get("edl"))
    edit_report = params.get("edit_report")
    if edit_report is None and isinstance(pkg, dict):
        edit_report = pkg.get("edit_report")
    er = _check_edit_ready(edl, edit_report)
    findings.extend(er)
    if edit_report is None or (
        isinstance(edit_report, dict)
        and not isinstance(edit_report.get("edit_ready"), bool)
    ):
        checks["edit_ready"] = {"passed": None, "status": "pending"}
    elif any(f["severity"] == "blocker" for f in er):
        checks["edit_ready"] = {"passed": False, "status": "blocker"}
    elif any(f["severity"] == "pending" for f in er):
        # C-08: ffmpeg pending (or any other pending) is neither a
        # pass nor a blocker at the check level.
        checks["edit_ready"] = {"passed": None, "status": "pending"}
    else:
        checks["edit_ready"] = {"passed": True, "status": "passed"}

    counts = {"blocker": 0, "major": 0, "minor": 0, "pending": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    passed = counts["blocker"] == 0
    failed_checks = sorted(
        {f["check"] for f in findings if f["severity"] == "blocker"}
    )

    payload = {
        "episode_no": pkg.get("episode_no"),
        "title": pkg.get("title", ""),
        "passed": passed,
        "counts": counts,
        "checks": checks,
        "failed_checks": failed_checks,
        "findings": findings,
        "total_duration_sec": total_sec,
        "total_dialogue_chars": total_dialogue_chars,
        "est_credits": est_credits,
        "rewrite_round": rewrite_round,
    }
    ledger = _append_ledger(Path(out_dir), payload)
    payload["ledger_path"] = str(ledger)
    if sp_info.get("report_json"):
        payload["script_polish_report_json"] = sp_info["report_json"]
    return payload


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prompt_package": {"type": "object"},
        "package": {"type": "object"},
        "episode_scenes": {"type": "array"},
        "budget": {"type": "object"},
        "rewrite_round": {"type": "integer"},
        "edl": {"type": "object"},
        "edit_report": {"type": "object"},
    },
    "additionalProperties": False,
}


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "drama_gates_report.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    payload = run_drama_gates(params, Path(out_dir))
    report = _write_report(Path(out_dir), payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_drama_gates_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.drama_gates",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "生成前门禁套件：对 episode_prompts 产物做完备性、首帧、"
                "时长/对白、预算、script_polish 硬门（deterministic 模式直调"
                "渲染函数，blocker 透传；改写超 2 轮停报）、动作节点"
                "（2 节点 major、3 节点及以上 blocker）、空间连续性"
                "（缺布局 blocker，同场景门／桌／光源与首镜不一致 blocker）"
                "九项检查，零 blocker 才 passed；剪辑就绪门接 edit_assemble "
                "报告：干净报告通过、含 blocker 报告为 blocker、ffmpeg"
                " pending 的干净报告仍为 pending、无报告时一律 pending，"
                "不计入 passed；"
                "每跑一次向 drama_pass_ledger.jsonl 追加一条台账。"
                "离线 deterministic，零 Monid、零网络。"
            ),
            line="drama_gates",
        )
    )
    return ["story.drama_gates"]


register_drama_gates_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.drama_gates on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
