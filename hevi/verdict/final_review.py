"""成片独立终检协议(3O 内化 Round 3,来源 shotcraft final-review.md)。

shotcraft 的 final-review 是比"判例自检"深的**成片独立终检协议**:
  - 审查者必须处于干净上下文,不参与制作;不给理由/辩解/修改历史/预期结论。
  - 六组检查:P(产品目标)/ F(功能完整性)/ V(视觉方向)/ S(镜头卡与 Gallery 变体)/
    B(分镜一致性)/ D(数据与素材安全)。
  - 缺少输入 → 标"无法验证",不自行猜测制作基准。
  - 索引/卡片文档/demo 源码/参考样片冲突 → 明确报告冲突来源,不自选真相。

本模块为 hevi 暂驻(待上游 `oskill.final_review`):确定性审查骨架 —— 输入清单、
检查项表、逐项判定(pass/fail/unverifiable/conflict) + 报告。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 审查输入清单(缺一项 → 相关检查标"无法验证")。
REVIEW_INPUTS: tuple[tuple[str, str], ...] = (
    ("final_mp4", "最新成片 MP4"),
    ("keyframes", "每镜头关键帧"),
    ("brief", "产品视频简报与必须展示的功能"),
    ("decision_table", "需求到执行决策表"),
    ("visual_direction", "视觉方向/styleframe/品牌 tokens"),
    ("shot_mapping", "功能到镜头映射"),
    ("card_library", "Gallery 卡库(library.json)"),
    ("demo_tsx", "准确 demo TSX 源码"),
    ("reference_preview", "Gallery 参考样片/关键帧"),
    ("final_storyboard", "最终分镜/字幕/页面状态/SFX 计划"),
    ("aesthetic_rules", "审美准则"),
    ("data_policy", "数据合规口径"),
)

#: 检查项表:(组, 编号, 检查内容, 依赖输入)。
FINAL_REVIEW_CHECKS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("P", "P1", "产品定位、目标用户和核心卖点是否清楚", ("brief",)),
    ("P", "P2", "成片注意力是否放在确认/记录的功能优先级上", ("brief", "shot_mapping")),
    ("P", "P3", "是否出现项目不存在/未经确认/误导的功能宣称", ("brief",)),
    (
        "P", "P4",
        "决策表执行选择能否在分镜/文案/页面/音频/素材中找到落地",
        ("decision_table", "final_storyboard"),
    ),
    (
        "F", "F1",
        "每个必须展示的功能是否至少有一个清楚可辨的镜头",
        ("brief", "final_storyboard"),
    ),
    ("F", "F2", "每镜头是否提供新信息,有无重复功能/重复 tagline", ("final_storyboard",)),
    ("F", "F3", "页面状态是否让观众理解功能,而非装饰性运动", ("final_mp4", "keyframes")),
    (
        "V", "V1",
        "字体/色板/材质/圆角/光感/信息密度是否符合视觉方向",
        ("visual_direction", "final_mp4"),
    ),
    ("V", "V2", "动效速度/过冲/停留/能量曲线是否符合动效性格", ("visual_direction", "final_mp4")),
    ("V", "V3", "是否偏离制作基准漂移到无关风格", ("visual_direction",)),
    ("V", "V4", "禁用的颜色/效果/品牌特征是否被使用", ("visual_direction",)),
    ("S", "S1", "功能映射中的镜头卡是否实际出现在对应镜头", ("shot_mapping", "final_storyboard")),
    (
        "S", "S2",
        "点名的 卡名·样式名 的 style-key/demo TSX/参考样片是否同变体且成片采用",
        ("card_library", "demo_tsx", "reference_preview"),
    ),
    (
        "S", "S3",
        "对照 demo TSX 与参考样片,是否保留动作语法/关键时值/缓动/遮罩时机",
        ("demo_tsx", "reference_preview", "final_mp4"),
    ),
    ("S", "S4", "是否违反卡片标注的已知坑/命门", ("card_library",)),
    ("S", "S5", "适配后的产品截图/坐标/品牌 token 是否自然", ("final_mp4",)),
    ("S", "S6", "标为'仅供参考/缺少预览'的样式是否得到点名并在报告标注风险", ("card_library",)),
    ("B", "B1", "镜头顺序/时长/功能信息是否符合最终分镜", ("final_storyboard", "final_mp4")),
    ("B", "B2", "主动作/页面状态/素材来源/字幕/转场/SFX 是否一致", ("final_storyboard",)),
    ("B", "B3", "品牌字标 hold ≥1s;批量动效收尾静止 ≥0.5s", ("final_mp4",)),
    ("B", "B4", "分镜放行后是否无依据删除/替换/增加关键镜头", ("final_storyboard",)),
    ("D", "D1", "是否遵守真实/虚构/脱敏数据口径", ("data_policy",)),
    ("D", "D2", "是否暴露客户/个人/密钥/内部地址等敏感信息", ("final_mp4", "data_policy")),
    ("D", "D3", "表现真实产品页面时是否用真实截图而非低质量手搓复刻", ("final_mp4",)),
    ("D", "D4", "截图状态/字体/图片/动态数据是否完整加载", ("final_mp4",)),
    ("D", "D5", "公开演示数据可复核;敏感数据已虚构/脱敏/冻结", ("data_policy",)),
)


@dataclass
class FinalReviewResult:
    """终检结果:逐项状态 + 无法验证项 + 冲突报告。"""

    checks: list[dict[str, Any]] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)  # 因缺输入无法验证的项
    conflicts: list[str] = field(default_factory=list)  # 来源冲突报告
    missing_inputs: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """全部已检项通过 且 无无法验证项。"""
        return not self.unverifiable and all(
            c.get("status") in (None, True) for c in self.checks if c.get("status") is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": self.checks,
            "unverifiable": self.unverifiable,
            "conflicts": self.conflicts,
            "missing_inputs": self.missing_inputs,
            "passed": self.passed,
        }


def run_final_review(
    inputs_present: dict[str, bool],
    *,
    verdicts: dict[str, bool] | None = None,
    conflicts: list[str] | None = None,
) -> FinalReviewResult:
    """确定性终检骨架。

    Args:
        inputs_present: {输入键: 是否提供};缺 → 依赖项标"无法验证"。
        verdicts: 审查者对检查项的判定 {编号: bool};缺省未检(? 标 None)。
        conflicts: 审查者报告的来源冲突(索引/卡文档/demo/样片不一致)。

    Returns:
        FinalReviewResult(逐项状态 + 无法验证 + 冲突 + 缺输入清单)。
    """
    result = FinalReviewResult()
    verdicts = verdicts or {}
    conflicts = conflicts or []
    result.conflicts = list(conflicts)

    for input_key, label in REVIEW_INPUTS:
        if not inputs_present.get(input_key):
            result.missing_inputs.append(f"{input_key}({label})")

    for group, code, text, deps in FINAL_REVIEW_CHECKS:
        missing_deps = [d for d in deps if not inputs_present.get(d)]
        if missing_deps:
            result.unverifiable.append(f"{code}(缺输入: {', '.join(missing_deps)})")
            result.checks.append(
                {"group": group, "code": code, "text": text, "status": None,
                 "state": "unverifiable", "missing_inputs": missing_deps}
            )
            continue
        state = "unchecked"
        status: bool | None = None
        if code in verdicts:
            status = bool(verdicts[code])
            state = "pass" if status else "fail"
        result.checks.append(
            {"group": group, "code": code, "text": text, "status": status, "state": state}
        )
    return result


def render_review_report(result: FinalReviewResult) -> str:
    """报告渲染:`组 编号 状态(文本)`;无法验证/冲突单列。"""
    lines: list[str] = []
    for c in result.checks:
        mark = {"pass": "✓", "fail": "✗", "unchecked": "?", "unverifiable": "—"}[c["state"]]
        lines.append(f"{mark} {c['group']}{c['code']} {c['text']}")
    if result.unverifiable:
        lines.append(f"\n无法验证({len(result.unverifiable)}): " + "; ".join(result.unverifiable))
    if result.conflicts:
        lines.append(f"\n来源冲突({len(result.conflicts)}): " + "; ".join(result.conflicts))
    if result.missing_inputs:
        lines.append(f"\n缺输入({len(result.missing_inputs)}): " + "; ".join(result.missing_inputs))
    return "\n".join(lines)


def save_review_result(result: FinalReviewResult, out_path: str | Path) -> Path:
    """终检结果落盘 JSON。"""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p
