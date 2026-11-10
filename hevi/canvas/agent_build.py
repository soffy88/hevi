"""S25：对话建画布（净室自写，对标 BeefTV Agent 的产品能力，不复用其代码）。

一句话 → 可确认的制作方案（节点、连线、逐节点费用、步骤进度）→ 确认后
落成画布图；确认后仍可改单个节点（只影响该节点与它的报价，不改别人）。

设计约束（与 hevi 既有契约一致，不另建第二套画布）：

* 节点类型只用现有 7 类（text/image/video/audio/script/segment/asset），
  连线只用 ``hevi.canvas.validation.EDGE_MATRIX`` 已批准的边集；
* 出品形式直接复用 S21 ``hevi.studio.formats.resolve_format``，内部 line_id
  不出现在方案里；
* 费用只调用 S22 ``craft_s22`` 的同一套函数（模型单价表 + 人民币汇率），
  与 ``craft_ledger`` 的逐镜报价同源，不维护第二张价目表；
* 纯函数、无网络：脚本行由调用方传入（API 可先调 ``script.quick``），
  LLM 不可用时也能给出确定性的可确认方案。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from hevi.studio import craft_s22
from hevi.studio.formats import resolve_format

PLAN_SCHEMA = "hevi.canvas.plan.v1"

# 每个形式默认几镜。只影响“默认方案”，用户可改。
SHOTS_BY_FORMAT: dict[str, int] = {
    "history_scene": 4,
    "digital_human": 2,
    "live_drama": 4,
    "comic_drama": 4,
    "animation": 3,
    "explainer": 3,
    "material_cut": 1,
}

ASPECT_BY_FORMAT: dict[str, str] = {
    "digital_human": "9:16",
    "live_drama": "9:16",
    "comic_drama": "9:16",
    "material_cut": "9:16",
}

_DEFAULT_PROVIDER = "wan_2_7"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _token(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _clean(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(分钟|分|min|秒|s\b)", re.I)


def parse_target_seconds(text: str) -> float | None:
    """从一句话里读“60 秒 / 1 分钟”，读不到就返回 None（不猜）。"""
    match = _DURATION_RE.search(text or "")
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in ("分钟", "分", "min"):
        value *= 60
    return value if 2 <= value <= 1800 else None


def default_lines(topic: str, format_id: str) -> list[str]:
    """确定性脚本行：不调模型也能出可确认方案。

    只按中文标点切句，不编造事实；少于 2 句时补一句“收束”，让分镜表可用。
    """
    text = _clean(topic)
    for sep in ("。", "！", "？", "；", "，", ",", "\n"):
        text = text.replace(sep, "｜")
    parts = [p.strip(" ，,") for p in text.split("｜") if p.strip(" ，,")]
    if not parts:
        parts = [topic]
    limit = SHOTS_BY_FORMAT.get(format_id, 3)
    return parts[:limit]


def default_shots(
    *,
    topic: str,
    lines: list[str],
    format_id: str,
    style_id: str,
    provider: str | None = None,
    seconds: float = 5.0,
) -> list[dict[str, Any]]:
    """把脚本行排成分镜（只做结构与时长，不写生成提示词细节）。"""
    shots: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        planned = craft_s22.plan_shot(
            index=index,
            line=line,
            prompt=_shot_prompt(line, format_id, style_id),
            duration_s=seconds,
            format_id=format_id,
            style_id=style_id,
            provider=provider,
        )
        shots.append(
            {
                "index": index,
                "line": line,
                "prompt": _shot_prompt(line, format_id, style_id),
                "duration_s": planned["duration_s"],
                "route": planned["route"],
                "model": planned["model"],
            }
        )
    return shots


_STYLE_HINTS = {
    "history_scene": "史料质感，年代考据，电影光",
    "digital_human": "干净的口播画面，胸前构图，柔和棚灯",
    "live_drama": "写实电影剧照，自然皮肤，浅景深",
    "comic_drama": "动漫关键帧，干净线稿，赛璐璐上色",
    "animation": "风格化动画关键帧，剪影清楚",
    "explainer": "克制的编辑插画，大留白，信息优先",
    "material_cut": "纪实空镜，自然纹理",
}


_BEATS: dict[str, tuple[str, ...]] = {
    "explainer": ("开场：先给结论", "问题：为什么反直觉", "拆解：第一个关键变量",
                  "拆解：第二个关键变量", "例子：一个可核对的场景", "对比：不这样会怎样", "收束：回到开场"),
    "history_scene": ("开场：时间与地点", "背景：当时的规则", "转折：一个人做了一个决定",
                      "代价：谁承担了什么", "证据：出处与实物", "收束：这件事留下了什么"),
    "live_drama": ("开场：建立空间", "发现：一个不对劲的细节", "反应：人物第一次选择",
                   "升级：对方反咬", "反转：拿出证据", "悬念：新的威胁出现", "收束：留下问题"),
    "comic_drama": ("开场：日常被打破", "发现：不可能的事", "反应：夸张的第一反应",
                    "升级：第二次冲突", "反转：真相露出", "收束：下一个钩子"),
    "digital_human": ("开场：一句反直觉的话", "问题：观众最想问的", "解释：一条主线",
                      "例子：一个具体数字", "纠错：常见误解", "收束：记住一句话"),
    "animation": ("开场：角色出场", "目标：他想要什么", "阻碍：第一次失败",
                  "尝试：换一个办法", "结果：得到/失去", "收束：一个动作结束"),
}


def _scaffold_lines(format_id: str, topic: str, need: int, existing: list[str]) -> list[tuple[str, bool]]:
    """不足镜头数时补“导演节拍”脚手架（明确标记，等用户改写成自己的内容）。"""
    beats = _BEATS.get(format_id) or _BEATS["explainer"]
    out: list[tuple[str, bool]] = [(line, False) for line in existing]
    index = 0
    while len(out) < need and index < len(beats):
        label = beats[index]
        index += 1
        text = f"{label}（围绕「{topic[:28]}」写一句可拍的内容）"
        if text in existing:
            continue
        out.append((text, True))
    while len(out) < need:
        out.append((f"待补镜头 {len(out) + 1}：写一句可拍的内容", True))
    return out[:need]


def _shot_prompt(line: str, format_id: str, style_id: str) -> str:
    hint = _STYLE_HINTS.get(format_id, "电影感画面")
    return f"{hint}。画面内容：{line}"


def _node(
    key: str,
    node_type: str,
    label: str,
    config: dict[str, Any],
    *,
    depth: int,
    row: int,
) -> dict[str, Any]:
    return {
        "key": key,
        "node_type": node_type,
        "label": label,
        "config": config,
        "position": {"x": 80 + depth * 300, "y": 80 + row * 190},
    }


def _compose_nodes(
    *,
    topic: str,
    format_id: str,
    style_id: str,
    line_id: str,
    aspect: str,
    lines: list[str],
    shots: list[dict[str, Any]],
    narration: str,
    provider: str,
    structural_only: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把方案拆成节点与连线；``structural_only`` 时只保留分镜结构节点。"""
    nodes: list[dict[str, Any]] = [
        _node(
            "script",
            "script",
            "剧本 / 脚本",
            {
                "tool_id": "script.quick",
                "topic": topic,
                "content": "\n".join(lines),
                "format": format_id,
                "style": style_id,
                "line_id": line_id,
            },
            depth=0,
            row=0,
        ),
        _node(
            "storyboard",
            "text",
            "分镜表",
            {
                "kind": "storyboard",
                "aspect": aspect,
                "content": _storyboard_markdown(shots),
                "shots": shots,
            },
            depth=1,
            row=0,
        ),
    ]
    # script -> text 不是合法数据流（EDGE_MATRIX），分镜表不画这条边；
    # 分镜表自己 -> 首帧（text -> image）是合法参考边。
    edges: list[dict[str, Any]] = []
    for i, shot in enumerate(shots):
        image_key = f"shot{i + 1}_image"
        video_key = f"shot{i + 1}_video"
        nodes.append(
            _node(
                image_key,
                "image",
                f"镜头 {i + 1} 首帧",
                {
                    "role": "first_frame",
                    "shot_index": shot["index"],
                    "prompt": shot["prompt"],
                    "aspect": aspect,
                    "line": shot["line"],
                },
                depth=2,
                row=i,
            )
        )
        nodes.append(
            _node(
                video_key,
                "video",
                f"镜头 {i + 1}",
                {
                    "shot_index": shot["index"],
                    "prompt": shot["prompt"],
                    "line": shot["line"],
                    "duration_s": shot["duration_s"],
                    "provider": shot.get("model") or provider,
                    "aspect": aspect,
                    "reference_role": "first_frame",
                },
                depth=3,
                row=i,
            )
        )
        edges.append(
            {"edge_id": f"e-script-{image_key}", "from": "script", "to": image_key, "kind": "reference"}
        )
        edges.append(
            {"edge_id": f"e-{image_key}-{video_key}", "from": image_key, "to": video_key, "kind": "data"}
        )
        if structural_only:
            continue
        edges.append(
            {"edge_id": f"e-storyboard-{image_key}", "from": "storyboard", "to": image_key, "kind": "reference"}
        )
    if structural_only:
        return nodes, edges

    nodes.append(
        _node(
            "narration",
            "audio",
            "旁白",
            {
                "tool_id": "tts.synth",
                "text": narration,
                "voice_id": "default",
                "provider": "edge_tts",
            },
            depth=2,
            row=len(shots),
        )
    )
    nodes.append(
        _node(
            "assembly",
            "video",
            "合成成片",
            {
                "tool_id": "nle.project",
                "aspect": aspect,
                "shots": [s["index"] for s in shots],
                "note": "按分镜顺序拼接；音频轨由旁白节点提供",
            },
            depth=4,
            row=0,
        )
    )
    edges.append({"edge_id": "e-script-narration", "from": "script", "to": "narration", "kind": "data"})
    edges.append({"edge_id": "e-narration-assembly", "from": "narration", "to": "assembly", "kind": "data"})
    edges.extend(
        {
            "edge_id": f"e-shot{i + 1}_video-assembly",
            "from": f"shot{i + 1}_video",
            "to": "assembly",
            "kind": "data",
        }
        for i in range(len(shots))
    )
    return nodes, edges


