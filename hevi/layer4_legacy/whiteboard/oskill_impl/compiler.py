"""Whiteboard narrative compilation and scene layout generator (oskill layer)."""

from __future__ import annotations

import re
from typing import Any

from hevi.layer4_legacy.whiteboard.oprim_impl.contracts import (
    WhiteboardBeat,
    WhiteboardSegment,
)

_PUNCT = re.compile(r"[，。？！；：、!?]+")
_PREFIX_STRIP = re.compile(
    r"^(今天我们要给大家介绍|其实非常简单，只需要|你是否好奇，|我们来看看|首先是|接着通过|最终形成|从.*?到|总的来说，|那么如何.*?呢[？?]?)"
)


def extract_beat_content(
    narration: str,
    *,
    keywords: list[str] | tuple[str, ...] = (),
    beat_index: int = 0,
    scene_type: str = "body",
) -> tuple[str, list[str]]:
    """Extract a concise title and 1-2 bullet points from narration text."""
    clean = narration.strip().replace("\n", " ")
    if not clean:
        return f"要点 {beat_index + 1}", ["内容详述"]

    # Use explicit keyword if available for this beat
    title = ""
    if keywords and beat_index < len(keywords) and keywords[beat_index].strip():
        title = keywords[beat_index].strip()

    # Split narration into meaningful sub-clauses
    clauses = [c.strip() for c in _PUNCT.split(clean) if c.strip()]
    if not clauses:
        clauses = [clean]

    if not title:
        first_clause = _PREFIX_STRIP.sub("", clauses[0]).strip()
        if not first_clause and len(clauses) > 1:
            first_clause = clauses[1]
        if first_clause:
            # Pick a short punchy phrase of 4-10 chars
            title = first_clause[:10].rstrip("的和与在")
        else:
            title = "核心概念" if scene_type == "intro" else "关键要点"

    # Derive bullet points from clauses
    points: list[str] = []
    for c in clauses:
        c_clean = c.strip()
        if not c_clean:
            continue
        if len(c_clean) > 22:
            # Break longer sentences into manageable chunks
            points.append(c_clean[:20] + "…")
        else:
            points.append(c_clean)
        if len(points) >= 2:
            break

    if not points:
        points = [clean[:24]]

    return title, points


def parse_storyboard(
    storyboard_data: dict[str, Any],
) -> list[WhiteboardSegment]:
    """Parse raw storyboard dict into typed WhiteboardSegment objects."""
    raw_segments = storyboard_data.get("segments", [])
    parsed: list[WhiteboardSegment] = []

    for i, seg in enumerate(raw_segments):
        scene_type = str(seg.get("sceneType") or seg.get("scene_type") or ("intro" if i == 0 else "body"))
        narration = str(seg.get("narration") or "").strip()
        keywords = tuple(str(k) for k in seg.get("keywords") or ())
        
        # Narration is split into beats by '|'
        beat_texts = [b.strip() for b in narration.split("|") if b.strip()]
        if not beat_texts:
            continue

        beats: list[WhiteboardBeat] = []
        for b_idx, b_text in enumerate(beat_texts):
            title, points = extract_beat_content(
                b_text,
                keywords=keywords,
                beat_index=b_idx,
                scene_type=scene_type,
            )
            motifs = ["card", "laptop", "robot", "cloud", "badge"]
            motif = motifs[b_idx % len(motifs)]
            beats.append(
                WhiteboardBeat(
                    index=b_idx,
                    narration=b_text,
                    title=title,
                    points=tuple(points),
                    motif=motif,
                )
            )

        parsed.append(
            WhiteboardSegment(
                scene_id=f"{i:02d}-{scene_type}",
                scene_type=scene_type,
                narration=narration,
                beats=tuple(beats),
                keywords=keywords,
                props=dict(seg.get("props") or {}),
            )
        )

    return parsed


