"""季弧线校验门 — ``story.season_arc``。

50 集真人短剧前期第二步：把一季各集的承诺/目标/障碍/兑现/出场状态、
钩子、节拍、伏笔埋与兑排成一张可审计的弧线表。本能力只做确定性校验
（零 LLM、零成本），不生成、不改写剧本。

方法层（只学方法，不抄任何既有作品的情节）：事实词典四栏 =
fact_id / audience_knows（观众知道什么）/ full_truth（完整真相）/
planned_reveal_ep（计划揭示集）＋ status（planted / paid / carried）；
钩子视觉优先：钩子必须能被拍出来，纯内心独白不算视觉钩子。

校验规则（severity 按任务约定）：

* episode_no 不连续（排序后相邻集号差值不为 1，含重复集号）→ major；
* 单集缺 promise / goal / obstacle / payoff / exit_state 任一 → blocker；
* 单集无 hook → major；
* hook 非视觉型（visual=false）→ minor；
* 已到揭示集（planned_reveal_ep ≤ 本季最大集数）仍未 paid → blocker；
* paid 却无 prior plant（兑现集之前没有任何一集埋过该 fact）→ blocker；
* planned_reveal_ep 超出季末且 status 不是 carried → blocker；
* 相邻集 beats 文本 SequenceMatcher ≥ 0.6 且无 escalation 标记 → minor。

任一 blocker 存在即 ``passed=false``。
输出 ``arc_report.json``；报告 sha256 进 ``CapabilityResult.sha256``
与 ``qa["report_sha256"]``。
"""

from __future__ import annotations

import argparse
import difflib
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

_EPISODE_REQUIRED = ["promise", "goal", "obstacle", "payoff", "exit_state"]
_LEDGER_STATUSES = ("planted", "paid", "carried")


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


def _beat_text(beat: Any) -> str:
    if isinstance(beat, str):
        return beat
    if isinstance(beat, dict):
        for key in ("text", "description", "content"):
            if isinstance(beat.get(key), str):
                return str(beat[key])
    return ""


def _episode_beats_text(episode: dict[str, Any]) -> str:
    beats = episode.get("beats", []) or []
    return "\n".join(_beat_text(b) for b in beats if _beat_text(b))


def _has_escalation(episode: dict[str, Any]) -> bool:
    if episode.get("escalation"):
        return True
    for beat in episode.get("beats", []) or []:
        if isinstance(beat, dict) and beat.get("escalation"):
            return True
    return False