def _storyboard_markdown(shots: list[dict[str, Any]]) -> str:
    rows = ["| 镜头 | 时长 | 台词 / 画面 | 路线 |", "|---|---|---|---|"]
    rows.extend(
        f"| {shot['index']} | {shot['duration_s']}s | {shot['line']} | {shot.get('route') or ''} |"
        for shot in shots
    )
    return "\n".join(rows)


def _questions(
    format_id: str,
    aspect: str,
    narration: str,
    shots: list[dict[str, Any]],
    target_seconds: float | None = None,
) -> list[dict[str, str]]:
    seconds = round(sum(float(s.get("duration_s") or 0) for s in shots), 1)
    items = [
        {"id": "aspect", "question": f"画幅用 {aspect}，对吗？", "answer": aspect},
        {
            "id": "duration",
            "question": f"成片约 {seconds} 秒（{len(shots)} 镜），可以吗？",
            "answer": f"{seconds}s",
        },
    ]
    if format_id != "material_cut":
        items.append(
            {
                "id": "narration",
                "question": "旁白用现有默认音色？" if narration else "不加旁白？",
                "answer": "默认音色" if narration else "无旁白",
            }
        )
    if target_seconds and target_seconds > seconds + 2:
        items.append(
            {
                "id": "target_seconds",
                "question": f"你说约 {target_seconds:g} 秒，当前方案 {seconds:g} 秒；先按现有镜头出，还是加镜？",
                "answer": f"先按 {len(shots)} 镜",
            }
        )
    return items


