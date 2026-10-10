"""CPU end-to-end proof for the talkcraft line (no GPU, no paid calls).

usage: python scripts/talkcraft_e2e.py <output_dir> [--host-only | --with-host]

--with-host also renders the presenter (host) layout for the talking_head and
avatar_spokesperson lines; --host-only renders just those two.
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

HOST_SCRIPTS = {
    "talking_head": (
        "三分钟看懂指数基金",
        [
            "大家好，今天用三分钟讲清楚指数基金。",
            "指数基金买的不是一只股票，而是一整篮子股票。",
            "它跟踪一个指数，比如沪深三百，涨跌跟着市场走。",
            "最大的好处是费用低，而且不用挑股票。",
            "长期定投，再加上耐心，就是普通人的好朋友。",
            "下期我们聊聊，怎么挑一只好的指数基金。",
        ],
    ),
    "avatar_spokesperson": (
        "晨光咖啡",
        [
            "你好，我是晨光咖啡的品牌代言人。",
            "我们只用当季新鲜烘焙的阿拉比卡豆子。",
            "每一颗豆子，都能追溯到具体的庄园。",
            "早上七点之前下单，半小时送到你楼下。",
            "这个月新用户首杯半价，会员再送一杯。",
            "晨光咖啡，让每个早晨都值得期待。",
        ],
    ),
}

if __name__ == "__main__":
    from hevi.layer4_legacy.talkcraft.omodul_impl._whisper import WhisperAligner
    from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec
    from hevi.talkcraft.host_lines import produce_host_line

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    root = Path(args[0] if args else "output/talkcraft_e2e")
    aligner = WhisperAligner()
    summary = {}

    def _summ(res: dict) -> dict:
        return {
            "status": res["status"],
            "wall_seconds": res["wall_seconds"],
            "gates": {Path(r["video_path"]).name: {g["name"]: [g["value"], g["passed"]] for g in r["gates"]} for r in res["records"]},
        }

    runs = (
        ("explainer", SEGMENTS, "复利的力量", AvatarSpec(mode="lipsync")),  # avatar on
        ("kinetic_promo", PROMO, "晨光咖啡", None),  # avatar off (optional)
    )
    if "--host-only" not in flags:
        for line, segs, name, avatar in runs:
            res = produce_talkcraft(segments=segs, output_dir=root / line, line=line, name=name, aligner=aligner, avatar=avatar)
            summary[line] = _summ(res)
    if flags & {"--host-only", "--with-host"}:
        for line, (topic, texts) in HOST_SCRIPTS.items():
            res = produce_host_line(line, texts=texts, topic=topic, output_dir=root / line, aligner=aligner)
            summary[line] = _summ(res)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
