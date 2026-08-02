"""口型与音频同步驱动 — oskill 边界(3O §3 Task 3.2)。

HEVI 路线图 Phase3 #42 的 lip-sync 能力驱动。现状核实(2026-07):
hevi 里**没有任何 lip-sync 后处理实现**(hevi/cinematic/schemas.py 的
`lipsync_note` 明确标 "not implemented"),原生支持靠 provider 能力矩阵
(veo3 声明 lip_sync=True;happyhorse_1_1 声称支持但未经 API 契约证实)。

因此本驱动为**能力感知**实现:查询 ProviderRegistry 的 capability,决定
"走原生音画同步"还是"报告暂不支持(留后处理钩子)",不做虚假实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LipSyncUnsupported(RuntimeError):
    """请求的 provider 无原生 lip-sync,且后处理路径尚未实现。"""


@dataclass(frozen=True)
class LipSyncCapability:
    provider: str
    native: bool
    post_processing: bool = False  # 后处理路径(未来)未实现


def lip_sync_capability(provider: str) -> LipSyncCapability:
    """查询 provider 的 lip-sync 能力(经 ProviderRegistry capability 矩阵)。

    能力矩阵来源:hevi/video/capability_guard.py 的 PROVIDER_LIMITS(lip_sync 列)。
    查询失败(provider 未注册/能力未知)→ 保守返回 native=False。
    """
    try:
        from hevi.video.capability_guard import PROVIDER_LIMITS

        limits = PROVIDER_LIMITS.get(provider)
        if limits is not None:
            return LipSyncCapability(provider=provider, native=bool(limits.lip_sync))
    except Exception:
        pass
    return LipSyncCapability(provider=provider, native=False)


def ensure_lip_sync(provider: str, *, require: bool = True) -> LipSyncCapability:
    """供渲染编排层调用:require=True 且 provider 无 lip-sync → 抛 LipSyncUnsupported。

    编排层(如 tongjian avatar 管线)只把本驱动当作**能力门禁**,不对 provider
    调用注入任何参数——原生支持的 provider 自己处理音画同步,无需 hevi 介入。
    """
    cap = lip_sync_capability(provider)
    if require and not cap.native:
        raise LipSyncUnsupported(
            f"provider={provider!r} 无原生 lip-sync(后处理路径未实现,"
            "见 HEVI 路线图 Phase3 #42);请改用 veo3 等原生支持 provider"
        )
    return cap


def drive_lip_sync(provider: str, *, audio: Any, video: Any) -> dict[str, Any]:
    """口型驱动入口(未来后处理路径的挂载点)。

    当前仅承载能力门禁 + 原生 provider 直通;返回决策记录,供 decision_trail/
    可观测性消费。后处理 lip-sync 一旦实现,在此按 provider 分发。
    """
    cap = ensure_lip_sync(provider)
    return {
        "provider": provider,
        "mode": "native" if cap.native else "none",
        "audio": str(audio),
        "video": str(video),
        "note": "native audio-video sync (no post-processing lip-sync)",
    }
