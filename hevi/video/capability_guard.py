from dataclasses import dataclass

from obase.provider_registry import ProviderRegistry

__all__ = ["PROVIDER_LIMITS", "CapabilityError", "ProviderLimits", "validate_request"]


class CapabilityError(ValueError):
    """Raised when a request exceeds a provider's declared capability."""


@dataclass(frozen=True)
class ProviderLimits:
    modes: frozenset[str]
    max_resolution: tuple[int, int]  # (width, height)
    max_duration_s: float
    fps_options: frozenset[int]


PROVIDER_LIMITS: dict[str, ProviderLimits] = {
    "ltx2_cloud": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(2160, 3840),
        max_duration_s=300.0,
        fps_options=frozenset({24, 30}),
    ),
    "wan_cloud": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=120.0,
        fps_options=frozenset({24, 30}),  # kernel 对 high 档传 30fps
    ),
    # 本地 wan2.1-1.3B: 原生 480p@16fps,但内核按朝向夹取 + 装配器可缩放到目标,
    # 故接受目标分辨率(上采样)与 16/24/30 目标帧率;单片时长上限 ~10s。
    # i2v 经 VACE 参考条件化支持(RFC-002 item 1)。
    "wan_local": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(2160, 3840),
        max_duration_s=10.0,
        fps_options=frozenset({16, 24, 30}),
    ),
    "ltx2_local": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(2160, 3840),
        max_duration_s=10.0,
        fps_options=frozenset({16, 24, 30}),
    ),
    # 高写实云档(fal)。这些 provider 已在 registry 注册但此前无能力声明,
    # 导致能力矩阵只覆盖 4/7 provider。此处补齐 —— 值为近似上限(fal 内部管理实际
    # 编码;非路由消费前不生效),待 L0 成本感知路由落地时按 fal 文档校准。
    # 注:oprim 现注册的是 t2v 原语;三者上游均有 i2v 端点,但 hevi 未接线,故声明 t2v。
    "veo3": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=8.0,  # veo3/fast 固定 8s
        fps_options=frozenset({24, 30}),
    ),
    "kling_v2": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=10.0,  # v2 master 支持 5s/10s
        fps_options=frozenset({24, 30}),
    ),
    "hailuo": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=10.0,  # 海螺02 standard 支持 6s/10s
        fps_options=frozenset({24, 30}),
    ),
}


async def validate_request(
    *,
    provider: str,
    mode: str,
    resolution: tuple[int, int],
    duration_s: float,
    fps: int,
) -> None:
    """Validate a video-generation request against provider capability limits.

    Checks obase-registered capability tags first; falls back to PROVIDER_LIMITS.
    Raises CapabilityError on any violation so invalid requests are caught before
    consuming an API call.
    """
    if provider not in PROVIDER_LIMITS:
        raise CapabilityError(f"Unknown provider: {provider!r}")

    limits = PROVIDER_LIMITS[provider]

    # Use obase-registered tags for mode check when available.
    # v0.15.8: capabilities() is an instance method, returns dict {modes: [...]} or {}.
    cap_meta = ProviderRegistry.get().capabilities(provider)
    registered_modes = cap_meta.get("modes", []) if cap_meta else []
    if registered_modes:
        if mode not in registered_modes:
            raise CapabilityError(
                f"Provider {provider!r} registered capabilities {registered_modes!r} "
                f"do not include mode {mode!r}"
            )
    elif mode not in limits.modes:
        raise CapabilityError(
            f"Provider {provider!r} does not support mode {mode!r} (supported: {set(limits.modes)})"
        )

    # 朝向无关的分辨率比较: 把请求与上限各自按长短边排序后逐边比较,
    # 这样 1280×720(横) 不会被 1080×1920(竖) 的上限误拒。
    req_long, req_short = sorted(resolution, reverse=True)
    max_long, max_short = sorted(limits.max_resolution, reverse=True)
    if req_long > max_long or req_short > max_short:
        raise CapabilityError(
            f"Resolution {resolution} exceeds {provider!r} max {limits.max_resolution}"
        )

    if duration_s > limits.max_duration_s:
        raise CapabilityError(
            f"Duration {duration_s}s exceeds {provider!r} max {limits.max_duration_s}s"
        )

    if fps not in limits.fps_options:
        raise CapabilityError(
            f"fps={fps} not in {provider!r} fps_options {set(limits.fps_options)}"
        )
