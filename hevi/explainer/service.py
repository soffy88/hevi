"""Stateless Explainer Master v8 orchestration facade.

HEVI owns authentication, task persistence and human approval.  This service
only coordinates research and approved cue assembly and never invents a task,
provider result or artifact path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.explainer.assembly import assemble_explainer_cues
from hevi.explainer.contracts import (
    ExplainerAssembleRequest,
    ExplainerResearchRequest,
    ExplainerServiceResult,
)
from hevi.explainer.props import deep_unpack_json
from hevi.explainer.research import research_and_generate
from hevi.explainer.research_cache import (  # noqa: F401  (service.py 对外暴露断点续传入口)
    load_research_cache,
    save_research_cache,
)


class ExplainerMasterService:
    """Provider-injected stateless facade used by API adapters and tests."""

    async def research(
        self,
        request: ExplainerResearchRequest,
        *,
        researcher: Any = None,
        script_generator: Any = None,
    ) -> ExplainerServiceResult:
        return await research_and_generate(
            request, researcher=researcher, script_generator=script_generator
        )

    async def assemble(
        self,
        request: ExplainerAssembleRequest,
        output_dir: Path,
        *,
        heygen_provider: Any = None,
        browser_broll_recorder: Any = None,
    ) -> Any:
        # 终极防爆:接收 payload 的第一行做全局递归解包——藏在 str 里的 dict /
        # list(含二重转义)全部自动 json.loads() 还原,再走 Pydantic 重新校验。
        # 从此 cue.get() / visual_config["chart_data"] 绝不会再撞上字符串。
        clean_payload = deep_unpack_json(request)
        clean_request = ExplainerAssembleRequest.model_validate(clean_payload)
        return await assemble_explainer_cues(
            clean_request.topic_or_url or clean_request.selected_hook,
            clean_request.final_script_cues,
            output_dir,
            voice=clean_request.voice_profile,
            enable_circle_avatar_mask=clean_request.enable_circle_avatar_mask,
            enable_remotion_code_render=clean_request.enable_remotion_code_render,
            enable_browser_broll=clean_request.enable_browser_broll,
            aspect_ratio=clean_request.aspect_ratio,
            heygen_presenter_id=clean_request.heygen_presenter_id,
            presenter_provider=clean_request.presenter_provider,
            presenter_name=clean_request.presenter_name,
            heygen_provider=heygen_provider,
            broll_recorder=browser_broll_recorder,
        )


__all__ = ["ExplainerMasterService"]
