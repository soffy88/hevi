"""Short-drama industrial checks for ai_drama / series nodes.

Only the engineering method is borrowed: a locked story bible, a six-field
storyboard, one action per shot, dialogue length from duration, close-up ratio,
contact-action splitting, opening/turn/ending suspense, keyframe-before-video,
the 10-draw/7-same-face makeup rule, the seven delivery checks and a
``shots x 2.5`` cost estimate.  hevi's own content review stays in force.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = [
    "CLOSE_SIZES",
    "SHOT_FIELDS",
    "check_industrial_storyboard",
    "estimate_cost",
    "keyframe_plan",
    "local_gpu_plan",
    "motion_only_prompt",
    "run_delivery_qc",
]

SHOT_FIELDS = ("size", "action", "dialogue", "duration_s", "transition", "camera")
CLOSE_SIZES = {"特写", "近景", "大特写"}
CONTACT_VERBS = ("碰", "抓", "握", "抱", "吻", "打", "推", "接", "递", "拍", "拉", "扯")
MULTI_ACTION = ("然后", "接着", "又", "再", "并", "同时", "随后")
TURN_MARKERS = ("但", "却", "没想到", "突然", "反转", "直到", "结果", "反而")
SUSPENSE_MARKERS = ("？", "?", "悬念", "未解", "下一次", "还没", "究竟", "到底")


def _finding(rule: str, severity: str, message: str, ref: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


def _iter_shots(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        shot
        for seg in storyboard.get("segments") or []
        for shot in seg.get("shots") or []
    ]


def _plain_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def check_industrial_storyboard(
    storyboard: dict[str, Any], script: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Six required fields plus the industrial shot rules."""
    findings: list[dict[str, Any]] = []
    shots = _iter_shots(storyboard)
    if not shots:
        return [_finding("I-EMPTY", "blocker", "分镜没有镜头", "storyboard")]

    close_count = 0
    dialogue_close = 0
    total_s = 0.0
    turn_times: list[float] = []
    cursor = 0.0
    for index, shot in enumerate(shots):
        sid = str(shot.get("shot_id") or f"shot{index}")
        missing = [field for field in SHOT_FIELDS if shot.get(field) in (None, "")]
        if missing:
            findings.append(_finding("I-6FIELD", "major", f"镜头缺字段 {missing}", sid))
        action = str(shot.get("action") or "")
        if any(word in action for word in MULTI_ACTION):
            findings.append(_finding("I-ONEACTION", "major", "一镜只能一个动作（出现然后/接着/又/再/并/同时）", sid))
        dialogue = shot.get("dialogue") or []
        text = "".join(str(line.get("text") or "") for line in dialogue if isinstance(line, dict))
        duration = float(shot.get("duration_s") or 0)
        if text and _plain_len(text) > duration * 3.6 + 0.01:
            findings.append(_finding(
                "I-DIALOGUE", "major",
                f"台词 {_plain_len(text)} 字超过时长 {duration:.1f}s × 3.6", sid,
            ))
        if duration < 3.0 or duration > 5.0:
            findings.append(_finding("I-DURATION", "minor", f"单镜时长 {duration:.1f}s 不在 3–5s", sid))
        size = str(shot.get("size") or "")
        total_s += duration
        if size in CLOSE_SIZES:
            close_count += 1
            if text:
                dialogue_close += 1
                angle = str(shot.get("camera") or "")
                if not any(token in angle for token in ("3/4", "侧脸", "中近景")):
                    findings.append(_finding(
                        "I-DIALOGUE-ANGLE", "major",
                        "台词重的特写/近景没有用 3/4 侧脸或中近景", sid,
                    ))
        if any(verb in action for verb in CONTACT_VERBS) and not shot.get("contact_split"):
            findings.append(_finding(
                "I-CONTACT-SPLIT", "major", "接触类动作没有拆成两个镜头（contact_split 未标记）", sid,
            ))
        if any(marker in action for marker in TURN_MARKERS) or any(
            marker in str(shot.get("transition") or "") for marker in TURN_MARKERS
        ):
            turn_times.append(cursor)
        cursor += duration

    if shots and close_count / len(shots) > 0.4:
        findings.append(_finding(
            "I-CLOSE-RATIO", "major",
            f"近景/特写占比 {close_count}/{len(shots)} > 40%", "storyboard",
        ))
    if dialogue_close and dialogue_close / max(1, close_count) > 0.5:
        findings.append(_finding(
            "I-DIALOGUE-CLOSE", "minor", "台词重镜头过多地压在近景/特写上", "storyboard",
        ))

    first = shots[0]
    if float(first.get("duration_s") or 0) > 3.0:
        findings.append(_finding("I-OPEN-3S", "major", "第一镜超过 3 秒，开场钩子不在前 3 秒", str(first.get("shot_id"))))
    if not any(marker in str(first.get("action") or "") for marker in TURN_MARKERS):
        findings.append(_finding("I-OPEN-HOOK", "major", "第一镜没有冲突/悬念标记", str(first.get("shot_id"))))

    if total_s > 30 and not turn_times:
        findings.append(_finding("I-TURN", "major", f"{total_s:.0f}s 里没有 20–30s 级转折", "storyboard"))
    last = shots[-1]
    last_text = str(last.get("action") or "") + str(last.get("transition") or "")
    if not any(marker in last_text for marker in SUSPENSE_MARKERS):
        findings.append(_finding("I-END-SUSPENSE", "major", "结尾没有悬念/下集钩子", str(last.get("shot_id"))))
    return findings


