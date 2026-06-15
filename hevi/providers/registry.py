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
        
        Satisfies oprim.llm_complete (async) and oskill.script_writer (sync + .get()).
        Includes robust JSON coercion to satisfy Pydantic models in oskill.
        """
        def __init__(self, **kwargs: Any):
            kwargs["result_format"] = "message"
            resp = raw_dashscope(**kwargs)
            if not isinstance(resp, dict):
                resp = dict(resp)
                
            choices = resp.get("output", {}).get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "")
                
                # SaaS-2/P10.F2 Fix: Coerce numeric IDs and string-list scenes
                import json
                import re
                try:
                    # 1. Strip Markdown code blocks if present
                    clean_text = text.strip()
                    if clean_text.startswith("```"):
                        # Extract content between first and last ```
                        match = re.search(r"```(?:json)?\n?(.*?)\n?```", clean_text, re.DOTALL)
                        if match:
                            clean_text = match.group(1).strip()

                    # 2. Coerce numeric IDs and list fields
                    json_match = re.search(r'(\{.*\}|\[.*\])', clean_text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                        data = json.loads(json_str)
                        
                        def _coerce_fields(obj: Any) -> Any:
                            if isinstance(obj, dict):
                                res = {}
                                for k, v in obj.items():
                                    # 1. Coerce IDs to string
                                    if (k.endswith("_id") or k == "id") and isinstance(v, (int, float)):
                                        res[k] = str(v)
                                    # 2. Coerce specific numeric fields to int (rounding if float)
                                    elif k in ("importance", "index", "scene_index") and isinstance(v, (int, float)):
                                        res[k] = int(round(v))
                                    # 3. Handle list fields like 'scenes' or 'shots'
                                    elif k in ("scenes", "shots") and isinstance(v, list):
                                        res[k] = []
                                        for i, item in enumerate(v):
                                            if isinstance(item, str):
                                                # Convert string item to dict
                                                field_name = "visual_description" if k == "scenes" else "narration"
                                                res[k].append({
                                                    "id": str(i + 1), # Fallback id
                                                    field_name: item
                                                })
                                            else:
                                                res[k].append(_coerce_fields(item))
                                    else:
                                        res[k] = _coerce_fields(v)
                                return res
                            elif isinstance(obj, list):
                                return [_coerce_fields(i) for i in obj]
                            return obj

                        coerced = _coerce_fields(data)
                        text = json.dumps(coerced, ensure_ascii=False)
                except Exception as e:
                    logger.debug(f"LLM Coercion failed: {e}")

                self._resp = resp
                self._resp["content"] = text
            else:
                self._resp = resp
        
        def __await__(self) -> Any:
            async def _dummy():
                return self._resp
            return _dummy().__await__()
            
        def get(self, key: str, default: Any = None) -> Any:
            return self._resp.get(key, default)
            
        def __getitem__(self, key: str) -> Any:
            return self._resp[key]

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
