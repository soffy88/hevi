"""分镜表（shot table）schema —— 方法论借鉴 Emily2040/seedance-2.0（MIT，仅思路，不接任何付费生成）。

schema avcraft.shot_table/v1：
{
 "schema", "title", "aspect":"9:16", "style":"一句话整体风格", "duration_budget_s"?,
 "characters": {cid: {"name","look","wardrobe","props"?:[]}},
 "locations":  {lid: {"name","look","light"}},
 "shots": [{
    "id","duration_s",
    "camera":   {"size","angle","move","lens"?},      # 机位：景别/角度/运动/焦段
    "in_frame": [cid...],                                # 画内主体
    "location": lid,
    "positions"?: {cid: "frame-left|center|frame-right|bg"},
    "gaze"?:    "视线（谁看向哪里）",
    "action":   "单一主动作（一镜一事）",
    "others"?:  "背景/他人",
    "light"?:   "本镜光线（缺省继承 location.light）",
    "end_frame":"末帧状态（供下一镜续接）",
    "dialogue"?: "...", "notes"?: "...", "continue_from"?: shot_id
 }]
}
"""

from __future__ import annotations

import json
from pathlib import Path

SHOT_SCHEMA = "avcraft.shot_table/v1"
CAMERA_SIZES = {"ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS", "WS", "OTS", "POV", "INSERT"}
REQUIRED = ("id", "duration_s", "camera", "in_frame", "location", "action", "end_frame")


def validate_shot_table(tbl: dict, *, max_shot_s: float = 15.0) -> list[str]:
    """返回错误列表（空=通过）。只做结构/引用/一镜一事等确定性检查。"""
    errs: list[str] = []
    if tbl.get("schema") != SHOT_SCHEMA:
        errs.append(f"schema != {SHOT_SCHEMA}")
    chars, locs = tbl.get("characters", {}), tbl.get("locations", {})
    ids = set()
    for i, s in enumerate(tbl.get("shots", [])):
        tag = f"shots[{i}]({s.get('id', '?')})"
        for k in REQUIRED:
            if s.get(k) in (None, "", []) and not (k == "in_frame" and s.get(k) == []):
                errs.append(f"{tag}: missing {k}")
        if s.get("id") in ids:
            errs.append(f"{tag}: duplicate id")
        ids.add(s.get("id"))
        cam = s.get("camera") or {}
        if cam and str(cam.get("size", "")).upper() not in CAMERA_SIZES:
            errs.append(f"{tag}: camera.size '{cam.get('size')}' not in {sorted(CAMERA_SIZES)}")
        if cam and not cam.get("move"):
            errs.append(f"{tag}: camera.move missing (用 static 表示固定机位)")
        for c in s.get("in_frame", []) or []:
            if c not in chars:
                errs.append(f"{tag}: unknown character {c}")
        if s.get("location") and s["location"] not in locs:
            errs.append(f"{tag}: unknown location {s['location']}")
        d = s.get("duration_s") or 0
        if d and not (1 <= float(d) <= max_shot_s):
            errs.append(f"{tag}: duration_s {d} out of [1,{max_shot_s}]")
        act = str(s.get("action", ""))
        if sum(act.count(x) for x in ("然后", "接着", " then ", "并且", "同时")) >= 2:
            errs.append(f"{tag}: action 含多个动作，建议拆镜（一镜一事）")
        cf = s.get("continue_from")
        if cf and cf not in ids:
            errs.append(f"{tag}: continue_from {cf} 不在其之前")
    if not tbl.get("shots"):
        errs.append("no shots")
    return errs


def load_shot_table(path: str | Path) -> dict:
    tbl = json.loads(Path(path).read_text())
    errs = validate_shot_table(tbl)
    if errs:
        raise ValueError("invalid shot table: " + "; ".join(errs))
    return tbl


def save_json(obj: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    return p
