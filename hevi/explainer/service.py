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
from hevi.explainer.research import research_and_generate


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
        return await assemble_explainer_cues(
            request.topic_or_url or request.selected_hook,
            request.final_script_cues,
            output_dir,
            voice=request.voice_profile,
            enable_circle_avatar_mask=request.enable_circle_avatar_mask,
            enable_remotion_code_render=request.enable_remotion_code_render,
            enable_browser_broll=request.enable_browser_broll,
            aspect_ratio=request.aspect_ratio,
            heygen_presenter_id=request.heygen_presenter_id,
            heygen_provider=heygen_provider,
            broll_recorder=browser_broll_recorder,
        )


__all__ = ["ExplainerMasterService"]
