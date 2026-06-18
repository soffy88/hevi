from __future__ import annotations

import logging
from typing import Any

import oprim.providers.dashscope as dashscope
from obase.provider_registry import ProviderRegistry
from oprim import avatar_generate, ltx2_cloud_generate, vibevoice_synthesize, video_generate

__all__ = ["ProviderRegistry", "register_all_providers"]

logger = logging.getLogger(__name__)


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup."""
    # 0. Patch Main Library Bugs (pending owner RFC)
    try:
        import oprim._providers.wan_cloud as wan_cloud_mod
        _orig_wan_invoke = wan_cloud_mod.invoke

        async def _patched_wan_invoke(*args: Any, **kwargs: Any) -> Any:
            # SaaS-3 Fix: oprim 3.6.1 uses broken defaults for Wan 2.1
            # 1. Correct the endpoint URL
            kwargs["base_url"] = (
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
                "video-generation/video-synthesis"
            )
            # 2. Correct the model name
            if "model" not in kwargs or kwargs.get("model") == "wanx2.6-t2v-turbo":
                kwargs["model"] = "wanx2.1-t2v-turbo"
            
            # 3. Filter unsupported arguments (like 'fps') passed by video_generate
            supported = {
                "mode", "prompt", "reference_image", "output_path", "api_key",
                "base_url", "model", "poll_interval_s", "timeout_s"
            }
            filtered = {k: v for k, v in kwargs.items() if k in supported}
            return await _orig_wan_invoke(*args, **filtered)

        wan_cloud_mod.invoke = _patched_wan_invoke
        logger.info("Main library bug patched: oprim.wan_cloud.invoke (model/args fix)")
    except Exception as e:
        logger.error(f"Failed to patch main library: {e}")

    # 1. LLM Providers (for agentic orchestration)
    dashscope.register(replace=True)

    # SaaS-3/P10.F3 Fix: oprim's native DashScope SDK raises 400 "Access denied" due to
    # account billing restrictions on the native endpoint. The OpenAI-compatible endpoint
    # does NOT have this restriction. We route all LLM calls through it.
    import os as _os

    import httpx as _httpx

    def _compat_llm_call(**kwargs: Any) -> dict[str, Any]:
        """Call DashScope via OpenAI-compatible REST endpoint (bypasses native SDK billing block)."""
        api_key = _os.getenv("DASHSCOPE_API_KEY", "")
        payload = {
            "model": kwargs.get("model") or "qwen-plus",
            "messages": kwargs.get("messages", []),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        r = _httpx.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
        data = r.json()
        # Adapt OpenAI-compatible format → native DashScope format expected by AsyncDashScopeAdapter
        oa_choices = data.get("choices", [])
        native_choices = [
            {"message": c.get("message", {}), "finish_reason": c.get("finish_reason", "")}
            for c in oa_choices
        ]
        return {"output": {"choices": native_choices}, "usage": data.get("usage", {})}

    class AsyncDashScopeAdapter:
        """Adapter that behaves like a coroutine but has a .get() method.

        Satisfies oprim.llm_complete (async) and oskill.script_writer (sync + .get()).
        Includes robust JSON coercion to satisfy Pydantic models in oskill.
        """
        def __init__(self, **kwargs: Any):
            kwargs.pop("result_format", None)
            resp = _compat_llm_call(**kwargs)
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
                                    elif k in ("importance", "index", "scene_index"):
                                        if isinstance(v, (int, float)):
                                            res[k] = int(round(v))
                                        elif isinstance(v, str):
                                            vl = v.lower()
                                            if vl in ("low", "minor"): res[k] = 1
                                            elif vl in ("medium", "normal"): res[k] = 2
                                            elif vl in ("high", "major"): res[k] = 3
                                            elif vl in ("critical", "extreme"): res[k] = 4
                                            else:
                                                try: res[k] = int(v)
                                                except ValueError: res[k] = 0
                                        else: res[k] = 0
                                    # 3. Handle list fields like 'scenes' or 'shots'
                                    elif k in ("scenes", "shots") and isinstance(v, list):
                                        res[k] = []
                                        for i, item in enumerate(v):
                                            if isinstance(item, str):
                                                field_name = "visual_description" if k == "scenes" else "narration"
                                                res[k].append({"id": str(i + 1), field_name: item})
                                            else:
                                                res[k].append(_coerce_fields(item))
                                    # 4. Handle None/null values (fix for Path(None) crash)
                                    elif v is None:
                                        res[k] = ""
                                    else:
                                        res[k] = _coerce_fields(v)
                                return res
                            elif isinstance(obj, list):
                                return [_coerce_fields(i) for i in obj]
                            elif obj is None:
                                return ""
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
        "video",
        "ltx2_cloud",
        lambda **kwargs: ltx2_cloud_generate(
            mode=kwargs.pop("mode", "t2v"),
            duration_s=kwargs.pop("duration_s", 5.0),
            resolution=kwargs.pop("resolution", (1080, 1920)),
            **kwargs
        ),
    )
    ProviderRegistry.register(
        "video",
        "wan_cloud",
        lambda **kwargs: video_generate(
            provider="wan_cloud", **kwargs
        ),
    )

    # 0.1 Chaos Monkey Overrides (SaaS-3 / P10.F3 fallback verification)
    import os
    if os.getenv("HEVI_CHAOS_FAIL_LTX2") == "true":
        async def failing_ltx2(**kwargs: Any) -> Any:
            raise RuntimeError("Chaos Monkey: LTX2 failure injected")
        ProviderRegistry.register("video", "ltx2_cloud", failing_ltx2, replace=True)
        logger.warning("Chaos Monkey ACTIVE: ltx2_cloud will fail.")

    if os.getenv("HEVI_CHAOS_FAIL_WAN") == "true":
        async def failing_wan(**kwargs: Any) -> Any:
            raise RuntimeError("Chaos Monkey: Wan failure injected")
        ProviderRegistry.register("video", "wan_cloud", failing_wan, replace=True)
        logger.warning("Chaos Monkey ACTIVE: wan_cloud will fail.")

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
