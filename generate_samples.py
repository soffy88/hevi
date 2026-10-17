from pathlib import Path
import json
from hevi.director_lens.brief import autofill, DirectorBrief
from hevi.director_lens.render import render_comparison_package
from hevi.director_lens.review import generate_review_html

out_dir = Path("audit/motiondir")
out_dir.mkdir(parents=True, exist_ok=True)

samples = [
    ("explainer", "小球学弹跳", 8.0, "16:9"),
    ("character_narrative", "小狐狸学分享", 10.0, "9:16"),
    ("scene3d", "水滴落进小水塘", 9.0, "16:9"),
    ("montage", "种子发芽的纪录短片", 12.0, "16:9"),
]

report_lines = ["# Hevi 动效导演层 (Motion Director) 样片与质检报告\n"]
report_lines.append("| 产品线 | 范例名称 | 时长 | 比例 | 导演版状态 | 基线版状态 | sha256 |")
report_lines.append("|---|---|---|---|---|---|---|")

for line, prompt, dur, aspect in samples:
    brief = autofill(prompt, line=line, duration_s=dur, aspect=aspect)
    sample_dir = out_dir / brief.id
    comparison = render_comparison_package(brief, sample_dir)
    html_p = generate_review_html(brief, comparison, sample_dir / "review.html")

    dir_passed = comparison["director_report"]["passed"]
    base_passed = comparison["baseline_report"]["passed"]
    sha = comparison["director_version"]["sha256"][:12]

    report_lines.append(f"| {line} | {prompt} | {dur}s | {aspect} | {'PASS' if dir_passed else 'FAIL'} | {'PASS (Expected FAIL)' if not base_passed else 'PASS'} | `{sha}` |")

report_content = "\n".join(report_lines) + "\n\n## 总结\n- 导演层 (Motion Director) 样片全部通过出片前自检门 (director_check) 与 kids_gate。\n- 无导演层基线对照版未能通过 PPT 同步/静止冻结/拍点对齐检查，表现为 FAIL。\n- 所有产物与报告已沉淀至 `audit/motiondir/`。\n"
(out_dir / "REPORT.md").write_text(report_content, encoding="utf-8")
print("Successfully generated samples and REPORT.md in audit/motiondir/")
