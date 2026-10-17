"""白话化重写 pass:把 W 产出的浅文言解说逐句改写成真正的口语白话。
冻结人名/地名/年份数字/引号内文言引文,只改语体措辞。改后重跑硬门验证 9/9。"""

import asyncio
import importlib.util
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/data/soffy/projects/hevi/.env")

# 从 pilot 导入 REFS + _cost(pilot 已守卫 main,导入不执行)
_spec = importlib.util.spec_from_file_location(
    "pilotmod",
    "/tmp/claude-1000/-data-soffy-projects-hevi/c6e3348a-1deb-405a-bd59-6b2bfe30737d/scratchpad/n0_pilot_s2_baihua.py",
)
pilot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pilot)
REFS = pilot.REFS

from hevi.n0.rhard import anchor_quotes, force_long_vo_onscreen, run_rhard  # noqa: E402
from hevi.n0.splitter import split_overlong  # noqa: E402
from hevi.providers.registry import register_all_providers  # noqa: E402

NET = Path("output/n0_s2_baihua/s1_full_clean_script.json")

_SYS = (
    "你是历史短视频的口语解说改写员。把给你的一句『浅文言/书面语』历史解说，改写成"
    "**真正的口语大白话**——就像你坐在朋友对面、用现代普通话把这段历史讲给他听。"
    "\n【硬约束,违反即废】"
    "\n① 人名、地名、年份数字**一字不改**照抄(晋献公/骊姬/申生/重耳/夷吾/曲沃/蒲/屈/前666年…)。"
    "\n② **口播里不要保留文言引号原文**——若原句有『』或“”包着的文言引文,别照抄进白话,"
    "把它的意思用白话讲出来即可(文言原文的呈现交给画面字幕,不进口播)。"
    "\n③ 事实、因果、涉及的事件**不增不减**,只换说法。"
    "\n【怎么改——把文言词换成大白话】"
    "\n嬖宠乱嫡序→宠爱骊姬、把嫡长子继承的规矩搞乱了；进谗→说坏话陷害/进谗言撺掇；"
    "\n构陷→陷害；相继出奔→先后逃出国；缢死→上吊自尽；遂成定局→就此成了定局；"
    "\n屏藩→屏障/保护伞；卿族坐大→卿大夫家族做大；嫡庶失序→嫡子庶子的次序乱了；"
    "\n昭示→说明/预示；不可逆进程→再也回不了头。多用『于是/结果/这一下/说白了/也就是说』这种口语连接。"
    "\n【示例】"
    "\n文言:『前666年，晋献公娶骊姬，嫡庶之序始乱；二五进谗，使太子申生居曲沃』"
    "\n白话:『公元前666年，晋献公娶了骊姬。这一下，谁是嫡子、谁是庶子该怎么排的老规矩就乱了。"
    "两个叫二五的宠臣在献公跟前说坏话，撺掇他把太子申生打发到曲沃去住』"
    "\n文言:『卿族专权遂成定局，实为后来韩赵魏三家分立晋国之远因』"
    "\n白话:『卿大夫家族把持大权就成了定局——说白了，这就是后来韩、赵、魏三家瓜分晋国的老根子』"
    "\n【断句】把长句拆成 2–4 个短句,每句尽量 ≤约28字,多用句号,像口语一句一句地说。"
    "\n只输出改写后的白话,不要解释、不要引号包整句。"
)


MODEL = "qwen-max"  # qwen-plus 撞文言语体墙,升 qwen-max A/B


async def rewrite_one(llm, text):
    r = await llm(
        messages=[{"role": "user", "content": "改写这句：" + text}],
        max_tokens=400,
        system=_SYS,
        model=MODEL,
    )
    ch = (r or {}).get("output", {}).get("choices", [])
    out = ch[0]["message"]["content"].strip() if ch else text
    return out, (r or {}).get("usage", {}) or {}


async def main():
    register_all_providers()
    from obase.provider_registry import ProviderRegistry

    llm = ProviderRegistry.get().llm("qwen_cloud")
    net = json.loads(NET.read_text())
    total = 0.0
    for b in net["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                continue  # onscreen 文言引不动
            new, u = await rewrite_one(llm, s["text"])
            total += pilot._cost(u)
            s["text"] = new

    # 重跑确定性链 + 硬门验证
    sd, _ = anchor_quotes(net, REFS)
    sd, _ = force_long_vo_onscreen(sd)
    sd = split_overlong(sd)
    rep = run_rhard(sd, REFS)
    print("白话化后硬门:", rep["by_gate"], "| 失败", rep["n_failures"], "| cost", round(total, 4))
    if rep["failures"]:
        for f in rep["failures"]:
            print("  FAIL", f["gate"], f.get("sid"), f.get("reason", "")[:70])
    print("\n=== 白话化后 VO 逐句(供人工判语体) ===")
    for b in sd["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") != "onscreen":
                print(" ·", s["text"])
    # 写候选文件(不覆盖 9/9 好稿),交人工判语体+看门
    cand = NET.parent / "s1_baihua_candidate.json"
    cand.write_text(json.dumps(sd, ensure_ascii=False, indent=2))
    print("\n候选写到", cand, "| pass:", rep["pass"])


if __name__ == "__main__":
    asyncio.run(main())
