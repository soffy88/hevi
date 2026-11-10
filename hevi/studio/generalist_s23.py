"""S23：吸收 creator-generalist 的 2D/3D 工作方法，做成可检查的节点。

只重述方法，不复制任何 SKILL 文本、模板或引擎代码。所有能力都是
"计划 + 自检"：给出可执行的参数，同时返回问题清单，渲染仍走 hevi 已有的
scene3d / explainer / shorts_clip / reference_adapt 产线。

六个能力：

1. ``plan_cutaway``   3D 剖面/建造过程：5–7 轮"失败 → 改进"，真实资产优先。
2. ``plan_world``     3D 时代场景/世界：年代考据、置景、镜头与声音。
3. ``plan_editorial_2d`` 2D 编辑部：地图路线、真实比例时间轴、纸张/半色调/撕纸。
4. ``check_character_motion`` / ``check_contact_and_slip`` 角色动作与穿模/滑步/悬空。
5. ``check_phone_speaker`` / ``check_masking`` / ``check_sync`` 手机外放与遮蔽、同步。
6. ``plan_remake_recipe`` / ``audit_shorts_edit`` 看片配方与 Shorts 剪辑规范。

约束：零付费、零新依赖、默认不联网；资产只接受 CC0 / CC BY，并要求署名。
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

# ---------------------------------------------------------------------------
# 资产与渲染策略
# ---------------------------------------------------------------------------

ALLOWED_ASSET_LICENSES = ("CC0", "CC BY", "public-domain")
MAX_FILE_BYTES = 300 * 1024 * 1024          # 单个下载 ≤300MB
MAX_CACHE_BYTES = 5 * 1024 * 1024 * 1024    # CC0/CC BY 缓存 ≤5G

RENDER_POLICY: dict[str, Any] = {
    "queue": "serial",                       # 3D 一次只渲一个
    "preview": {"width": 720, "height": 1280, "samples": 16, "label": "preview_720p"},
    "final": {"width": 1080, "height": 1920, "samples": 24, "label": "final_1080p"},
    "requires_approval": True,               # 720p 预览确认后才出 1080p
    "timeout_s": 20 * 60,
}

ASSET_SOURCES: tuple[dict[str, str], ...] = (
    {"name": "Poly Haven", "url": "https://polyhaven.com", "license": "CC0"},
    {"name": "ambientCG", "url": "https://ambientcg.com", "license": "CC0"},
    {"name": "Sketchfab (CC0/CC BY filter)", "url": "https://sketchfab.com", "license": "CC0/CC BY"},
    {"name": "BlenderKit (free plan)", "url": "https://www.blenderkit.com", "license": "CC0/CC BY"},
    {"name": "Wikimedia Commons", "url": "https://commons.wikimedia.org", "license": "CC0/CC BY"},
)


def _issue(code: str, detail: str, *, severity: str = "error") -> dict[str, str]:
    return {"code": code, "detail": detail, "severity": severity}


def _result(issues: list[dict[str, str]], **extra: Any) -> dict[str, Any]:
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {"ok": not errors, "issues": issues, "error_count": len(errors),
            "warning_count": len(warnings), **extra}


# ---------------------------------------------------------------------------
# 1. 3D 剖面 / 建造过程
# ---------------------------------------------------------------------------

CUTAWAY_ROUNDS: tuple[dict[str, str], ...] = (
    {
        "round": "01_blockout",
        "goal": "用最简几何把整体占位做对：一个能读懂的剪影。",
        "likely_failure": "一上来就做细节，比例失真，剖面切不到关键机构。",
        "fix": "先只做主体块、地面和相机；从正侧两个角度检查剪影。",
        "asset_need": "none",
        "check": "silhouette_readable",
    },
    {
        "round": "02_proportion",
        "goal": "按真实尺寸修正主体比例，确定剖面位置。",
        "likely_failure": "门窗、轮径、层高与真实差一截，剖面像玩具。",
        "fix": "用一张带尺寸的参考图对齐；把剖面平面做成可见的切割盒。",
        "asset_need": "reference_image",
        "check": "proportion_within_10pct",
    },
    {
        "round": "03_cut_and_mechanism",
        "goal": "切开外壳，让主机构（齿轮/活塞/梁/水路）露出来。",
        "likely_failure": "切面糊成一片，观众看不出动力怎么传。",
        "fix": "给切面单独的材质；主机构加高对比度；一条动线只讲一件事。",
        "asset_need": "cc0_mechanism_or_modeled",
        "check": "mechanism_line_visible",
    },
    {
        "round": "04_connections",
        "goal": "补二级结构与连接件，让结构站得住。",
        "likely_failure": "零件悬空、互穿，或连接方式在物理上不成立。",
        "fix": "检查每个零件的支撑关系；用螺栓/榫卯/焊缝等可见连接替代悬空。",
        "asset_need": "cc0_fasteners",
        "check": "no_floating_parts",
    },
    {
        "round": "05_materials",
        "goal": "上真实材质与磨损，区分木、石、金属、水。",
        "likely_failure": "全是一个塑料灰，剖面失去材质信息。",
        "fix": "每种材质只用一个主色 + 一个粗糙度；边缘加轻微磨损。",
        "asset_need": "cc0_pbr_textures",
        "check": "material_contrast_ok",
    },
    {
        "round": "06_light_and_camera",
        "goal": "用侧逆光突出剖面，用缓慢推近交代机构。",
        "likely_failure": "正面平光把剖面压平，镜头运动抢戏。",
        "fix": "主光 45° 侧逆，补光只提暗部；一个镜头只做一个运动。",
        "asset_need": "none",
        "check": "cut_face_lit",
    },
    {
        "round": "07_polish_qa",
        "goal": "统一色温、清理噪点，导出 720p 预览给确认。",
        "likely_failure": "直接出 1080p，返工成本高；或预览里全是临时占位。",
        "fix": "先 720p/16 samples；确认后再 1080p/24 samples。",
        "asset_need": "none",
        "check": "preview_then_final",
    },
)


def plan_cutaway(
    *,
    topic: str,
    rounds: int = 6,
    assets: list[dict[str, Any]] | None = None,
    cache_bytes: int = 0,
) -> dict[str, Any]:
    """3D 剖面的 5–7 轮建造计划；``rounds`` 夹在 5..7。"""
    count = max(5, min(7, int(rounds)))
    selected = [dict(item) for item in CUTAWAY_ROUNDS[:count]]
    for index, item in enumerate(selected, start=1):
        item["index"] = index
    manifest = check_asset_manifest(assets or [], cache_bytes=cache_bytes)
    issues = list(manifest["issues"])
    if not topic.strip():
        issues.append(_issue("topic_missing", "先给一个具体物件或结构（如“14 世纪水磨”）。"))
    return _result(
        issues,
        kind="cutaway_3d",
        topic=topic.strip(),
        rounds=selected,
        round_count=len(selected),
        asset_policy={
            "allowed_licenses": list(ALLOWED_ASSET_LICENSES),
            "prefer_real_scans": True,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_cache_bytes": MAX_CACHE_BYTES,
            "sources": list(ASSET_SOURCES),
            "credits_required": True,
        },
        credits=manifest["credits"],
        render=dict(RENDER_POLICY),
        acceptance=[
            "每一轮只解决一个问题，并在预览里留下前后对比。",
            "切面必须能读出动力/受力/水路中的一条主线。",
            "没有任何悬空件或互穿件。",
            "720p 预览确认后才允许 1080p。",
        ],
    )


# ---------------------------------------------------------------------------
# 2. 3D 时代场景 / 世界
# ---------------------------------------------------------------------------

WORLD_CHECKS: tuple[dict[str, str], ...] = (
    {"id": "period", "label": "年代考据", "detail": "建筑、服饰、器物、文字都要能对上年代。"},
    {"id": "geography", "label": "地理", "detail": "地形、水系、道路方向与真实地理一致。"},
    {"id": "scale", "label": "尺度", "detail": "人 / 门 / 车 / 树的比例经得起对照。"},
    {"id": "life", "label": "生活痕迹", "detail": "炊烟、晾晒、货物、磨损，让场景有居住感。"},
    {"id": "camera", "label": "镜头", "detail": "一条进入世界的路径，不做无目的环绕。"},
    {"id": "sound_bed", "label": "声音底", "detail": "环境声先于配乐；远处人声不压主叙事。"},
)


def plan_world(
    *,
    topic: str,
    era: str = "",
    assets: list[dict[str, Any]] | None = None,
    cache_bytes: int = 0,
    shots: int = 5,
) -> dict[str, Any]:
    """3D 时代场景：先考据，再置景，再让人走进画面。"""
    manifest = check_asset_manifest(assets or [], cache_bytes=cache_bytes)
    issues = list(manifest["issues"])
    if not topic.strip():
        issues.append(_issue("topic_missing", "先给一个地点/年代，如“北宋汴河边的一个清晨”。"))
    count = max(3, min(8, int(shots)))
    plan = [
        {"shot": 1, "role": "establish", "camera": "高位缓降，先给地理关系",
         "content": "地形、水系、聚落边界"},
        {"shot": 2, "role": "enter", "camera": "沿一条真实路径推进",
         "content": "道路/河道/城门，交代尺度"},
        {"shot": 3, "role": "life", "camera": "低位跟随一个人/车/船",
         "content": "日常动作与声音，让世界有生活"},
        {"shot": 4, "role": "detail", "camera": "手持感特写",
         "content": "一件能证明年代的器物"},
        {"shot": 5, "role": "pullback", "camera": "缓慢拉远",
         "content": "把人物放回环境，收束主题"},
    ]
    while len(plan) < count:
        plan.append({
            "shot": len(plan) + 1,
            "role": "texture",
            "camera": "固定机位，等一个动作发生",
            "content": "补一层生活质感，不新增信息",
        })
    return _result(
        issues,
        kind="world_3d",
        topic=topic.strip(),
        era=era.strip(),
        shots=plan[:count],
        checks=[dict(item) for item in WORLD_CHECKS],
        asset_policy={
            "allowed_licenses": list(ALLOWED_ASSET_LICENSES),
            "prefer_real_scans": True,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_cache_bytes": MAX_CACHE_BYTES,
            "sources": list(ASSET_SOURCES),
            "credits_required": True,
        },
        credits=manifest["credits"],
        render=dict(RENDER_POLICY),
        acceptance=[
            "年代考据表逐项有出处；查不到的器物不用。",
            "镜头路径是一条可复述的路线，不是随机环绕。",
            "环境声先铺，配乐后进。",
            "720p 预览确认后才允许 1080p。",
        ],
    )


def check_asset_manifest(
    assets: list[dict[str, Any]], *, cache_bytes: int = 0
) -> dict[str, Any]:
    """资产许可 / 体积 / 署名检查。资产项：``name``、``license``、``author``、``url``、``bytes``。"""
    issues: list[dict[str, str]] = []
    credits: list[dict[str, str]] = []
    total = 0
    for asset in assets:
        name = str(asset.get("name") or "").strip()
        license_name = str(asset.get("license") or "").strip()
        author = str(asset.get("author") or "").strip()
        url = str(asset.get("url") or "").strip()
        size = int(asset.get("bytes") or 0)
        total += max(0, size)
        if not name:
            issues.append(_issue("asset_name_missing", "资产没有名字，CREDITS 无法生成。"))
            continue
        if license_name not in ALLOWED_ASSET_LICENSES:
            issues.append(_issue(
                "asset_license",
                f"{name} 的许可 {license_name or '(空)'} 不在 {ALLOWED_ASSET_LICENSES}，不能进片。",
            ))
        if "CC BY" in license_name and not author:
            issues.append(_issue("asset_author_missing", f"{name} 是 CC BY，必须写作者署名。"))
        if size > MAX_FILE_BYTES:
            issues.append(_issue(
                "asset_too_large",
                f"{name} 为 {size / 1048576:.0f}MB，超过单文件 300MB 上限。",
            ))
        if name:
            credits.append({
                "name": name,
                "author": author or "unknown",
                "license": license_name or "unknown",
                "url": url,
            })
    if cache_bytes + total > MAX_CACHE_BYTES:
        issues.append(_issue(
            "asset_cache_overflow",
            f"CC0/CC BY 缓存将达 {(cache_bytes + total) / 1073741824:.2f}G，超过 5G 上限。",
        ))
    return _result(issues, credits=credits, total_bytes=total)


def credits_markdown(plan: dict[str, Any]) -> str:
    """从剖面/世界计划生成可直接贴进片尾的 CREDITS。"""
    lines = ["## 3D 资产 CREDITS", ""]
    credits = plan.get("credits") or []
    if not credits:
        lines.append("本片未使用外部 3D 资产；全部几何在 Blender 内自建。")
    lines.extend(
        f"- {item['name']} — {item['author']} — {item['license']} — {item['url']}"
        for item in credits
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 2D 编辑部（地图 / 真实比例时间轴 / 档案拼贴）
# ---------------------------------------------------------------------------

EDITORIAL_COMPONENTS = (
    "S23MapRoute",          # SVG 路径逐段绘制 + 地名标签
    "S23TrueScaleTimeline", # 年份按真实比例定位
    "S23ArchiveCollage",    # 纸张/半色调/撕纸/油墨错位
)


def _project(points: list[dict[str, Any]]) -> list[dict[str, float]]:
    """等距圆柱近似：把 lon/lat 归一到 0..1 画布；已有 x/y 则原样使用。"""
    if all("x" in point and "y" in point for point in points):
        return [{"x": float(point["x"]), "y": float(point["y"])} for point in points]
    lons = [float(point["lon"]) for point in points]
    lats = [float(point["lat"]) for point in points]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    span_lon = max(max_lon - min_lon, 1e-9)
    span_lat = max(max_lat - min_lat, 1e-9)
    return [
        {
            "x": round((float(point["lon"]) - min_lon) / span_lon, 5),
            "y": round(1.0 - (float(point["lat"]) - min_lat) / span_lat, 5),
        }
        for point in points
    ]


def plan_editorial_2d(
    *,
    topic: str,
    route: list[dict[str, Any]] | None = None,
    timeline: list[dict[str, Any]] | None = None,
    collage: bool = True,
) -> dict[str, Any]:
    """2D 编辑部计划：地图路线 + 真实比例时间轴 + 档案拼贴，Remotion/SVG 实现。"""
    issues: list[dict[str, str]] = []
    route = route or []
    timeline = timeline or []
    if not topic.strip():
        issues.append(_issue("topic_missing", "先给主题，再决定地图与时间轴讲哪条线。"))

    route_plan: dict[str, Any] = {}
    if route:
        if len(route) < 2:
            issues.append(_issue("route_points", "地图路线至少两个点。"))
        positions = _project(route)
        legs = []
        distance = 0.0
        for index in range(1, len(positions)):
            dx = positions[index]["x"] - positions[index - 1]["x"]
            dy = positions[index]["y"] - positions[index - 1]["y"]
            step = math.hypot(dx, dy)
            distance += step
            legs.append({
                "from": str(route[index - 1].get("name") or index),
                "to": str(route[index].get("name") or index + 1),
                "length": round(step, 5),
            })
        route_plan = {
            "points": [
                {**position, "name": str(source.get("name") or index + 1)}
                for index, (position, source) in enumerate(zip(positions, route, strict=True))
            ],
            "legs": legs,
            "total_length": round(distance, 5),
            "draw_on": {"engine": "svg", "stroke_dash": True, "duration_s": round(2.0 + distance, 2)},
            "labels": "每个点只放一个地名，避开路线与时间轴。",
        }

    timeline_plan: dict[str, Any] = {}
    if timeline:
        years = [float(item.get("year")) for item in timeline]
        if years != sorted(years):
            issues.append(_issue("timeline_order", "时间轴事件必须按年份从早到晚。"))
        low, high = min(years), max(years)
        span = max(high - low, 1e-9)
        timeline_plan = {
            "events": [
                {
                    "label": str(item.get("label") or ""),
                    "year": int(float(item.get("year"))),
                    "position": round((float(item.get("year")) - low) / span, 5),
                }
                for item in timeline
            ],
            "scale": "true_scale",
            "note": "位置=年份差/总跨度；不允许等距排布。",
        }

    collage_plan = {
        "enabled": bool(collage),
        "layers": [
            {"name": "paper", "texture": "fibrous paper", "opacity": 0.92, "blend": "normal"},
            {"name": "halftone", "texture": "halftone dots", "opacity": 0.35, "blend": "multiply"},
            {"name": "torn_edge", "texture": "torn paper edge", "opacity": 1.0, "blend": "normal"},
            {"name": "ink_offset", "texture": "misregistered ink", "opacity": 0.22, "blend": "multiply"},
        ],
        "palette": ["#f3ead6", "#1c1b18", "#b23a2e", "#2f5d62"],
        "duotone": True,
    }
    if collage and len(collage_plan["layers"]) < 3:
        issues.append(_issue("collage_layers", "档案拼贴至少三层：纸、半色调、撕纸。"))

    return _result(
        issues,
        kind="editorial_2d",
        topic=topic.strip(),
        route=route_plan,
        timeline=timeline_plan,
        collage=collage_plan,
        implementation={
            "engine": "remotion",
            "svg": True,
            "components": list(EDITORIAL_COMPONENTS),
            "fps": 30,
            "free_tools": ["remotion", "svg", "ffmpeg", "pillow"],
            "no_paid_assets": True,
        },
        rules=[
            "地图只画一条主路线；支线用更细/更淡的线。",
            "时间轴按真实年份比例，不按事件数量等距。",
            "纸张/半色调/撕纸只做质感，不遮挡信息。",
            "标题、地名、年份都在后期叠加，不烘进素材。",
        ],
    )


def check_timeline_scale(
    events: list[dict[str, Any]], *, tolerance: float = 0.005
) -> dict[str, Any]:
    """独立检查时间轴是否真实比例（不依赖 plan 的返回值）。"""
    issues: list[dict[str, str]] = []
    if len(events) < 2:
        issues.append(_issue("timeline_events", "至少两个事件才能检查比例。"))
        return _result(issues)
    years = [float(item.get("year")) for item in events]
    low, high = min(years), max(years)
    span = max(high - low, 1e-9)
    for item in events:
        expected = (float(item.get("year")) - low) / span
        actual = float(item.get("position", expected))
        if abs(expected - actual) > tolerance:
            issues.append(_issue(
                "timeline_not_true_scale",
                f"{item.get('label') or item.get('year')} 应在 {expected:.3f}，实际 {actual:.3f}。",
            ))
    return _result(issues, span_years=high - low)


# ---------------------------------------------------------------------------
# 4. 角色动作与穿模 / 滑步 / 悬空
# ---------------------------------------------------------------------------

MOTION_RULES: dict[str, Any] = {
    "head_leads_body_frames": [4, 6],
    "joint_stop_stagger_frames": 2,
    "anticipation_frames": [2, 8],
    "reaction_frames": [0, 8],
}


def check_character_motion(
    beats: list[dict[str, Any]], *, fps: int = 24
) -> dict[str, Any]:
    """动作规则自检。

    ``beats`` 每项：``part``、``kind``（move/anticipation/reaction）、
    ``start_frame``、``end_frame``、可选 ``group``。头部要先于身体 4–6 帧；
    同组关节的停止帧至少错开 2 帧；大动作前有预备、后有反应。
    """
    issues: list[dict[str, str]] = []
    if not beats:
        issues.append(_issue("motion_empty", "没有动作节拍，无法自检。"))
        return _result(issues)
    for index, beat in enumerate(beats):
        if int(beat.get("end_frame", 0)) < int(beat.get("start_frame", 0)):
            issues.append(_issue("motion_order", f"第 {index + 1} 拍结束早于开始。"))
    moves = [beat for beat in beats if str(beat.get("kind") or "move") == "move"]
    heads = [beat for beat in moves if "head" in str(beat.get("part") or "")]
    bodies = [beat for beat in moves if "head" not in str(beat.get("part") or "")]

    lead_low, lead_high = MOTION_RULES["head_leads_body_frames"]
    for head in heads:
        for body in bodies:
            overlap = (
                int(head["start_frame"]) < int(body.get("end_frame", 0))
                and int(head.get("end_frame", 0)) > int(body["start_frame"])
            )
            if not overlap:
                continue
            lead = int(body["start_frame"]) - int(head["start_frame"])
            if not lead_low <= lead <= lead_high:
                issues.append(_issue(
                    "head_lead",
                    f"头部应先于身体 {lead_low}–{lead_high} 帧；当前 {lead} 帧。",
                ))

    for group in {str(beat.get("group") or "default") for beat in moves}:
        ends = sorted(int(beat["end_frame"]) for beat in moves if str(beat.get("group") or "default") == group)
        for previous, current in pairwise(ends):
            if current - previous < MOTION_RULES["joint_stop_stagger_frames"]:
                issues.append(_issue(
                    "joint_stop_stagger",
                    f"同组关节停止帧 {previous}/{current} 太齐，至少错开 "
                    f"{MOTION_RULES['joint_stop_stagger_frames']} 帧。",
                ))
                break

    for move in moves:
        start = int(move["start_frame"])
        end = int(move.get("end_frame", start))
        has_anticipation = any(
            str(beat.get("kind")) == "anticipation"
            and int(beat["start_frame"]) <= start
            and int(beat.get("end_frame", start)) >= start - MOTION_RULES["anticipation_frames"][1]
            for beat in beats
        )
        if not has_anticipation:
            issues.append(_issue(
                "anticipation_missing",
                f"{move.get('part')} 从第 {start} 帧开始的大动作没有预备拍。",
                severity="warning",
            ))
        has_reaction = any(
            str(beat.get("kind")) == "reaction"
            and int(beat["start_frame"]) >= end
            and int(beat["start_frame"]) <= end + MOTION_RULES["reaction_frames"][1]
            for beat in beats
        )
        if not has_reaction:
            issues.append(_issue(
                "reaction_missing",
                f"{move.get('part')} 第 {end} 帧落定后没有反应拍。",
                severity="warning",
            ))

    return _result(issues, fps=fps, rules=dict(MOTION_RULES), beat_count=len(beats))


def check_contact_and_slip(
    contacts: list[dict[str, Any]],
    *,
    fps: int = 24,
    ground_y: float = 0.0,
    float_tolerance: float = 0.015,
    slip_per_frame: float = 0.012,
    cross_tolerance: float = 0.02,
) -> dict[str, Any]:
    """节点自检：脚/手的悬空、贴地滑步、肢体互穿。

    ``contacts`` 每项：``frame``、``part``、``x``、``y``、``planted``、可选 ``solid``。
    坐标使用 0..1 的归一化坐标；``ground_y`` 是贴地时脚应有的 y（默认 0），
    脚标记贴地却离 ``ground_y`` 超过容差即视为悬空。
    """
    issues: list[dict[str, str]] = []
    if not contacts:
        issues.append(_issue("contact_empty", "没有接触关键帧，无法检查。"))
        return _result(issues)
    by_part: dict[str, list[dict[str, Any]]] = {}
    for item in contacts:
        by_part.setdefault(str(item.get("part") or ""), []).append(item)
    for part, rows in by_part.items():
        rows.sort(key=lambda row: int(row.get("frame", 0)))
        previous: dict[str, Any] | None = None
        for row in rows:
            frame = int(row.get("frame", 0))
            planted = bool(row.get("planted", False))
            y = float(row.get("y", 0.0))
            x = float(row.get("x", 0.0))
            if planted and "foot" in part and abs(y - ground_y) > float_tolerance:
                issues.append(_issue(
                    "foot_floating",
                    f"{part} 第 {frame} 帧标记贴地，但 y={y:.3f} 离地 {abs(y - ground_y):.3f}。",
                ))
            if planted and previous and bool(previous.get("planted")):
                gap = max(1, frame - int(previous.get("frame", frame)))
                drift = abs(x - float(previous.get("x", x))) / gap
                if drift > slip_per_frame:
                    issues.append(_issue(
                        "foot_slip",
                        f"{part} 第 {previous.get('frame')}–{frame} 帧贴地横移 {drift:.4f}/帧，滑步。",
                    ))
            previous = row

    frames: dict[int, list[dict[str, Any]]] = {}
    for item in contacts:
        if bool(item.get("solid", False)):
            frames.setdefault(int(item.get("frame", 0)), []).append(item)
    for frame, rows in frames.items():
        for index, first in enumerate(rows):
            for second in rows[index + 1:]:
                if str(first.get("part")) == str(second.get("part")):
                    continue
                distance = math.hypot(
                    float(first.get("x", 0)) - float(second.get("x", 0)),
                    float(first.get("y", 0)) - float(second.get("y", 0)),
                )
                if distance < cross_tolerance:
                    issues.append(_issue(
                        "limb_crossing",
                        f"第 {frame} 帧 {first.get('part')} 与 {second.get('part')} 距离 "
                        f"{distance:.3f}，疑似互穿。",
                    ))

    return _result(issues, fps=fps, parts=sorted(by_part), contact_count=len(contacts))


# ---------------------------------------------------------------------------
# 5. 手机外放可听性 / 遮蔽 / 同步
# ---------------------------------------------------------------------------

PHONE_SPEAKER = {
    "usable_band_hz": [300, 3400],
    "max_low_boost_db": 6.0,
    "min_mid_relative_db": -6.0,
    "min_loudness_lufs": -16.0,
}


def check_phone_speaker(
    bands: dict[str, float], *, loudness_lufs: float = -14.0
) -> dict[str, Any]:
    """手机外放检查。``bands``：``low``(<200), ``mid``(300–3400), ``high``(>6000) 的 dB。"""
    issues: list[dict[str, str]] = []
    low = float(bands.get("low", -60))
    mid = float(bands.get("mid", -60))
    high = float(bands.get("high", -60))
    peak = max(low, mid, high)
    if low - peak > -PHONE_SPEAKER["max_low_boost_db"]:
        issues.append(_issue(
            "phone_low_dominant",
            f"低频 {low:.1f}dB 相对峰值过高，手机外放会只剩嗡嗡声。",
        ))
    if mid - peak < PHONE_SPEAKER["min_mid_relative_db"]:
        issues.append(_issue(
            "phone_mid_buried",
            f"中频 {mid:.1f}dB 比峰值低 {peak - mid:.1f}dB，人声会听不清。",
        ))
    if loudness_lufs < PHONE_SPEAKER["min_loudness_lufs"]:
        issues.append(_issue(
            "phone_too_quiet",
            f"整体 {loudness_lufs:.1f} LUFS，低于手机外放下限 "
            f"{PHONE_SPEAKER['min_loudness_lufs']} LUFS。",
        ))
    return _result(issues, loudness_lufs=loudness_lufs, bands={"low": low, "mid": mid, "high": high})


def check_masking(
    stems: list[dict[str, Any]], *, min_dialogue_margin_db: float = 6.0
) -> dict[str, Any]:
    """遮蔽检查：对白要比音乐高 ≥6dB，比音效高 ≥3dB。"""
    issues: list[dict[str, str]] = []
    dialogue = next((row for row in stems if str(row.get("name")) == "dialogue"), None)
    if dialogue is None:
        issues.append(_issue("dialogue_missing", "没有对白轨，无法判断遮蔽。"))
        return _result(issues)
    dialogue_db = float(dialogue.get("db", -60))
    for stem in stems:
        name = str(stem.get("name"))
        if name == "dialogue":
            continue
        level = float(stem.get("db", -60))
        margin = dialogue_db - level
        required = min_dialogue_margin_db if name == "music" else 3.0
        if margin < required:
            issues.append(_issue(
                "stem_masking",
                f"{name} 只比对白低 {margin:.1f}dB，需要 ≥{required:.0f}dB。",
            ))
    return _result(issues, dialogue_db=dialogue_db)


def check_sync(
    cues: list[dict[str, Any]], *, tolerance_ms: float = 40.0
) -> dict[str, Any]:
    """音画同步：每项 ``name``、``audio_ms``、``video_ms``，偏差 ≤40ms。"""
    issues: list[dict[str, str]] = []
    for cue in cues:
        offset = float(cue.get("audio_ms", 0)) - float(cue.get("video_ms", 0))
        if abs(offset) > tolerance_ms:
            issues.append(_issue(
                "sync_offset",
                f"{cue.get('name') or 'cue'} 偏移 {offset:.0f}ms，超过 ±{tolerance_ms:.0f}ms。",
            ))
    return _result(issues, tolerance_ms=tolerance_ms, cues=len(cues))


# ---------------------------------------------------------------------------
# 6. 看片配方 + Shorts 剪辑规范
# ---------------------------------------------------------------------------

def plan_remake_recipe(
    *,
    topic: str,
    duration_s: float,
    cuts: list[dict[str, Any]],
    frames: list[dict[str, Any]] | None = None,
    transcript: list[dict[str, Any]] | None = None,
    spectrogram_peaks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把参考片拆成可复用的"翻拍配方"，交给 reference_adapt。

    ``cuts`` 每项 ``in_s``/``out_s``；``frames`` 每项 ``t``/``path``/可选 ``ocr``；
    ``transcript`` 每项 ``start``/``end``/``text``；``spectrogram_peaks`` 每项 ``t``/``hz``/``db``。
    """
    issues: list[dict[str, str]] = []
    frames = frames or []
    transcript = transcript or []
    peaks = spectrogram_peaks or []
    ordered = sorted(cuts, key=lambda item: float(item.get("in_s", 0)))
    shots = []
    covered = 0.0
    for index, cut in enumerate(ordered):
        start = float(cut.get("in_s", 0))
        end = float(cut.get("out_s", start))
        if end <= start:
            issues.append(_issue("cut_order", f"第 {index + 1} 个切点结束不晚于开始。"))
        if index and start < float(ordered[index - 1].get("out_s", 0)) - 1e-6:
            issues.append(_issue("cut_overlap", f"第 {index + 1} 个切点与上一个重叠。"))
        covered += max(0.0, end - start)
        line = next(
            (row for row in transcript if float(row.get("start", 0)) < end and float(row.get("end", 0)) > start),
            None,
        )
        shot_frames = [row for row in frames if start <= float(row.get("t", 0)) <= end]
        sound = [row for row in peaks if start <= float(row.get("t", 0)) <= end]
        shots.append({
            "index": index + 1,
            "in_s": round(start, 3),
            "out_s": round(end, 3),
            "duration_s": round(end - start, 3),
            "frame_sheet": [str(row.get("path") or "") for row in shot_frames],
            "on_screen_text": " / ".join(str(row.get("ocr")) for row in shot_frames if row.get("ocr")),
            "speech": str(line.get("text")) if line else "",
            "sound_events": [
                {"t": float(row.get("t", 0)), "hz": float(row.get("hz", 0)), "db": float(row.get("db", 0))}
                for row in sound
            ],
        })
    if duration_s > 0 and covered / duration_s < 0.9:
        issues.append(_issue(
            "coverage_low",
            f"切点只覆盖 {covered / duration_s:.0%}，配方会漏掉参考片的节奏。",
            severity="warning",
        ))
    durations = [shot["duration_s"] for shot in shots if shot["duration_s"] > 0]
    average = sum(durations) / len(durations) if durations else 0.0
    variance = (
        sum((value - average) ** 2 for value in durations) / len(durations) if durations else 0.0
    )
    cut_rhythm = {
        "shot_count": len(shots),
        "average_shot_s": round(average, 3),
        "cut_interval_cv": round((variance ** 0.5) / average, 3) if average else 0.0,
    }
    return _result(
        issues,
        kind="remake_recipe",
        topic=topic.strip(),
        duration_s=float(duration_s),
        shots=shots,
        cut_rhythm=cut_rhythm,
        recipe={
            "hook": _first_text(transcript) or "把参考片前 3 秒的信息压成一句结论。",
            "structure": "按切点还原：钩子 → 展开 → 转折 → 收束。",
            "visual_grammar": "记录景别、机位、字幕位置、转场方式，不复制具体画面。",
            "sound_grammar": "记录配乐进入点、音效落点与静音，不复制原曲。",
            "differentiation_required": [
                "换一个具体例子或数据，不能只换标题。",
                "至少一个关键结论要与参考片不同。",
                "画面、配乐、字体全部重做。",
            ],
            "do_not_copy": ["台词原句", "原片音乐", "原片人脸/素材", "原片字幕版式"],
        },
        reference_adapt_slots={
            "topic": topic.strip(),
            "transcript": "\n".join(shot["speech"] for shot in shots if shot["speech"]),
            "duration_s": float(duration_s),
        },
    )


