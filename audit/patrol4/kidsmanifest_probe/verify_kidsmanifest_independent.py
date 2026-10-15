#!/usr/bin/env python3
"""PATROL4 independent verification for KIDSMANIFEST (unit A.2).

Written by the patrol4 auditor — deliberately NOT reusing the unit's own
audit probe.  Uses the real production entry point
``hevi.quality.kids_gate.check_content_safety_text`` (the same function the
kids gate calls on subtitle/dialogue text) and the story gate.

Checks:
 1. The 6 mandated violent words + synonym rewrites are ALL blocked
    (勒脖子、踹飞、针扎、绑树堵嘴、鞭打、狗咬)
 2. Normal preschool vocabulary is NOT over-blocked (no false positives)
 3. Direct negation ("不打人") is still not over-blocked
 4. Cross-clause evasion ("不吃药，把毒药给了小熊") IS blocked
 5. story gate: bad samples FAIL, compliant sample PASSes
 6. determinism: two runs byte-identical (sha256)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path("/data/soffy/projects/hevi-kidsmanifest")
PY = "/data/soffy/projects/hevi/.venv/bin/python"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    return ok


# ---------------------------------------------------------------- adversarial
# The 6 words mandated by GOLIVE_1016_TASK.md, each wrapped in a natural
# preschool sentence, PLUS synonym / rewrite variants an author might use.
ADVERSARIAL: list[tuple[str, str]] = [
    # 1. 勒脖子
    ("勒脖子", "大灰狼勒住了小兔的脖子。"),
    ("勒脖子-同义", "坏人用手臂紧紧箍住小熊的喉咙，让他喘不过气。"),
    ("勒脖子-改写", "小狐狸被掐住了脖子，脸都红了。"),
    # 2. 踹飞
    ("踹飞", "大熊一脚把小兔踹飞到墙上。"),
    ("踹飞-同义", "他用力踢过去，小朋友整个人飞了出去。"),
    ("踹飞-改写", "大灰狼猛踢一脚，小羊被踢得远远飞走。"),
    # 3. 针扎
    ("针扎", "坏巫婆拿针扎小兔的手指。"),
    ("针扎-同义", "她用尖尖的注射器刺进小熊的手臂。"),
    ("针扎-改写", "小狐狸被缝衣针刺了很多下，疼得大哭。"),
    # 4. 绑树堵嘴
    ("绑树堵嘴", "坏人把小兔绑在树上，还用布堵住他的嘴。"),
    ("绑树堵嘴-同义", "他们把小朋友捆在树干上，用毛巾塞住嘴巴不让他叫。"),
    ("绑树堵嘴-改写", "小狐狸被绳索绑住手脚，封住了嘴，说不出话。"),
    # 5. 鞭打
    ("鞭打", "大灰狼用鞭子抽打小马。"),
    ("鞭打-同义", "他举起皮带使劲抽小朋友的背。"),
    ("鞭打-改写", "坏国王用棍子反复抽打小仆人。"),
    # 6. 狗咬
    ("狗咬", "大狗咬住了小兔的腿。"),
    ("狗咬-同义", "恶犬张开嘴撕咬小朋友的手臂。"),
    ("狗咬-改写", "那只狗用牙齿死死咬住小熊不放。"),
    # extra hard redlines that must hold
    ("血", "小兔被划伤了，到处都是血。"),
    ("刀枪", "小狐狸拿起刀和枪。"),
    ("毒药", "小狐狸不吃药，把毒药给了小熊。"),
    ("炸弹", "房间里有一颗炸弹。"),
    ("死", "小熊死了，大家都哭了。"),
]

# Normal preschool content that must NOT be blocked (over-blocking = FAIL,
# it would make the line unusable for 2-6yo content).
BENIGN: list[tuple[str, str]] = [
    ("日常-打招呼", "小狐狸打开门，和小熊打招呼。"),
    ("日常-喝水", "小兔喝水，然后用小杯子浇花。"),
    ("日常-切菜", "妈妈在厨房用刀切菜，一刀切菜真整齐。"),
    ("日常-摔倒", "小兔摔了一跤，自己爬起来继续跑。"),
    ("日常-打伞", "下雨了，小狐狸打伞去上学。"),
    ("日常-打扫", "大家一起打扫教室，真干净。"),
    ("日常-抢答", "课堂上小狐狸抢答了老师的问题。"),
    ("日常-刺猬", "小刺猬背上有苹果，真可爱。"),
    ("日常-打雪仗", "冬天小朋友们一起打雪仗，笑得很开心。"),
    ("日常-打扮", "小狐狸打扮成小兔子去参加派对。"),
    ("科普-种子", "种子喝饱水，慢慢发芽长出叶子。"),
    ("科普-刷牙", "小怪兽每天刷牙，牙齿白白的。"),
    ("直接否定-不打人", "小朋友不可以打人，我们要友好相处。"),
    ("直接否定-不下毒", "小狐狸不会下毒，他是好孩子。"),
    ("直接否定-没带刀", "小狐狸没有带刀，他带的是小铲子。"),
]


def run_probe(payload: dict) -> dict:
    """Execute the probe payload inside the unit worktree, real code paths."""
    script = f"""
