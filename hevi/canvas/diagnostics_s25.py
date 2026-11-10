"""S25：失败节点可读化（原因分类 + 能否重试 + 一键动作）。

画布执行失败时，``incremental_executor`` 只把 ``TypeError: ...`` 这样的原始异常
写进 review.reasons；对用户来说既不知道是自己没额度、素材丢了，还是上游抽风，
也不知道点“重试”有没有意义。这里做一层**纯函数**归因：

* ``explain_failure`` 把错误文本/自检原因归到 6 类，给出标题、可读说明、动作；
* ``redact`` 去掉密钥、Bearer、URL 查询串（报错里不能回显凭据）；
* ``annotate_graph`` 按节点已有状态补一个 ``diagnostic`` 字段，前端直接展示。

不做任何网络/模型调用：分类是确定性的字符串规则，宁可归到“未知”也不猜。
"""

from __future__ import annotations

import re
from typing import Any

CATEGORIES: dict[str, dict[str, Any]] = {
    "quota": {
        "title": "额度不足",
        "detail": "本次生成需要的额度超过账户余额或当日上限。",
        "action": "充值/降低时长或分辨率后重试；也可以换成本地免费模型。",
        "retryable": False,
    },
    "auth": {
        "title": "渠道鉴权失败",
        "detail": "模型渠道的密钥无效、过期，或没有该模型的权限。",
        "action": "到“模型服务”重新保存 Key 或换一个渠道；不要重复重试。",
        "retryable": False,
    },
    "rate_limit": {
        "title": "被上游限流",
        "detail": "渠道短时间请求过多（429），或并发超过套餐上限。",
        "action": "等 30–60 秒再重试；批量任务可降低并发。",
        "retryable": True,
    },
    "timeout": {
        "title": "请求超时",
        "detail": "上游在等待时间内没有返回，任务可能仍在跑。",
        "action": "先重试一次；仍失败则缩短时长或换渠道。",
        "retryable": True,
    },
    "network": {
        "title": "网络 / 代理不通",
        "detail": "连接被重置、DNS/TLS 失败，或代理没有放行该域名。",
        "action": "检查网络与代理规则后重试；不要连续重试。",
        "retryable": True,
    },
    "upstream": {
        "title": "上游服务失败",
        "detail": "渠道返回 5xx 或明确的内部错误，通常是对方临时故障。",
        "action": "稍后重试；连续两次失败就换渠道。",
        "retryable": True,
    },
    "parameter": {
        "title": "参数不被接受",
        "detail": "时长、分辨率、画幅或提示词超出该模型允许的范围。",
        "action": "按模型能力改小/改窄后重试；参数问题重试不会变好。",
        "retryable": False,
    },
    "media": {
        "title": "素材缺失或损坏",
        "detail": "引用的图片/视频/音频找不到、为空或格式不支持。",
        "action": "重新上传或换成同类型的可用素材后再重试。",
        "retryable": False,
    },
    "config": {
        "title": "节点配置缺失",
        "detail": "节点缺少必填字段（提示词、时长、工具 id 等）。",
        "action": "补全配置后重试。",
        "retryable": False,
    },
    "unknown": {
        "title": "未归类的失败",
        "detail": "没有匹配到已知原因，原始信息保留在下方。",
        "action": "可重试一次；把下方信息连同诊断包一起反馈。",
        "retryable": True,
    },
}

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("quota", re.compile(r"insufficient|quota|credit|余额|额度|积分不足|balance", re.I)),
    ("auth", re.compile(r"\b401\b|\b403\b|unauthori[sz]ed|forbidden|invalid[ _-]?api[ _-]?key|authentication|鉴权|密钥|权限", re.I)),
    ("rate_limit", re.compile(r"\b429\b|rate[ _-]?limit|too many requests|限流|并发", re.I)),
    ("timeout", re.compile(r"timeout|timed out|readtimeout|deadline exceeded|超时", re.I)),
    ("network", re.compile(r"connection (reset|refused|aborted)|ssl|dns|proxy|network is unreachable|网络|代理", re.I)),
    ("upstream", re.compile(r"\b5\d\d\b|internal server error|bad gateway|service unavailable|upstream|上游", re.I)),
    ("parameter", re.compile(r"\b400\b|\b422\b|invalid (parameter|argument|value)|validation error|unsupported|参数|不支持", re.I)),
    ("media", re.compile(r"no such file|file not found|not found.*(media|image|video|audio)|cannot identify image|素材|文件不存在|解码失败", re.I)),
    ("config", re.compile(r"missing|required|keyerror|config|未配置|缺少", re.I)),
]

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"), "***"),
    (re.compile(r"(oc_sk_[A-Za-z0-9_\-]{6,})"), "***"),
    (re.compile(r"(AIza[0-9A-Za-z_\-]{10,})"), "***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;\"']+"), r"\1***"),
    (re.compile(r"([?&](?:key|token|sig|signature|api_key)=)[^&\s]+", re.I), r"\1***"),
]
_URL_WITH_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]*")


def redact(text: str) -> str:
    """去掉密钥、Bearer、URL 查询串；保留可读的主体信息。"""
    out = str(text or "")
    out = _URL_WITH_QUERY.sub(r"\1?…", out)
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def _classify(text: str) -> str:
    for name, pattern in _RULES:
        if pattern.search(text):
            return name
    return "unknown"


def explain_failure(
    error: str | None = None,
    *,
    node_type: str = "",
    config: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把一次失败翻译成用户能行动的一段话。

    优先用真实异常文本；没有时用自检原因；再没有就看配置是否明显缺字段。
    """
    cfg = config or {}
    reasons = [str(r) for r in (review or {}).get("reasons") or [] if str(r).strip()]
    raw = str(error or "").strip() or (reasons[0] if reasons else "")
    category = _classify(raw) if raw else "unknown"
    if not raw:
        if node_type in ("video", "image") and not str(cfg.get("prompt") or "").strip():
            category = "config"
            raw = "节点没有提示词"
        elif node_type == "video" and not cfg.get("duration_s"):
            category = "config"
            raw = "视频节点没有时长"
    meta = CATEGORIES[category]
    return {
        "category": category,
        "title": meta["title"],
        "detail": meta["detail"],
        "action": meta["action"],
        "retryable": bool(meta["retryable"]),
        "raw": redact(raw),
        "retry": {
            "kind": "node_rerun" if meta["retryable"] else "manual",
            "max_attempts": 1 if meta["retryable"] else 0,
        },
    }


def annotate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """给失败/待重做节点补 ``diagnostic``，其余节点不动。"""
    nodes = graph.get("nodes") or graph.get("nodes_json") or []
    out: list[dict[str, Any]] = []
    for node in nodes:
        node = dict(node)
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        status = str(node.get("status") or "")
        review = node.get("review") if isinstance(node.get("review"), dict) else None
        error = str(node.get("error") or cfg.get("last_error") or "")
        if status in ("failed", "fail", "needs_redo", "warn") or error or (
            review and review.get("result") == "fail"
        ):
            node["diagnostic"] = explain_failure(
                error or None,
                node_type=str(node.get("node_type") or ""),
                config=cfg,
                review=review,
            )
        out.append(node)
    return {"nodes": out, "nodes_json": out, "edges": graph.get("edges") or graph.get("edges_json") or []}
