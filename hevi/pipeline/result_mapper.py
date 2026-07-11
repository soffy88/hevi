from typing import Any

from omodul.agentic_longvideo_pipeline import LongVideoResult

from hevi.verdict.scorecard import Scorecard, coarse_diagnosis


def map_longvideo_result(
    result: LongVideoResult,
    *,
    scorecards: dict[int, Scorecard] | None = None,
    subject_id: str | None = None,
    subject_version: int | None = None,
    style_pack_id: str | None = None,
    style_pack_version: int | None = None,
    tier0_passed: bool | None = None,
) -> dict[str, Any]:
    """Map omodul.LongVideoResult to hevi app business result.

    shot_verdict 扩展(HEVI 路线图 Phase1):omodul 的 ShotRecord 只落 identity_score
    (consistency_score),`scorecards`(shot index → 完整 Scorecard,由
    `hevi.verdict.scorecard.make_scorecard_consistency_fn(capture=...)` 在生成时旁路收集)
    补上 style_score/vlm_score/诊断分类;subject/stylepack 的 id+version 是**生成当时**
    的快照(不是"当前版本引用")——资产升级后历史校验记录不会跟着失真。
    """
    shots: list[dict[str, Any]] = []
    for r in getattr(result, "shots", []):
        shot = r.model_dump(mode="json")
        sc = (scorecards or {}).get(shot.get("index"))
        shot.update(
            {
                # style_score 目前没有任何调用方传 style_ref_embedding(#34/#38 才会接
                # 上)——Scorecard 里恒为 0.0,不是真测量结果,记 None 而不是假装测过。
                "style_score": (sc.style_score if sc and sc.style_score else None),
                # vlm_score/vlm_violations 是 Tier1(#33)的真实产出:None = 没触发
                # (Tier0 没报警/mllm 不可用),非 None = 真跑过本地 VLM 质检。
                "vlm_score": (sc.vlm_score if sc else None),
                "vlm_violations": (sc.vlm_violations if sc else []),
                "diagnosis_category": coarse_diagnosis(sc) if sc else None,
                "subject_id": subject_id,
                "subject_version": subject_version,
                "style_pack_id": style_pack_id,
                "style_pack_version": style_pack_version,
                "model_version": shot.get("provider"),
                # Tier0 现状是整片级检查(quality_report),没有逐镜头拆分依据,这里先记
                # 整片结果作粗粒度代理。
                "tier0_passed": tier0_passed,
                "tier1_passed": (not sc.vlm_violations)
                if (sc and sc.vlm_score is not None)
                else None,
            }
        )
        shots.append(shot)

    return {
        "id": f"hevi_{result.video_path.stem}",
        "url": str(result.video_path),
        "duration": result.duration_s,
        "metadata": {
            "chapters": result.chapters,
            "shots": result.shots_generated,
            "providers": result.provider_used,
        },
        # C3: 逐镜头选优明细(omodul v1.36.0),供 task_service 落 ShotState。
        # mode="json" → Path 转 str,可直接 JSONB 落库。老版 omodul 无 shots → 空列表。
        "shots": shots,
    }