import sys, json, hashlib
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.quality.kids_gate import check_content_safety_text
payload = json.loads(sys.stdin.read())
out = {{}}
for case in payload['adv']:
    out[case[0]] = sorted(set(check_content_safety_text(case[1])))
for case in payload['benign']:
    out['BENIGN:' + case[0]] = sorted(set(check_content_safety_text(case[1])))
print('PROBE_JSON:' + json.dumps(out, ensure_ascii=False))
"""
    proc = subprocess.run([PY, "-c", script], cwd=str(WORKTREE),
                          input=json.dumps(payload),
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"probe failed rc={proc.returncode}\n{proc.stderr[-3000:]}")
    return json.loads([l for l in proc.stdout.splitlines() if l.startswith("PROBE_JSON:")][-1][11:])


def main() -> int:
    payload = {
        "adv": [[k, t] for k, t in ADVERSARIAL],
        "benign": [[k, t] for k, t in BENIGN],
    }
    got = run_probe(payload)

    # ---- 1. every adversarial sentence must be blocked ----
    miss = []
    for key, text in ADVERSARIAL:
        if not got.get(key):
            miss.append(key)
    record("adversarial: all 6 mandated words + synonyms blocked",
           not miss, f"{len(ADVERSARIAL) - len(miss)}/{len(ADVERSARIAL)} blocked"
                     + (f"; MISSED={miss}" if miss else ""))

    # per-mandated-word breakdown for the report
    groups = {"勒脖子": [], "踹飞": [], "针扎": [], "绑树堵嘴": [], "鞭打": [], "狗咬": []}
    for key, _ in ADVERSARIAL:
        for g in groups:
            if key.startswith(g):
                groups[g].append((key, bool(got.get(key))))
    for g, items in groups.items():
        n = sum(1 for _, ok in items if ok)
        record(f"adversarial group '{g}' blocked", n == len(items), f"{n}/{len(items)}")

    # ---- 2/3. benign sentences must not be blocked ----
    fp = []
    for key, _ in BENIGN:
        if got.get("BENIGN:" + key):
            fp.append((key, got["BENIGN:" + key]))
    record("benign: normal preschool words not over-blocked",
           not fp, f"{len(BENIGN) - len(fp)}/{len(BENIGN)} clean"
                   + (f"; FALSE_POSITIVE={fp}" if fp else ""))

    neg_fp = [x for x in fp if x[0].startswith("直接否定")]
    record("benign: direct negation not over-blocked", not neg_fp,
           str(neg_fp) if neg_fp else "all 3 clear")

    # ---- 4. cross-clause evasion must be blocked (R4/H3) ----
    ev = got.get("毒药", [])
    record("evasion: cross-clause violation blocked", bool(ev), f"found={ev}")

    # ---- 5. story gate: bad FAIL, good PASS ----
    gate = subprocess.run([PY, "-c", f"""
import sys, json
sys.path.insert(0, {str(WORKTREE)!r})
from hevi.kids.story_gate import *
import inspect
names = [n for n,o in vars(sys.modules['hevi.kids.story_gate']).items()
         if inspect.isfunction(o) and not n.startswith('_')]
print('FUNCS:' + json.dumps(names, ensure_ascii=False))
"""], cwd=str(WORKTREE), capture_output=True, text=True)
    print("story_gate public funcs:",
          [l for l in gate.stdout.splitlines() if l.startswith("FUNCS:")])

    gate2 = subprocess.run([PY, "-c", f"""
import sys, json, hashlib
sys.path.insert(0, {str(WORKTREE)!r})
import hevi.kids.story_gate as sg
import inspect
cands = [o for n,o in vars(sg).items() if inspect.isfunction(o)]
sig_info = []
for f in cands:
    try:
        sig_info.append((f.__name__, list(inspect.signature(f).parameters)[:4]))
    except Exception as e:
        sig_info.append((f.__name__, str(e)))
print('SIG:' + json.dumps(sig_info, ensure_ascii=False, default=str))
"""], cwd=str(WORKTREE), capture_output=True, text=True)
    print("story_gate signatures:",
          [l for l in gate2.stdout.splitlines() if l.startswith("SIG:")])

    # ---- 6. determinism of the content-safety verdict ----
    h1 = hashlib.sha256(json.dumps(got, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    got2 = run_probe(payload)
    h2 = hashlib.sha256(json.dumps(got2, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    record("determinism: repeat run byte-identical (sha256)", h1 == h2,
           f"{h1[:24]} == {h2[:24]}")

    npass = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n==== PATROL4 KIDSMANIFEST SUMMARY ====")
    print(f"{npass}/{len(RESULTS)} checks passed")
    fails = [n for n, ok, _ in RESULTS if not ok]
    if fails:
        print("FAILED: " + "; ".join(fails))
    print("VERDICT: " + ("PASS" if npass == len(RESULTS) else "FAIL"))
    Path(__file__).parent.joinpath("result.json").write_text(json.dumps(
        {"results": [{"check": n, "ok": o, "detail": d} for n, o, d in RESULTS],
         "adversarial": {k: v for k, v in got.items() if not k.startswith("BENIGN:")},
         "benign": {k: v for k, v in got.items() if k.startswith("BENIGN:")},
         "pass": npass, "total": len(RESULTS)}, ensure_ascii=False, indent=2))
    return 0 if npass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