def _first_text(transcript: list[dict[str, Any]]) -> str:
    rows = sorted(transcript, key=lambda row: float(row.get("start", 0)))
    return str(rows[0].get("text") or "").strip()[:80] if rows else ""


SHORTS_SPEC: dict[str, Any] = {
    "aspect": "9:16",
    "resolution": [1080, 1920],
    "fps": 30,
    "hook_by_s": 2.0,
    "avg_shot_s": [1.0, 3.5],
    "max_shot_s": 4.0,
    "beat_sync_tolerance_s": 0.12,
    "min_beat_sync_ratio": 0.6,
    "caption_safe": {"x": [0.05, 0.95], "y": [0.08, 0.86]},
    "loudness_lufs": [-16.0, -12.0],
    "platforms": {
        "tiktok": {"max_s": 180, "safe_bottom": 0.18},
        "reels": {"max_s": 90, "safe_bottom": 0.16},
        "shorts": {"max_s": 60, "safe_bottom": 0.14},
    },
}


def audit_shorts_edit(spec: dict[str, Any]) -> dict[str, Any]:
    """按 Shorts 规范检查现有剪辑计划，返回缺口。

    ``spec``：``hook`` {start_s,end_s}、``shots`` [{duration_s,cut_s}]、
    ``beats_s``、``captions`` [{x,y,w,h}]、``loudness_lufs``、``exports`` [..]。
    """
    issues: list[dict[str, str]] = []
    shots = spec.get("shots") or []
    durations = [float(shot.get("duration_s", 0)) for shot in shots if float(shot.get("duration_s", 0)) > 0]
    hook = spec.get("hook") or {}
    if not hook:
        issues.append(_issue("shorts_hook_missing", "前 2 秒没有钩子（结论/冲突/悬念）。"))
    else:
        if float(hook.get("start_s", 99)) > 0.5:
            issues.append(_issue("shorts_hook_late", "钩子必须在前 0.5 秒内出现。"))
        if float(hook.get("end_s", 0)) > SHORTS_SPEC["hook_by_s"]:
            issues.append(_issue("shorts_hook_long", "钩子要在 2 秒内讲完。"))
    if durations:
        average = sum(durations) / len(durations)
        low, high = SHORTS_SPEC["avg_shot_s"]
        if not low <= average <= high:
            issues.append(_issue(
                "shorts_shot_length",
                f"平均镜头 {average:.2f}s，规范 {low}–{high}s。",
            ))
        longest = max(durations)
        if longest > SHORTS_SPEC["max_shot_s"]:
            issues.append(_issue(
                "shorts_shot_too_long",
                f"最长镜头 {longest:.2f}s，超过 {SHORTS_SPEC['max_shot_s']}s。",
            ))
    else:
        issues.append(_issue("shorts_shots_missing", "没有镜头时长，无法检查节奏。"))

    beats = [float(value) for value in (spec.get("beats_s") or [])]
    cut_times = [float(shot.get("cut_s", 0)) for shot in shots if shot.get("cut_s") is not None]
    if beats and cut_times:
        tolerance = SHORTS_SPEC["beat_sync_tolerance_s"]
        on_beat = sum(
            1 for cut in cut_times if any(abs(cut - beat) <= tolerance for beat in beats)
        )
        ratio = on_beat / len(cut_times)
        if ratio < SHORTS_SPEC["min_beat_sync_ratio"]:
            issues.append(_issue(
                "shorts_beat_sync",
                f"卡点率 {ratio:.0%}，低于 {SHORTS_SPEC['min_beat_sync_ratio']:.0%}。",
            ))
    elif cut_times:
        issues.append(_issue(
            "shorts_beats_missing", "有切点但没给拍点，无法检查卡点。", severity="warning"
        ))

    safe = SHORTS_SPEC["caption_safe"]
    for index, caption in enumerate(spec.get("captions") or [], start=1):
        x = float(caption.get("x", 0))
        y = float(caption.get("y", 0))
        w = float(caption.get("w", 0))
        h = float(caption.get("h", 0))
        if x < safe["x"][0] or x + w > safe["x"][1] or y < safe["y"][0] or y + h > safe["y"][1]:
            issues.append(_issue(
                "shorts_caption_safe",
                f"第 {index} 条字幕超出安全区（x {safe['x']}, y {safe['y']}）。",
            ))
    if spec.get("captions") and float(min((c.get("y", 0) for c in spec["captions"]), default=0)) < 0.08:
        issues.append(_issue("shorts_caption_top", "字幕太靠上，会被平台标题/头像遮住。"))

    loudness = float(spec.get("loudness_lufs", 0))
    low, high = SHORTS_SPEC["loudness_lufs"]
    if not low <= loudness <= high:
        issues.append(_issue(
            "shorts_loudness",
            f"{loudness:.1f} LUFS 不在 {low}–{high} LUFS。",
        ))

    exports = spec.get("exports") or []
    for platform, rule in SHORTS_SPEC["platforms"].items():
        if platform not in exports:
            issues.append(_issue(
                "shorts_export_missing", f"缺少 {platform} 导出（≤{rule['max_s']}s）。",
                severity="warning",
            ))
    if spec.get("duration_s") and float(spec["duration_s"]) > 60:
        issues.append(_issue("shorts_duration", "Shorts 主平台上限 60 秒。"))

    errors = [item for item in issues if item["severity"] == "error"]
    score = max(0.0, round(1.0 - 0.15 * len(errors), 2))
    return _result(issues, **{"score": score, "pass": not errors, "spec": dict(SHORTS_SPEC)})


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------

