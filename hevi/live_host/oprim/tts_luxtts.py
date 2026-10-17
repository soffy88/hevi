"""LuxTTS 引擎 TTS 原子（HTTP 委托 tailnet 上的 LuxTTS 服务，可选热切换）。

LuxTTS 是 zipvoice 架构的轻量克隆 TTS（4 步采样 / 48kHz / 标称 150× 实时）。
赛博小雅是女声：默认音色 ``soffy``；服务侧 ``auto`` 会把中文路由到 ``soffy``。
小雅候选里 **不含** ``en_male``（男声，仅评测记录）。

设计约束（与 oprim 其它引擎一致）：
* **Opt-in, default off.** 经 ``EngineConfig.tts="luxtts"`` + registry 选择启用，
  默认引擎仍是 piper，不改默认直播配置。
* **不可达自动回退。** 服务探活失败或合成失败时，``synthesize`` 抛错由上层
  ``skill_speak`` 兜底；若要"自动回退到现有默认 TTS"，用 ``LuxTTSWithFallback``
  包一层 —— 它在构造期记录一个 fallback 引擎（通常为 piper），调用出错时代合。
* **可流式则按句。** 服务返回完整 wav；调用方本就越句调用（skill_speak 逐句），
  无需额外切分。``speed`` 映射到服务端语速。

环境变量：
  ``HEVI_LIVE_LUXTTS_URL``    服务根地址（默认 http://100.119.113.90:8795）
  ``HEVI_LIVE_LUXTTS_VOICE``  默认音色（默认 soffy，女声）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from hevi.live_host.schemas import Engine

logger = logging.getLogger(__name__)

# tailnet 上的用户自建 LuxTTS 服务（赛博小雅 / 善学记英文陪练调用方）。
DEFAULT_BASE_URL = "http://100.119.113.90:8795"
DEFAULT_VOICE = "soffy"  # 女声；auto 会按语种在服务端路由到 soffy/en_male

# ⚠️ tailnet IP 必须 trust_env=False：宿主机 env 里的 http_proxy（本机 7890）
# 会把 100.x 请求吃掉返回 502。no_proxy 虽写了 100.64.0.0/10 CIDR，但 httpx
# 只按主机名后缀匹配、不解析 CIDR 段，所以必须显式绕开 proxy。
# 直播宿主进程继承同样 env，此坑线上必踩。


class LuxTTS(Engine):
    """HTTP 委托 LuxTTS 服务把文本合成 wav。"""

    name = "luxtts"

    def __init__(
        self,
        base_url: str | None = None,
        voice: str | None = None,
        *,
        speed: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("HEVI_LIVE_LUXTTS_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self.voice = voice or os.getenv("HEVI_LIVE_LUXTTS_VOICE") or DEFAULT_VOICE
        self.speed = speed
        self.timeout = timeout

    # -- 可用性 --------------------------------------------------------
    def available(self) -> bool:
        """探活 /health。不可达（tailnet 断开/服务停）返回 False，供上层降级。"""
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=5.0, trust_env=False)
            return r.status_code == 200 and bool(r.json().get("ok"))
        except Exception:  # noqa: BLE001 - 探活失败不应影响默认引擎
            return False

    # -- 合成 ----------------------------------------------------------
    def synthesize(self, text: str, output_path: str | Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"text": text, "voice": self.voice, "speed": self.speed}
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            resp = client.post(f"{self.base_url}/tts", json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"LuxTTS 合成失败 HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.content
        if not data:
            raise RuntimeError(f"LuxTTS 未产出音频: {out}")
        out.write_bytes(data)
        return out


class LuxTTSWithFallback(Engine):
    """包一层：LuxTTS 优先，不可达/失败自动回退到 fallback 引擎（通常 piper）。

    默认直播配置仍走 piper；只有显式选中 luxtts 且服务不可达时才代合，保证
    直播不中断。回退发生时记 WARNING（不刷屏）。
    """

    name = "luxtts_fallback"

    def __init__(self, primary: LuxTTS, fallback: Engine, *, retry_health: bool = True) -> None:
        self.primary = primary
        self.fallback = fallback
        self._retry_health = retry_health
        self._primary_ok: bool | None = None  # None=未探测 / True=可用 / False=已回退

    def available(self) -> bool:
        return self.fallback.available() or self.primary.available()

    def _probe(self) -> bool:
        if self._primary_ok is None or self._retry_health:
            self._primary_ok = self.primary.available()
        return self._primary_ok

    def synthesize(self, text: str, output_path: str | Path) -> Path:
        if self._probe():
            try:
                return self.primary.synthesize(text, output_path)
            except Exception as exc:  # noqa: BLE001 - 合成期抖动也回退
                logger.warning("LuxTTS 合成失败，回退 %s: %s", self.fallback.name, exc)
                self._primary_ok = False
        else:
            logger.warning("LuxTTS 不可达，使用回退引擎 %s", self.fallback.name)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # 回退引擎可能写出别的扩展名/残留；清掉旧文件再让 fallback 生成
        if out.exists():
            out.unlink()
        return self.fallback.synthesize(text, output_path)
