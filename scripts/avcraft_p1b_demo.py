"""avcraft P1 剩余项样例：多信号高光拆条 + 横转竖跟随说话人（有脸/无脸回退）+ moderation 预审接入 sequence
+ init_session 开放参数。python scripts/avcraft_p1b_demo.py （在 hevi 仓库根目录；需 .venv 的 cv2/numpy）"""
import copy
import json
import time
from pathlib import Path

from hevi.avcraft.obase.shot_table import save_json
from hevi.avcraft.omodul.edit_session import init_session
from hevi.avcraft.omodul.highlight_clips import highlight_clips
from hevi.avcraft.omodul.reframe_vertical import reframe_vertical
from hevi.avcraft.omodul.sequence_plan import prompts_markdown, sequence_plan
from hevi.avcraft.oskill.moderation import moderation_prescreen
from hevi.avcraft.oskill.timeline import keep_ranges, load_timeline, render_cues

P0, P1, OUT = Path("output/avcraft_p0"), Path("output/avcraft_p1"), Path("output/avcraft_p1b")
OUT.mkdir(parents=True, exist_ok=True)
rep, t0 = {}, time.time()

# 1) 多信号高光：p0 cues（原片轴）经 p0 停顿时间线映射到 cut.mp4 轴
p0 = load_timeline(P0 / "dub_sample.timeline.json")
p0["cues"] = [{**c, "deleted": False} for c in json.loads((P0 / "dub_sample.cues.json").read_text())["cues"]]
cues = render_cues(p0)
hl = highlight_clips(P0 / "dub_sample.cut.mp4", OUT / "highlights", cues=cues, top_n=3, min_len=12, max_len=30,
                     keywords=["Peking Man", "fire", "700,000", "skull"])
rep["highlights"] = [{k: h[k] for k in ("rank", "start", "end", "score", "reasons", "text")} for h in hl["highlights"]]
rep["highlight_signals"] = hl["signals"]
rep["highlight_s"] = round(time.time() - t0, 1)

# 2) 横转竖跟随：有脸素材（YuNet 本机已有）+ 无脸素材（回退运动/中心）；cue 演示字幕兼容（时间轴不变）
t1 = time.time()
face_src = Path("data/cinematic_output/ep01_beijingren/beat_05.mp4")
r_face = reframe_vertical(face_src, OUT / "reframe/face_9x16.mp4", size=(720, 1280),
                          cues=[{"id": 1, "start": 0.3, "end": 3.0, "text": "Crop follows the front walker.",
                                 "tr": "裁切跟随最前面的人。"},
                                {"id": 2, "start": 3.2, "end": 6.0, "text": "Subtitles keep the same timeline.",
                                 "tr": "字幕沿用同一时间线。"}])
nf = sorted(Path("data/workspace").glob("*/landscape.mp4"))[0]
r_nf = reframe_vertical(nf, OUT / "reframe/noface_9x16.mp4", size=(720, 1280), burn=False)
rep["reframe"] = {"face": {k: r_face[k] for k in ("detector", "src", "crop", "out_size", "output_s", "stats")},
                  "noface": {k: r_nf[k] for k in ("detector", "src", "crop", "out_size", "output_s", "stats")},
                  "sources": {"face": str(face_src), "noface": str(nf)}, "secs": round(time.time() - t1, 1)}

# 3) moderation_prescreen 接入 shotprompt/sequence：在 p1 分镜表上注入风险词
table = copy.deepcopy(json.loads((P1 / "seq/shot_table.json").read_text()))
table["title"] += " · moderation 演示"
table["shots"][0]["action"] = "Elder feeds a branch into the fire while a bloody knife lies on the rock"
table["shots"][0]["others"] = "a Coca-Cola can glints in the ash"
st = sequence_plan(table, max_per_shot=2)
save_json(st, OUT / "seq/sequence_state.json")
(OUT / "seq/prompts.md").write_text(prompts_markdown(st))
m = st["shots"]["s1"]["prompt"]["moderation"]
rep["moderation"] = {"s1": {"risk": m["risk"], "hits": [(h["term"], h["category"], h["suggestion"]) for h in m["hits"]],
                            "rewritten_excerpt": m["rewritten"][:220]},
                     "samples": {t: moderation_prescreen(t)["risk"] for t in
                                 ["a naked child on the beach", "Spider-Man drinks Pepsi", "calm sunrise over hills",
                                  "他用匕首捅了对方，血泊中"]}}

# 4) init_session 开放参数：同一素材不同灵敏度
sess = {}
for name, kw in {"default": {}, "sensitive": {"scene_threshold": 5, "still_sensitivity": "high", "still_min": 1.0},
                 "strict": {"scene_threshold": 20, "still_sensitivity": 0.1, "still_min": 3.0}}.items():
    row = {}
    for vid, cs in ((P0 / "dub_sample.cut.mp4", cues),
                    (Path("data/cinematic_output/ep01_beijingren/final_no_audio.mp4"), [])):
        tl = init_session(vid, cs, repair=False, visual=True, **kw)
        row[vid.name] = {"params": tl["params"].get("visual_detect"), "stats": tl["params"].get("visual_stats"),
                         "scene_markers": len([x for x in tl.get("markers", []) if x["kind"] == "scene"]),
                         "kept_s": round(sum(b - a for a, b in keep_ranges(tl)), 2)}
    sess[name] = row
rep["init_session_params"] = sess
rep["total_s"] = round(time.time() - t0, 1)
(OUT / "p1b_demo.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
print(json.dumps(rep, ensure_ascii=False, indent=1))
