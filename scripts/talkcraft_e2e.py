"""CPU end-to-end proof for the talkcraft line (no GPU, no paid calls).

usage: python scripts/talkcraft_e2e.py <output_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hevi.layer4_legacy.talkcraft.omodul_impl.produce import produce_talkcraft
from hevi.layer4_legacy.talkcraft.oprim_impl.sync import NarrationSegment

SEGMENTS = [
    NarrationSegment(
        id="hook", role="hook",
        sentences=("为什么复利被称作世界第八大奇迹？", "答案藏在三个词里：时间、本金和收益率。"),
        keywords=("复利", "时间"),
        props={"title": "复利的力量", "subtitle": "三分钟讲清楚", "items": [{"label": "时间"}, {"label": "本金"}, {"label": "收益率"}]},
    ),
    NarrationSegment(
        id="def", role="definition",
        sentences=("复利，就是利息也能继续生利息。", "第一年赚的钱，第二年会一起参与增长。"),
        keywords=("利息", "增长"),
        props={"formulaHead": "复利公式", "formulaLines": ["本金 × (1+收益率)ⁿ", "n 越大，曲线越陡"]},
    ),
    NarrationSegment(
        id="method", role="method",
        sentences=("想让复利为你工作，记住三步。", "越早开始越好，因为时间是最大的杠杆。", "保持投入，不要轻易中断。", "最后，控制成本，别让手续费吃掉收益。"),
        keywords=("三步", "杠杆", "中断", "成本"),
        props={"header": "让复利工作的三步", "points": [{"num": "01", "title": "尽早开始"}, {"num": "02", "title": "持续投入"}, {"num": "03", "title": "控制成本"}]},
    ),
    NarrationSegment(
        id="outro", role="outro",
        sentences=("真正的财富，是时间的朋友。", "从今天开始，让时间替你赚钱。"),
        keywords=("朋友", "今天"),
        props={"quoteLine1": "真正的财富", "quoteLine2": "是时间的朋友"},
    ),
]

PROMO = [
    NarrationSegment(
        id="promo", role="hook",
        sentences=("一杯好咖啡，只需要三分钟。", "新鲜烘焙，每一颗豆子都可追溯。", "早上七点，准时送到你楼下。", "现在下单，首杯半价。"),
        keywords=("三分钟", "可追溯", "七点", "半价"),
        props={"title": "晨光咖啡", "subtitle": "三分钟一杯好咖啡"},
    ),
]

if __name__ == "__main__":
    from hevi.layer4_legacy.talkcraft.omodul_impl._whisper import WhisperAligner

    root = Path(sys.argv[1] if len(sys.argv) > 1 else "output/talkcraft_e2e")
    aligner = WhisperAligner()
    summary = {}
    from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec

    runs = (
        ("explainer", SEGMENTS, "复利的力量", AvatarSpec(mode="lipsync")),  # avatar on
        ("kinetic_promo", PROMO, "晨光咖啡", None),  # avatar off (optional)
    )
    for line, segs, name, avatar in runs:
        res = produce_talkcraft(segments=segs, output_dir=root / line, line=line, name=name, aligner=aligner, avatar=avatar)
        summary[line] = {
            "status": res["status"],
            "wall_seconds": res["wall_seconds"],
            "gates": {Path(r["video_path"]).name: {g["name"]: [g["value"], g["passed"]] for g in r["gates"]} for r in res["records"]},
        }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
