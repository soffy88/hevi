"""hevi 错误分类 taxonomy(P1-5)。

三条正交语义:
  RetryableError   —— 瞬时故障,重试可能成功(429/5xx/超时/连接拒绝)。
  UnretryableError —— 重试无用的确定性失败(4xx/账户锁定/欠费/配额/未配置/未安装)。
  DegradableError  —— 非致命,可降级/跳过继续出片(如配音失败→纯视频、封面失败→跳过)。

``classify_error`` 供 retry_policy 判定是否重试:除 httpx 状态码外,还按**消息**识别
hevi 实际会撞的错(RuntimeError("fal submit 403 ... User is locked")、"FAL_API_KEY
not configured"、"Connection refused" 等),避免对锁定账户/配置缺失做无谓重试、或对
瞬时网络错误过早放弃。
"""

import httpx


class HeviError(Exception):
    """Base error for Hevi."""


class UnretryableError(HeviError):
    """Errors that should NOT be retried (e.g. 401, 400, quota exhausted)."""


class RetryableError(HeviError):
    """Errors that CAN be retried (e.g. 429, 5xx, timeout)."""


class RateLimitError(RetryableError):
    """429 Rate Limit."""


class DegradableError(HeviError):
    """非致命错误:可降级/跳过继续(旁白/封面/数字人等增强步骤失败,不应毁掉整任务)。

    "增强而非必需"的步骤失败后可包成此类,或直接 catch 走降级路径。
    不参与 retry(retry_policy 只看 Retryable/Unretryable)。
    """


# 重试无用的确定性失败关键词(账户/配额/配置/鉴权)。
_UNRETRYABLE_KEYS = (
    "user is locked",
    "exhausted balance",
    "arrearage",
    "overdue",
    "insufficient",
    "quota",
    "not configured",
    "not installed",
    "access denied",
    "unauthorized",
    "forbidden",
)
# 瞬时故障关键词(网络/服务端)。
_RETRYABLE_KEYS = (
    "connection refused",
    "connection reset",
    "econnrefused",
    "timed out",
    "timeout",
    "temporarily",
    "try again",
    "service unavailable",
    # longvideo_orchestrator.py 检测 omodul 静默吞掉的镜头失败(返回占位/空文件)时抛出
    # "Pipeline produced placeholder/empty output with {provider}"——这条错误存在的
    # 目的注释里写得很明确,就是"触发 provider 级 fallback",但它不匹配上面任何关键词,
    # 会被 classify_error 兜底成 UnretryableError,直接跟自己的设计意图相反:线上真实
    # 撞过(kling_v2 单镜头返回空文件),run_with_fallback 直接放弃、不重试也不切
    # provider。这里补上关键词,让它真的按"瞬时故障"处理。
    "placeholder/empty output",
    "bad gateway",
)


def classify_error(exc: Exception) -> HeviError:
    """Classify an exception into Hevi errors (retryable vs not)."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return RateLimitError(f"Rate limited: {exc}")
        if status in (401, 403, 400, 404):
            return UnretryableError(f"Client error (unretryable): {exc}")
        if 500 <= status < 600:
            return RetryableError(f"Server error: {exc}")

    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, TimeoutError)):
        return RetryableError(f"Network/Timeout error: {exc}")

    # 消息级分类:hevi 大量错误是带消息的 RuntimeError(fal/config/provider),
    # 仅靠类型分不出,这里按关键词识别,顺序:确定性失败 → 瞬时故障。
    msg = str(exc).lower()
    if any(k in msg for k in _UNRETRYABLE_KEYS):
        return UnretryableError(f"Determinate failure (unretryable): {exc}")
    if any(k in msg for k in _RETRYABLE_KEYS):
        return RetryableError(f"Transient failure (retryable): {exc}")

    # Default to unretryable if we don't know (to avoid infinite loops on logic bugs)
    return UnretryableError(f"Unknown error (assumed unretryable): {exc}")