def _check_episode_numbers(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    numbers = sorted(ep["episode_no"] for ep in episodes)
    for prev_no, cur_no in zip(numbers, numbers[1:]):
        if cur_no != prev_no + 1:
            findings.append(
                _finding(
                    "episode_numbers",
                    "major",
                    f"集号不连续：第 {prev_no} 集之后直接是第 {cur_no} 集。",
                    "补齐缺失集号的单集，或修正写错的集号；跳号会让伏笔"
                    "揭示集与弧线对照全部错位。",
                )
            )
    return findings


def _check_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for ep in episodes:
        no = ep["episode_no"]
        for field in _EPISODE_REQUIRED:
            if _is_missing(ep.get(field)):
                findings.append(
                    _finding(
                        "episode_fields",
                        "blocker",
                        f"第 {no} 集缺 {field}。",
                        f"补齐第 {no} 集的 {field}：单集五项（承诺/目标/障碍/"
                        "兑现/出场状态）缺一，单集就无法立项与验收。",
                    )
                )
        hook = ep.get("hook")
        if hook is None or (isinstance(hook, dict) and not hook):
            findings.append(
                _finding(
                    "hook",
                    "major",
                    f"第 {no} 集无 hook。",
                    "给本集一个钩子（类型＋强度＋视觉呈现＋钩子文本），"
                    "无钩子的集观众没有留下的理由。",
                )
            )
        elif isinstance(hook, dict):
            if hook.get("visual") is not True:
                findings.append(
                    _finding(
                        "hook",
                        "minor",
                        f"第 {no} 集 hook 非视觉型（visual 不是 true）："
                        "纯内心独白类钩子拍不出来。",
                        "把钩子改成看得见的画面、动作或道具（视觉优先），"
                        "内心活动只作对白或字幕的补充。",
                    )
                )
    return findings


def _check_ledger(
    episodes: list[dict[str, Any]], ledger: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    max_ep = max(ep["episode_no"] for ep in episodes)
    for entry in ledger:
        fact_id = entry["fact_id"]
        planned = entry["planned_reveal_ep"]
        status = entry["status"]
        if planned <= max_ep and status != "paid":
            findings.append(
                _finding(
                    "foreshadow_due",
                    "blocker",
                    f"伏笔 {fact_id} 已到揭示集（计划第 {planned} 集揭示，"
                    f"本季最大集数为 {max_ep}）仍未 paid（现状 {status}）。",
                    f"要么在本季内兑现 {fact_id}，要么把它的 planned_reveal_ep "
                    "与 status 改为 carried 并写明带往下一季的理由。",
                )
            )
        if planned > max_ep and status != "carried":
            findings.append(
                _finding(
                    "foreshadow_carried",
                    "blocker",
                    f"伏笔 {fact_id} 计划揭示集第 {planned} 集超出季末"
                    f"（本季最大集数为 {max_ep}），但 status 不是 carried"
                    f"（现状 {status}）。",
                    f"把 {fact_id} 的 status 改为 carried（明确带往下一季），"
                    "或把 planned_reveal_ep 改回本季内并按期兑现。",
                )
            )
    # paid 却无 prior plant：兑现集之前没有任何一集埋过该 fact。
    planted_before: dict[str, set[int]] = {}
    for ep in episodes:
        for fact_id in ep.get("foreshadows_planted", []) or []:
            planted_before.setdefault(str(fact_id), set()).add(ep["episode_no"])
    for ep in episodes:
        no = ep["episode_no"]
        for fact_id in ep.get("foreshadows_paid", []) or []:
            priors = [n for n in planted_before.get(str(fact_id), set()) if n < no]
            if not priors:
                findings.append(
                    _finding(
                        "foreshadow_paid",
                        "blocker",
                        f"第 {no} 集兑现伏笔 {fact_id}，但之前没有任何一集埋过它。",
                        f"在第 {no} 集之前补一集埋下 {fact_id}（观众可感知的"
                        "画面或信息），或删掉这次兑现——没有埋的兑现观众无从追认。",
                    )
                )
    return findings


def _check_routine(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ordered = sorted(episodes, key=lambda ep: ep["episode_no"])
    for prev_ep, cur_ep in zip(ordered, ordered[1:]):
        prev_text = _episode_beats_text(prev_ep)
        cur_text = _episode_beats_text(cur_ep)
        if not prev_text or not cur_text:
            continue
        ratio = difflib.SequenceMatcher(None, prev_text, cur_text).ratio()
        if ratio >= 0.6 and not (
            _has_escalation(prev_ep) or _has_escalation(cur_ep)
        ):
            findings.append(
                _finding(
                    "routine",
                    "minor",
                    f"相邻集 routine 重复未升级：第 {prev_ep['episode_no']} 集与"
                    f"第 {cur_ep['episode_no']} 集 beats 文本相似度 {ratio:.2f}，"
                    "且两集均无 escalation 标记。",
                    "让后一集带上升级（风险、情绪、关系、代价任一递进）并打上"
                    "escalation 标记，或改写其中一集的节拍。",
                )
            )
    return findings


_HOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "intensity": {"type": "integer"},
        "visual": {"type": "boolean"},
        "text": {"type": "string"},
    },
}
_EPISODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episode_no": {"type": "integer"},
        "promise": {"type": "string"},
        "goal": {"type": "string"},
        "obstacle": {"type": "string"},
        "payoff": {"type": "string"},
        "exit_state": {"type": "string"},
        "hook": _HOOK_SCHEMA,
        "beats": {"type": "array"},
        "foreshadows_planted": {"type": "array", "items": {"type": "string"}},
        "foreshadows_paid": {"type": "array", "items": {"type": "string"}},
        "escalation": {"type": "boolean"},
    },
}
_LEDGER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fact_id": {"type": "string"},
        "first_seen_ep": {"type": "integer"},
        "audience_knows": {"type": "string"},
        "full_truth": {"type": "string"},
        "planned_reveal_ep": {"type": "integer"},
        "status": {"type": "string", "enum": list(_LEDGER_STATUSES)},
    },
}
_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "season_title": {"type": "string"},
        "episodes": {"type": "array", "items": _EPISODE_SCHEMA},
        "foreshadow_ledger": {"type": "array", "items": _LEDGER_SCHEMA},
    },
    "additionalProperties": False,
}


