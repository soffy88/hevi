"""季圣经校验门 — ``story.season_bible``。

50 集真人短剧前期第一步：先把一季的世界、人物、场景、道具、视觉锁、
基调定死，后续单集 prompt 才能从同一本圣经编译，人物才不会跨集换脸、
换设定。本能力只做确定性校验（零 LLM、零成本），不生成、不改写圣经。

方法层字段（只学方法，不抄任何既有作品的人物与情节）：人物档案 =
id / name / age / occupation / appearance / personality_core / values /
fears / flaw / desire / backstory / mbti / contradiction / long_arc；
其中 contradiction（内在矛盾）、flaw（致命缺陷）、desire（内心渴望）、
long_arc（长期弧线）四项缺一不可——没有矛盾与缺陷的人物立不住，没有
渴望与弧线的人物走不完一季。

校验规则（severity 按任务约定）：

* premise / worldview 为空 → blocker；
* 人物缺 contradiction / flaw / desire / long_arc 任一 → blocker，
  缺其余档案字段 → major；
* 人物 / 场景 / 道具各自 id 重复 → blocker；
* 人物无 visual lock（以 character id 为键）→ blocker，
  visual lock 缺 portrait_block / outfit / signature_props /
  face_anchors 任一 → major；
* tone_style 缺 palette / lighting / camera_style / dialogue_style /
  era 任一 → major。

任一 blocker 存在即 ``passed=false``，不许进单集 prompt 编译。
输出 ``bible_report.json`` ＋原样回显的 validated bible；
报告 sha256 进 ``CapabilityResult.sha256`` 与 ``qa["report_sha256"]``。
"""

from __future__ import annotations

import argparse
import json
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

_CHARACTER_FIELDS = [
    "id",
    "name",
    "age",
    "occupation",
    "appearance",
    "personality_core",
    "values",
    "fears",
    "flaw",
    "desire",
    "backstory",
    "mbti",
    "contradiction",
    "long_arc",
]
# 缺失即 blocker 的四项；其余档案字段缺失记 major。
_BLOCKER_CHARACTER_FIELDS = {"contradiction", "flaw", "desire", "long_arc"}
_VISUAL_LOCK_FIELDS = ["portrait_block", "outfit", "signature_props", "face_anchors"]
_TONE_STYLE_FIELDS = ["palette", "lighting", "camera_style", "dialogue_style", "era"]


def _finding(
    check: str, severity: str, issue: str, suggestion: str
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "issue": issue,
        "suggestion": suggestion,
    }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _check_premise_worldview(params: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if _is_missing(params.get("premise")):
        findings.append(
            _finding(
                "premise",
                "blocker",
                "premise 为空：一季没有一句话前提，单集无从判断偏离。",
                "写一句 premise：谁、在什么处境、要什么、代价是什么。",
            )
        )
    if _is_missing(params.get("worldview")):
        findings.append(
            _finding(
                "worldview",
                "blocker",
                "worldview 为空：一季没有世界观，场景与规则会跨集打架。",
                "写清世界观：时代、地点规则、社会规则、超常设定（若有）及其边界。",
            )
        )
    return findings


def _check_characters(
    characters: list[dict[str, Any]], visual_locks: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not characters:
        findings.append(
            _finding(
                "characters",
                "blocker",
                "characters 为空：季圣经没有任何人物，无法编译单集 prompt。",
                "至少登记一位主角，并填满全部档案字段。",
            )
        )
        return findings
    seen_ids: dict[str, int] = {}
    for idx, char in enumerate(characters):
        label = f"人物[{idx}]"
        char_id = char.get("id")
        if _is_missing(char_id):
            findings.append(
                _finding(
                    "characters",
                    "blocker",
                    f"{label} 缺 id：人物无法被场景、视觉锁与单集引用。",
                    "给每位人物一个稳定唯一的 id，后续只用 id 引用，不用名字。",
                )
            )
        else:
            cid = str(char_id)
            seen_ids[cid] = seen_ids.get(cid, 0) + 1
            if cid not in visual_locks:
                findings.append(
                    _finding(
                        "visual_lock",
                        "blocker",
                        f"人物 {cid} 无 visual lock：跨集出图无法锁定长相与穿搭。",
                        f"在 visual_locks 里为 {cid} 补 portrait_block / outfit / "
                        "signature_props / face_anchors。",
                    )
                )
        for field in _CHARACTER_FIELDS:
            if field == "id":
                continue
            if _is_missing(char.get(field)):
                severity = (
                    "blocker" if field in _BLOCKER_CHARACTER_FIELDS else "major"
                )
                findings.append(
                    _finding(
                        "characters",
                        severity,
                        f"{label}（id={char_id}）缺 {field}。",
                        f"补齐人物档案字段 {field}，缺 contradiction / flaw / "
                        "desire / long_arc 的人物立不住、走不完一季。",
                    )
                )
    for cid, count in seen_ids.items():
        if count > 1:
            findings.append(
                _finding(
                    "characters",
                    "blocker",
                    f"人物 id 重复：{cid} 出现 {count} 次。",
                    "人物 id 必须唯一，重复 id 会让视觉锁与单集引用指向不明。",
                )
            )
    return findings


def _check_entries(
    entries: list[dict[str, Any]], kind: str
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    for idx, entry in enumerate(entries):
        label = f"{kind}[{idx}]"
        entry_id = entry.get("id")
        if _is_missing(entry_id):
            findings.append(
                _finding(
                    kind,
                    "major",
                    f"{label} 缺 id。",
                    "给每个场景/道具一个稳定唯一的 id，单集只用 id 引用。",
                )
            )
        else:
            seen_ids[str(entry_id)] = seen_ids.get(str(entry_id), 0) + 1
        for field in ("name", "description"):
            if _is_missing(entry.get(field)):
                findings.append(
                    _finding(
                        kind,
                        "major",
                        f"{label}（id={entry_id}）缺 {field}。",
                        f"补齐{kind}的 {field}，否则单集 prompt 无法还原该{kind}。",
                    )
                )
    for eid, count in seen_ids.items():
        if count > 1:
            findings.append(
                _finding(
                    kind,
                    "blocker",
                    f"{kind} id 重复：{eid} 出现 {count} 次。",
                    f"{kind} id 必须唯一，重复 id 会让单集引用指向不明。",
                )
            )
    return findings


def _check_visual_locks(visual_locks: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for cid, lock in visual_locks.items():
        for field in _VISUAL_LOCK_FIELDS:
            if _is_missing(lock.get(field)):
                findings.append(
                    _finding(
                        "visual_lock",
                        "major",
                        f"人物 {cid} 的 visual lock 缺 {field}。",
                        f"补齐 visual lock 字段 {field}，否则该人物的跨集一致性无锚点。",
                    )
                )
    return findings


def _check_tone_style(tone_style: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for field in _TONE_STYLE_FIELDS:
        if _is_missing(tone_style.get(field)):
            findings.append(
                _finding(
                    "tone_style",
                    "major",
                    f"tone_style 缺 {field}。",
                    f"补齐 tone_style 字段 {field}，基调缺项会让各集风格漂移。",
                )
            )
    return findings


_CHARACTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {f: {} for f in _CHARACTER_FIELDS},
}
_SCENE_PROP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
    },
}
_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "premise": {"type": "string"},
        "worldview": {"type": "string"},
        "characters": {"type": "array", "items": _CHARACTER_SCHEMA},
        "scenes": {"type": "array", "items": _SCENE_PROP_SCHEMA},
        "props": {"type": "array", "items": _SCENE_PROP_SCHEMA},
        "visual_locks": {"type": "object"},
        "tone_style": {"type": "object"},
    },
    "additionalProperties": False,
}

