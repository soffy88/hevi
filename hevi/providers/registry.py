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


def _coerce_llm_json_text(text: str) -> str:
    """SaaS-2/P10.F2 Fix:纠正 LLM 回复里常见的 JSON 形状漂移(数字 ID 该是字符串、
    scenes/shots 该是字典列表却给了字符串列表、null 值),满足 oskill 里 pydantic
    模型的校验。原是 `AsyncDashScopeAdapter.__init__` 内的私有闭包,只喂给 "default"
    (公共 DashScope)。`_qwen_cloud_llm`(阿里云百炼 workspace 端点)接的是同一套
    oskill 消费方(script_writer/storyboard_planner),回复一样会漂移形状,故抽成
    共用函数——两边都用同一套纠正,而不是只修一边。任何失败都原样返回 text,不阻断。
    """
    import json
    import re

    try:
        clean_text = text.strip()
        if clean_text.startswith("```"):
            match = re.search(r"```(?:json)?\n?(.*?)\n?```", clean_text, re.DOTALL)
            if match:
                clean_text = match.group(1).strip()

        json_match = re.search(r"(\{.*\}|\[.*\])", clean_text, re.DOTALL)
        if not json_match:
            return text
        data = json.loads(json_match.group(1))

        def _coerce_fields(obj: Any) -> Any:
            if isinstance(obj, dict):
                res: dict[str, Any] = {}
                for k, v in obj.items():
                    is_id = k.endswith("_id") or k == "id"
                    if is_id and isinstance(v, (int, float)):
                        res[k] = str(v)
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
                    elif k in ("scenes", "shots") and isinstance(v, list):
                        fld = "visual_description" if k == "scenes" else "narration"
                        res[k] = []
                        for i, item in enumerate(v):
                            if isinstance(item, str):
                                res[k].append({"id": str(i + 1), fld: item})
                            else:
                                res[k].append(_coerce_fields(item))
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

        return json.dumps(_coerce_fields(data), ensure_ascii=False)
    except Exception as e:
        logger.debug(f"LLM Coercion failed: {e}")
        return text


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup."""
    # 0. Patch Main Library Bugs (pending owner RFC)
    # [B1 已回迁 oprim v3.11.0:wan_cloud 默认值(endpoint/model)+ 不支持参数过滤已在
    #  上游修复,原 _patched_wan_invoke 猴补丁删除。]

    from hevi.audio.vibevoice_patch import (
        patch_vibevoice_exports,
        patch_vibevoice_reference_audio_kwarg,
    )

    patch_vibevoice_exports()
    patch_vibevoice_reference_audio_kwarg()

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

    def _make_sync_llm_adapter(call_fn: Any) -> type:
        """工厂:给一个同步 HTTP 调用函数(签名同 `_compat_llm_call`),生产一个满足
        oskill 两种调用约定的适配器类。

        oskill.storyboard_planner/shot_generator 同步调用 LLM:
            result = llm(messages=...)        # sync call(构造实例即已发出请求)
            content = result.get("content")  # sync .get()
        其余 oskill 调用方用 `await llm(...)`。两条约定都要满足,故实例要同时支持
        `__await__` + `.get()`——`AsyncDashScopeAdapter`("default")和 `qwen_cloud`
        （之前误注册成 plain async 函数,只满足 await 一条,shot_generator 走 sync
        调用时会拿到未执行的 coroutine)都走这个工厂,不重复实现三份一样的壳。
        """

        class _SyncLLMAdapter:
            def __init__(self, **kwargs: Any):
                kwargs.pop("result_format", None)
                resp = call_fn(**kwargs)
                if not isinstance(resp, dict):
                    resp = dict(resp)

                choices = resp.get("output", {}).get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", "")
                    text = _coerce_llm_json_text(text)
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

        return _SyncLLMAdapter

    AsyncDashScopeAdapter = _make_sync_llm_adapter(_compat_llm_call)
    ProviderRegistry.register("llm", "default", AsyncDashScopeAdapter, replace=True)

    # 1.0.1 云 qwen(阿里云百炼 workspace 专属端点,非欠费)——通鉴 cloud_avatar 管道的 LLM。
    # 公共 dashscope.aliyuncs.com 那把 DASHSCOPE_API_KEY 账户欠费,只有 workspace(ALIBABA_MAAS_*)
    # 的 compatible-mode 端点可用(2026-07-10 端到端验证过)。qwen-plus 出剧本质量远好于本地 llama3.2。
    def _compat_llm_call_maas(**kwargs: Any) -> dict[str, Any]:
        """Call ALIBABA_MAAS workspace 专属端点(同步,同 `_compat_llm_call` 约定)。"""
        host = _os.getenv("ALIBABA_MAAS_HOST", "")
        key = _os.getenv("ALIBABA_MAAS_API_KEY", "")
        payload = {
            "model": kwargs.get("model") or "qwen-plus",
            "messages": kwargs.get("messages", []),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        r = _httpx.post(
            f"https://{host}/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        oa_choices = data.get("choices", [])
        native_choices = [
            {"message": c.get("message", {}), "finish_reason": c.get("finish_reason", "")}
            for c in oa_choices
        ]
        return {"output": {"choices": native_choices}, "usage": data.get("usage", {})}

    AsyncQwenCloudAdapter = _make_sync_llm_adapter(_compat_llm_call_maas)
    ProviderRegistry.register("llm", "qwen_cloud", AsyncQwenCloudAdapter, replace=True)

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

    # HEVI-EXEC-01 §0:视频生成主通道(Reference-to-Video,animated 强项)。
    from hevi.video.vidu_service import vidu_reference_to_video

    ProviderRegistry.register("video", "vidu", vidu_reference_to_video, replace=True)

    # WaveSpeed AI(阿里模型聚合网关)—— HappyHorse 1.1 / Wan 2.7 文生视频。
    from hevi.video.wavespeed_service import (
        happyhorse_1_1_generate,
        happyhorse_1_1_reference_to_video,
        wan_2_7_generate,
    )

    ProviderRegistry.register("video", "happyhorse_1_1", happyhorse_1_1_generate, replace=True)
    ProviderRegistry.register("video", "wan_2_7", wan_2_7_generate, replace=True)
    # 单独一个 provider 名——跟上面的 t2v 版本调用约定不同(吃 reference_images,
    # 跟 vidu 同一层级),不能共用 "happyhorse_1_1" 这个名字。
    ProviderRegistry.register(
        "video", "happyhorse_1_1_ref", happyhorse_1_1_reference_to_video, replace=True
    )

    # 阿里云百炼(Model Studio)业务空间专属域名 —— 同样是 HappyHorse 1.1 / Wan 2.7,
    # 但走阿里官方直连(而非 WaveSpeed 转售),见 alibaba_maas_service.py 顶部的排错
    # 记录。名字加 _maas 后缀,不跟上面 WaveSpeed 版本的 "happyhorse_1_1"/"wan_2_7"
    # 混用——两者密钥/host 配置完全不同,选错了会打到错的账号上。
    from hevi.video.alibaba_maas_service import (
        happyhorse_1_1_maas_generate,
        happyhorse_1_1_maas_lock_generate,
        happyhorse_1_1_maas_reference_to_video,
        wan_2_7_maas_generate,
    )

    ProviderRegistry.register(
        "video", "happyhorse_1_1_maas", happyhorse_1_1_maas_generate, replace=True
    )
    ProviderRegistry.register("video", "wan_2_7_maas", wan_2_7_maas_generate, replace=True)
    ProviderRegistry.register(
        "video",
        "happyhorse_1_1_maas_ref",
        happyhorse_1_1_maas_reference_to_video,
        replace=True,
    )
    # 主线管线(create_episode/Series/orchestrate_longvideo)专用——单张 reference_image
    # 约定,见 happyhorse_1_1_maas_lock_generate 顶部注释。
    ProviderRegistry.register(
        "video",
        "happyhorse_1_1_maas_lock",
        happyhorse_1_1_maas_lock_generate,
        replace=True,
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

    # 4.1 json2video 云端场景底图(仅供 L6 generate_scene_assets 无角色镜头用,本地 GPU
    # 不可用时手动切换;不注册成 default——有角色的镜头必须走 sdxl_local 的 IP-Adapter
    # 一致性条件化,见 hevi/image/json2video_scene_service.py 模块 docstring)。
    from hevi.image.json2video_scene_service import json2video_scene_generate

    ProviderRegistry.register(
        "image_gen", "json2video_scene", json2video_scene_generate, replace=True
    )

    # 5. VLM provider (L5 tongjian 年代审 + 3O §C2 mllm 双变体一致性,复用同一个本地
    # qwen2.5vl adapter;之前只在 longvideo_orchestrator 里临时注入,这里注册成全局
    # 默认,让 tongjian 也能走 ProviderRegistry.get().vlm("default") 同款惯例。
    from hevi.providers.local_qwen_vl_adapter import local_qwen_vl_adapter, vl_model_available

    if vl_model_available():
        ProviderRegistry.register("vlm", "default", local_qwen_vl_adapter, replace=True)
        logger.info("VLM provider: local_qwen_vl_adapter (qwen2.5vl via ollama)")
    else:
        logger.warning("VLM provider: 本地 qwen2.5vl 不可用,vlm/default 未注册")
