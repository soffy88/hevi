"""A-QIN 成本 ledger — 付费调用的落盘可查询记录（append-only JSONL）。

背景：G0 首笔真机支出（¥4.725）此前只落在签核 markdown 里，是记账不是 ledger——
tranche 2 用实测单价写预算时数据来源不能只有人手写文档（DR-1 反静默断链）。本模块把
adapter 的内存态花费改为**持久结构化记录**：每笔付费调用一行，含
fingerprint / provider / 模型 / 时长或张数 / 单价 / 金额 / trail digest。

无时钟纪律：ts 由调用方传入，本模块不取时钟（承接 gen_adapter 同规）。
落点：默认 `docs/ledgers/aqin-cost-ledger.jsonl`（已跟踪，作可提交可复核证据）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 摸底文档 §2.1：ledger 每条的字段契约（缺一即视为记账不完整）。
LEDGER_FIELDS = (
    "ts",  # 调用方传入时间戳（无时钟）
    "op",  # T-V / 未来付费 op
    "provider",
    "model_or_tier",
    "unit",  # per_second | per_image
    "quantity",  # 时长(s) 或 张数
    "unit_price_cny",
    "cost_cny",  # 本笔金额
    "cost_usd",
    "fingerprint",  # vault pack_id（未入库=None）
    "trail_digest",  # decision_trail 摘要
    "cumulative_cny",  # 记账后累计
    "cap_cny",  # 当时金额帽
)


def append_record(path: str | Path, record: dict[str, Any]) -> None:
    """把一条付费记录追加进 JSONL ledger（父目录不存在则建）。"""
    missing = [f for f in LEDGER_FIELDS if f not in record]
    if missing:
        raise ValueError(f"ledger 记录缺字段 {missing}——记账不完整，拒绝落盘")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_records(path: str | Path) -> list[dict[str, Any]]:
    """读回全部 ledger 记录（供 tranche 2 预算查询 / 累计核对）。文件不存在返回空。"""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def total_cny(path: str | Path) -> float:
    """ledger 内累计金额（¥）——独立于内存态 breaker 的可核对真值。"""
    return round(sum(float(r["cost_cny"]) for r in read_records(path)), 4)