def estimate_plan_cost(
    *,
    nodes: list[dict[str, Any]],
    shots: list[dict[str, Any]],
) -> dict[str, Any]:
    """逐节点报价，复用 ``pricing_s25.estimate_graph``（与 S22 账本同源）。"""
    from hevi.canvas.pricing_s25 import estimate_graph

    est = estimate_graph(
        {
            "nodes": [
                {
                    "node_id": n["key"],
                    "node_type": n["node_type"],
                    "config": n.get("config") or {},
                }
                for n in nodes
            ]
        }
    )
    for row in est["per_node"]:
        row["key"] = row.get("node_id")
    for row in est["unpriced"]:
        row["key"] = row.get("node_id")
    return est


def _steps(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    groups = [
        ("script", "读题与定形式"),
        ("storyboard", "写脚本 / 分镜"),
        ("image", "镜头首帧"),
        ("video", "镜头视频"),
        ("audio", "旁白"),
        ("assembly", "合成成片"),
    ]
    steps: list[dict[str, str]] = []
    for key, label in groups:
        if key == "assembly":
            keys = [n["key"] for n in nodes if (n.get("config") or {}).get("tool_id") == "nle.project"]
        elif key == "video":
            keys = [
                n["key"]
                for n in nodes
                if n["node_type"] == "video" and (n.get("config") or {}).get("tool_id") != "nle.project"
            ]
        else:
            keys = [n["key"] for n in nodes if n["node_type"] == key]
        if keys:
            steps.append({"id": key, "label": label, "status": "ready", "node_keys": keys})
    return steps


def _signable(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": plan["schema"],
        "goal": plan["goal"],
        "format": plan["format"],
        "style": plan["style"],
        "aspect": plan["aspect"],
        "lines": plan["lines"],
        "narration": plan["narration"],
        "provider": plan["provider"],
        "nodes": [
            {k: v for k, v in node.items() if k != "position"} for node in plan["nodes"]
        ],
        "edges": plan["edges"],
    }


def build_plan(
    prompt: str,
    *,
    format_id: str | None = None,
    style_id: str | None = None,
    line_id: str | None = None,
    slots: dict[str, Any] | None = None,
    lines: list[str] | None = None,
    shots: list[dict[str, Any]] | None = None,
    seconds: float = 5.0,
    provider: str | None = None,
    narration: str | None = None,
    aspect: str | None = None,
    structural_only: bool = False,
) -> dict[str, Any]:
    """一句话 → 可确认方案。确定性、无网络、无副作用。"""
    goal = _clean(prompt)
    if not goal:
        raise ValueError("请先写一句你想做什么")
    slots = dict(slots or {})
    slots.setdefault("topic", goal)
    resolved = resolve_format(
        format_id=format_id, style_id=style_id, line_id=line_id, slots=slots
    )
    fmt = str(resolved["format"])
    style = str(resolved["style"])
    chosen_line = str(resolved["line_id"])
    aspect = aspect or ASPECT_BY_FORMAT.get(fmt, "16:9")
    chosen_provider = provider or _DEFAULT_PROVIDER

    script_lines = [_clean(x) for x in (lines or default_lines(goal, fmt)) if _clean(x)]
    if not script_lines:
        script_lines = [goal]
    target_seconds = parse_target_seconds(goal)
    scaffold_flags: list[bool] = [False] * len(script_lines)
    per_shot = float(seconds)
    if not shots:
        if target_seconds:
            desired = max(len(script_lines), min(8, round(target_seconds / max(6.0, seconds))))
            per_shot = max(3.0, min(12.0, target_seconds / max(1, desired)))
        else:
            desired = max(len(script_lines), min(SHOTS_BY_FORMAT.get(fmt, 3), 4))
        pairs = _scaffold_lines(fmt, goal, desired, script_lines)
        script_lines = [text for text, _ in pairs]
        scaffold_flags = [flag for _, flag in pairs]
    shot_list = shots or default_shots(
        topic=goal,
        lines=script_lines,
        format_id=fmt,
        style_id=style,
        provider=chosen_provider,
        seconds=per_shot,
    )
    for shot, flag in zip(shot_list, scaffold_flags, strict=False):
        shot["scaffold"] = bool(flag)
    scaffold_count = sum(1 for shot in shot_list if shot.get("scaffold"))
    narration_text = (
        narration
        if narration is not None
        else (f"{goal}。先说结论，再讲为什么。" if fmt != "material_cut" else "")
    )
    nodes, edges = _compose_nodes(
        topic=goal,
        format_id=fmt,
        style_id=style,
        line_id=chosen_line,
        aspect=aspect,
        lines=script_lines,
        shots=shot_list,
        narration=narration_text,
        provider=chosen_provider,
        structural_only=structural_only,
    )
    estimate = estimate_plan_cost(nodes=nodes, shots=shot_list)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "goal": goal,
        "format": fmt,
        "style": style,
        "line_id": chosen_line,
        "gated": bool(resolved.get("gated")),
        "aspect": aspect,
        "lines": script_lines,
        "shots": shot_list,
        "narration": narration_text,
        "provider": chosen_provider,
        "structural_only": structural_only,
        "nodes": nodes,
        "edges": edges,
        "steps": _steps(nodes),
        "questions": _questions(fmt, aspect, narration_text, shot_list, parse_target_seconds(goal)),
        "estimate": estimate,
        "numbers": {
            "nodes": len(nodes),
            "edges": len(edges),
            "shots": len(shot_list),
            "seconds": round(sum(float(s["duration_s"]) for s in shot_list), 1),
            "target_seconds": target_seconds,
            "scaffold_shots": scaffold_count,
        },
        "requires_confirm": True,
    }
    plan["confirm_token"] = _token(_signable(plan))
    return plan


