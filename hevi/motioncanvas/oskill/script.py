"""oskill：剧本 JSON（hevi.motioncanvas.script/v1）→ Motion Canvas 场景 TSX。纯函数，无 IO。

剧本按时间顺序写：
{
  "schema": "hevi.motioncanvas.script/v1",
  "size": [960, 540], "fps": 30, "background": "#101418",
  "objects": [
    {"id": "t", "type": "text", "text": "标题", "x": 0, "y": -220, "fontSize": 36, "hidden": true},
    {"id": "c", "type": "code", "code": "a = 1\\nb = 2", "language": "js", "x": 0, "y": 0},
    {"id": "b", "type": "rect", "width": 80, "height": 80, "fill": "#68abdf", "x": 300, "y": 0},
    {"id": "o", "type": "circle", "size": 60, "x": -300, "y": 0}
  ],
  "timeline": [
    {"op": "show", "target": "t", "duration": 0.4},
    {"op": "text", "target": "t", "text": "新标题", "duration": 0.6},
    {"op": "code", "target": "c", "code": "...", "duration": 0.8},
    {"op": "highlight", "target": "c", "lines": [2, 3], "duration": 0.3},   # 1 基，闭区间；int 表示单行；null 复位
    {"op": "move", "target": "b", "x": 100, "y": 50, "duration": 0.8},
    {"op": "hide", "target": "t", "duration": 0.3},
    {"op": "wait", "duration": 0.5},
    {"op": "parallel", "steps": [ ... ]}
  ]
}
"""
from __future__ import annotations

import json

SCHEMA = "hevi.motioncanvas.script/v1"
OBJECT_TYPES = {"text", "code", "rect", "circle"}
OPS = {"wait", "show", "hide", "text", "code", "highlight", "move", "parallel"}
CJK_FONT = "Noto Sans CJK SC, Noto Serif CJK SC, sans-serif"
MONO_FONT = "DejaVu Sans Mono, Noto Sans Mono, monospace"
JS_LANGS = {"js", "javascript", "ts", "typescript", "jsx", "tsx"}
DEFAULT_DUR = {"show": 0.4, "hide": 0.3, "text": 0.6, "code": 0.8, "highlight": 0.3, "move": 0.8}


class ScriptError(ValueError):
    pass


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ScriptError(f"{name} 必须是数字: {v!r}")
    return v


def _line_count(obj) -> int:
    return len(str(obj.get("code", "")).split("\n"))


