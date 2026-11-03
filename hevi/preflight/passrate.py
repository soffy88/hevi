"""preflight.passrate —— 一次通过率统计与模板反哺。

记录格式（JSONL，一行一次生成）：
{ts, beat_id, model, prompt_sha256, cost, currency,
 outcome: pass|fail, failure_category, notes}

一次通过率 = 首条记录即 pass 的 beat 数 ／ 有记录的 beat 数
（同一 beat 反复重试只算首条，这才是“一次能过”）。
失败原因分布按 failure_category 计；反哺报告把每个出现过的
失败模式映射到一条模板修正建议（FIX_SUGGESTIONS），不写空话。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.preflight.beats import FAILURE_CATEGORIES

FIX_SUGGESTIONS: dict[str, str] = {
    "face_drift": "模板修正：编译时强制附定妆图＋人物锁定段；首帧与定妆人工比对后再发（门禁 character_ref_weak 不许再是 WARN 放行，改 FAIL）。",
    "pseudo_text": "模板修正：强制 no-text 段；含牌匾／题字／招牌的场景先人工验首帧，验过再发。",
    "dialogue_garbled": "模板修正：门禁按 4.5 字／秒硬算，超窗拆镜；生成后必过 ASR 验真再入库。",
    "timeout": "模板修正：避开 UTC 14–17 点高峰；超时先降档（Quality→Fast／Lite）再重试，不原价重烧。",
    "model_refusal": "模板修正：改写触发审核的表述（暴力／敏感词），或拆镜、换模型。",
    "other": "模板修正：先人工归因、补进分类，再写修正——other 不许直接进模板。",
}


class PassRateLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(
        self,
        *,
        beat_id: str,
        model: str,
        prompt_text: str = "",
        cost: float | int | None = None,
        currency: str = "",
        outcome: str,
        failure_category: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        if outcome not in ("pass", "fail"):
            raise ValueError(f"outcome must be pass|fail, got {outcome!r}")
        if outcome == "fail" and failure_category not in FAILURE_CATEGORIES:
            raise ValueError(
                f"failure_category must be one of {list(FAILURE_CATEGORIES)}, "
                f"got {failure_category!r}"
            )
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "beat_id": beat_id,
            "model": model,
            "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16],
            "cost": cost,
            "currency": currency,
            "outcome": outcome,
            "failure_category": failure_category if outcome == "fail" else "",
            "notes": notes,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def stats(self) -> dict[str, Any]:
        recs = self.records()
        first: dict[str, dict[str, Any]] = {}
        for r in recs:
            first.setdefault(r["beat_id"], r)
        beats = len(first)
        first_pass = sum(1 for r in first.values() if r["outcome"] == "pass")
        fails = [r for r in recs if r["outcome"] == "fail"]
        return {
            "attempts": len(recs),
            "beats": beats,
            "pass_count": sum(1 for r in recs if r["outcome"] == "pass"),
            "fail_count": len(fails),
            "pass_rate": round(sum(1 for r in recs if r["outcome"] == "pass") / len(recs), 4) if recs else 0.0,
            "first_pass_rate": round(first_pass / beats, 4) if beats else 0.0,
            "failure_distribution": dict(Counter(r["failure_category"] for r in fails)),
            "by_model": {
                m: {
                    "attempts": sum(1 for r in recs if r["model"] == m),
                    "pass": sum(1 for r in recs if r["model"] == m and r["outcome"] == "pass"),
                }
                for m in sorted({r["model"] for r in recs})
            },
        }

    def feedback_report(self) -> str:
        """失败模式 → 模板修正建议（markdown）。"""
        st = self.stats()
        lines = [
            "# 一次通过率反哺报告",
            "",
            f"- 尝试 {st['attempts']} 次，覆盖 {st['beats']} 个 beat；"
            f"一次通过率 {st['first_pass_rate']:.1%}，总体通过率 {st['pass_rate']:.1%}",
            f"- 失败分布：{st['failure_distribution'] or '无失败'}",
            "",
        ]
        for category, count in sorted(st["failure_distribution"].items()):
            lines.append(f"## {category}（{count} 次）")
            lines.append("")
            lines.append(FIX_SUGGESTIONS.get(category, "（无建议）"))
            lines.append("")
        if not st["failure_distribution"]:
            lines.append("暂无失败记录：模板无需修正。")
        return "\n".join(lines)
