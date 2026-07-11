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
    # HEVI 路线图 Phase2 #35:能力矩阵补列。native_audio/lip_sync 只在有真实依据时
    # 标 True(见各条目旁注引用的具体证据),不是按"看起来应该支持"猜的。
    native_audio: bool = False
    lip_sync: bool = False
    # 能力声明最后核实的日期——provider 会悄悄换模型版本/降配额,这张表不该被
    # 一直信任到 403 才发现过期(HEVI 路线图 §3.1)。这次审的都标今天。
    last_verified: str = "2026-07-09"


PROVIDER_LIMITS: dict[str, ProviderLimits] = {
    # native_audio=True:hevi 自己的 audio_provider 枚举里就有 "ltx2_native"
    # (hevi/audio/audio_config.py)专门表示"LTX-2 内核已含原生音视频,音频层不用
    # 再处理"——这不是猜的,是既有代码路径的既定行为。
    "ltx2_cloud": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(2160, 3840),
        max_duration_s=300.0,
        fps_options=frozenset({24, 30}),
        native_audio=True,
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
    # native_audio/lip_sync=True:HEVI 路线图 §0 明确写"lip-sync —— Veo3 已原生
    # 音画,Kling/海螺在跟进"——这是路线图自己的判断依据,不是新猜测。
    "veo3": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=8.0,  # veo3/fast 固定 8s
        fps_options=frozenset({24, 30}),
        native_audio=True,
        lip_sync=True,
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
    # WaveSpeed AI 聚合网关(hevi/video/wavespeed_service.py)。规格来自 WaveSpeed REST
    # 文档(非营销页):duration 3~15s、720p/1080p。fps 只标 24——两个端点的请求体都不
    # 接受 fps 参数(原生固定输出),文档也只对 wan_2_7 写明 "24fps standard",30 没有
    # 依据故不列入。native_audio/lip_sync 均不标 True——见 wavespeed_service.py 顶部
    # 注释:营销页的"原生音画/多语种对口型"宣称在 REST API 契约里找不到对应字段。
    "happyhorse_1_1": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=15.0,
        fps_options=frozenset({24}),
    ),
    "wan_2_7": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=15.0,
        fps_options=frozenset({24}),
    ),
    # 阿里云百炼(Model Studio)业务空间专属域名直连版(hevi/video/alibaba_maas_service.py)
    # —— 同一对模型(happyhorse-1.1-t2v/wan2.7-t2v),但走阿里官方 API 而非 WaveSpeed
    # 转售,规格来自阿里官方 API 文档:duration 2~15s、720P/1080P。fps/native_audio/
    # lip_sync 未在官方文档发现对应字段,同上面 WaveSpeed 条目一样不标 True。
    "happyhorse_1_1_maas": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=15.0,
        fps_options=frozenset({24}),
    ),
    "wan_2_7_maas": ProviderLimits(
        modes=frozenset({"t2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=15.0,
        fps_options=frozenset({24}),
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