def validate(script: dict) -> dict:
    """校验并补默认值，返回规范化副本（不改入参）。"""
    if not isinstance(script, dict):
        raise ScriptError("剧本必须是 JSON 对象")
    if script.get("schema", SCHEMA) != SCHEMA:
        raise ScriptError(f"schema 必须是 {SCHEMA}")
    s = json.loads(json.dumps(script))
    s["schema"] = SCHEMA
    w, h = s.setdefault("size", [960, 540])
    if not (16 <= _num(w, "size") <= 3840 and 16 <= _num(h, "size") <= 2160):
        raise ScriptError("size 超出范围")
    if not (1 <= _num(s.setdefault("fps", 30), "fps") <= 60):
        raise ScriptError("fps 需在 1..60")
    s.setdefault("background", "#101418")
    objs = {}
    for o in s.setdefault("objects", []):
        oid, typ = o.get("id"), o.get("type")
        if not isinstance(oid, str) or not oid.isidentifier():
            raise ScriptError(f"对象 id 需为合法标识符: {oid!r}")
        if oid in objs:
            raise ScriptError(f"对象 id 重复: {oid}")
        if typ not in OBJECT_TYPES:
            raise ScriptError(f"未知对象类型 {typ!r}（支持 {sorted(OBJECT_TYPES)}）")
        for k in ("x", "y"):
            _num(o.setdefault(k, 0), f"{oid}.{k}")
        objs[oid] = o
    if "timeline" not in s or not isinstance(s["timeline"], list):
        raise ScriptError("缺少 timeline 列表")

    def chk(step, where):
        op = step.get("op")
        if op not in OPS:
            raise ScriptError(f"{where}: 未知 op {op!r}")
        if op == "parallel":
            subs = step.get("steps")
            if not isinstance(subs, list) or not subs:
                raise ScriptError(f"{where}: parallel 需要非空 steps")
            for i, sub in enumerate(subs):
                chk(sub, f"{where}.steps[{i}]")
            return
        if op == "wait":
            if _num(step.get("duration", 0), f"{where}.duration") < 0:
                raise ScriptError(f"{where}: wait 时长不能为负")
            step.setdefault("duration", 0)
            return
        d = _num(step.setdefault("duration", DEFAULT_DUR[op]), f"{where}.duration")
        if d <= 0:
            raise ScriptError(f"{where}: duration 必须 > 0")
        tgt = objs.get(step.get("target"))
        if tgt is None:
            raise ScriptError(f"{where}: 未知 target {step.get('target')!r}")
        if op == "text" and tgt["type"] != "text":
            raise ScriptError(f"{where}: text 只能作用于 text 对象")
        if op in ("code", "highlight") and tgt["type"] != "code":
            raise ScriptError(f"{where}: {op} 只能作用于 code 对象")
        if op == "text" and not isinstance(step.get("text"), str):
            raise ScriptError(f"{where}: 缺少 text")
        if op == "code" and not isinstance(step.get("code"), str):
            raise ScriptError(f"{where}: 缺少 code")
        if op == "highlight":
            ln = step.get("lines")
            if ln is not None:
                a, b = (ln, ln) if isinstance(ln, int) and not isinstance(ln, bool) else tuple(ln)
                n = max([_line_count(tgt)] + [_line_count(x) for x in _code_steps(s, tgt["id"])])
                if not (1 <= a <= b <= n):
                    raise ScriptError(f"{where}: 行号 {ln} 超出 1..{n}")
                step["lines"] = [a, b]
        if op == "move":
            if "x" not in step and "y" not in step and "scale" not in step:
                raise ScriptError(f"{where}: move 需 x/y/scale 之一")
            for k in ("x", "y", "scale"):
                if k in step:
                    _num(step[k], f"{where}.{k}")

    for i, st in enumerate(s["timeline"]):
        chk(st, f"timeline[{i}]")
    return s


def _code_steps(s, oid):
    out = []
    def walk(steps):
        for st in steps:
            if st.get("op") == "parallel":
                walk(st.get("steps", []))
            elif st.get("op") == "code" and st.get("target") == oid:
                out.append(st)
    walk(s.get("timeline", []))
    return out


def step_duration(step: dict) -> float:
    if step["op"] == "parallel":
        return max(step_duration(x) for x in step["steps"])
    return float(step.get("duration", 0))


def total_duration(script: dict) -> float:
    s = validate(script)
    return round(sum(step_duration(x) for x in s["timeline"]), 6)


def _obj_jsx(o: dict) -> str:
    oid, typ = o["id"], o["type"]
    p = [f"ref={{{oid}}}", f"position={{[{o['x']}, {o['y']}]}}"]
    op = 0 if o.get("hidden") else o.get("opacity", 1)
    p.append(f"opacity={{{_num(op, oid + '.opacity')}}}")
    if typ == "text":
        p += [f"fontFamily={{{_j(o.get('fontFamily', CJK_FONT))}}}", f"fontSize={{{o.get('fontSize', 36)}}}",
              f"fill={{{_j(o.get('fill', '#e6edf3'))}}}", f"text={{{_j(o.get('text', ''))}}}"]
        return f"<Txt {' '.join(p)} />"
    if typ == "code":
        p += [f"fontFamily={{{_j(o.get('fontFamily', MONO_FONT))}}}", f"fontSize={{{o.get('fontSize', 24)}}}",
              f"code={{{_j(o.get('code', ''))}}}"]
        if str(o.get("language", "")).lower() in JS_LANGS:
            p.append("highlighter={jsHL}")
        return f"<Code {' '.join(p)} />"
    p.append(f"fill={{{_j(o.get('fill', '#68abdf'))}}}")
    if typ == "rect":
        p += [f"width={{{o.get('width', 100)}}}", f"height={{{o.get('height', 100)}}}", f"radius={{{o.get('radius', 8)}}}"]
        return f"<Rect {' '.join(p)} />"
    p.append(f"size={{{o.get('size', 100)}}}")
    return f"<Circle {' '.join(p)} />"