def patch_plan_node(plan: dict[str, Any], node_key: str, patch: dict[str, Any]) -> dict[str, Any]:
    """改单个节点：只更新该节点 config/label，并重算报价与确认令牌。

    不重建其它节点、不改它们的位置；方案还是同一个方案。
    """
    if not any(n["key"] == node_key for n in plan.get("nodes") or []):
        raise ValueError(f"方案里没有节点：{node_key}")
    updated = json.loads(json.dumps(plan, ensure_ascii=False))
    for node in updated["nodes"]:
        if node["key"] != node_key:
            continue
        if "label" in patch and str(patch["label"]).strip():
            node["label"] = _clean(str(patch["label"]))
        cfg = patch.get("config")
        if isinstance(cfg, dict):
            node["config"] = {**(node.get("config") or {}), **cfg}
    # 视频时长/模型改动要同步回分镜，报价才和“确认后实际提交”一致。
    for node in updated["nodes"]:
        if node["node_type"] != "video":
            continue
        cfg = node.get("config") or {}
        index = int(cfg.get("shot_index") or 0)
        for shot in updated["shots"]:
            if int(shot["index"]) == index:
                if "duration_s" in cfg:
                    shot["duration_s"] = float(cfg["duration_s"])
                if "line" in cfg:
                    shot["line"] = str(cfg["line"])
                if "prompt" in cfg:
                    shot["prompt"] = str(cfg["prompt"])
    updated["estimate"] = estimate_plan_cost(
        nodes=updated["nodes"], shots=updated["shots"]
    )
    updated["numbers"] = {
        "nodes": len(updated["nodes"]),
        "edges": len(updated["edges"]),
        "shots": len(updated["shots"]),
        "seconds": round(sum(float(s["duration_s"]) for s in updated["shots"]), 1),
    }
    updated["confirm_token"] = _token(_signable(updated))
    return updated


