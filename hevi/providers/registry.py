from __future__ import annotations

import logging
from typing import Any

import oprim.providers.dashscope as dashscope
from obase.provider_registry import ProviderRegistry
from oprim import avatar_generate, ltx2_cloud_generate

# oprim 3.10.37 added a facade submodule oprim/video_generate.py that shadows the
# function for static analysis; import the function from the facade explicitly.
from oprim.video_generate import video_generate

# SaaS-4 Fix: 音频走 hevi 子进程隔离版(退出即释放 ~8GB VRAM),而非 oprim 原生
# 主进程内加载 —— 后者与 ollama(qwen)/Wan2GP 抢 10GB 显存,是 wan_local
# "zombie: worker restarted" 的诱因。此版本还遵循 VIBEVOICE_MODEL_DIR。
from hevi.audio.tts_service import vibevoice_synthesize
from hevi.video.wan_local_service import wan_local_generate

__all__ = ["ProviderRegistry", "register_all_providers"]

logger = logging.getLogger(__name__)


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup."""
    # 0. Patch Main Library Bugs (pending owner RFC)
    # [B1 已回迁 oprim v3.11.0:wan_cloud 默认值(endpoint/model)+ 不支持参数过滤已在
    #  上游修复,原 _patched_wan_invoke 猴补丁删除。]

    try:
        # vibevoice PyPI 0.0.1 (the only release published) ships an empty
        # top-level __init__.py — the classes oprim._vibevoice_synthesize needs
        # only exist in submodules. Re-export them so `from vibevoice import
        # VibeVoiceForConditionalGenerationInference, VibeVoiceProcessor` works.
        import vibevoice
        from vibevoice.modular.modeling_vibevoice_inference import (
            VibeVoiceForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

        vibevoice.VibeVoiceForConditionalGenerationInference = (
            VibeVoiceForConditionalGenerationInference
        )
        vibevoice.VibeVoiceProcessor = VibeVoiceProcessor
        logger.info("Main library bug patched: vibevoice top-level exports (empty __init__.py)")
    except Exception as e:
        logger.error(f"Failed to patch vibevoice exports: {e}")

    # 1. LLM Providers (for agentic orchestration)
    dashscope.register(replace=True)

    # SaaS-3/P10.F3 Fix: oprim's native DashScope SDK raises 400 "Access denied" due to
    # account billing restrictions on the native endpoint. The OpenAI-compatible endpoint
    # does NOT have this restriction. We route all LLM calls through it.
    import os as _os

    import httpx as _httpx

    def _compat_llm_call(**kwargs: Any) -> dict[str, Any]:
        """Call DashScope via OpenAI-compatible REST endpoint."""
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
        """Sync-callable LLM adapter with async protocol and .get() fallback.

        oskill.storyboard_planner calls the LLM synchronously:
            result = llm(messages=...)        # sync call
            content = result.get("content")  # sync .get()
        All other oskill callers use `await llm(...)`.
        This adapter satisfies both patterns via __await__ + get().
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
                    json_match = re.search(r"(\{.*\}|\[.*\])", clean_text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                        data = json.loads(json_str)

                        def _coerce_fields(obj: Any) -> Any:
                            if isinstance(obj, dict):
                                res: dict[str, Any] = {}
                                for k, v in obj.items():
                                    # 1. Coerce IDs to string
                                    is_id = k.endswith("_id") or k == "id"
                                    if is_id and isinstance(v, (int, float)):
                                        res[k] = str(v)
                                    # 2. Coerce specific numeric fields to int (rounding if float)
                                    elif k in ("importance", "index", "scene_index"):
                                        if isinstance(v, (int, float)):
                                            res[k] = round(v)
                                        elif isinstance(v, str):
                                            vl = v.lower()
                                            if vl in ("low", "minor"):
                                                res[k] = 1
                                            elif vl in ("medium", "normal"):
                                                res[k] = 2
                                            elif vl in ("high", "major"):
                                                res[k] = 3
                                            elif vl in ("critical", "extreme"):
                                                res[k] = 4
                                            else:
                                                try:
                                                    res[k] = int(v)
                                                except ValueError:
                                                    res[k] = 0
                                        else:
                                            res[k] = 0
                                    # 3. Handle list fields like 'scenes' or 'shots'
                                    elif k in ("scenes", "shots") and isinstance(v, list):
                                        fld = "visual_description" if k == "scenes" else "narration"
                                        res[k] = []
                                        for i, item in enumerate(v):
                                            if isinstance(item, str):
                                                res[k].append({"id": str(i + 1), fld: item})
                                            else:
                                                res[k].append(_coerce_fields(item))
                                    # 4. Handle None/null values (fix for Path(None) crash)
                                    elif v is None:
                                        res[k] = ""
                                    else:
                                        res[k] = _coerce_fields(v)
                                return res
                            if isinstance(obj, list):
                                return [_coerce_fields(i) for i in obj]
                            if obj is None:
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
            async def _dummy() -> dict[str, Any]:
                return self._resp

            return _dummy().__await__()

        def get(self, key: str, default: Any = None) -> Any:
            return self._resp.get(key, default)

    ProviderRegistry.register("llm", "default", AsyncDashScopeAdapter, replace=True)

    # 1.1 Local LLM fallback — register LocalQwenAdapter as "local";
    # overrides "default" when HEVI_LLM_PROVIDER=qwen_local
    from hevi.providers.local_qwen_adapter import register_if_local

    register_if_local()

    # 2. Video Providers
    ProviderRegistry.register(
        "video",
        "ltx2_cloud",
        lambda **kwargs: ltx2_cloud_generate(
            mode=kwargs.pop("mode", "t2v"),
            duration_s=kwargs.pop("duration_s", 5.0),
            resolution=kwargs.pop("resolution", (1080, 1920)),
            **kwargs,
        ),
        replace=True,
    )
    ProviderRegistry.register(
        "video",
        "wan_cloud",
        lambda **kwargs: video_generate(provider="wan_cloud", **kwargs),
        replace=True,
    )
    ProviderRegistry.register("video", "wan_local", wan_local_generate, replace=True)

    # 高写实云 provider(fal):Veo3 / Kling v2 / 海螺 —— A2 已回迁 oprim v3.11.0,直接导入。
    from oprim import hailuo_generate, kling_v2_generate, veo3_generate

    ProviderRegistry.register("video", "veo3", veo3_generate, replace=True)
    ProviderRegistry.register("video", "kling_v2", kling_v2_generate, replace=True)
    ProviderRegistry.register("video", "hailuo", hailuo_generate, replace=True)

    # ltx2_local: 路由到 wan_local(本机无独立 LTX2 local 推理实现)
    ProviderRegistry.register("video", "ltx2_local", wan_local_generate, replace=True)

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
    # edge_tts:默认音频 provider(多语言云 TTS)。A1 已回迁 oprim v3.11.0,直接导入。
    from oprim import edge_tts_synthesize

    ProviderRegistry.register("audio", "edge_tts", edge_tts_synthesize, replace=True)
    ProviderRegistry.register("audio", "vibevoice", vibevoice_synthesize, replace=True)
    ProviderRegistry.register("audio", "cosyvoice", vibevoice_synthesize, replace=True)
    ProviderRegistry.register(
        "audio",
        "duix",
        lambda **kwargs: avatar_generate(
            provider="duix",
            portrait_image=kwargs["portrait_image"],
            audio_path=kwargs["audio_path"],
            output_path=kwargs["output_path"],
        ),
        replace=True,
    )

    # 4. Image-gen provider (L5 tongjian 角色卡参考图,本地 SDXL,subprocess 隔离)
    from hevi.image.sdxl_local_service import sdxl_local_generate

    ProviderRegistry.register("image_gen", "sdxl_local", sdxl_local_generate, replace=True)
    ProviderRegistry.register("image_gen", "default", sdxl_local_generate, replace=True)

    # 5. VLM provider (L5 tongjian 年代审 + 3O §C2 mllm 双变体一致性,复用同一个本地
    # qwen2.5vl adapter;之前只在 longvideo_orchestrator 里临时注入,这里注册成全局
    # 默认,让 tongjian 也能走 ProviderRegistry.get().vlm("default") 同款惯例。
    from hevi.providers.local_qwen_vl_adapter import local_qwen_vl_adapter, vl_model_available

    if vl_model_available():
        ProviderRegistry.register("vlm", "default", local_qwen_vl_adapter, replace=True)
        logger.info("VLM provider: local_qwen_vl_adapter (qwen2.5vl via ollama)")
    else:
        logger.warning("VLM provider: 本地 qwen2.5vl 不可用,vlm/default 未注册")