def generate_landscape_scene_js(
    segment: WhiteboardSegment,
    *,
    topic: str,
) -> list[str]:
    """Generate DSL lines for a landscape (1920x1080) scene."""
    lines: list[str] = []
    # Join beats with '|' for scene audio segmentation
    narration_dsl = " | ".join(b.narration for b in segment.beats)
    lines.append(f"{{ const s = new Scene('{segment.scene_id}', `{narration_dsl}`);")

    num_beats = len(segment.beats)
    colors = ["C.brand", "C.blue", "C.purple", "C.orange", "C.green"]
    fill_colors = ["C.fGreen", "C.fBlue", "C.fPurple", "C.fYellow", "C.fGray"]

    if num_beats == 1:
        b0 = segment.beats[0]
        pts_str = "\\n· ".join(b0.points)
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX, 100, `{topic}`, {{ size: 68, align: 'center', color: C.brand }});")
        lines.append("s.squiggle(CX - 280, CX + 280, 180, { color: C.brand });")
        lines.append("s.rect(360, 260, 1200, 600, { round: true, stroke: C.brand, strokeWidth: 3, fill: C.fGreen });")
        lines.append("s.robot(460, 420, 1.2);")
        lines.append(f"s.text(780, 360, `{b0.title}`, {{ size: 64, color: C.brand }});")
        lines.append(f"s.text(780, 480, `· {pts_str}`, {{ size: 40, color: C.ink }});")

    elif num_beats == 2:
        b0, b1 = segment.beats[0], segment.beats[1]
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX, 80, `{topic}`, {{ size: 60, align: 'center', color: C.brand }});")
        lines.append("s.rect(200, 200, 720, 680, { round: true, stroke: C.blue, strokeWidth: 3, fill: C.fBlue });")
        lines.append(f"s.text(560, 250, `{b0.title}`, {{ size: 54, align: 'center', color: C.blue }});")
        lines.append("s.laptop(460, 400, 1.0);")
        pts0_str = "\\n· ".join(b0.points)
        lines.append(f"s.text(260, 640, `· {pts0_str}`, {{ size: 38, color: C.ink }});")

        lines.append("s.nextBeat();")
        lines.append("s.rect(1000, 200, 720, 680, { round: true, stroke: C.purple, strokeWidth: 3, fill: C.fPurple });")
        lines.append(f"s.text(1360, 250, `{b1.title}`, {{ size: 54, align: 'center', color: C.purple }});")
        lines.append("s.robot(1260, 400, 1.0);")
        pts1_str = "\\n· ".join(b1.points)
        lines.append(f"s.text(1060, 640, `· {pts1_str}`, {{ size: 38, color: C.ink }});")

    elif num_beats == 3:
        b0, b1, b2 = segment.beats[0], segment.beats[1], segment.beats[2]
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX, 70, `{topic}`, {{ size: 60, align: 'center', color: C.brand }});")
        lines.append(f"s.robot(340, 210, 0.85);")
        lines.append(f"s.text(480, 180, `{b0.title}`, {{ size: 48, color: C.brand }});")
        pts0_str = " · ".join(b0.points)
        lines.append(f"s.text(480, 250, `{pts0_str}`, {{ size: 34, color: C.gray }});")
        lines.append("s.line([[200, 340], [1720, 340]], { strokeStyle: 'dashed', stroke: C.gray });")

        lines.append("s.nextBeat();")
        lines.append("s.rect(220, 380, 700, 520, { round: true, stroke: C.blue, strokeWidth: 3, fill: C.fBlue });")
        lines.append(f"s.text(570, 430, `{b1.title}`, {{ size: 48, align: 'center', color: C.blue }});")
        lines.append("s.laptop(470, 540, 0.9);")
        pts1_str = "\\n· ".join(b1.points)
        lines.append(f"s.text(280, 730, `· {pts1_str}`, {{ size: 36, color: C.ink }});")

        lines.append("s.nextBeat();")
        lines.append("s.rect(1000, 380, 700, 520, { round: true, stroke: C.orange, strokeWidth: 3, fill: C.fYellow, fillStyle: 'solid' });")
        lines.append(f"s.text(1350, 430, `{b2.title}`, {{ size: 48, align: 'center', color: C.orange }});")
        lines.append("s.ellipse(1350, 580, 420, 90, { fill: C.fGreen, fillStyle: 'solid' });")
        badge = b2.points[0] if b2.points else "核心总结"
        lines.append(f"s.text(1350, 565, `{badge}`, {{ size: 34, align: 'center', color: C.ink }});")
        pts2_str = "\\n· ".join(b2.points[1:]) if len(b2.points) > 1 else "深入拆解，一目了然"
        lines.append(f"s.text(1060, 730, `· {pts2_str}`, {{ size: 36, color: C.ink }});")

    else:
        # 4 or more beats
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX, 60, `{topic}`, {{ size: 56, align: 'center', color: C.brand }});")
        col_w, col_h = 720, 360
        positions = [
            (200, 160),
            (1000, 160),
            (200, 560),
            (1000, 560),
        ]
        for idx, beat in enumerate(segment.beats[:4]):
            if idx > 0:
                lines.append("s.nextBeat();")
            px, py = positions[idx]
            col = colors[idx % len(colors)]
            fill = fill_colors[idx % len(fill_colors)]
            lines.append(f"s.rect({px}, {py}, {col_w}, {col_h}, {{ round: true, stroke: {col}, strokeWidth: 2, fill: {fill} }});")
            lines.append(f"s.text({px + col_w // 2}, {py + 30}, `{beat.title}`, {{ size: 44, align: 'center', color: {col} }});")
            pts_str = "\\n· ".join(beat.points)
            lines.append(f"s.text({px + 40}, {py + 110}, `· {pts_str}`, {{ size: 34, color: C.ink }});")

    lines.append("scenes.push(s); }")
    return lines


