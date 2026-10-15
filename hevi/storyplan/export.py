"""分镜表与镜头清单导出（Markdown / CSV / HTML）。"""

from __future__ import annotations

from hevi.storyplan.model import StoryPlan


def export_storyboard_markdown(plan: StoryPlan) -> str:
    """导出分镜表及镜头清单为 Markdown 格式。"""
    lines = [
        f"# 分镜表与镜头清单：{plan.title}",
        "",
        f"- **纵横比**: {plan.aspect}",
        f"- **帧率**: {plan.fps} fps",
        f"- **总时长**: {plan.duration_sec} s",
        f"- **受众**: {plan.audience}",
        f"- **顺口播稿**: {plan.narration_text}",
        "",
        "## 一、 叙事层（Beats & Hook）",
        f"- **开场钩子类型**: {plan.narrative.hook.hook_type}",
        f"- **钩子文案**: {plan.narrative.hook.text}",
        "",
        "### 叙事关键拍点 (Beats)",
        "| ID | 阶段 | 摘要 | 对应期待 | 时间范围 |",
        "|---|---|---|---|---|",
    ]
    for b in plan.narrative.beats:
        lines.append(f"| `{b.beat_id}` | {b.phase} | {b.summary} | {b.expectation} | {b.start_ms}ms - {b.end_ms}ms |")

    lines.extend([
        "",
        "## 二、 镜头层 (Shots)",
        "| 编号 | 用途 | 开始状态 | 动作与结束状态 | 声音 | A/B 角色 | 来源 | 验收点 |",
        "|---|---|---|---|---|---|---|---|",
    ])

    all_shots = [sh for seq in plan.shots.sequences for sc in seq.scenes for sh in sc.shots]
    for sh in all_shots:
        action_desc = f"{sh.action} -> {sh.end_state}"
        lines.append(
            f"| `{sh.shot_id}` | {sh.purpose} | {sh.start_state} | {action_desc} | {sh.sound} | {sh.roll_role} ({sh.b_roll_function}) | {sh.material_source} | {sh.acceptance} |"
        )

    lines.extend([
        "",
        "## 三、 时间线轨序 (Timeline Tracks)",
    ])
    for tr in plan.timeline.tracks:
        lines.append(f"- **轨道**: `{tr.track_kind}` (包含 {len(tr.clips)} 个片段)")

    return "\n".join(lines) + "\n"


def export_storyboard_html(plan: StoryPlan, check_report: Any = None) -> str:
    """导出单文件审片 HTML（分镜表 + 时间线多轨可视化 + 验收结果）。"""
    all_shots = [sh for seq in plan.shots.sequences for sc in seq.scenes for sh in sc.shots]
    check_html = ""
    if check_report:
        badge = '<span style="color: green; font-weight: bold;">PASS</span>' if check_report.passed else '<span style="color: red; font-weight: bold;">FAIL</span>'
        items_list = []
        for c in check_report.checks:
            color = "green" if c.status == "PASS" else "red"
            items_list.append(f"<li><b>{c.check_id} ({c.name})</b>: <span style='color: {color};'>{c.status}</span> - {c.message}</li>")
        items_html = "".join(items_list)
        check_html = f"""
        <div class="card" style="margin-bottom: 20px; background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2>结构自检门 (Story Check): {badge}</h2>
            <ul>{items_html}</ul>
        </div>
        """

    shots_rows = "".join(
        f"""
        <tr>
            <td><code>{sh.shot_id}</code></td>
            <td>{sh.purpose}</td>
            <td>{sh.start_state}</td>
            <td><b>动作:</b> {sh.action}<br><b>结束:</b> {sh.end_state}</td>
            <td>{sh.sound}</td>
            <td>{sh.roll_role}</td>
            <td>{sh.material_source}</td>
            <td>{sh.acceptance}</td>
        </tr>
        """
        for sh in all_shots
    )

    tracks_html = ""
    for tr in plan.timeline.tracks:
        clips_html = "".join(
            f"""
            <div style="position: absolute; left: {c.start_ms / max(1, plan.timeline.duration_ms) * 100}%; width: {max(2.0, (c.end_ms - c.start_ms) / max(1, plan.timeline.duration_ms) * 100)}%; background: #38bdf8; color: #fff; padding: 2px 5px; font-size: 11px; overflow: hidden; border-radius: 3px;" title="{c.clip_id}: {c.text or c.source_ref}">
                {c.clip_id}
            </div>
            """
            for c in tr.clips
        )
        tracks_html += f"""
        <div style="display: flex; margin-bottom: 8px; align-items: center;">
            <div style="width: 100px; font-weight: bold; font-size: 12px; color: #475569;">{tr.track_kind}</div>
            <div style="flex-grow: 1; background: #e2e8f0; height: 24px; position: relative; border-radius: 4px;">
                {clips_html}
            </div>
        </div>
        """

    html = f"""<!doctype html>
<html lang="zh">
<head>
    <meta charset="utf-8">
    <title>Hevi StoryPlan 审片报告: {plan.title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
        h1, h2 {{ color: #0f172a; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; margin-bottom: 20px; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
        th {{ background: #f1f5f9; color: #334155; }}
        .card {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    </style>
</head>
<body>
    <h1>Hevi StoryPlan 审片报告与可视化</h1>
    <p><b>视频主题:</b> {plan.title} | <b>纵横比:</b> {plan.aspect} | <b>时长:</b> {plan.duration_sec}s | <b>受众:</b> {plan.audience}</p>
    <p><b>顺口播稿:</b> {plan.narration_text}</p>

    {check_html}

    <div class="card">
        <h2>时间线多轨可视化</h2>
        {tracks_html}
    </div>

    <div class="card">
        <h2>分镜表清单 (Storyboard)</h2>
        <table>
            <thead>
                <tr>
                    <th>镜头 ID</th>
                    <th>用途</th>
                    <th>开始状态</th>
                    <th>动作 / 结束状态</th>
                    <th>声音</th>
                    <th>角色</th>
                    <th>来源</th>
                    <th>验收点</th>
                </tr>
            </thead>
            <tbody>
                {shots_rows}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    return html
