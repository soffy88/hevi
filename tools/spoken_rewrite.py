"""大白话口语重写:把书面白话打成真·口语。禁书面词,逐句对语体尺,超阈重写(≤3次)。"""

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
TARGET = 0.05  # 单句口语目标(书面版各句 0.15–0.40,口语应 <0.05)

_SYS = (
    "你把历史解说改写成【大白话口语】,就像你面对面跟朋友聊天讲故事,让没读过古文的人一听就懂。"
    "\n【硬规矩】"
    "\n1. 人名/地名/年份照抄不改(晋献公/骊姬/申生/重耳/夷吾/曲沃/前666年…)。"
    "\n2. **绝对禁用下列书面/文言词**(用右边口语替代):"
    "则/而(连词)→不用直接说;遂→就;由此/自此→打这以后;并未→并没有;始于→是从…开始的;"
    "随之→跟着;二人→他俩;诸子→其他几个儿子;乃至→甚至;继而/旋即→接着;"
    "自缢/缢→上吊自杀;身亡→死了;赴死→替他去送死;遭/遭受/遇害/遭杀→被(杀);"
    "式微→衰落;膨胀→越来越大;坐大/专权→做大/把持大权;宗法→继承那套老规矩;"
    "内耗→内斗;纲纪→规矩;屏藩→靠山/挡箭牌;公室→国君家;嫡庶→嫡子庶子;先后/相继→一个接一个。"
    "\n3. 短句为主,一句一个意思,多用'的了就都把被这那'。可用'你想啊/说白了/这么一来/结果'。"
    "\n4. 不许在白话里塞文言引号原文。"
    "\n只输出改写后的大白话,别解释、别加引号包整句。"
)


async def one(llm, text, extra=""):
    r = await llm(
        messages=[{"role": "user", "content": "改成大白话口语：" + text + extra}],
        max_tokens=400,
        system=_SYS,
        model="qwen-max",
    )
    ch = (r or {}).get("output", {}).get("choices", [])
    return ch[0]["message"]["content"].strip() if ch else text, (r or {}).get("usage", {}) or {}


async def main():
    register_all_providers()
    from obase.provider_registry import ProviderRegistry

    llm = ProviderRegistry.get().llm("qwen_cloud")
    net = json.loads(NET.read_text())
    total = 0.0
    for b in net["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                continue
            best = s["text"]
            for k in range(3):
                if wenyan_score(best) <= TARGET:
                    break
                flagged = wenyan_hits(best)
                extra = ""
                if k > 0:
                    bad = flagged["wenyan_chars"] + flagged["shumian_words"]
                    extra = f"(上一版还有书面词 {bad},务必全换成口语)"
                new, u = await one(llm, best if k == 0 else best, extra)
                total += pilot._cost(u)
                if wenyan_score(new) < wenyan_score(best):
                    best = new
            s["text"] = best

    sd, _ = anchor_quotes(net, REFS)
    sd, _ = force_long_vo_onscreen(sd)
    sd = split_overlong(sd)
    rep = run_rhard(sd, REFS)
    reg = episode_register(sd)
    print("硬门:", rep["by_gate"], "| 失败", rep["n_failures"], "| cost", round(total, 4))
    for f in rep["failures"]:
        print("  FAIL", f["gate"], f.get("sid"), f.get("reason", "")[:60])
    print(f"\n整集口语度: {reg['score']} (阈将定;书面版是 0.228)")
    print("\n=== 大白话口语 VO 逐句 ===")
    for b in sd["beats"]:
        for s in b["sentences"]:
            if s.get("presentation") != "onscreen":
                print(f" [{wenyan_score(s['text']):.3f}] {s['text']}")
    if rep["pass"]:
        cand = NET.parent / "s1_spoken_candidate.json"
        cand.write_text(json.dumps(sd, ensure_ascii=False, indent=2))
        print("\n候选写到", cand)


if __name__ == "__main__":
    asyncio.run(main())