KINDS = {
    "cutaway_3d": plan_cutaway,
    "world_3d": plan_world,
    "editorial_2d": plan_editorial_2d,
    "remake_recipe": plan_remake_recipe,
    "motion_check": check_character_motion,
    "contact_check": check_contact_and_slip,
    "phone_speaker": check_phone_speaker,
    "masking": check_masking,
    "sync": check_sync,
    "shorts_audit": audit_shorts_edit,
}


def catalog() -> dict[str, Any]:
    return {
        "version": "s23",
        "source": "creator-generalist (MIT) — method restatement only",
        "kinds": sorted(KINDS),
        "constraints": {
            "paid_services": False,
            "new_dependencies": False,
            "default_network": False,
            "asset_licenses": list(ALLOWED_ASSET_LICENSES),
            "max_file_bytes": MAX_FILE_BYTES,
            "max_cache_bytes": MAX_CACHE_BYTES,
            "render": dict(RENDER_POLICY),
        },
    }


def plan_for(
    format_id: str, style_id: str, *, topic: str, slots: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """给 /formats/plan 用的轻量挂载：只有相关形式才返回 S23 计划。"""
    slots = slots or {}
    if style_id == "cutaway_3d":
        return plan_cutaway(
            topic=topic,
            assets=slots.get("assets") or [],
            cache_bytes=int(slots.get("asset_cache_bytes") or 0),
        )
    if style_id == "world_3d":
        return plan_world(
            topic=topic,
            era=str(slots.get("era") or ""),
            assets=slots.get("assets") or [],
            cache_bytes=int(slots.get("asset_cache_bytes") or 0),
        )
    if style_id == "editorial_2d":
        return plan_editorial_2d(
            topic=topic,
            route=slots.get("route") or [],
            timeline=slots.get("timeline") or [],
        )
    if style_id in {"character", "motion"}:
        return {
            "kind": "motion_rules",
            "rules": dict(MOTION_RULES),
            "checks": ["check_character_motion", "check_contact_and_slip"],
        }
    if style_id == "reference":
        watch = slots.get("watch") or {}
        if watch.get("cuts"):
            return plan_remake_recipe(
                topic=topic,
                duration_s=float(watch.get("duration_s") or 0),
                cuts=watch["cuts"],
                frames=watch.get("frames"),
                transcript=watch.get("transcript"),
                spectrogram_peaks=watch.get("spectrogram_peaks"),
            )
        return {
            "kind": "remake_recipe",
            "status": "needs_watch",
            "topic": topic,
            "required": ["cuts", "frames", "transcript", "spectrogram_peaks"],
            "note": "先用 watch-video 方法取帧表/切点/声谱/转写，再生成翻拍配方。",
        }
    if style_id == "shorts":
        shorts_spec = slots.get("shorts_spec") or {}
        if shorts_spec:
            return audit_shorts_edit(shorts_spec)
        return {
            "kind": "shorts_spec",
            "spec": dict(SHORTS_SPEC),
            "note": "把现有镜头/拍点/字幕/导出参数传进来即可审计。",
        }
    return None


__all__ = [
    "ALLOWED_ASSET_LICENSES",
    "CUTAWAY_ROUNDS",
    "EDITORIAL_COMPONENTS",
    "MOTION_RULES",
    "PHONE_SPEAKER",
    "RENDER_POLICY",
    "SHORTS_SPEC",
    "WORLD_CHECKS",
    "audit_shorts_edit",
    "catalog",
    "check_asset_manifest",
    "check_character_motion",
    "check_contact_and_slip",
    "check_masking",
    "check_phone_speaker",
    "check_sync",
    "check_timeline_scale",
    "credits_markdown",
    "plan_cutaway",
    "plan_editorial_2d",
    "plan_for",
    "plan_remake_recipe",
    "plan_world",
]