def _validate_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise CapabilityError("story.season_arc: params must be an object")
    for key in ("season_title", "episodes", "foreshadow_ledger"):
        if key not in params:
            raise CapabilityError(
                f"story.season_arc: missing required top-level field: {key}"
            )
    if not isinstance(params["season_title"], str):
        raise CapabilityError("story.season_arc: 'season_title' must be a string")
    if not isinstance(params["episodes"], list) or not params["episodes"]:
        raise CapabilityError(
            "story.season_arc: 'episodes' must be a non-empty list"
        )
    if not isinstance(params["foreshadow_ledger"], list):
        raise CapabilityError("story.season_arc: 'foreshadow_ledger' must be a list")
    for ep in params["episodes"]:
        if not isinstance(ep, dict):
            raise CapabilityError("story.season_arc: each episode must be an object")
        if (
            not isinstance(ep.get("episode_no"), int)
            or isinstance(ep.get("episode_no"), bool)
        ):
            raise CapabilityError(
                "story.season_arc: each episode needs an integer 'episode_no'"
            )
        if "hook" in ep and ep["hook"] is not None and not isinstance(ep["hook"], dict):
            raise CapabilityError("story.season_arc: 'hook' must be an object")
        for key in ("beats", "foreshadows_planted", "foreshadows_paid"):
            if key in ep and ep[key] is not None and not isinstance(ep[key], list):
                raise CapabilityError(f"story.season_arc: {key!r} must be a list")
    for entry in params["foreshadow_ledger"]:
        if not isinstance(entry, dict):
            raise CapabilityError("story.season_arc: each ledger entry must be an object")
        for key in ("fact_id", "status", "planned_reveal_ep"):
            if key not in entry:
                raise CapabilityError(
                    f"story.season_arc: ledger entry missing {key!r}"
                )
        if entry["status"] not in _LEDGER_STATUSES:
            raise CapabilityError(
                "story.season_arc: ledger status must be one of "
                f"{list(_LEDGER_STATUSES)}"
            )
        if not isinstance(entry["planned_reveal_ep"], int) or isinstance(
            entry["planned_reveal_ep"], bool
        ):
            raise CapabilityError(
                "story.season_arc: 'planned_reveal_ep' must be an integer"
            )
    return params


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "arc_report.json"
    report.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    params = _validate_params(params)
    episodes = params["episodes"]
    ledger = params["foreshadow_ledger"]
    findings: list[dict[str, Any]] = []
    findings.extend(_check_episode_numbers(episodes))
    findings.extend(_check_episodes(episodes))
    findings.extend(_check_ledger(episodes, ledger))
    findings.extend(_check_routine(episodes))

    counts = {"blocker": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    passed = counts["blocker"] == 0

    payload = {
        "season_title": params["season_title"],
        "passed": passed,
        "counts": counts,
        "episode_count": len(episodes),
        "ledger_count": len(ledger),
        "findings": findings,
    }
    report = _write_report(Path(out_dir), payload)
    sha = compute_sha256(report)
    return CapabilityResult(
        duration_s=0.0,
        sha256=sha,
        qa={"report_json": str(report), "report_sha256": sha, **payload},
    )


def register_season_arc_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.season_arc",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,  # deterministic audit only, no generation, no LLM
            render=_render,
            has_media_output=False,
            description=(
                "季弧线校验门：50 集真人短剧前期第二步，确定性校验一季各集的"
                "承诺/目标/障碍/兑现/出场状态、钩子（视觉优先）、集号连续性、"
                "伏笔事实词典（到期未兑、兑而无埋、超季未 carried 皆 blocker）、"
                "相邻集节拍 routine 重复未升级。任一 blocker 即 passed=false。"
                "零 LLM、零成本。"
            ),
            line="season_arc",
        )
    )
    return ["story.season_arc"]


register_season_arc_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run story.season_arc on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