def apply_plan(
    plan: dict[str, Any],
    *,
    confirm_token: str,
    name: str | None = None,
    selected_nodes: list[str] | None = None,
) -> dict[str, Any]:
    """确认令牌校验后把方案落成 GraphService 能直接存的图。

    ``selected_nodes`` 只用于“只建这一步”（例如先建分镜结构），连线保留两端
    都在集合内的边——不会留下悬空边。
    """
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("方案版本不认识，请重新生成")
    if not confirm_token or confirm_token != plan.get("confirm_token"):
        raise ValueError("方案已改动或确认令牌不匹配，请重新查看方案再确认")
    selected = set(selected_nodes or [])
    nodes = [n for n in plan["nodes"] if not selected or n["key"] in selected]
    keys = {n["key"] for n in nodes}
    edges = [e for e in plan["edges"] if e["from"] in keys and e["to"] in keys]
    graph_nodes = [
        {
            "node_id": n["key"],
            "node_type": n["node_type"],
            "label": n["label"],
            "config": n["config"],
            "position": n["position"],
        }
        for n in nodes
    ]
    graph_edges = [
        {"edge_id": e["edge_id"], "from_node_id": e["from"], "to_node_id": e["to"], "kind": e["kind"]}
        for e in edges
    ]
    return {
        "name": name or f"{plan['goal'][:24]} · {plan['format']}",
        "description": f"S25 对话建画布：{plan['goal']}",
        "format": plan["format"],
        "style": plan["style"],
        "plan_token": plan["confirm_token"],
        "estimate": plan["estimate"],
        "nodes": graph_nodes,
        "edges": graph_edges,
        "numbers": {"nodes": len(graph_nodes), "edges": len(graph_edges)},
    }


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    """给右侧进度面板的窄结构（不重复整张图）。"""
    est = plan.get("estimate") or {}
    return {
        "goal": plan["goal"],
        "format": plan["format"],
        "style": plan["style"],
        "numbers": plan["numbers"],
        "steps": plan["steps"],
        "questions": plan["questions"],
        "total_cny": est.get("total_cny", 0.0),
        "unpriced_nodes": est.get("unpriced_nodes", 0),
        "requires_confirm": True,
        "confirm_token": plan["confirm_token"],
    }