def _step_expr(st: dict) -> str:
    op, d = st["op"], st.get("duration", 0)
    if op == "wait":
        return f"waitFor({d})"
    if op == "parallel":
        return "all(" + ", ".join(_step_expr(x) for x in st["steps"]) + ")"
    t = st["target"]
    if op == "show":
        return f"{t}().opacity(1, {d})"
    if op == "hide":
        return f"{t}().opacity(0, {d})"
    if op == "text":
        return f"{t}().text({_j(st['text'])}, {d})"
    if op == "code":
        return f"{t}().code({_j(st['code'])}, {d})"
    if op == "highlight":
        if st.get("lines") is None:
            return f"{t}().selection(DEFAULT, {d})"
        a, b = st["lines"]
        return f"{t}().selection(lines({a - 1}, {b - 1}), {d})"
    if op == "move":
        parts = []
        if "x" in st and "y" in st:
            parts.append(f"{t}().position([{st['x']}, {st['y']}], {d})")
        elif "x" in st:
            parts.append(f"{t}().position.x({st['x']}, {d})")
        elif "y" in st:
            parts.append(f"{t}().position.y({st['y']}, {d})")
        if "scale" in st:
            parts.append(f"{t}().scale({st['scale']}, {d})")
        return parts[0] if len(parts) == 1 else "all(" + ", ".join(parts) + ")"
    raise ScriptError(op)


def to_scene_tsx(script: dict) -> str:
    s = validate(script)
    objs = s["objects"]
    used = {o["type"] for o in objs}
    comps = sorted({"makeScene2D", "lines"} | {{"text": "Txt", "code": "Code", "rect": "Rect", "circle": "Circle"}[t] for t in used}
                   | ({"LezerHighlighter"} if any(str(o.get("language", "")).lower() in JS_LANGS for o in objs) else set()))
    refs_t = {"text": "Txt", "code": "Code", "rect": "Rect", "circle": "Circle"}
    out = ["// 由 hevi.motioncanvas.oskill.script 生成，勿手改",
           f"import {{{', '.join(comps)}}} from '@motion-canvas/2d';",
           "import {DEFAULT, all, createRef, waitFor} from '@motion-canvas/core';"]
    if "LezerHighlighter" in comps:
        out += ["import {parser} from '@lezer/javascript';",
                "const jsHL = new LezerHighlighter(parser.configure({dialect: 'jsx ts'}));"]
    out += ["", "export default makeScene2D(function* (view) {", f"  view.fill({_j(s['background'])});"]
    for o in objs:
        out.append(f"  const {o['id']} = createRef<{refs_t[o['type']]}>();")
    out.append("  view.add(<>")
    out += [f"    {_obj_jsx(o)}" for o in objs]
    out.append("  </>);")
    for st in s["timeline"]:
        out.append(f"  yield* {_step_expr(st)};")
    out.append("});")
    return "\n".join(out) + "\n"


def project_ts(scene_name: str = "main") -> str:
    return ("import {makeProject} from '@motion-canvas/core';\n"
            f"import scene from './scenes/{scene_name}?scene';\n\n"
            "export default makeProject({scenes: [scene]});\n")


def project_meta(script: dict) -> str:
    s = validate(script)
    w, h = s["size"]
    meta = {"version": 0,
            "shared": {"background": None, "range": [0, None], "size": {"x": w, "y": h}, "audioOffset": 0},
            "preview": {"fps": 30, "resolutionScale": 1},
            "rendering": {"fps": s["fps"], "resolutionScale": 1, "colorSpace": "srgb",
                          "exporter": {"name": "@motion-canvas/ffmpeg",
                                       "options": {"fastStart": True, "includeAudio": False}}}}
    return json.dumps(meta, indent=2) + "\n"
