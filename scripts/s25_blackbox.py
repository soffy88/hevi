"""S25 黑盒：对话建画布 / 报价 / 备份 / 模板版本 / 素材加工 / 报错归因。

不调用外部模型、不产生费用；输出 JSON + 便于贴进报告的 Markdown 表。
用法：JWT_SECRET=... python scripts/s25_blackbox.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET", "s25-blackbox")

from PIL import Image

from hevi.canvas import (
    agent_build,
    backup_s25,
    diagnostics_s25,
    material_ops_s25,
    pricing_s25,
    skills_s25,
    templates_s25,
)

OUT = Path("output/s25")
CASES = [
    ("explainer", "用 60 秒讲清楚复利为什么反直觉"),
    ("live_drama", "深夜便利店，店员发现常客的小票停在五年前"),
    ("history_scene", "安史之乱前夜，长安城的一夜"),
    ("digital_human", "用 60 秒讲清楚 AI 为什么会胡说"),
    ("comic_drama", "社畜的猫在凌晨三点开口说话了"),
]


def ms(fn, *args, **kwargs):
    t = time.perf_counter()
    value = fn(*args, **kwargs)
    return (time.perf_counter() - t) * 1000, value


def graph_500() -> dict:
    nodes = [
        {
            "node_id": f"n{i}",
            "node_type": "video" if i % 5 == 0 else "image",
            "label": f"节点 {i}",
            "config": {"prompt": f"p{i}", "provider": "wan_2_7" if i % 5 == 0 else "", "duration_s": 5},
            "position": {"x": (i % 25) * 280, "y": (i // 25) * 180},
        }
        for i in range(500)
    ]
    edges = [
        {"edge_id": f"e{i}", "from_node_id": f"n{i}", "to_node_id": f"n{i+1}", "kind": "data"}
        for i in range(499)
        if i % 5 != 0
    ]
    return {"name": "perf500", "nodes": nodes, "edges": edges}


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict = {"cases": [], "perf": {}, "templates": {}, "material": {}, "diagnostics": [], "skills": {}}

    for fmt, prompt in CASES:
        plan_ms, plan = ms(agent_build.build_plan, prompt, format_id=fmt)
        apply_ms, graph = ms(agent_build.apply_plan, plan, confirm_token=plan["confirm_token"])
        types = {n["node_id"]: n["node_type"] for n in graph["nodes"]}
        from hevi.canvas.validation import EDGE_MATRIX
        illegal = [
            f"{types[edge['from_node_id']]}->{types[edge['to_node_id']]}"
            for edge in graph["edges"]
            if types[edge["to_node_id"]] not in EDGE_MATRIX.get(types[edge["from_node_id"]], frozenset())
        ]
        result["cases"].append({
            "format": fmt, "prompt": prompt,
            "plan_ms": round(plan_ms, 2), "apply_ms": round(apply_ms, 2),
            "nodes": plan["numbers"]["nodes"], "edges": plan["numbers"]["edges"],
            "shots": plan["numbers"]["shots"], "seconds": plan["numbers"]["seconds"],
            "total_cny": plan["estimate"]["total_cny"],
            "unpriced_nodes": plan["estimate"]["unpriced_nodes"],
            "illegal_edges": illegal,
            "confirm_token": plan["confirm_token"][:12],
        })

    g500 = graph_500()
    export_ms, backup = ms(backup_s25.export_backup, g500)
    verify_ms, report = ms(backup_s25.verify_backup, backup)
    import_ms, imported = ms(backup_s25.import_backup, backup)
    estimate_ms, est = ms(pricing_s25.estimate_graph, g500)
    result["perf"] = {
        "nodes": 500,
        "export_ms": round(export_ms, 2),
        "verify_ms": round(verify_ms, 2),
        "import_ms": round(import_ms, 2),
        "estimate_ms": round(estimate_ms, 2),
        "backup_ok": report["ok"],
        "backup_nodes": len(imported["nodes"]),
        "total_cny": est["total_cny"],
        "unpriced_nodes": est["unpriced_nodes"],
    }

    # 模板版本
    tdir = OUT / "templates"
    import shutil

    shutil.rmtree(tdir, ignore_errors=True)
    os.environ["HEVI_CANVAS_TEMPLATE_DIR"] = str(tdir)
    builtin_ms, builtins = ms(templates_s25.ensure_builtin_templates)
    base_graph = {"nodes": [
        {"node_id": "s", "node_type": "script", "config": {"content": "旧脚本"}},
        {"node_id": "v", "node_type": "video", "config": {"prompt": "旧画面", "provider": "wan_2_7", "duration_s": 5}},
    ], "edges": [{"edge_id": "e", "from_node_id": "s", "to_node_id": "v", "kind": "data"}]}
    created = templates_s25.create_template(template_id="blackbox-flow", name="黑盒流程", graph=base_graph, format_id="explainer")
    changed = json.loads(json.dumps(base_graph))
    changed["nodes"][1]["config"]["prompt"] = "新画面"
    v2 = templates_s25.publish_version("blackbox-flow", changed, note="换一个画面")
    old = templates_s25.get_template("blackbox-flow", 1)
    slot = next(s for s in old["slots"] if s["field"] == "prompt")
    applied = templates_s25.apply_template("blackbox-flow", {slot["key"]: "换素材后的画面"}, version=1)
    diff = templates_s25.diff_versions("blackbox-flow", 1, 2)
    result["templates"] = {
        "builtin_count": sum(1 for b in builtins if b.get("builtin")),
        "builtin_ms": round(builtin_ms, 2),
        "created_version": created["version"], "published_version": v2["version"],
        "old_pinned": old["version"],
        "applied_prompt": next(n for n in applied["nodes"] if n["node_id"] == "v")["config"]["prompt"],
        "diff": diff["summary"],
    }

    # 素材加工
    src = OUT / "material-src.png"
    if not src.is_file():
        Image.new("RGB", (640, 360), (30, 80, 150)).save(src)
    crop_ms, cropped = ms(material_ops_s25.crop, src, {"x": 10, "y": 10, "w": 320, "h": 180}, out_dir=OUT)
    split_ms, split = ms(material_ops_s25.split_grid, src, cols=4, rows=3, out_dir=OUT)
    annotate_ms, annotated = ms(material_ops_s25.annotate, src, [
        {"type": "box", "x": 20, "y": 20, "x2": 200, "y2": 140},
        {"type": "text", "x": 30, "y": 200, "text": "S25 标注"},
    ], out_dir=OUT)
    result["material"] = {
        "crop_ms": round(crop_ms, 1), "crop": [cropped["width"], cropped["height"]],
        "split_ms": round(split_ms, 1), "tiles": split["count"],
        "annotate_ms": round(annotate_ms, 1), "marks": annotated["marks"],
        "inpaint": material_ops_s25.inpaint_availability(),
    }

    # 报错归因
    for err in ("429 rate limit", "401 unauthorized sk-abcdefgh123", "ReadTimeout",
                "insufficient credit", "502 bad gateway", "no such file /data/a.png",
                "ValueError odd"):
        out = diagnostics_s25.explain_failure(err, node_type="video")
        result["diagnostics"].append({"error": err, "category": out["category"], "retryable": out["retryable"]})

    # 技能
    result["skills"] = {
        "count": len(skills_s25.list_skills()),
        "items": [{k: s[k] for k in ("id", "version", "sha256")} for s in skills_s25.list_skills()],
    }

    (OUT / "blackbox.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("| 形式 | 计划 ms | 建图 ms | 节点 | 连线 | 镜 | 秒 | ¥ | 未定价 | 非法边 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for c in result["cases"]:
        print(f"| {c['format']} | {c['plan_ms']} | {c['apply_ms']} | {c['nodes']} | {c['edges']} | "
              f"{c['shots']} | {c['seconds']:g} | {c['total_cny']} | {c['unpriced_nodes']} | {len(c['illegal_edges'])} |")
    p = result["perf"]
    print(f"\n500 节点：导出 {p['export_ms']}ms / 校验 {p['verify_ms']}ms / 导入 {p['import_ms']}ms / "
          f"报价 {p['estimate_ms']}ms / 合法 {p['backup_ok']}")
    print(f"模板：内置 {result['templates']['builtin_count']} 个（{result['templates']['builtin_ms']}ms）；"
          f"v{result['templates']['created_version']} → v{result['templates']['published_version']}；"
          f"{result['templates']['diff']}")
    print(f"素材：裁切 {result['material']['crop']} / 宫格 {result['material']['tiles']} 张 / "
          f"标注 {result['material']['marks']} 处 / 局部重绘 available={result['material']['inpaint']['available']}")
    print("报错归因：" + ", ".join(f"{d['error']}→{d['category']}" for d in result["diagnostics"]))
    print(f"技能：{result['skills']['count']} 个")
    return result


if __name__ == "__main__":
    main()