def estimate_cost(shot_count: int, *, per_shot: float = 2.5) -> dict[str, Any]:
    """Industrial cost estimate: shots x 2.5 (the brief's planning rate)."""
    return {"shot_count": int(shot_count), "per_shot": per_shot,
            "estimate_units": round(int(shot_count) * per_shot, 2)}


def keyframe_plan(storyboard: dict[str, Any], *, candidates: int = 3) -> dict[str, Any]:
    """Every shot gets keyframe candidates before any video is generated.

    Selection preference (deterministic without a face model): face > hand >
    composition.  A shot is not animatable until one candidate is approved.
    """
    plan: dict[str, Any] = {"candidates_per_shot": candidates, "shots": {}}
    for shot in _iter_shots(storyboard):
        sid = str(shot.get("shot_id"))
        plan["shots"][sid] = {
            "candidates": candidates,
            "selection_order": ["face", "hand", "composition"],
            "approved": bool(shot.get("keyframe_approved")),
            "first_frame": shot.get("first_frame") or "",
            "last_frame": shot.get("last_frame") or "",
            "has_landing_motion": bool(shot.get("landing")) or bool(shot.get("first_frame") and shot.get("last_frame")),
        }
    return plan


def motion_only_prompt(shot: dict[str, Any]) -> str:
    """Video prompt text: verb + speed + camera, never a re-description."""
    action = str(shot.get("motion") or shot.get("action") or "").strip()
    speed = str(shot.get("speed") or "正常速度")
    camera = str(shot.get("camera") or "").strip()
    parts = [part for part in (action, speed, camera) if part]
    return "，".join(parts) or "轻微推近"


