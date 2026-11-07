"""avcraft P1 样例：用 output/avcraft_p0 跑通 统一时间线编辑 + 画面信号 + 断句修补 + 烧录/软挂 + 分镜 sequence。
python scripts/avcraft_p1_demo.py  （在 hevi 仓库根目录）"""
import json
import time
from pathlib import Path

from hevi.avcraft.oskill.timeline import load_timeline, render_cues, apply_ops, save_timeline, keep_ranges
from hevi.avcraft.omodul.edit_session import init_session, export_session
from hevi.avcraft.omodul.sequence_plan import sequence_plan, record_take, prompts_markdown
from hevi.avcraft.obase.shot_table import SHOT_SCHEMA, save_json

P0, OUT = Path("output/avcraft_p0"), Path("output/avcraft_p1")
OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
# p0 的 cues 在原片时间轴（原片已删以省空间）；借 p0 停顿剪辑时间线映射到 cut.mp4 时间轴 —— 正是“剪辑与字幕共用时间线”
p0 = load_timeline(P0 / "dub_sample.timeline.json")
p0["cues"] = [{**c, "deleted": False} for c in json.loads((P0 / "dub_sample.cues.json").read_text())["cues"]]
mapped = render_cues(p0)
terms = ["Dragonbone Hill", "Peking Man", "Homo erectus", "Zhoukoudian"]
tl = init_session(P0 / "dub_sample.cut.mp4", mapped, terms=terms, visual=True,
                  visual_policy={"freeze": {"min": 2.0}})
fixed = [(c["id"], c["text"], c["fix"]) for c in tl["cues"] if c.get("fix")]
ops = [
    {"op": "retext", "cue": 1, "text": "Peking Man was not a cave monster from mythology.",
     "tr": "北京猿人不是神话里的洞穴怪物。"},
    {"op": "retext", "cue": 3, "text": "in Zhoukoudian about 700,000 years ago.", "tr": "在周口店，约七十万年前。"},
    {"op": "delete", "cue": 45},
    {"op": "retime", "cue": 4, "start": tl["cues"][3]["start"] - 0.2},
]
apply_ops(tl, ops)
save_timeline(tl, OUT / "dub_sample.session.json")
r = export_session(tl, OUT, stem="dub_sample")
r["mapped_cues"] = len(mapped)
r["repair_fixed"] = fixed
r["visual"] = tl["params"].get("visual_stats")
r["scene_markers"] = len(tl.get("markers", []))
r["edit_s"] = round(time.time() - t0, 1)

table = {
    "schema": SHOT_SCHEMA, "title": "北京猿人 · 龙骨山", "aspect": "9:16",
    "style": "photoreal documentary reenactment, muted earth tones, 35mm film grain",
    "characters": {
        "elder": {"name": "Elder", "look": "Homo erectus male, heavy brow ridge, grey-streaked hair",
                  "wardrobe": "brown deer-hide wrap over left shoulder"},
        "youth": {"name": "Youth", "look": "Homo erectus teen, short dark hair, scar on right cheek",
                  "wardrobe": "grey wolf-fur waist wrap"}},
    "locations": {"cave": {"name": "Dragonbone Hill cave mouth", "look": "limestone cave mouth, ash layer on floor",
                           "light": "warm firelight from frame-left, cool dusk sky behind"}},
    "shots": [
        {"id": "s1", "duration_s": 5, "camera": {"size": "WS", "angle": "eye-level", "move": "slow push-in"},
         "in_frame": ["elder", "youth"], "location": "cave",
         "positions": {"elder": "frame-left by the fire", "youth": "frame-right, standing"},
         "action": "Elder feeds a branch into the fire", "gaze": "Youth watches Elder's hands",
         "end_frame": "fire flares, Elder still crouched, Youth leaning in"},
        {"id": "s2", "duration_s": 4, "camera": {"size": "CU", "angle": "low", "move": "static"},
         "in_frame": ["elder"], "location": "cave", "continue_from": "s1",
         "action": "Elder strikes a quartz flake against a cobble", "gaze": "looks down at the stone",
         "end_frame": "a sharp flake drops into his palm"},
        {"id": "s3", "duration_s": 5, "camera": {"size": "MS", "angle": "over-the-shoulder", "move": "static"},
         "in_frame": ["elder", "youth"], "location": "cave", "continue_from": "s2",
         "action": "Elder hands the flake to Youth", "gaze": "they meet each other's eyes",
         "end_frame": "Youth holds the flake up to the firelight"},
    ],
}
save_json(table, OUT / "seq/shot_table.json")
st = sequence_plan(table, max_per_shot=2)
st = record_take(st, "s1", False, ["extra person appeared in background"])
st = record_take(st, "s1", True, facts={"end_frame": "fire flares, Elder crouched frame-left, Youth leaning in frame-right",
                                         "clip": "takes/s1_t2.mp4"})
st = record_take(st, "s2", False, ["face drift: Elder looks different"])
st = record_take(st, "s2", True, facts={"end_frame": "sharp quartz flake resting in Elder's right palm"})
save_json(st, OUT / "seq/sequence_state.json")
(OUT / "seq/prompts.md").write_text(prompts_markdown(st))
r["sequence"] = {k: v["status"] for k, v in st["shots"].items()} | {"bible_v": st["bible"]["version"],
                                                                      "retakes": st["retakes_total"]}
(OUT / "p1_demo.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
print(json.dumps(r, ensure_ascii=False, indent=1))
