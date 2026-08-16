"""NVIDIA NIM LLM provider(研究模型专用,2 KEY 轮换)。

背景:explainer research 单次生成 max_tokens 可达 8000,原 default(DashScope
qwen-plus)在 registry.py 里硬编码 120s 超时,长研究任务经常整单
"研究模型调用失败: timed out"。NIM 云端快且密钥池现成(stratum
aii/.pipeline_keys.json 有 8 个命名 key),这里取其中 2 个轮换使用:

- 每次调用换下一个 key(round-robin),分摊免费层 40 req/min/key 限流;
- 单次调用失败(429/5xx/超时/空 content)自动用另一个 key 重试一次;
- 每个 key 独立时间槽限流(HEVI_NIM_RPM),防跨进程共用 key 撞 429。

研究入口 research._default_llm() 优先取 llm("nim"),未注册时回落 default。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NIM_BASE = "https://integrate.api.nvidia.com/v1/chat/completions"

# stratum 飞轮共用密钥池(命名槽位),见 /data/soffy/projects/stratum/aii/.pipeline_keys.json
_PIPELINE_KEYS_CANDIDATES = (
    Path("/data/soffy/projects/stratum/aii/.pipeline_keys.json"),
)

DEFAULT_NIM_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

# 实测选型(2026-08-03,研究 JSON 任务):
# - meta/llama-3.1-70b-instruct: content 稳定但 ~11 tok/s,8000 token 大纲单次
#   ~10 分钟,共享 key 拥堵时 300s 内必再超时(实测 ReadTimeout);
# - meta/llama-3.1-8b-instruct: ~200 tok/s 但研究深度/JSON 质量差;
# - nvidia/llama-3.3-nemotron-super-49b-v1.5: 单次完整研究实测 195s 出稿,
#   质量接近 70b(与 stratum 全局 NIM_MODEL 默认一致)。偶发 content=None
#   (reasoning 模型特性)由双 key 轮换重试兜底;仍不放心可 HEVI_NIM_MODEL 覆盖。


def _load_pipeline_keys() -> dict[str, str]:
    """读 stratum 密钥池。找不到返回 {}。"""
    # env 指定路径每次调用时动态解析(便于测试/部署覆盖)
    candidates = [Path(os.environ.get("HEVI_PIPELINE_KEYS", ""))]
    candidates.extend(_PIPELINE_KEYS_CANDIDATES)
    for p in candidates:
        try:
            if p.exists():
                raw = json.loads(p.read_text())
                return {k: str(v).strip() for k, v in raw.items() if str(v).strip()}
        except Exception as exc:  # pragma: no cover - depends on deployment
            logger.debug("NIM 密钥池读取失败 %s: %s", p, exc)
    return {}


def _nim_keys() -> list[str]:
    """选定轮换用的 key 列表(优先取 2 个,池不足则用现有)。

    优先级:HEVI_NIM_KEYS(逗号分隔,字面 key)> HEVI_NIM_KEY_NAMES(池中槽位名)
    > 池文件前两个不同 key > NVIDIA_NIM_API_KEY。
    """
    env_keys = os.getenv("HEVI_NIM_KEYS", "").strip()
    if env_keys:
        return [k.strip() for k in env_keys.split(",") if k.strip()]

    pool = _load_pipeline_keys()
    names = [n.strip() for n in os.getenv("HEVI_NIM_KEY_NAMES", "").split(",") if n.strip()]
    picked: list[str] = []
    if names:
        picked = [pool[n] for n in names if n in pool]
    if not picked:
        # 未指定名字,或指定槽位全部缺失 → 回落到池默认(前两个不同 key)
        picked = list(dict.fromkeys(pool.values()))
    picked = picked[:2] if len(picked) > 2 else picked

    env_key = os.getenv("NVIDIA_NIM_API_KEY", "").strip()
    if env_key and env_key not in picked:
        picked.append(env_key)
    return picked


def _make_nim_caller(
    keys: list[str],
    *,
    model: str = DEFAULT_NIM_MODEL,
    rpm: float = 36.0,
    timeout: float = 600.0,
    fallback_model: str | None = None,
) -> Any:
    """返回 omodul 约定的 async LLM caller(messages/max_tokens 等 kwargs → dict)。

    返回 dict 形状 {"content": "<text>"},与 research._llm_json 的
    response.get("content") 约定一致。单次调用失败自动换另一个 key 重试一次;
    两个 key 都返回空 content(reasoning 模型偶发 content=None)时,兜底用
    fallback_model(默认 llama-3.1-8b-instruct,内容稳定且快)再试一次。
    """
    if not keys:
        raise ValueError("NIM caller 需要至少 1 个 key")
    if fallback_model is None:
        fallback_model = os.getenv("HEVI_NIM_FALLBACK_MODEL", "meta/llama-3.1-8b-instruct") or None
    _client = httpx.Client(trust_env=True, timeout=timeout)
    _min_int = (60.0 / rpm) if rpm > 0 else 0.0
    _rl_lock = threading.Lock()
    _rl_next = [0.0] * len(keys)  # 每 key 独立时间槽(免费层 40 req/min/key)
    _counter = [0]

    def _throttle(idx: int) -> None:
        if not _min_int:
            return
        with _rl_lock:
            start = max(time.monotonic(), _rl_next[idx])
            _rl_next[idx] = start + _min_int
        w = start - time.monotonic()
        if w > 0:
            time.sleep(w)

    def _call_with_rotation(payload: dict[str, Any]) -> str:
        """按轮换序尝试 ≤2 个 key:429 直接换 key 不耗尝试次数,其余异常换 key 重试一次。"""
        start = _counter[0] % len(keys)
        _counter[0] += 1
        attempts = min(len(keys), 2)
        last_err: Exception | None = None
        for i in range(attempts):
            idx = (start + i) % len(keys)
            _throttle(idx)
            try:
                resp = _client.post(
                    NIM_BASE,
                    headers={
                        "Authorization": f"Bearer {keys[idx]}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code == 429 and i < attempts - 1:
                    # 限流是瞬时的(跨进程共用 key 常撞),等窗口后换下一个 key
                    wait = float(resp.headers.get("retry-after", 0)) or 3.0
                    time.sleep(min(wait, 20.0))
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                if content is None or not str(content).strip():
                    # nemotron-super 等 reasoning 模型偶发 content=null
                    raise RuntimeError("NIM 返回空 content")
                return str(content)
            except Exception as exc:
                last_err = exc
        # 双 key 都返回空 content(reasoning 模型偶发 content=None)→ 兜底模型重试一次
        if (
            fallback_model
            and isinstance(last_err, RuntimeError)
            and "空 content" in str(last_err)
        ):
            logger.warning("NIM 主模型空 content,兜底 %s 重试", fallback_model)
            try:
                idx = start % len(keys)
                _throttle(idx)
                resp = _client.post(
                    NIM_BASE,
                    headers={
                        "Authorization": f"Bearer {keys[idx]}",
                        "Content-Type": "application/json",
                    },
                    json=dict(payload, model=fallback_model),
                )
                resp.raise_for_status()
                content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content")
                if content and str(content).strip():
                    return str(content)
            except Exception as exc:
                last_err = exc
        raise last_err or RuntimeError("NIM 调用失败")

    async def _call_async(
        messages: list[dict[str, str]] | None = None,
        *,
        system: str = "",
        max_tokens: int = 4096,
        result_format: str | None = None,
        temperature: float | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        parts = [system] if system else []
        parts.extend(
            str(msg.get("content", ""))
            for msg in messages or []
            if isinstance(msg, dict) and msg.get("role") == "user"
        )
        combined = "\n\n".join(p for p in parts if p)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": combined}],
            "max_tokens": max_tokens,
            "temperature": temperature if temperature is not None else 0.4,
        }
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            text = await loop.run_in_executor(ex, _call_with_rotation, payload)
        return {"content": text}

    return _call_async


def register_nim_llm() -> None:
    """注册 llm("nim")。没有可用 key 时静默跳过,research 会回落 default。"""
    from obase.provider_registry import ProviderRegistry

    keys = _nim_keys()
    if not keys:
        logger.warning(
            "NIM 研究 LLM 未注册:无可用 key(检查 stratum aii/.pipeline_keys.json "
            "或设置 HEVI_NIM_KEYS/HEVI_NIM_KEY_NAMES)"
        )
        return
    model = os.getenv("HEVI_NIM_MODEL", os.getenv("NIM_MODEL", DEFAULT_NIM_MODEL))
    timeout = float(os.getenv("HEVI_NIM_TIMEOUT", "600"))
    rpm = float(os.getenv("HEVI_NIM_RPM", "36"))
    caller = _make_nim_caller(keys, model=model, rpm=rpm, timeout=timeout)
    ProviderRegistry.register("llm", "nim", caller, replace=True)
    logger.info("NIM 研究 LLM registered: %s (轮换 key=%d 个)", model, len(keys))
