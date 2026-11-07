"""分镜表 → 视频生成提示词编译 / lock line / continuity bible / 单变量重拍诊断与次数预算。

LEGACY storyboard-table renderer (2026-10-31): this module's
``compile_shot_prompt`` takes a storyboard table, not the beat
schema, and its return shape (prompt + moderation + lock_line +
retake helpers) is wired into sequence_plan / storyboard_enrich.
The canonical generation-ready entry point is
``story.prompt_compiler.compile_generation_ready_episode``; do
not add new callers to this legacy renderer, and do not treat its
output as generation-ready (no anchor/binding/tier checks here).

方法论借鉴 Emily2040/seedance-2.0（MIT，仅思路，纯文本实现，不调用任何生成 API）：
- 一镜一事、按固定顺序写：机位 → 画内主体(外观) → 站位 → 动作 → 视线 → 他人/背景 → 光 → 末帧；
- 每镜末尾重复同一条 lock line（人物外观/服装/场景/光/站位），保证跨镜一致；
- continuity bible 记录“已接受片段”的事实（末帧、站位、道具、服装变化），下一镜据此续写；
- 重拍一次只改一个变量（便于归因），并设次数预算，超预算就简化/拆镜/接受最好的一条。
纯函数，可单测。
"""

from __future__ import annotations

import copy

# 问题 → 单一可调变量（按优先级）及改法
_RETAKE_RULES = [
    ({"identity", "face", "脸", "换人", "不像", "drift", "长相"}, "lock",
     "加强 lock line：把人物外观/服装逐字重复，并在开头点名人物"),
    ({"wardrobe", "服装", "衣服", "costume"}, "lock", "lock line 写死服装颜色与款式"),
    ({"camera", "机位", "运镜", "镜头运动", "move", "shake", "抖"}, "camera",
     "运镜降级为 static 或单一方向慢推"),
    ({"extra", "多人", "多出", "他人", "crowd", "背景人"}, "others", "背景改为 'no other people'"),
    ({"light", "光", "flicker", "闪", "曝光", "color", "色"}, "light", "光线写成单一主光方向+色温，去掉变化描述"),
    ({"gaze", "视线", "看错", "eyeline"}, "gaze", "视线写成明确目标（看向画左/看向某人/看镜头）"),
    ({"action", "动作", "没做", "too much", "过多", "变形", "morph"}, "action", "动作简化为一个动词短语，删修饰"),
    ({"end", "末帧", "衔接", "continuity", "跳"}, "end_frame", "末帧写成可续接的静态姿态"),
    ({"duration", "太快", "太慢", "节奏"}, "duration_s", "时长调整 ±2s"),
]
_FALLBACK_ORDER = ["action", "camera", "others", "light", "gaze", "lock", "end_frame"]


def _chars(tbl: dict, bible: dict | None) -> dict:
    ch = copy.deepcopy(tbl.get("characters", {}))
    for cid, st in ((bible or {}).get("characters") or {}).items():
        ch.setdefault(cid, {}).update({k: v for k, v in st.items() if v})
    return ch


def lock_line(shot: dict, tbl: dict, bible: dict | None = None, *, extra: str = "") -> str:
    """每镜重复的一致性锁定句：人物外观+服装、场景、光、站位、风格（来自分镜表 + bible 最新状态）。"""
    ch = _chars(tbl, bible)
    loc = tbl.get("locations", {}).get(shot.get("location"), {})
    pos = {**((bible or {}).get("positions") or {}), **(shot.get("positions") or {})}
    parts = []
    for cid in shot.get("in_frame", []):
        c = ch.get(cid, {})
        desc = ", ".join(x for x in (c.get("look"), c.get("wardrobe")) if x)
        p = pos.get(cid)
        parts.append(f"{c.get('name', cid)} ({desc}{'; ' + p if p else ''})")
    light = shot.get("light") or loc.get("light")
    seg = ["LOCK: same " + "; same ".join(parts)] if parts else ["LOCK:"]
    if loc:
        seg.append(f"same location {loc.get('name', '')}: {loc.get('look', '')}".strip())
    if light:
        seg.append(f"same light: {light}")
    if tbl.get("style"):
        seg.append(f"style: {tbl['style']}")
    if extra:
        seg.append(extra)
    return " | ".join(seg) + "."


