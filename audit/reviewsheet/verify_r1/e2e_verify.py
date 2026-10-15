"""核验员独立端到端：manifest → review_sheet → 标注 patch → 应用 → 重新渲染 → kids_gate（K2 验收 4/5）。
全部本地 CPU（PIL + ffmpeg），产物在 e2e/。输出 results_e2e.json。
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

from hevi.kids import annotation_revision as ar
from hevi.kids import render_local, review_sheet
from hevi.kids.manifest_adapter import load_manifest
from hevi.production.shot_spec import ShotSpec, merge_patch
from hevi.quality.kids_gate import kids_gate_extended, kids_gate_workflow

OUT = Path(__file__).resolve().parent / "e2e"
OUT.mkdir(parents=True, exist_ok=True)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                        "-of", "json", str(p)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def frames(p, tag, times):
    outs = []
    for t in times:
        f = OUT / f"{tag}_t{t:05.2f}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(p), "-frames:v", "1",
                        "-vf", "scale=270:-2", str(f)], check=True)
        outs.append(str(f))
    return outs


lines = ["小狐狸抬头看夜空", "星星眨眨眼睛", "小狐狸找到一颗小星星", "它把星星送给小兔子", "大家一起笑了", "分享让快乐变大"]
shots = []
for i, ln in enumerate(lines, 1):
    shots.append({"shot_index": i, "duration": 4.0, "line": ln, "camera": "缓慢推近", "framing": "中景",
                  "shot_spec": {"template": None, "transition_in": "fade", "effect": "warm", "style": "soft",
                                "sfx": [], "camera": "slow_push_in", "subtitle_style": "kids_large",
                                "duration": 4.0}})
data = {
    "schema_version": "1.0", "project_id": "kids_fox_star", "episode": 1, "title": "小狐狸与星星",
    "theme": {"one_line": "分享让快乐变大"},
    "style_bible": {"art_style": "圆润绘本", "camera_language": "缓慢推近", "color_grade": "暖色马卡龙",
                    "negative": "无暴力无快切"},
    "characters": [{"id": "char_fox", "name": "小狐狸"}],
    "props": [{"id": "prop_star", "fixed_description": "暖黄五角星", "state": "constant"}],
    "scenes": [{"id": "scene_forest", "palette": ["#F7D774"]}],
    "transition_table": [{"cut": f"S{i}->S{i+1}", "technique": "fade"} for i in range(1, 6)],
    "spoken_language": [{"shot_index": i, "language": "zh-CN"} for i in range(1, 7)],
    "shots": shots,
}
R = {}
mp = OUT / "manifest_v1.json"
mp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
m1 = load_manifest(mp)
r1 = render_local.render_episode(m1, OUT / "ep_v1.mp4", width=540, height=960)
R["render_v1"] = {**r1, "probe": probe(r1["path"])}
R["frames_v1"] = frames(r1["path"], "v1", [2.0, 9.0, 21.0])
sheets = review_sheet.render_both_aspects(m1, OUT, base_name="sheet_v1")
R["sheets_v1"] = {a: {"path": str(p), "sha256": sha(p)} for a, p in sheets.items()}

# S3 上 pin + arrow(right) + rect（rect → effect=vignette，可见变化）
inp = ar.AnnotationInput(shot_index=3, from_revision=0,
                         marks=[ar.AnnotationMark("pin", .5, .4), ar.AnnotationMark("arrow", .5, .5, direction="right"),
                                ar.AnnotationMark("rect", .5, .5, .4, .3)],
                         source_time_ms=[9500.0], authoritative_source=R["frames_v1"][1])
patch = ar.build_patch(m1, inp)
R["patch"] = patch.to_dict()
before = m1.shot(3).spec()
merged = merge_patch(ShotSpec.model_validate(before), patch.changes).to_dict()
R["patch_unmapped_fields_byte_equal"] = all(
    json.dumps(before[k], sort_keys=True) == json.dumps(merged[k], sort_keys=True)
    for k in before if k not in patch.changes)
data2 = copy.deepcopy(data)
data2["shots"][2]["shot_spec"] = merged
mp2 = OUT / "manifest_v2.json"
mp2.write_text(json.dumps(data2, ensure_ascii=False, indent=1), encoding="utf-8")
m2 = load_manifest(mp2)
r2 = render_local.render_episode(m2, OUT / "ep_v2.mp4", width=540, height=960)
R["render_v2"] = {**r2, "probe": probe(r2["path"])}
R["frames_v2"] = frames(r2["path"], "v2", [2.0, 9.0, 21.0])
R["v1_v2_video_differs"] = r1["sha256"] != r2["sha256"]
# S3 内帧是否真的变了（vignette 应使边角变暗），S1 帧应不变
import numpy as np
from PIL import Image
a1 = np.asarray(Image.open(R["frames_v1"][1]).convert("RGB")).astype(int)
a2 = np.asarray(Image.open(R["frames_v2"][1]).convert("RGB")).astype(int)
b1 = np.asarray(Image.open(R["frames_v1"][0]).convert("RGB")).astype(int)
b2 = np.asarray(Image.open(R["frames_v2"][0]).convert("RGB")).astype(int)
R["s3_frame_mean_absdiff"] = float(np.abs(a1 - a2).mean())
R["s3_corner_luma_v1_v2"] = [float(a1[:20, :20].mean()), float(a2[:20, :20].mean())]
R["s1_frame_mean_absdiff"] = float(np.abs(b1 - b2).mean())
# camera 字段是否影响渲染：只改 camera 再渲染一次
data3 = copy.deepcopy(data)
data3["shots"][2]["shot_spec"]["camera"] = "pan_right+push_in"
mp3 = OUT / "manifest_cam_only.json"
mp3.write_text(json.dumps(data3, ensure_ascii=False, indent=1), encoding="utf-8")
r3 = render_local.render_episode(load_manifest(mp3), OUT / "ep_cam_only.mp4", width=540, height=960)
R["camera_only_patch_changes_render"] = r3["sha256"] != r1["sha256"]
# 确定性
r1b = render_local.render_episode(m1, OUT / "ep_v1_again.mp4", width=540, height=960)
R["render_deterministic"] = r1b["sha256"] == r1["sha256"]
# gate
g = kids_gate_extended(Path(r2["path"]), manifest=m2)
w = kids_gate_workflow(Path(r2["path"]))
R["gate_ext"] = {k: g[k] for k in ("status", "violations", "warnings", "timecodes", "checklist")}
R["gate_orig"] = {k: w[k] for k in ("status", "violations")}
(OUT.parent / "results_e2e.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: R[k] for k in ("patch", "patch_unmapped_fields_byte_equal", "v1_v2_video_differs",
                                     "s3_frame_mean_absdiff", "s3_corner_luma_v1_v2", "s1_frame_mean_absdiff",
                                     "camera_only_patch_changes_render", "render_deterministic")},
                 ensure_ascii=False, default=str))
print(json.dumps(R["gate_ext"], ensure_ascii=False)[:1500])
print("E2EDONE")