_TOP_KEYS = [
    "title",
    "premise",
    "worldview",
    "characters",
    "scenes",
    "props",
    "visual_locks",
    "tone_style",
]


def _validate_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise CapabilityError("story.season_bible: params must be an object")
    for key in _TOP_KEYS:
        if key not in params:
            raise CapabilityError(
                f"story.season_bible: missing required top-level field: {key}"
            )
    for key in ("title", "premise", "worldview"):
        if not isinstance(params[key], str):
            raise CapabilityError(
                f"story.season_bible: {key!r} must be a string"
            )
    for key in ("characters", "scenes", "props"):
        if not isinstance(params[key], list):
            raise CapabilityError(
                f"story.season_bible: {key!r} must be a list"
            )
    for key in ("visual_locks", "tone_style"):
        if not isinstance(params[key], dict):
            raise CapabilityError(
                f"story.season_bible: {key!r} must be an object"
            )
    for entry in params["characters"] + params["scenes"] + params["props"]:
        if not isinstance(entry, dict):
            raise CapabilityError(
                "story.season_bible: characters/scenes/props entries must be objects"
            )
    for cid, lock in params["visual_locks"].items():
        if not isinstance(lock, dict):
            raise CapabilityError(
                f"story.season_bible: visual lock for {cid!r} must be an object"
            )
    return params


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "bible_report.json"
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    params = _validate_params(params)
    findings: list[dict[str, Any]] = []
    findings.extend(_check_premise_worldview(params))
    findings.extend(_check_characters(params["characters"], params["visual_locks"]))
    findings.extend(_check_entries(params["scenes"], "scenes"))
    findings.extend(_check_entries(params["props"], "props"))
    findings.extend(_check_visual_locks(params["visual_locks"]))
    findings.extend(_check_tone_style(params["tone_style"]))

    counts = {"blocker": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    passed = counts["blocker"] == 0

    bible = {key: params[key] for key in _TOP_KEYS}
    payload = {
        "title": params["title"],
        "passed": passed,
        "counts": counts,
        "findings": findings,
        "bible": bible,
    }
    report = _write_report(Path(out_dir), payload)
    sha = compute_sha256(report)
    return CapabilityResult(
        duration_s=0.0,
        sha256=sha,
        qa={"report_json": str(report), "report_sha256": sha, **payload},
    )


def register_season_bible_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.season_bible",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,  # deterministic audit only, no generation, no LLM
            render=_render,
            has_media_output=False,
            description=(
                "季圣经校验门：50 集真人短剧前期第一步，确定性校验一季的"
                "前提、世界观、人物档案（矛盾/缺陷/渴望/长期弧线缺一即 blocker）、"
                "场景与道具 id 唯一性、人物视觉锁、基调五项。任一 blocker 即"
                "passed=false，不许进单集 prompt 编译。零 LLM、零成本。"
            ),
            line="season_bible",
        )
    )
    return ["story.season_bible"]


register_season_bible_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.season_bible on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
