"""连续性报告(HEVI 路线图 Phase3 #41)。

从 shot_states(#27 扩展后的 selection_json)派生,随高阶交付一起给用户——纯聚合
已落库的数据,零增量计算成本(不重新跑任何打分/检测)。

给专业/代理商用户的"完整制作包"的一部分:镜头清单 + 逐镜头一致性/诊断明细 +
这次用到的 Subject/StylePack 版本快照说明。
"""

from __future__ import annotations

from typing import Any


def build_continuity_report(shots: list[dict[str, Any]]) -> dict[str, Any]:
    """shot_states 行(含 selection_json)→ 连续性报告 dict。

    没有镜头数据(空列表)也要返回一个合法的空报告,不报错——任务可能还没落过
    shot_states(老数据/落库失败),报告本身是锦上添花,不该因为数据不全就崩。
    """
    shot_rows: list[dict[str, Any]] = []
    diagnosis_counts: dict[str, int] = {}
    consistency_scores: list[float] = []
    passed_count = 0
    subject_refs: dict[str, int | None] = {}
    style_pack_refs: dict[str, int | None] = {}

    for row in shots:
        sel = row.get("selection_json") or {}
        passed = bool(sel.get("passed", True))
        if passed:
            passed_count += 1
        score = sel.get("consistency_score")
        if isinstance(score, (int, float)):
            consistency_scores.append(float(score))
        category = sel.get("diagnosis_category")
        if category:
            diagnosis_counts[category] = diagnosis_counts.get(category, 0) + 1
        if sel.get("subject_id"):
            subject_refs[sel["subject_id"]] = sel.get("subject_version")
        if sel.get("style_pack_id"):
            style_pack_refs[sel["style_pack_id"]] = sel.get("style_pack_version")

        shot_rows.append(
            {
                "index": row.get("shot_index"),
                "status": row.get("status"),
                "provider": sel.get("provider"),
                "model_version": sel.get("model_version"),
                "passed": sel.get("passed"),
                "consistency_score": sel.get("consistency_score"),
                "style_score": sel.get("style_score"),
                "vlm_score": sel.get("vlm_score"),
                "vlm_violations": sel.get("vlm_violations") or [],
                "diagnosis_category": sel.get("diagnosis_category"),
                "duration_s": sel.get("duration_s"),
                "tier0_passed": sel.get("tier0_passed"),
                "tier1_passed": sel.get("tier1_passed"),
            }
        )

    total = len(shot_rows)
    return {
        "shots": shot_rows,
        "summary": {
            "total_shots": total,
            "passed_shots": passed_count,
            "pass_rate": (passed_count / total) if total else None,
            "avg_consistency_score": (
                sum(consistency_scores) / len(consistency_scores) if consistency_scores else None
            ),
            "diagnosis_breakdown": diagnosis_counts,
            "subject_refs": [
                {"subject_id": sid, "subject_version": ver} for sid, ver in subject_refs.items()
            ],
            "style_pack_refs": [
                {"style_pack_id": pid, "style_pack_version": ver}
                for pid, ver in style_pack_refs.items()
            ],
        },
    }
