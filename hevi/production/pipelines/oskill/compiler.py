"""Pipeline selection rules; stage execution remains in canonical HEVI adapters."""

from __future__ import annotations

from hevi.production.pipelines.oprim.contracts import PipelineSpec


def pipeline_for_brief(brief: str, specs: list[PipelineSpec]) -> PipelineSpec:
    text = brief.lower()
    keywords = (
        (("短剧", "drama", "剧情"), "short_drama"),
        (("podcast", "播客", "访谈"), "podcast_repurpose"),
        (("screen", "截图", "产品演示"), "screen_demo"),
        (("avatar", "数字人", "口播"), "avatar_spokesperson"),
        (("纪录", "documentary"), "documentary_montage"),
    )
    for terms, pipeline_id in keywords:
        if any(term in text or term in brief for term in terms):
            found = next((spec for spec in specs if spec.pipeline_id == pipeline_id), None)
            if found is not None:
                return found
    return next(spec for spec in specs if spec.pipeline_id == "cinematic")


__all__ = ["pipeline_for_brief"]
