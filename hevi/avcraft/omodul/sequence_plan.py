"""多片段 sequence 编排（方法论借鉴 seedance-2.0，MIT，纯文本；不调用任何生成 API）。

状态文件 avcraft.sequence/v1：{"schema","table","bible","shots":{id:{"status":pending|ready|retake|accepted|gave_up,
"take","history":[...],"prompt":{...}}},"retakes_total","budget":{...}}
流程：plan(table) → 对 ready 镜头外部生成 → record_take(…accepted/rejected+issues) → 自动单变量重拍或续写下一镜。
下一镜只有在其 continue_from 的镜头被接受后才 ready（按已接受片段续写）。

CLI:
  python -m hevi.avcraft.omodul.sequence_plan plan SHOT_TABLE.json STATE.json [--md PROMPTS.md]
  python -m hevi.avcraft.omodul.sequence_plan take STATE.json SHOT_ID accept|reject ["issue1;issue2"] [--end-frame ".."]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from hevi.avcraft.obase.shot_table import save_json, validate_shot_table
SEQ_SCHEMA = "avcraft.sequence/v1"


def _refresh(state: dict) -> dict:
    # Deferred module: lazy import so the package imports without it;
    # calling this path without oskill/shotprompt.py raises
    # ModuleNotFoundError naming the deferred module.
    from hevi.avcraft.oskill.shotprompt import compile_shot_prompt

    tbl, bible = state["table"], state["bible"]
    for s in tbl["shots"]:
        st = state["shots"][s["id"]]
        if st["status"] in ("accepted", "gave_up"):
            continue
        dep = s.get("continue_from")
        ok = not dep or state["shots"][dep]["status"] == "accepted"
        if st["status"] == "retake" or ok:
            st["status"] = "retake" if st["status"] == "retake" else "ready"
            st["prompt"] = compile_shot_prompt(s, tbl, bible)
        else:
            st["status"], st["prompt"] = "pending", None
    return state


def sequence_plan(table: dict, *, max_per_shot: int = 3, max_total: int | None = None) -> dict:
    # Deferred module: lazy import (see _refresh).
    from hevi.avcraft.oskill.shotprompt import new_bible

    errs = validate_shot_table(table)
    if errs:
        raise ValueError("; ".join(errs))
    state = {
        "schema": SEQ_SCHEMA,
        "table": copy.deepcopy(table),
        "bible": new_bible(table),
        "shots": {s["id"]: {"status": "pending", "take": 0, "history": [], "prompt": None} for s in table["shots"]},
        "retakes_total": 0,
        "budget": {"max_per_shot": max_per_shot, "max_total": max_total or max_per_shot * len(table["shots"])},
    }
    return _refresh(state)


def record_take(state: dict, shot_id: str, accepted: bool, issues: list[str] | None = None,
                facts: dict | None = None) -> dict:
    """记录一次生成结果。接受→更新 continuity bible 并解锁后续镜头；拒绝→单变量诊断+预算判定。"""
    # Deferred module: lazy import (see _refresh).
    from hevi.avcraft.oskill.shotprompt import (
        apply_retake,
        diagnose_retake,
        retake_budget,
        update_continuity_bible,
    )

    st = copy.deepcopy(state)
    shot_i = next(i for i, s in enumerate(st["table"]["shots"]) if s["id"] == shot_id)
    shot = st["table"]["shots"][shot_i]
    rec = st["shots"][shot_id]
    rec["take"] += 1
    if accepted:
        st["bible"] = update_continuity_bible(st["bible"], shot, {**(facts or {}), "take": rec["take"]})
        rec["status"] = "accepted"
        rec["result"] = {"take": rec["take"], **(facts or {})}
    else:
        b = st["budget"]
        bud = retake_budget(rec["history"], max_per_shot=b["max_per_shot"], max_total=b["max_total"],
                            total_used=st["retakes_total"])
        if not bud["allowed"]:
            rec["status"], rec["verdict"] = "gave_up", bud
        else:
            d = diagnose_retake(shot, issues or [], rec["history"])
            st["table"]["shots"][shot_i] = apply_retake(shot, d, st["table"])
            rec["history"].append({"take": rec["take"], "issues": issues or [], "variable": d["variable"],
                                   "change": d["change"]})
            rec["status"] = "retake"
            st["retakes_total"] += 1
    return _refresh(st)


def prompts_markdown(state: dict) -> str:
    lines = [f"# {state['table'].get('title', 'sequence')} — 分镜提示词（bible v{state['bible']['version']}）", ""]
    for s in state["table"]["shots"]:
        r = state["shots"][s["id"]]
        lines.append(f"## {s['id']} · {r['status']} · take {r['take']} · {s.get('duration_s')}s")
        if r.get("prompt"):
            lines += ["", "```", r["prompt"]["prompt"], "```", f"negative: {r['prompt']['negative']}"]
            mod = r["prompt"].get("moderation")
            if mod and mod["hits"]:
                lines.append(f"moderation: {mod['risk']} · " + "；".join(
                    f"{h['term']}[{h['category']}]→{h['suggestion']}" for h in mod["hits"]))
                lines += [f"note: {n}" for n in mod.get("notes", [])]
        if r["history"]:
            lines.append("retakes: " + "; ".join(f"t{h['take']}→{h['variable']}" for h in r["history"]))
        lines.append("")
    return "\n".join(lines)


def _main() -> None:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan")
    p.add_argument("table"), p.add_argument("state"), p.add_argument("--md")
    t = sp.add_parser("take")
    t.add_argument("state"), t.add_argument("shot"), t.add_argument("verdict", choices=["accept", "reject"])
    t.add_argument("issues", nargs="?", default="")
    t.add_argument("--end-frame"), t.add_argument("--md")
    a = ap.parse_args()
    if a.cmd == "plan":
        st = sequence_plan(json.loads(Path(a.table).read_text()))
    else:
        st = record_take(json.loads(Path(a.state).read_text()), a.shot, a.verdict == "accept",
                         [x for x in a.issues.split(";") if x],
                         {"end_frame": a.end_frame} if a.end_frame else None)
    save_json(st, a.state)
    if a.md:
        Path(a.md).write_text(prompts_markdown(st))
    print(json.dumps({k: v["status"] for k, v in st["shots"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    _main()