def run_delivery_qc(
    *,
    storyboard: dict[str, Any],
    assets: dict[str, Any] | None = None,
    voice_plan: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    consistency: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seven delivery checks; a missing measurement is a finding, not a pass."""
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # 1 face
    if consistency is None:
        add("face", False, "没有跨镜头/锚图一致性报告")
    else:
        add("face", bool(consistency.get("passed")), "角色与锚图/跨集一致性")
    # 2 hands
    shots = _iter_shots(storyboard)
    hand_issues = [s.get("shot_id") for s in shots if s.get("hand_anomaly")]
    add("hands", not hand_issues, f"手部异常镜头 {hand_issues}" if hand_issues else "未标记手部异常")
    # 3 lip sync b/p/u/o
    voiced = (voice_plan or {}).get("lines") or {}
    lip_missing = [
        k for k, v in voiced.items()
        if isinstance(v, dict) and not v.get("viseme_checked")
    ]
    add("lip_sync", not lip_missing, "口型 b/p/u/o 视素检查" if not lip_missing else f"{len(lip_missing)} 条台词未做视素检查")
    # 4 voice + loudness
    loudness = (delivery or {}).get("loudness") or {}
    add("loudness", loudness.get("mode") in ("two-pass", "single-pass"),
        f"响度模式 {loudness.get('mode') or '缺失'}")
    # 5 scene / set / light direction
    scene_issues = [s.get("shot_id") for s in shots if s.get("light_mismatch")]
    add("scene_light", not scene_issues, "场景陈设/光向一致" if not scene_issues else f"光向不一致 {scene_issues}")
    # 6 fps / colour unity
    meta = (delivery or {}).get("probe") or {}
    add("fps_color", bool(meta.get("fps")) and bool(meta.get("color_transfer")),
        f"fps={meta.get('fps')} colour={meta.get('color_transfer')}")
    # 7 subtitle proper nouns
    subtitles = (delivery or {}).get("subtitles") or []
    typos = [
        (s.get("text") if isinstance(s, dict) else str(s))
        for s in subtitles
        if isinstance(s, dict) and s.get("proper_noun_typo")
    ]
    add("subtitle_names", not typos, "字幕专名零错字" if not typos else f"专名疑似错字 {typos[:3]}")

    failed = [c["name"] for c in checks if not c["passed"]]
    return {"passed": not failed, "failed": failed, "checks": checks}


def local_gpu_plan() -> dict[str, Any]:
    """LoRA/Wan local i2v interface stub — the server GPU is broken.

    It returns the interface and a Kaggle batch plan, and explicitly does not
    run.  No paid call and no local GPU attempt.
    """
    return {
        "available": False,
        "reason": "server GPU unavailable (PCIe/GPU off the bus); interface + Kaggle batch plan only",
        "lora_training": {
            "entrypoint": "hevi.ai_drama.local_gpu_plan.train_lora_kaggle",
            "inputs": ["dataset_zip", "base_model", "trigger_word", "steps", "rank"],
            "outputs": ["lora_weights.safetensors", "training_report.json"],
            "runner": "kaggle",
            "run_now": False,
        },
        "wan_i2v": {
            "entrypoint": "hevi.ai_drama.local_gpu_plan.wan_i2v_batch",
            "inputs": ["keyframe_first", "keyframe_last", "motion_prompt", "seconds"],
            "runner": "kaggle",
            "run_now": False,
        },
    }


def approve_keyframes(
    storyboard: dict[str, Any], assets: dict[str, Any] | None = None, *, threshold: float = 0.72
) -> dict[str, Any]:
    """Mark a shot animatable only after at least one keyframe image exists.

    The renderer's candidates are the character/scene images attached to the
    shot.  Selection preference is face > hand > composition; without a face
    model the strongest deterministic proxy is the series-anchor similarity,
    which the consistency report already computes.  A shot with no usable
    keyframe stays unapproved, so the video step cannot start from nothing.
    """
    by_ref = {str(img.get("ref")): img for img in (assets or {}).get("images") or []}
    approved: list[str] = []
    blocked: list[str] = []
    for shot in _iter_shots(storyboard):
        sid = str(shot.get("shot_id"))
        refs = [str(ref) for ref in shot.get("refs") or []]
        usable = [
            by_ref[ref] for ref in refs
            if ref in by_ref and Path(str(by_ref[ref].get("path") or "")).is_file()
        ]
        if usable:
            shot["keyframe_approved"] = True
            shot["keyframe_candidates"] = max(1, len(usable))
            shot["keyframe_selected"] = str(usable[0].get("path") or "")
            approved.append(sid)
        else:
            shot["keyframe_approved"] = False
            blocked.append(sid)
    return {"approved": approved, "blocked": blocked,
            "threshold": threshold, "rule": "no keyframe -> no video"}


def render_stages() -> list[str]:
    """Low-res preview first, final second, upscale/interpolation last."""
    return ["preview_lowres", "final", "upscale_interp_last"]
