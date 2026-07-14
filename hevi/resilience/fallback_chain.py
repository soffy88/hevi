import logging
from collections.abc import Callable, Coroutine
from typing import Any

from oprim.provider_health_check import provider_health_check

from hevi.observability import log_event
from hevi.resilience.live_state import provider_routable, record_provider_outcome
from hevi.resilience.retry_policy import RetryPolicy, with_retry

logger = logging.getLogger(__name__)

# provider 失败(含 omodul 静默吞掉镜头后返回的占位/空文件,longvideo_orchestrator.py
# 会检测并抛错)时的降级链。终点落到 happyhorse_1_1_maas_lock——它走阿里云百炼
# workspace 专属账户(ALIBABA_MAAS_*),是本机当前唯一有余额的视频通道。
#
# 2026-07-14 实测:所有 fal 系 provider(ltx2_cloud/kling_v2/veo3/hailuo)都撞
# "fal.ai 403 User is locked. Exhausted balance"——fal 账户已欠费停用,历史上 ltx2_cloud
# 的 342 次成功全部发生在欠费之前。公共 DashScope 账户(wan_cloud 用的 DASHSCOPE_API_KEY)
# 同样欠费。wan_local 因 GPU 反复掉 PCIe 总线基本必失败(1042 失败 / 4 成功)。故三者都
# 不能作为降级目标;唯一有钱的是 MAAS workspace(同一把 key 刚成功生成了本任务的角色
# 参考图),对应的主线视频 provider 就是 happyhorse_1_1_maas_lock。
#
# 占位/空输出被 classify_error 判为 unretryable(见 errors.py 默认分支),with_retry 立刻
# 放弃当前 provider(不浪费钱重跑同一个坏 provider 的整条管线),由这里的链切到下一个。
_TERMINAL = "happyhorse_1_1_maas_lock"
PROVIDER_FALLBACK = {
    # fal/公共 DashScope 系(可能欠费)失败/空输出 → 落到有余额的 MAAS provider。
    "ltx2_cloud": ["ltx2_cloud", _TERMINAL],
    "wan_cloud": ["wan_cloud", _TERMINAL],
    "kling_v2": ["kling_v2", _TERMINAL],
    "veo3": ["veo3", _TERMINAL],
    "hailuo": ["hailuo", _TERMINAL],
    "happyhorse_1_1": ["happyhorse_1_1", _TERMINAL],
    "happyhorse_1_1_ref": ["happyhorse_1_1_ref", _TERMINAL],
    "happyhorse_1_1_maas": ["happyhorse_1_1_maas", _TERMINAL],
    "wan_2_7": ["wan_2_7", _TERMINAL],
    "vidu": ["vidu", _TERMINAL],
    # 终点自身:无更多降级目标(已是有余额的账户)。
    "happyhorse_1_1_maas_lock": ["happyhorse_1_1_maas_lock"],
}

# 欠费/403 信号(fal/DashScope 欠费表现为 403 / "exhausted balance" / "user is locked")。
_BALANCE_403_KEYS = ("403", "exhausted balance", "arrearage", "user is locked", "quota")


def _is_balance_403(exc: Exception) -> bool:
    """该异常是否表明 provider 欠费/被锁(→ 拉低其活状态 health)。"""
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 403:
        return True
    msg = str(exc).lower()
    return any(k in msg for k in _BALANCE_403_KEYS)


async def run_with_fallback[T](
    *,
    initial_provider: str,
    runner: Callable[[str], Coroutine[Any, Any, T]],
    on_fallback: Callable[[str, str, Exception], Coroutine[Any, Any, None]],
    retry_policy: RetryPolicy | None = None,
) -> T:
    """Execute a runner function with provider-level fallback.

    Before calling on_fallback and switching to a candidate provider, a health
    probe is performed. Unhealthy candidates are skipped immediately without
    consuming a retry cycle and without triggering on_fallback.

    Args:
        initial_provider: The first provider to try.
        runner: A function that takes a provider name and returns a result coroutine.
        on_fallback: Callback called only when switching to a *healthy* fallback provider.
        retry_policy: Retry configuration for each provider attempt. Defaults to RetryPolicy().

    Returns:
        T: The result from the first successful provider.
    """
    p_policy = retry_policy or RetryPolicy()
    chain = PROVIDER_FALLBACK.get(initial_provider, [initial_provider])
    last_exc: Exception | None = None

    for idx, provider in enumerate(chain):
        # L0 活状态门:滚动 403 率显示该 provider 欠费/被锁 → 不尝试(不烧一次必失败的调用)。
        # 无记录 → 可路由(不误杀)。链中所有 provider 都不可路由则最终抛 last_exc。
        if not provider_routable(provider):
            last_exc = last_exc or RuntimeError(f"provider {provider} unroutable (欠费/403)")
            log_event(
                stage="resilience",
                event="provider_unroutable_skipped",
                provider=provider,
                reason="live_state",
            )
            logger.warning(f"Provider {provider} 活状态不可路由(欠费/403)— skipping attempt.")
            continue
        try:
            logger.info(f"Attempting task with provider: {provider} (idx={idx})")
            log_event(stage="resilience", event="provider_attempt", provider=provider, attempt=idx)

            def make_runner(p: str) -> Callable[[], Coroutine[Any, Any, T]]:
                return lambda: runner(p)

            return await with_retry(make_runner(provider), policy=p_policy)
        except Exception as e:
            last_exc = e
            # L0 活状态:把本次失败喂进滚动 403 率 → 欠费/被锁的 provider 后续被路由跳过。
            record_provider_outcome(provider, is_403=_is_balance_403(e))

            # Find the next candidate, skipping any that fail health check OR活状态门。
            switched = False
            for next_idx in range(idx + 1, len(chain)):
                next_provider = chain[next_idx]

                # health 探针 + 活状态门:任一不过则不通知切到它(免把任务切到随后会被跳过的 provider)。
                healthy = await provider_health_check(next_provider) and provider_routable(
                    next_provider
                )
                if not healthy:
                    log_event(
                        stage="resilience",
                        event="provider_unhealthy_skipped",
                        provider=next_provider,
                    )
                    logger.warning(f"Provider {next_provider} 不健康/活状态不可路由 — skipping.")
                    continue

                # Healthy: notify caller and proceed.
                log_event(
                    stage="resilience",
                    event="provider_failed_switching",
                    old_provider=provider,
                    next_provider=next_provider,
                    error=str(e),
                )
                logger.warning(
                    f"Provider {provider} failed after retries. "
                    f"Falling back to {next_provider}. Error: {e}"
                )
                await on_fallback(provider, next_provider, e)
                switched = True
                break

            if not switched:
                log_event(
                    stage="resilience", event="all_providers_failed", level="error", error=str(e)
                )
                logger.error(f"All providers in chain {chain} failed or were unhealthy.")

    if last_exc:
        raise last_exc
    raise RuntimeError("Fallback chain exited without result or exception")