def compile_shot_prompt(
    shot: dict,
    tbl: dict,
    bible: dict | None = None,
    *,
    max_chars: int = 900,
    prescreen: bool = True,
    auto_rewrite: bool = False,
    moderation_opts: dict | None = None,
) -> dict:
    """单镜提示词（LEGACY storyboard-table 渲染器，见模块 docstring）。
    返回 {"shot_id","prompt","negative","lock_line","continue_from","moderation"?}。

    prescreen=True 时附 moderation_prescreen 结果（风险词+改写建议）；auto_rewrite=True 时直接用改写后的
    prompt（lock line 也会被改写，保持跨镜一致需在分镜表源头改词）。
    """
    ch = _chars(tbl, bible)
    cam = shot.get("camera", {})
    cam_s = " ".join(x for x in (str(cam.get("size", "")).upper(), cam.get("angle"), cam.get("lens")) if x)
    move = cam.get("move", "static")
    names = [ch.get(c, {}).get("name", c) for c in shot.get("in_frame", [])]
    lines = [f"[{shot.get('duration_s', '')}s, {tbl.get('aspect', '16:9')}] {cam_s} shot, camera {move}."]
    if names:
        lines.append("In frame: " + ", ".join(names) + ".")
    pos = shot.get("positions") or {}
    if pos:
        lines.append("Blocking: " + ", ".join(f"{ch.get(k, {}).get('name', k)} {v}" for k, v in pos.items()) + ".")
    cont = shot.get("continue_from")
    prev_end = ((bible or {}).get("accepted") or {}).get(cont, {}).get("end_frame") if cont else None
    if prev_end:
        lines.append(f"Starts exactly where previous clip ended: {prev_end}.")
    lines.append(f"Action: {shot['action']}.")
    if shot.get("gaze"):
        lines.append(f"Gaze: {shot['gaze']}.")
    lines.append(f"Background: {shot.get('others') or 'no other people'}.")
    loc = tbl.get("locations", {}).get(shot.get("location"), {})
    if shot.get("light") or loc.get("light"):
        lines.append(f"Light: {shot.get('light') or loc.get('light')}.")
    if shot.get("dialogue"):
        lines.append(f'Dialogue: "{shot["dialogue"]}".')
    lines.append(f"Ends on: {shot['end_frame']}.")
    if shot.get("vocab"):  # 可选：oskill.motion.shot_vocab_inject 注入的 Motion Prompt 术语（MIT 词条）
        from hevi.avcraft.oskill.motion import vocab_line

        lines.append(vocab_line(shot["vocab"]))
    ll = lock_line(shot, tbl, bible)
    body = " ".join(lines)
    if len(body) + len(ll) + 1 > max_chars:  # 超长先砍背景/台词，lock line 永不砍
        body = " ".join(l for l in lines if not l.startswith(("Background:", "Dialogue:")))
        if len(body) + len(ll) + 1 > max_chars:
            terms = ""
            if shot.get("vocab"):  # 仍超长：术语行压成只留术语名，正文截断，术语保底
                terms = "Terms: " + "; ".join(v["term"] for v in shot["vocab"]) + "."
            core = " ".join(l for l in lines if not l.startswith(("Background:", "Dialogue:", "Terms:")))
            room = max(0, max_chars - len(ll) - 1 - (len(terms) + 1 if terms else 0))
            body = (core[:room] + (" " + terms if terms else "")).strip()
    neg = "extra people, identity change, wardrobe change, text, watermark, jump cut, flicker"
    if move == "static":
        neg += ", camera movement"
    res = {"shot_id": shot["id"], "prompt": f"{body} {ll}", "negative": neg, "lock_line": ll,
           "continue_from": cont}
    if prescreen:
        from hevi.avcraft.oskill.moderation import moderation_prescreen

        mod = moderation_prescreen(res["prompt"], **(moderation_opts or {}))
        res["moderation"] = {k: mod[k] for k in ("ok", "risk", "hits", "changed", "notes")}
        if mod["hits"]:
            res["moderation"]["rewritten"] = mod["rewritten"]
        if auto_rewrite and mod["changed"]:
            res["prompt_original"], res["prompt"] = res["prompt"], mod["rewritten"]
    return res


def new_bible(tbl: dict) -> dict:
    return {"version": 0, "characters": {}, "positions": {}, "props": {}, "accepted": {}, "log": []}


