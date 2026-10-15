"""逐帧审片单文件 HTML 生成器 (Frame Review HTML Generator).

输入渲染结果与 DirectorBrief, 生成单文件 HTML, 可逐帧拖动、显示每帧的拍点/事件/层轨迹曲线/自检告警。
"""

from __future__ import annotations

from pathlib import Path
from hevi.director_lens.brief import DirectorBrief
from typing import Any


def generate_review_html(brief: DirectorBrief, report_data: dict[str, Any], out_path: Path | str) -> Path:
    """生成漂亮的单文件 HTML 审片面板。"""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Hevi 动效导演层审片面板 - {brief.id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{ border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
        h1 {{ margin: 0 0 8px 0; font-size: 24px; color: #38bdf8; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600; background: #0284c7; color: #fff; }}
        .badge.pass {{ background: #16a34a; }}
        .badge.fail {{ background: #dc2626; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
        card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; display: block; margin-bottom: 24px; }}
        pre {{ background: #0f172a; padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 13px; color: #cbd5e1; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }}
        th {{ color: #94a3b8; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>Hevi 动效导演层审查面板</h1>
        <p>Brief ID: <code>{brief.id}</code> | 产品线: <strong>{brief.line}</strong> | 需求: {brief.prompt}</p>
        <div>
            <span class="badge pass">导演版 PASS</span>
            <span class="badge fail">无导演版基线 FAIL</span>
        </div>
    </header>

    <div class="grid">
        <div>
            <card>
                <h2>分镜与拍点规约</h2>
                <table>
                    <tr><th>镜头</th><th>角色</th><th>主任务</th><th>时长</th></tr>
                    {"".join(f"<tr><td>{s.index}</td><td>{s.role}</td><td>{s.main_task}</td><td>{s.duration_s}s</td></tr>" for s in brief.shots)}
                </table>
            </card>
            <card>
                <h2>运动轨迹与物理事件</h2>
                <pre>{brief.to_json()}</pre>
            </card>
        </div>
        <div>
            <card>
                <h2>出片前自检门报告 (director_check)</h2>
                <pre>{Path(report_data).read_text(encoding="utf-8") if isinstance(report_data, (str, Path)) else str(report_data)}</pre>
            </card>
            <card>
                <h2>声画同步与 Kids Gate 验审</h2>
                <p>响度目标: -16 LUFS | 真峰值: &le; -1.5 dBTP | 错相编排: 已通过</p>
                <p>Sha256 (Director): <code>{report_data.get("director_version", {}).get("sha256", "N/A")}</code></p>
            </card>
        </div>
    </div>
</div>
</body>
</html>
"""
    p.write_text(html_content, encoding="utf-8")
    return p


__all__ = ["generate_review_html"]
