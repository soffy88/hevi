"""通用书面史述改写(N0-D-029,任意集):env SHISHU_PILOT=pilot路径 SHISHU_NET=净稿路径。
qwen-max 书面史述改写 + 确定性文言兜底 + 双向语体门验证。只改语体,不动事实/引文/结构。"""

import asyncio
import importlib.util
import json
import os
import re
from collections import OrderedDict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/data/soffy/projects/hevi/.env")

PILOT = os.environ["SHISHU_PILOT"]
NET = Path(os.environ["SHISHU_NET"])
spec = importlib.util.spec_from_file_location("pilotmod", PILOT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
REFS = pilot.REFS
REFS["episode_plan"]["vo_window"] = (5.0, 20.0)  # N0-D-030 从容

from hevi.n0.register_meter import (  # noqa: E402
    episode_register,
    koutou_score,
    wenyan_hits,
    wenyan_score,
)
from hevi.n0.rhard import anchor_quotes, force_long_vo_onscreen, run_rhard  # noqa: E402
from hevi.n0.splitter import split_overlong  # noqa: E402
from hevi.providers.registry import register_all_providers  # noqa: E402

_SYS = (
    "你把历史解说改写成【规范、清楚的现代书面语】,就是严肃历史读物正文那种语感——庄重、准确、"
    "沉稳,但**用的是现代白话的词汇,绝不是半文言,也不是聊天口语**。"
    "\n【这就是标准,照这个语感来】:『晋献公宠爱骊姬,为了让骊姬之子继位,骊姬设计诬陷,逼死了"
    "太子申生。公子重耳与夷吾预感大祸临头,先后逃离晋国。』"
    "\n——看清楚:上面用的是『宠爱/为了/设计诬陷/逼死/预感/大祸临头/先后/逃离』这样清清楚楚的"
    "现代书面词,没有一个文言虚词。你就写成这样,不要比它更文。"
    "\n【硬规矩】"
    "\n1. 人名/地名/年份照抄不改。"
    "\n2. 【绝不用文言】:之(作『的』的虚词,如『晋国之乱』写成『晋国的动乱』)、则、而(连词)、"
    "遂、乃、亦、焉、矣、此乃、其(文言)、何人、抑或;也不用 缢/谮/嬖/弑/薨/赴死/自缢/出奔/进谗/"
    "式微/随之/由此/自此/致使/所致/二人/相继 等文言词,一律换成现代说法(也/两人/先后/导致…)。"
    "\n3. 【也不用聊天口语】:不用 那事儿/哥俩/搞出来/搞/撑场面/说白了/使坏/吓跑/乱套/散了/挺/"
    "特别宠/一下子/闹得挺凶/中了诅咒似的 这类随便的口头语。"
    "\n4. 句子沉稳、清楚,一句一个意思;可略长(叙述从容),但不堆文言虚词、不掉书袋。只改写不加评论。"
    "\n只输出改写后的现代书面语,不要解释、不要前缀。"
)


def _post_fix(t: str) -> str:
    # 组合短语在前(避免 自缢→上吊自尽 后 身亡→死去 造成"上吊自尽死去")
    for a, b in (
        ("自缢身亡", "上吊自尽"),
        ("上吊而死死去", "上吊自尽"),
        ("上吊而亡", "上吊自尽"),
        ("自缢", "上吊自尽"),
        ("身亡", "死去"),
        ("废黜", "废除"),
        ("遇害", "被杀"),
        ("遭杀害", "被杀害"),
        ("遭杀", "被杀"),
        ("遭受", "受到"),
        ("随之", "此后"),
        ("并未", "并没有"),
        ("乃至", "甚至"),
        ("由此", "因此"),
        ("自此", "从此"),
        ("诸子", "众公子"),
        ("出奔", "出逃"),
        ("式微", "衰落"),
        ("继而", "接着"),
        ("旋即", "随即"),
        ("始于", "起于"),
        ("所致", "造成的"),
        ("致使", "导致"),
        ("赴死", "去死"),
        ("此乃", "这是"),
        ("亦", "也"),
        ("二人", "两人"),
        ("相继", "先后"),
        ("何人", "谁"),
        ("三氏", "三家"),
        ("此种", "这种"),
        ("紊乱", "混乱"),
        ("抑或", "或者"),
        ("是项", "这个"),
        ("进谗", "进谗言陷害"),
        ("日渐", "逐渐"),
        ("日益", "越来越"),
        ("实因", "其实是因为"),
        ("以避祸端", "来躲避祸患"),
        ("困境之中", "困境中"),
        ("之根本原因", "的根本原因"),
        ("之纷争", "的纷争"),
        ("之疆域", "的领土"),
        ("之领土", "的领土"),
        ("之罪名", "的罪名"),
        ("困惑之境", "困惑"),
        ("困惑的境", "困惑"),
        ("以维系", "来维系"),
        ("以应对", "来应对"),
        ("以解决", "来解决"),
        ("於是", "于是"),
        ("岂能", "怎能"),
        ("岂", "难道"),
        ("悉数", "全部"),
        ("彼处", "那里"),
        ("昔日", "当年"),
        ("此语", "这句话"),
        ("此举", "这一举动"),
        ("之手", "手中"),
        ("之地", "一带"),
        ("之师", "的军队"),
    ):
        t = t.replace(a, b)
    t = re.sub(r"(?<![规原否准法细])则", "就", t)
    t = re.sub(r"(?<![未])遂(?![心愿])", "于是", t)  # 遂→于是(避开 未遂/遂心/遂愿)
    # 之→的:仅当『之』后接 2+ 汉字(定语所有格,如 国家之建立→的建立);留 之后/之间/之中/之一(后 1 字)
    t = re.sub(r"之(?=[一-鿿]{2,})", "的", t)
    return t


def _strip_meta(t: str) -> str:
    t = t.strip().strip("「」『』\"'")
    t = re.sub(r"^[^。！？]{0,24}?(就是|如下|表达|版本|结果)[:：]\s*", "", t)
    t = re.sub(r"^(书面史述|正式白话|改写后|解说词)[:：]\s*", "", t)
    return t.strip()


async def rw(llm, text, extra=""):
    r = await llm(
        messages=[{"role": "user", "content": "改成规范书面史述语：" + text + extra}],
        max_tokens=500,
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
    groups = OrderedDict()
    for b in net["beats"]:
        root = b.get("parent_beat") or b["beat_id"]
        groups.setdefault(root, []).extend(b["sentences"])
    net["beats"] = [{"beat_id": k, "sentences": v} for k, v in groups.items()]
    total = 0.0
    for b in net["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                continue
            cur = s["text"]
            for k in range(3):
                extra = ""
                if k and wenyan_score(cur) > 0.05:
                    bad = wenyan_hits(cur)["wenyan_chars"] + wenyan_hits(cur)["shumian_words"]
                    extra = f"(上一版还有文言词 {bad},务必全换成现代书面白话)"
                new, u = await rw(llm, cur, extra)
                total += pilot._cost(u)
                cur = new
                if wenyan_score(cur) <= 0.05 and koutou_score(cur) <= 0.03:
                    break
            s["text"] = cur
            # 书面史述改述后原文言 quote 不再逐字匹配 → 清 vo 陈旧 quote(改述非逐字引,onscreen 不动)
            s.pop("quote", None)

    sd, _ = anchor_quotes(net, REFS)
    sd, _ = force_long_vo_onscreen(sd)
    sd = split_overlong(sd, max_secs=20.0, min_secs=5.0)
    rep = run_rhard(sd, REFS)
    reg = episode_register(sd)
    print("硬门:", rep["by_gate"], "| 失败", rep["n_failures"], "| cost", round(total, 4))
    for f in rep["failures"]:
        print("  FAIL", f["gate"], f.get("sid"), f.get("reason", "")[:60])
    print(f"\n整集 文言度={reg['wenyan']} 口语度={reg['koutou']} (阈 文言<0.05 口语<0.03)")
    print("\n=== 书面史述 VO 逐句 [文言度|口语度] ===")
    for b in sd["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") != "onscreen":
                print(f" [{wenyan_score(s['text']):.3f}|{koutou_score(s['text']):.3f}] {s['text']}")
    if rep["pass"]:
        cand = NET.parent / "shishu_candidate.json"
        cand.write_text(json.dumps(sd, ensure_ascii=False, indent=2))
        print("\n候选写到", cand)


if __name__ == "__main__":
    asyncio.run(main())