def update_continuity_bible(bible: dict, shot: dict, accepted: dict) -> dict:
    """记录已接受片段的事实（不是计划）：accepted={"end_frame"?, "positions"?, "wardrobe"?:{cid:..},
    "props"?:{name:state}, "take": n, "clip"?: path}。返回新 bible（version+1）。"""
    b = copy.deepcopy(bible)
    b["version"] = b.get("version", 0) + 1
    b.setdefault("accepted", {})[shot["id"]] = {
        "end_frame": accepted.get("end_frame") or shot.get("end_frame"),
        "take": accepted.get("take", 1),
        "clip": accepted.get("clip"),
    }
    b["positions"] = {**b.get("positions", {}), **(shot.get("positions") or {}),
                      **(accepted.get("positions") or {})}
    for cid, w in (accepted.get("wardrobe") or {}).items():
        b.setdefault("characters", {}).setdefault(cid, {})["wardrobe"] = w
    b["props"] = {**b.get("props", {}), **(accepted.get("props") or {})}
    b.setdefault("log", []).append(f"v{b['version']}: accepted {shot['id']} take {accepted.get('take', 1)}")
    return b


def diagnose_retake(shot: dict, issues: list[str], history: list[dict] | None = None) -> dict:
    """单变量重拍诊断：从问题描述里选**一个**最该改的变量；同一变量已改过且问题仍在→换下一个候选。
    history=[{"variable":..}] 为本镜以往重拍记录。"""
    tried = [h.get("variable") for h in (history or [])]
    text = " ".join(issues).lower()
    cands = []
    for keys, var, how in _RETAKE_RULES:
        if any(k.lower() in text for k in keys):
            cands.append((var, how))
    for var in _FALLBACK_ORDER:
        if all(v != var for v, _ in cands):
            cands.append((var, "无明确匹配：按默认顺序尝试"))
    for var, how in cands:
        if tried.count(var) < 1:
            return {"shot_id": shot["id"], "variable": var, "change": how, "issues": issues,
                    "single_variable": True}
    var, how = cands[0]
    return {"shot_id": shot["id"], "variable": var, "change": how + "（已试过，再试一次）",
            "issues": issues, "single_variable": True}


def apply_retake(shot: dict, diag: dict, tbl: dict | None = None) -> dict:
    """按诊断只改一个字段，返回新 shot（retake+1）。"""
    s = copy.deepcopy(shot)
    v = diag["variable"]
    if v == "camera":
        s["camera"] = {**s.get("camera", {}), "move": "static"}
    elif v == "others":
        s["others"] = "no other people, empty background"
    elif v == "light":
        loc = (tbl or {}).get("locations", {}).get(s.get("location"), {})
        s["light"] = (loc.get("light") or "soft key light from frame-left, neutral 5600K") + ", constant, no flicker"
    elif v == "gaze":
        s["gaze"] = s.get("gaze") or "looks at camera"
        s["gaze"] = s["gaze"].split(",")[0] + ", steady eyeline"
    elif v == "action":
        a = str(s.get("action", ""))
        for sep in ("然后", "接着", " then ", "并且", "同时", ",", "，", " and "):
            a = a.split(sep)[0]
        s["action"] = a.strip()
    elif v == "end_frame":
        s["end_frame"] = str(s.get("end_frame", "")).split(",")[0] + ", holds still"
    elif v == "duration_s":
        s["duration_s"] = max(2, float(s.get("duration_s", 5)) - 2)
    elif v == "lock":
        s["lock_boost"] = True
        s["notes"] = (s.get("notes", "") + " [lock reinforced]").strip()
    s["retake"] = s.get("retake", 0) + 1
    s.setdefault("retake_log", []).append({"variable": v, "change": diag["change"]})
    return s


def retake_budget(history: list[dict], *, max_per_shot: int = 3, max_total: int = 12,
                  total_used: int = 0) -> dict:
    """重拍预算：每镜 ≤max_per_shot 次、整片 ≤max_total。超了给出降级动作。"""
    used = len(history)
    if total_used >= max_total:
        return {"allowed": False, "remaining": 0, "action": "accept_best",
                "why": f"整片重拍已用 {total_used}/{max_total}"}
    if used >= max_per_shot:
        same = len({h.get('variable') for h in history}) == 1
        return {"allowed": False, "remaining": 0, "action": "split_shot" if same else "simplify_or_accept_best",
                "why": f"本镜重拍已用 {used}/{max_per_shot}"}
    return {"allowed": True, "remaining": max_per_shot - used, "action": "retake",
            "why": f"本镜 {used}/{max_per_shot}，整片 {total_used}/{max_total}"}
