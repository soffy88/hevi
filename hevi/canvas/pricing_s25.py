"""S25：生成前费用预估（画布图 → 逐节点人民币报价）。

与 S22 账本同源：模型单价只从 ``hevi.cost.pricing_table`` 取，美元→人民币汇率
用 ``HEVI_USD_CNY``（默认 7.2），调用 ``craft_s22.model_price_cny_per_second``，
不新建价目表。算不出的项目（按张计费的图片、未收录的渠道）**不猜**，单列在
``unpriced``，合计只算已知部分——和报价要能对得上账本，不能靠占位数凑。

用法::

    est = estimate_graph({"nodes": [...], "edges": [...]})
    est["total_cny"]      # 已知部分合计
    est["per_node"]       # 逐节点
    compare_with_ledger(est["plan_id"])   # 与账本逐镜报价的偏差

``plan_id`` 只在调用方提供时才有（画布尚未执行时没有账本记录，偏差为 None）。
"""

from __future__ import annotations

from typing import Any

from hevi.studio import craft_s22

# 本地/随包音色：无第三方现金成本。名单与 pricing_table 的音频档一致。
LOCAL_AUDIO_PROVIDERS = frozenset({"edge_tts", "voicebox", "vibevoice", "duix", ""})
DEFAULT_VIDEO_MODEL = "wan_2_7"


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("nodes") or graph.get("nodes_json") or []
    return [dict(n) for n in raw if isinstance(n, dict)]


def _cfg(node: dict[str, Any]) -> dict[str, Any]:
    cfg = node.get("config")
    return dict(cfg) if isinstance(cfg, dict) else {}


def _seconds(cfg: dict[str, Any], default: float = 5.0) -> float:
    for key in ("duration_s", "seconds", "duration"):
        value = cfg.get(key)
        if value is None:
            continue
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return default


def estimate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """逐节点报价。视频/片段按秒；音频本地为 0；图片单列（按张计费无统一价）。"""
    per_node: list[dict[str, Any]] = []
    unpriced: list[dict[str, str]] = []
    total = 0.0
    for node in _nodes(graph):
        node_id = str(node.get("node_id") or node.get("id") or "")
        node_type = str(node.get("node_type") or node.get("type") or "")
        cfg = _cfg(node)
        if node_type in ("video", "segment"):
            if str(cfg.get("tool_id") or "") in ("nle.project", "nle.jianying_export"):
                per_node.append(
                    {"node_id": node_id, "node_type": node_type, "kind": "assembly",
                     "cny": 0.0, "priced": True, "model": "local"}
                )
                continue
            model = str(
                cfg.get("provider") or cfg.get("model") or cfg.get("video_provider")
                or DEFAULT_VIDEO_MODEL
            )
            seconds = _seconds(cfg)
            price = craft_s22.model_price_cny_per_second(model)
            cny = round(price * seconds, 3)
            priced = price > 0
            if priced:
                total += cny
            else:
                unpriced.append(
                    {"node_id": node_id, "reason": f"{model} 为本地/免费或未收录单价"}
                )
            per_node.append(
                {"node_id": node_id, "node_type": node_type, "kind": "video",
                 "model": model, "seconds": seconds, "cny": cny, "priced": priced}
            )
            continue
        if node_type == "image":
            per_node.append(
                {"node_id": node_id, "node_type": node_type, "kind": "image",
                 "cny": 0.0, "priced": False, "model": str(cfg.get("provider") or "")}
            )
            unpriced.append(
                {"node_id": node_id, "reason": "按张计费，渠道价未统一，未计入合计"}
            )
            continue
        if node_type == "audio":
            provider = str(cfg.get("provider") or "")
            local = provider in LOCAL_AUDIO_PROVIDERS
            per_node.append(
                {"node_id": node_id, "node_type": node_type, "kind": "audio",
                 "cny": 0.0, "priced": local, "model": provider or "edge_tts"}
            )
            if not local:
                unpriced.append({"node_id": node_id, "reason": f"音频渠道 {provider} 无公开单价"})
            continue
        per_node.append(
            {"node_id": node_id, "node_type": node_type, "kind": node_type,
             "cny": 0.0, "priced": True}
        )
    priced = [n for n in per_node if n.get("priced")]
    return {
        "currency": "CNY",
        "per_node": per_node,
        "unpriced": unpriced,
        "total_cny": round(total, 2),
        "priced_nodes": len(priced),
        "unpriced_nodes": len(unpriced),
        "source": "hevi.cost.pricing_table + HEVI_USD_CNY（与 S22 账本同源）",
    }


def quote_text(estimate: dict[str, Any], *, seconds: float | None = None, shots: int | None = None) -> str:
    head = "费用预估"
    if shots is not None:
        head += f"：{shots} 镜"
    if seconds is not None:
        head += f" · {seconds:g} 秒"
    text = f"{head} · 已知合计 ¥{float(estimate.get('total_cny') or 0):.2f}"
    if estimate.get("unpriced_nodes"):
        text += f"；另有 {estimate['unpriced_nodes']} 项未定价（图片按张/渠道另算）"
    return text


def compare_with_ledger(plan_id: str, estimate: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """把预估与账本里同一 ``plan_id`` 的逐镜报价对照。

    ``estimate`` 省略时，用账本自己汇总（等价于“预估=报价”，偏差 0），只用于
    验证账本本身可用。返回 None 表示账本里没有该 plan_id。
    """
    from hevi.studio import craft_ledger

    rows = [r for r in craft_ledger.read_rows(limit=5000) if str(r.get("plan_id") or "") == plan_id]
    if not rows:
        return None
    ledger_cny = round(sum(float(r.get("cny") or 0) for r in rows), 2)
    if estimate is None:
        return {"plan_id": plan_id, "ledger_cny": ledger_cny, "estimate_cny": ledger_cny,
                "delta_cny": 0.0, "delta_pct": 0.0, "rows": len(rows), "source": "ledger_only"}
    estimate_cny = round(float(estimate.get("total_cny") or 0), 2)
    delta = round(estimate_cny - ledger_cny, 2)
    pct = round((delta / ledger_cny) * 100, 2) if ledger_cny else (0.0 if delta == 0 else None)
    return {
        "plan_id": plan_id,
        "ledger_cny": ledger_cny,
        "estimate_cny": estimate_cny,
        "delta_cny": delta,
        "delta_pct": pct,
        "rows": len(rows),
        "source": "ledger_vs_estimate",
    }
