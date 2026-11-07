"""preflight.gate —— 生成前门禁总入口。

run_gate(beat, model) 按固定顺序跑四组检查：
prompt 审计 → 首帧验真 → 对白适配 → 成本预估＋预算门。
任一 FAIL 即 verdict=FAIL、blocked=True（除非人工 override 留理由）。
WARN 不阻塞，但报告里逐条列出，生成后复盘时可对照。

门禁是“生成前”关卡：它不调任何付费 API、不登录任何账号，
只读本地 beat／首帧／台账。
"""

from __future__ import annotations

from typing import Any

from hevi.preflight.beats import Beat, get_model_spec
from hevi.preflight.budget import budget_gate, estimate_cost
from hevi.preflight.dialogue_fit import fit_dialogue
from hevi.preflight.findings import Finding, GateReport
from hevi.preflight.first_frame import HUMAN_CHECKLIST, check_first_frame
from hevi.preflight.prompt_audit import audit_prompt


def run_gate(
    beat: Beat,
    model: str,
    *,
    prompt_text: str = "",
    ledger: Any = None,
    character_sheets: dict[str, str] | None = None,
    allow_override: bool = False,
    override_reason: str = "",
) -> GateReport:
    get_model_spec(model)  # 未知模型直接抛，不许带病放行
    findings: list[Finding] = []
    checklist: list[str] = list(HUMAN_CHECKLIST)

    findings.extend(audit_prompt(beat, prompt_text))
    frame_findings, frame_checklist = check_first_frame(beat, character_sheets)
    findings.extend(frame_findings)
    checklist = frame_checklist
    findings.extend(fit_dialogue(beat, model))

    spec = get_model_spec(model)
    window = spec.window_s or beat.duration_s
    estimate = estimate_cost(model, window)
    findings.extend(budget_gate(estimate, ledger, beat_id=beat.beat_id))

    verdict = "PASS"
    if any(f.level == "FAIL" for f in findings):
        verdict = "FAIL"
    elif any(f.level == "WARN" for f in findings):
        verdict = "WARN"

    blocked = verdict == "FAIL"
    if blocked and allow_override and override_reason.strip():
        blocked = False  # 人工 override：理由写进报告，不删 FAIL 记录

    return GateReport(
        beat_id=beat.beat_id,
        model=model,
        verdict=verdict,
        findings=findings,
        estimated_cost=estimate,
        human_checklist=checklist,
        override_reason=override_reason if (blocked is False and verdict == "FAIL") else "",
        blocked=blocked,
    )


def run_batch(
    beats: list[Beat],
    model: str,
    *,
    ledger: Any = None,
    character_sheets: dict[str, str] | None = None,
) -> dict[str, Any]:
    """批量门禁：返回逐条报告＋合计（总成本、拦住条数）。"""
    reports = [run_gate(b, model, ledger=ledger, character_sheets=character_sheets) for b in beats]
    total = 0
    currency = ""
    for r in reports:
        amount = r.estimated_cost.get("amount")
        if isinstance(amount, (int, float)):
            total += amount
        currency = r.estimated_cost.get("currency", currency)
    return {
        "model": model,
        "reports": [r.to_dict() for r in reports],
        "total_cost": total,
        "currency": currency,
        "blocked_count": sum(1 for r in reports if r.blocked),
        "fail_count": sum(1 for r in reports if r.verdict == "FAIL"),
        "warn_count": sum(1 for r in reports if r.verdict == "WARN"),
    }
