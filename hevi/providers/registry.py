from __future__ import annotations

import logging
from typing import Any

from obase.provider_registry import ProviderRegistry
from oprim import avatar_generate, ltx2_cloud_generate, vibevoice_synthesize, video_generate
import oprim.providers.dashscope as dashscope

__all__ = ["ProviderRegistry", "register_all_providers"]

logger = logging.getLogger(__name__)


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup."""
    # 1. LLM Providers (for agentic orchestration)
    dashscope.register(replace=True)
    
    raw_dashscope = ProviderRegistry.get("llm", "qwen3_dashscope")

    class AsyncDashScopeAdapter:
        """Adapter that behaves like a coroutine but has a .get() method.
        
        This satisfies:
        1. oprim.llm_complete (expects coroutine or awaitable)
        2. oskill.script_writer (calls it sync and then calls .get() on result)
        """
        def __init__(self, **kwargs: Any):
            # Ensure result_format is message for consistent parsing
            kwargs["result_format"] = "message"
            # oskill.script_writer provides messages, we need to pass it to dashscope.Generation.call
            # raw_dashscope is a function that calls Generation.call
            self._resp = raw_dashscope(**kwargs)
            # Convert DashScope response to dict if it's an object
            if not isinstance(self._resp, dict):
                self._resp = dict(self._resp)
                
            choices = self._resp.get("output", {}).get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "")
                # Map DashScope 'message' format to oprim 'content' format
                self._resp["content"] = text
        
        def __await__(self) -> Any:
            # Make it awaitable for oprim.llm_complete
            async def _dummy():
                return self._resp
            return _dummy().__await__()
            
        def get(self, key: str, default: Any = None) -> Any:
            # Provide .get() for oskill.script_writer (sync use case)
            return self._resp.get(key, default)
            
        def __getitem__(self, key: str) -> Any:
            return self._resp[key]

    # Register the adapter as the default LLM
    ProviderRegistry.register("llm", "default", AsyncDashScopeAdapter, replace=True)

    # 2. Video Providers
    ProviderRegistry.register(
        "video", "ltx2_cloud", ltx2_cloud_generate
    )
    ProviderRegistry.register(
        "video",
        "wan_cloud",
        lambda **kwargs: video_generate(
            provider="wan_cloud", **kwargs
        ),
    )

    # 3. Audio Providers
    ProviderRegistry.register(
        "audio", "vibevoice", vibevoice_synthesize
    )
    ProviderRegistry.register(
        "audio",
        "duix",
        lambda **kwargs: avatar_generate(
            provider="duix", **kwargs
        ),
    )