def generate_portrait_scene_js(
    segment: WhiteboardSegment,
    *,
    topic: str,
) -> list[str]:
    """Generate DSL lines for a portrait (1080x1920) scene.

    F2 返工布局规则（实测可复现）：
    * 标题区 y 120–240；卡片区 y 260–1560（1300px，占可用高度 70.7%）；
      字幕 baselineY=1780，卡片底边 ≤1600，不压字幕。
    * 每 beat 一张卡片，高度均分卡片区，beat 间留 40px 箭头。
    * 图标（robot/laptop）固定左栏（x 140–360），文字固定右栏
      （x 400–940），两栏不相交。
    * 要点按 12 字折行，长句不出卡片右边框。
    """
    lines: list[str] = []
    narration_dsl = " | ".join(b.narration for b in segment.beats)
    lines.append(f"{{ const s = new Scene('{segment.scene_id}', `{narration_dsl}`);")

    num_beats = len(segment.beats)
    colors = ["C.brand", "C.blue", "C.purple", "C.orange", "C.green"]
    fill_colors = ["C.fGreen", "C.fBlue", "C.fPurple", "C.fYellow", "C.fGray"]

    # ---- 竖版排版常量（1080 x 1920） ----
    card_x = 100
    card_w = 880
    title_y = 120
    title_size = 64
    divider_y = 230
    card_top = 260
    card_bottom = 1560
    # 图标列：x [140, 360]，宽 220；文字列：x [400, 940]，宽 540
    icon_w = 220
    icon_h = 260
    icon_x = card_x + 40
    text_x = icon_x + icon_w + 40
    text_w = card_x + card_w - 40 - text_x

    # 每 beat 卡片高度：均分卡片区，beat 间留 40px 箭头
    arrow_gap = 40
    n = min(num_beats, 5)
    card_h = (card_bottom - card_top - (n - 1) * arrow_gap) // n
    y_starts = [card_top + i * (card_h + arrow_gap) for i in range(n)]

    def wrap_points(pts: tuple[str, ...], max_chars: int = 12) -> list[str]:
        """长句按 max_chars 折行，保证不超出卡片宽度。"""
        wrapped: list[str] = []
        for p in pts:
            if len(p) <= max_chars:
                wrapped.append(p)
            else:
                buf = ""
                for ch in p:
                    buf += ch
                    if len(buf) >= max_chars:
                        wrapped.append(buf)
                        buf = ""
                if buf:
                    wrapped.append(buf)
        return wrapped

    def draw_card(b_idx: int, beat: WhiteboardBeat, y: int, col: str, fill: str) -> None:
        """在 y 处画一张卡片：图标左栏，标题+要点右栏。"""
        lines.append(f"s.rect({card_x}, {y}, {card_w}, {card_h}, {{ round: true, stroke: {col}, strokeWidth: 3, fill: {fill} }});")
        # 标题：右栏顶部居中
        title_center_x = text_x + text_w // 2
        lines.append(f"s.text({title_center_x}, {y + 30}, `{beat.title}`, {{ size: 54, align: 'center', color: {col} }});")
        # 图标：左栏垂直居中
        icon_y = y + (card_h - icon_h) // 2
        motif = beat.motif or ("robot" if b_idx % 2 == 0 else "laptop")
        if motif == "laptop":
            lines.append(f"s.laptop({icon_x}, {icon_y}, 0.85);")
        else:
            lines.append(f"s.robot({icon_x}, {icon_y}, 0.85);")
        # 要点：右栏，自动换行
        wrapped = wrap_points(beat.points)
        pt_lines = "\\n· ".join(wrapped)
        pt_y = y + 130
        lines.append(f"s.text({text_x}, {pt_y}, `· {pt_lines}`, {{ size: 40, color: C.ink }});")

    # ---- 按 beat 数生成 ----
    if n == 1:
        b0 = segment.beats[0]
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX_P, {title_y}, `{topic}`, {{ size: {title_size}, align: 'center', color: C.brand }});")
        lines.append(f"s.line([[180, {divider_y}], [900, {divider_y}]], {{ stroke: C.brand, strokeWidth: 4, roughness: 1.2 }});")
        draw_card(0, b0, y_starts[0], "C.brand", "C.fGreen")

    elif n == 2:
        b0, b1 = segment.beats[0], segment.beats[1]
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX_P, {title_y}, `{topic}`, {{ size: {title_size}, align: 'center', color: C.brand }});")
        lines.append(f"s.line([[180, {divider_y}], [900, {divider_y}]], {{ stroke: C.brand, strokeWidth: 4, roughness: 1.2 }});")
        draw_card(0, b0, y_starts[0], "C.blue", "C.fBlue")
        lines.append("s.nextBeat();")
        lines.append(f"s.arrow([[CX_P, {y_starts[0] + card_h + 5}], [CX_P, {y_starts[1] - 5}]], {{ stroke: C.gray, strokeWidth: 3 }});")
        draw_card(1, b1, y_starts[1], "C.purple", "C.fPurple")

    elif n == 3:
        b0, b1, b2 = segment.beats[0], segment.beats[1], segment.beats[2]
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX_P, {title_y}, `{topic}`, {{ size: {title_size}, align: 'center', color: C.brand }});")
        lines.append(f"s.line([[180, {divider_y}], [900, {divider_y}]], {{ stroke: C.brand, strokeWidth: 4, roughness: 1.2 }});")
        draw_card(0, b0, y_starts[0], "C.brand", "C.fGreen")
        lines.append("s.nextBeat();")
        lines.append(f"s.arrow([[CX_P, {y_starts[0] + card_h + 5}], [CX_P, {y_starts[1] - 5}]], {{ stroke: C.gray, strokeWidth: 3 }});")
        draw_card(1, b1, y_starts[1], "C.blue", "C.fBlue")
        lines.append("s.nextBeat();")
        lines.append(f"s.arrow([[CX_P, {y_starts[1] + card_h + 5}], [CX_P, {y_starts[2] - 5}]], {{ stroke: C.gray, strokeWidth: 3 }});")
        draw_card(2, b2, y_starts[2], "C.orange", "C.fYellow")

    else:
        # 4–5 beats
        lines.append("s.nextBeat();")
        lines.append(f"s.text(CX_P, {title_y}, `{topic}`, {{ size: {title_size}, align: 'center', color: C.brand }});")
        lines.append(f"s.line([[180, {divider_y}], [900, {divider_y}]], {{ stroke: C.brand, strokeWidth: 4, roughness: 1.2 }});")
        for idx, beat in enumerate(segment.beats[:5]):
            if idx > 0:
                lines.append("s.nextBeat();")
                lines.append(f"s.arrow([[CX_P, {y_starts[idx - 1] + card_h + 5}], [CX_P, {y_starts[idx] - 5}]], {{ stroke: C.gray, strokeWidth: 3 }});")
            col = colors[idx % len(colors)]
            fill = fill_colors[idx % len(fill_colors)]
            draw_card(idx, beat, y_starts[idx], col, fill)

    lines.append("scenes.push(s); }")
    return lines


def compile_storyboard_to_dsl(
    storyboard_data: dict[str, Any],
    *,
    orientation: str = "landscape",
    runtime_root: str,
) -> str:
    """Compile storyboard into complete scenes.js code."""
    topic = str(storyboard_data.get("topic") or "白板讲解")
    segments = parse_storyboard(storyboard_data)

    js_lines = [
        f"// 《{topic}》- 白板讲解 scenes.js",
        f"const {{ Scene, C, CX, CY, W_P, H_P, CX_P, CY_P, build }} = require('{runtime_root}/scene-dsl').use(__dirname);",
        "const scenes = [];",
    ]

    for seg in segments:
        if orientation == "portrait":
            seg_lines = generate_portrait_scene_js(seg, topic=topic)
        else:
            seg_lines = generate_landscape_scene_js(seg, topic=topic)
        js_lines.extend(seg_lines)

    # Cover layout
    js_lines.append(
        f"const cover = (s, ratio) => s.coverLayout({{ ratio, title: '{topic}', sub: '手绘白板讲解' }});"
    )
    js_lines.append("build(__dirname, scenes, { cover });")

    return "\n".join(js_lines) + "\n"
