"""分镜充实：按每镜的运镜/光线/风格，从 Motion Prompt 词条库挑标准术语注入，再编译提示词。

词条：showheyohtaki/motion-prompt（MIT License (c) 2026 Shohei Ohtaki）。纯离线，不调模型。
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from hevi.avcraft.obase.motion_catalog import motion_catalog_load
from hevi.avcraft.oskill.motion import motion_search, shot_vocab_inject

_STATIC = {"static", "locked", "fixed", "固定", "静止", "定机位", ""}


def _pick(cat, query, packs, k):
    return [r["id"] for r in motion_search(cat, query, packs=packs, k=k)] if query.strip() else []


def storyboard_enrich(table: dict, *, catalog: dict | None = None, manual: dict | None = None,
                      k_camera: int = 1, k_light: int = 1, k_style: int = 1, compile: bool = True,
                      prescreen: bool = True) -> dict:
    """返回 {table(充实后), shots:[{shot_id, picked:{camera,light,style,manual}, vocab, prompt?, negative?}], markdown, credit}。

    - camera：shot.camera.move（static 跳过）+ angle → camera 包；
    - light：shot.light 或 location.light → photo 包；
    - style：table.style → photo 包（整片统一，每镜都带）；
    - manual：{shot_id: [id/slug...]} 人工指定，优先；shot 里已有 vocab_ids 也会并入。
    """
    cat = catalog or motion_catalog_load()
    tbl = copy.deepcopy(table)
    manual = manual or {}
    style_ids = _pick(cat, tbl.get("style", ""), ["photo"], k_style)
    rows, md = [], [f"# {tbl.get('title', 'storyboard')} · Motion Prompt 充实分镜", ""]
    bible = None
    for i, shot in enumerate(tbl.get("shots", [])):
        cam = shot.get("camera", {}) or {}
        move = str(cam.get("move", "")).strip()
        cam_ids = [] if move.lower() in _STATIC else _pick(cat, f"{move} {cam.get('angle', '')}", ["camera"], k_camera)
        loc = tbl.get("locations", {}).get(shot.get("location"), {})
        light_ids = _pick(cat, shot.get("light") or loc.get("light", ""), ["photo"], k_light)
        man = list(manual.get(shot["id"], [])) + list(shot.get("vocab_ids", []))
        ids = [*man, *cam_ids, *light_ids, *style_ids]
        new = shot_vocab_inject(shot, ids, cat)
        tbl["shots"][i] = new
        row = {"shot_id": shot["id"], "picked": {"manual": man, "camera": cam_ids, "light": light_ids,
                                                  "style": style_ids}, "vocab": new["vocab"]}
        if compile:
            # Deferred module: lazy import; without it this branch
            # raises ModuleNotFoundError naming the deferred module.
            from hevi.avcraft.oskill.shotprompt import compile_shot_prompt

            r = compile_shot_prompt(new, tbl, bible, prescreen=prescreen)
            row.update(prompt=r["prompt"], negative=r["negative"])
        rows.append(row)
        md += [f"## {shot['id']}  ({shot.get('duration_s', '')}s · {cam.get('size', '')} · {move or 'static'})",
               "术语：" + ("；".join(f"{v['term']}（#{v['id']}）" for v in new["vocab"]) or "—")]
        if compile:
            md += ["", "```", row["prompt"], "```", f"negative: {row['negative']}"]
        md.append("")
    md.append(f"> 术语来源：{cat['credit']}（词条 v{cat['version']}）")
    return {"table": tbl, "shots": rows, "markdown": "\n".join(md), "credit": cat["credit"]}


def _main() -> None:
    ap = argparse.ArgumentParser(description="分镜表 → Motion Prompt 术语充实 + 提示词")
    ap.add_argument("table")
    ap.add_argument("--out", required=True, help="输出目录")
    a = ap.parse_args()
    res = storyboard_enrich(json.loads(Path(a.table).read_text(encoding="utf-8")))
    o = Path(a.out)
    o.mkdir(parents=True, exist_ok=True)
    (o / "shot_table_enriched.json").write_text(json.dumps(res["table"], ensure_ascii=False, indent=1), "utf-8")
    (o / "storyboard_enriched.md").write_text(res["markdown"], "utf-8")
    (o / "storyboard_enriched.json").write_text(json.dumps(res["shots"], ensure_ascii=False, indent=1), "utf-8")
    print(o)


if __name__ == "__main__":
    _main()
