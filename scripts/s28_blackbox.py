"""S28 black-box: two short dramas + two short films, from topic to review.

Writes JSON + Markdown under ``verify_s28/`` and one aggregate ``eval.json``.
No network, no paid model: the generator is deterministic, and the checks use
the same ai_drama script/storyboard rules the production line uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.ai_drama import rules as drama_rules
from hevi.ai_drama.compile import compile_storyboard
from hevi.ai_drama.schema import normalize_script
from hevi.scriptcraft.characters import check_characters
from hevi.scriptcraft.filmability import check_filmability
from hevi.scriptcraft.review import review_document
from hevi.scriptcraft.shortdrama import plan_short_drama
from hevi.scriptcraft.shortfilm import build_short_film

OUT = Path("/data/soffy/projects/seq-1108/verify_s28")
DRAMAS = (
    ("D1", "离婚冷静期最后一天，她把公司公章缝进婚纱", "都市复仇"),
    ("D2", "外卖骑手救下坠楼孩子，监控却显示他推了人", "现实悬疑"),
)
FILMS = (
    ("F1", "养老院最会唱戏的老人，把最后一场戏演给空椅子", "家庭剧情"),
    ("F2", "深夜自习室，最后一个学生发现管理员每天都在重复同一天", "悬疑"),
)


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _json(path: Path, data: Any) -> str:
    return _write(path, json.dumps(data, ensure_ascii=False, indent=2))


def _master_md(plan: dict[str, Any]) -> str:
    master = plan["master_plan"]
    lines = [f"# 故事总盘：{master.get('title')}", ""]
    for key, label in (
        ("sell_point", "卖点"),
        ("genre", "类型"),
        ("route", "路线"),
        ("core_hook", "核心钩子"),
        ("mainline", "主线"),
        ("relation_line", "关系线"),
        ("trump_card", "底牌"),
        ("core_payoff", "核心爽点"),
        ("ending", "结局方向"),
        ("why_vertical", "为何适合竖屏"),
    ):
        if master.get(key):
            lines += [f"- **{label}**：{master[key]}"]
    if master.get("reversal_path"):
        lines += ["- **反转路径**："] + [f"  - {item}" for item in master["reversal_path"]]
    if master.get("escalation"):
        lines.append("- **前中后期升级**：")
        lines += [f"  - {name}：{value}" for name, value in master["escalation"].items()]
    if master.get("door"):
        lines.append(f"- **开发句**：{master['door']}")
    if master.get("dramatic_game"):
        lines.append("- **戏剧游戏**：")
        lines += [f"  - {key}：{value}" for key, value in master["dramatic_game"].items()]
    if master.get("seven_steps"):
        lines.append("- **7 步结构**：")
        lines += [f"  {step['step']}. {step['label']}（第 {step['scene']} 场）：{step['summary']}" for step in master["seven_steps"]]
    if master.get("reversals"):
        lines.append("- **反转**：")
        lines += [f"  - 第 {r['index']} 次（改 {r['changes']}）：{r['summary']}" for r in master["reversals"]]
    if master.get("motif"):
        motif = master["motif"]
        lines.append(f"- **母题**：{motif.get('object')} × {motif.get('count')} 次，出现在第 {motif.get('appearances')} 场")
    if master.get("subtext"):
        lines.append(f"- **潜台词**：{master['subtext']}")
    return "\n".join(lines) + "\n"


def _outline_md(plan: dict[str, Any]) -> str:
    lines = ["# 10 集大纲", "", "| 集 | 开头接什么 | 核心事件 | 爽点（已发生结果） | 卡点 |", "|---:|---|---|---|---|"]
    lines.extend(
        f"| {row['ep']} | {row['opening_connects']} | {row['core_event']} | {row['payoff']} | "
        f"{row['cliffhanger_type']}：{row['cliffhanger']} |"
        for row in plan["episode_outline"]
    )
    return "\n".join(lines) + "\n"


def _beats_md(plan: dict[str, Any]) -> str:
    lines = ["# 第 1 集秒级节拍表", "", "| 秒 | 模块 | 拍 | 钩子类型 |", "|---|---|---|---|"]
    lines.extend(
        f"| {row['start_s']}–{row['end_s']}s | {row['module']} | {row['beat']} | {row['hook_type']} |"
        for row in plan["ep1_beat_sheet"]
    )
    return "\n".join(lines) + "\n"


def _screenplay_md(script: dict[str, Any]) -> str:
    lines = [f"# {script.get('title', '')}", ""]
    if script.get("logline"):
        lines += [f"> {script['logline']}", ""]
    for scene in script.get("scenes") or []:
        header = scene.get("header") or (
            f"{scene.get('scene_no')} {scene.get('name')} [{scene.get('int_ext')}] [{scene.get('day_night')}]"
        )
        lines += [f"## {header}", ""]
        for beat in scene.get("beats") or []:
            for action in beat.get("action") or []:
                lines.append(str(action))
            for line in beat.get("dialogue") or []:
                kind = {"said": "", "inner": "（内心独白）", "vo": "（画外音）"}.get(str(line.get("kind")), "")
                name = line.get("speaker_name") or line.get("speaker")
                lines.append(f"**{name}**{kind}：{line.get('text')}")
            lines.append("")
    return "\n".join(lines)


def _review_md(review: dict[str, Any]) -> str:
    lines = [
        "# 三轮审稿",
        "",
        f"必须修 {review['summary']['must']} · 应该修 {review['summary']['should']} · 可选 {review['summary']['optional']}",
        "",
    ]
    for round_row in review["rounds"]:
        lines += [f"## {round_row['label']}（{round_row['focus']}）", ""]
        if not round_row["findings"]:
            lines += ["无。", ""]
            continue
        lines += ["| 位置 | 问题 | 观众会怎样 | 改法 | 级别 |", "|---|---|---|---|---|"]
        for item in round_row["findings"]:
            lines.append(
                f"| {item['position']} | {item['problem']} | {item['audience']} | {item['fix']} | {item['severity_label']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _score(plan: dict[str, Any], script: dict[str, Any], review: dict[str, Any]) -> dict[str, float]:
    checks = plan["checks"]
    dims = {
        "立项": 5.0 if plan["premise_gate"]["verdict"] == "pass" else 3.0,
        "人物": 5.0 if not [f for f in checks["cast"] if f["severity"] == "must"] else 3.5,
        "结构": 5.0 if not [f for f in checks.get("rhythm", []) if f["severity"] == "must"] else 3.5,
        "可拍": 5.0 if checks["filmability"]["passed"] else 3.5,
        "审稿": 5.0 if review["summary"]["must"] == 0 else 3.0,
    }
    if plan["kind"] == "short_film":
        dims["结构"] = 5.0 if len(plan["master_plan"]["seven_steps"]) == 7 else 3.5
    return dims


def _normalise(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[Any], list[Any]]:
    script = normalize_script(plan["script"])
    storyboard = compile_storyboard(script)
    script_checks = drama_rules.check_script(script)
    storyboard_checks = drama_rules.check_storyboard(storyboard, script)
    return script, storyboard, script_checks, storyboard_checks


def _negative_control() -> dict[str, Any]:
    document = {
        "kind": "short_drama",
        "characters": [
            {"id": "c1", "name": "苏念念", "role": "主角", "bio": "", "relations": [],
             "arc": "", "defect": "太善良", "visual_markers": [], "state": {"pose": "坐"}},
        ],
        "props": [{"name": "公章"}],
        "scenes": [{
            "scene_id": "sc_01", "location": "大厅", "day_night": "日",
            "characters_present": ["c1", "c2", "c3", "c4", "c5"],
            "beats": [{
                "beat_id": "sc_01_b01",
                "action": ["△ 苏念念坐回椅子，她很难过。", "△ 她委屈。", "△ 她把公章放在桌上。", "△ 她仿佛被定住。"],
                "dialogue": [{"speaker": "苏念念", "kind": "说", "text": "我今天必须把这件事说清楚否则谁都别想走", "duration_s": 1.0}],
            }],
        }],
    }
    filmability = check_filmability(document)
    cast = check_characters(document["characters"])
    review = review_document(document, mode="short_drama", filmability=filmability)
    codes = sorted({f["rule"] for f in filmability["findings"] if f["severity"] == "must"})
    return {
        "filmability_must": codes,
        "cast_must": sorted({f["rule"] for f in cast if f["severity"] == "must"}),
        "review_must": sorted({f["code"] for f in review["findings"] if f["severity"] == "must"}),
        "passed": False,
        "note": "反例：故意写慢开场、情绪无动作、坐姿矛盾、道具无尺寸、同框 5 人、台词类型错误。",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for code, topic, genre in DRAMAS:
        plan = plan_short_drama(topic=topic, genre=genre, confirm=True)
        script, storyboard, script_checks, storyboard_checks = _normalise(plan)
        folder = OUT / code
        _json(folder / "plan.json", plan)
        _write(folder / "master_plan.md", _master_md(plan))
        _write(folder / "episode_outline.md", _outline_md(plan))
        _write(folder / "ep1_beats.md", _beats_md(plan))
        _write(folder / "screenplay.md", _screenplay_md(plan["script"]))
        _write(folder / "review.md", _review_md(plan["review"]))
        _json(folder / "script.json", script)
        _json(folder / "storyboard.json", storyboard)
        results.append({
            "code": code,
            "kind": "short_drama",
            "topic": topic,
            "genre": genre,
            "checks_passed": plan["checks"]["passed"],
            "checks_must": plan["checks"]["must_count"],
            "review_must": plan["review"]["summary"]["must"],
            "review_should": plan["review"]["summary"]["should"],
            "script_blockers": [f for f in script_checks if f["severity"] == "blocker"],
            "storyboard_blockers": [f for f in storyboard_checks if f["severity"] == "blocker"],
            "segments": len(storyboard["segments"]),
            "shots": sum(len(seg["shots"]) for seg in storyboard["segments"]),
            "score": _score(plan, script, plan["review"]),
            "files": {
                "master_plan": str(folder / "master_plan.md"),
                "episode_outline": str(folder / "episode_outline.md"),
                "ep1_beats": str(folder / "ep1_beats.md"),
                "screenplay": str(folder / "screenplay.md"),
                "review": str(folder / "review.md"),
            },
        })

    for code, topic, genre in FILMS:
        plan = build_short_film(topic=topic, genre=genre, confirm=True)
        script, storyboard, script_checks, storyboard_checks = _normalise(plan)
        folder = OUT / code
        _json(folder / "plan.json", plan)
        _write(folder / "master_plan.md", _master_md(plan))
        _write(folder / "screenplay.md", _screenplay_md(plan["script"]))
        _write(folder / "review.md", _review_md(plan["review"]))
        _json(folder / "script.json", script)
        _json(folder / "storyboard.json", storyboard)
        results.append({
            "code": code,
            "kind": "short_film",
            "topic": topic,
            "genre": genre,
            "checks_passed": plan["checks"]["passed"],
            "checks_must": plan["checks"]["must_count"],
            "review_must": plan["review"]["summary"]["must"],
            "review_should": plan["review"]["summary"]["should"],
            "script_blockers": [f for f in script_checks if f["severity"] == "blocker"],
            "storyboard_blockers": [f for f in storyboard_checks if f["severity"] == "blocker"],
            "segments": len(storyboard["segments"]),
            "shots": sum(len(seg["shots"]) for seg in storyboard["segments"]),
            "score": _score(plan, script, plan["review"]),
            "files": {
                "master_plan": str(folder / "master_plan.md"),
                "screenplay": str(folder / "screenplay.md"),
                "review": str(folder / "review.md"),
            },
        })

    plans = len(results)
    passed = sum(1 for r in results if r["checks_passed"])
    review_clean = sum(1 for r in results if r["review_must"] == 0)
    script_clean = sum(1 for r in results if not r["script_blockers"])
    storyboard_clean = sum(1 for r in results if not r["storyboard_blockers"])
    negative = _negative_control()
    aggregate = {
        "schema": "s28-blackbox-v1",
        "plans": plans,
        "check_pass_rate": round(passed / plans, 3),
        "review_clean_rate": round(review_clean / plans, 3),
        "script_rule_clean_rate": round(script_clean / plans, 3),
        "storyboard_rule_clean_rate": round(storyboard_clean / plans, 3),
        "must_total": sum(r["review_must"] for r in results),
        "results": results,
        "negative_control": negative,
        "note": "确定性规则 + 人工审读自评；不是外部评分，也不调用付费模型。",
    }
    sample_score = OUT / "ai_drama_sample" / "score.json"
    if sample_score.is_file():
        aggregate["ai_drama_sample"] = json.loads(sample_score.read_text(encoding="utf-8"))
    _json(OUT / "eval.json", aggregate)
    print(json.dumps({
        "plans": plans,
        "check_pass_rate": aggregate["check_pass_rate"],
        "review_clean_rate": aggregate["review_clean_rate"],
        "script_rule_clean_rate": aggregate["script_rule_clean_rate"],
        "storyboard_rule_clean_rate": aggregate["storyboard_rule_clean_rate"],
        "must_total": aggregate["must_total"],
        "negative_control": negative,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
