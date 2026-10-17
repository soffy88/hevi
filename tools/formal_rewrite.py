"""正式白话讲解重写:纪录片解说词体——庄重规范现代白话,不文言、不口语随便。"""

import asyncio
import importlib.util
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/data/soffy/projects/hevi/.env")

spec = importlib.util.spec_from_file_location(
    "pilotmod",
    "/tmp/claude-1000/-data-soffy-projects-hevi/c6e3348a-1deb-405a-bd59-6b2bfe30737d/scratchpad/n0_pilot_s2_baihua.py",
)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
REFS = pilot.REFS

from hevi.n0.register_meter import episode_register, wenyan_hits, wenyan_score  # noqa: E402
from hevi.n0.rhard import anchor_quotes, force_long_vo_onscreen, run_rhard  # noqa: E402
from hevi.n0.splitter import split_overlong  # noqa: E402
from hevi.providers.registry import register_all_providers  # noqa: E402

NET = Path("output/n0_s2_baihua/s1_full_clean_script.json")
TARGET = 0.08

_SYS = (
    "你把历史解说改写成【正式、规范的现代白话文】,风格像高质量历史纪录片的解说词——"
    "庄重、清晰、有讲解感,但绝不用文言。"
    "\n【要求】"
    "\n1. 人名/地名/年份照抄不改(晋献公/骊姬/申生/重耳/夷吾/曲沃/前666年…)。"
    "\n2. **绝不用文言词**,一律换成现代规范说法:"
    "之/则/而(连词)/遂/乃/焉/矣→不用;自缢/缢→上吊自尽;身亡→死去;赴死→赴死改为『代其受死』的白话『替他去死』;"
    "遭/遭受→受到/被;进谗→进谗言陷害;出奔→出逃/逃亡;式微→衰落;随之→随后;由此/自此→从此;"
    "并未→并没有;乃至→甚至;诸子→其他公子;二人→两人;相继/先后→先后;继而→接着。"
    "\n3. **也不要过于口语随便**:不用『那事儿/哥俩/搞出来/撑场面/说白了/闹得挺凶/中了诅咒似的/"
    "那会儿/一下子』这类口头语。用规范、庄重的书面语,但让普通观众也能听懂。"
    "\n4. 句子清晰、有条理,一句一个意思;可用『其根本原因在于/最终导致/正是…的深层原因』这类"
    "解说式表达,但不堆术语、不掉书袋。"
    "\n5. **只改写、不添加原文没有的评论或总结**(别加『这段历史展现了…』之类的话)。"
    "\n6. **直接输出改写后的句子本身**,绝对不要加『改写成…』『正式白话：』『如下』之类任何前缀、"
    "说明或口语化备注;只要那一句正式白话,别的都不要。"
)


def _strip_meta(t: str) -> str:
    """去掉 qwen-max 偶发的元话前缀(改写成…就是:/正式白话:/如下:)。"""
    import re

    t = t.strip().strip("「」『』\"'")
    t = re.sub(r"^[^。！？]{0,24}?(就是|如下|表达|版本|结果)[:：]\s*", "", t)
    t = re.sub(r"^(正式白话|改写后|白话讲解|解说词)[:：]\s*", "", t)
    return t.strip()


# 确定性文言→正式白话兜底替换(qwen-max 顽固不换的,机械替掉;保序保义)。
_POST = {
    "赴死": "送死",
    "废黜": "废除",
    "遇害": "被杀害",
    "遭杀害": "被杀害",
    "遭杀": "被杀",
    "遭受": "受到",
    "随之": "随后",
    "自缢": "上吊自尽",
    "身亡": "死去",
    "并未": "并没有",
    "乃至": "甚至",
    "由此": "因此",
    "自此": "从此",
    "诸子": "其他公子",
    "出奔": "出逃",
    "式微": "衰落",
    "继而": "接着",
    "旋即": "随即",
    "遂成": "最终成为",
    "始于": "起于",
    "之叹": "的感叹",
    "所致": "造成的",
    "以致": "以至于",
    "难逃一劫": "没能逃过一劫",
}


def _post_fix(t: str) -> str:
    import re

    for a, b in _POST.items():
        t = t.replace(a, b)
    # 则→就(避开 规则/原则/否则/准则/法则/细则)
    t = re.sub(r"(?<![规原否准法细])则", "就", t)
    return t


async def one(llm, text, extra=""):
    r = await llm(
        messages=[{"role": "user", "content": "改成正式白话讲解体：" + text + extra}],
        max_tokens=400,
        system=_SYS,
        model="qwen-max",
    )
    ch = (r or {}).get("output", {}).get("choices", [])
    out = _post_fix(_strip_meta(ch[0]["message"]["content"])) if ch else text
    return (out or text), (r or {}).get("usage", {}) or {}


async def main():
    register_all_providers()
    from obase.provider_registry import ProviderRegistry

    llm = ProviderRegistry.get().llm("qwen_cloud")
    net = json.loads(NET.read_text())
    # 先摊平回 plan 拍(合并 split 子拍),避免往已拆拍插句再拆生成 #x#y 双层不对齐 plan。
    from collections import OrderedDict

    groups: OrderedDict = OrderedDict()
    for b in net["beats"]:
        root = b.get("parent_beat") or b["beat_id"]
        groups.setdefault(root, []).extend(b["sentences"])
    net["beats"] = [{"beat_id": k, "sentences": v} for k, v in groups.items()]

    total = 0.0
    for b in net["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                continue
            # 总是正式化一遍(口语版已过文言尺,但语体要从口语抬到正式);超阈再重试。
            cur = s["text"]
            extra = ""
            for k in range(3):
                new, u = await one(llm, cur, extra)
                total += pilot._cost(u)
                cur = new
                if wenyan_score(cur) <= TARGET:
                    break
                bad = wenyan_hits(cur)["wenyan_chars"] + wenyan_hits(cur)["shumian_words"]
                extra = f"(上一版还有文言词 {bad},务必全换成现代规范白话)"
            s["text"] = cur

    sd, _ = anchor_quotes(net, REFS)
    sd, _ = force_long_vo_onscreen(sd)
    sd = split_overlong(sd)
    rep = run_rhard(sd, REFS)
    reg = episode_register(sd)
    print("硬门:", rep["by_gate"], "| 失败", rep["n_failures"], "| cost", round(total, 4))
    for f in rep["failures"]:
        print("  FAIL", f["gate"], f.get("sid"), f.get("reason", "")[:60])
    print(f"\n整集文言度: {reg['score']} (阈0.08)")
    print("\n=== 正式白话讲解 VO 逐句 ===")
    for b in sd["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") != "onscreen":
                print(f" [{wenyan_score(s['text']):.3f}] {s['text']}")
    if rep["pass"]:
        (NET.parent / "s1_formal_candidate.json").write_text(
            json.dumps(sd, ensure_ascii=False, indent=2)
        )
        print("\n候选写到 s1_formal_candidate.json")


if __name__ == "__main__":
    asyncio.run(main())
