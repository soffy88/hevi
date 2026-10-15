"""R3 verifier adversarial probe.

Beyond re-running the unit's 12 samples, this constructs NEW counter-examples:
 (1) the mandated 12 texts (regression check),
 (2) general false-negative harm using DIFFERENT words than the fix listed,
 (3) negation-window weakness (a real harm word inside a 6-char negation window),
 (4) the FIX-B default-strict behavior.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from hevi.kids.story_gate import kids_story_gate  # noqa: E402
from hevi.kids.consistency_manifest import (  # noqa: E402
    KidsConsistencyManifest,
    attach_to_task_shot_rows,
)

FIX = Path("tests/fixtures/kids")
fox = json.loads((FIX / "story_fox_star.json").read_text(encoding="utf-8"))
rows = []


def run(cid, label, text, expect, beat=3):
    s = copy.deepcopy(fox)
    s["beats"][beat]["text"] = text
    try:
        r = kids_story_gate(s)
        st = r.status
        bad = [f.rule for f in r.findings if f.severity != "PASS"]
    except Exception as e:  # noqa: BLE001
        st, bad = "FAIL", ["exc:" + type(e).__name__]
    ok = (st == "PASS") if expect == "PASS" else st in ("FAIL", "WARN")
    rows.append({"id": cid, "expect": expect, "got": st, "ok": ok, "text": text, "rules": bad})
    print(("OK  " if ok else "MISS"), cid, "->", st, bad, "|", text)


# (1) mandated 12 from KIDSMANIFEST_FIX.md
print("--- mandated 12 ---")
run("m_fp_open", "误杀-打开/打招呼", "小狐狸打开了门，向大家打招呼。", "PASS")
run("m_fp_sweep", "误杀-打扫", "大家一起打扫房间，把玩具放回篮子里。", "PASS")
run("m_fp_umbrella", "误杀-打伞", "小狐狸打着小雨伞，走过彩色的小路。", "PASS")
run("m_ok_hot", "正常", "太阳公公出来啦，小狐狸热得出汗，喝了一大口水。", "PASS")
run("m_fn_hit", "漏杀-揍", "小狐狸狠狠地揍了小兔子一顿，小兔子疼得大哭。", "FAIL")
run("m_fn_kick", "漏杀-踢/推/嘲弄", "大家一起踢小松鼠，推他摔进泥坑里嘲弄他。", "FAIL")
run("m_fn_monster", "漏杀-吞", "夜里怪兽把小朋友一口吞进肚子里，再也没有出来。", "FAIL")
run("m_fn_poison", "漏杀-毒药", "小熊偷偷在水里放了毒药，想让朋友们肚子疼。", "FAIL")
run("m_fn_bomb", "漏杀-炸弹/炸飞", "小狐狸点燃炸弹，轰的一声把房子炸飞了。", "FAIL")
run(
    "m_fn_stranger",
    "漏杀-跟陌生人走",
    "陌生叔叔说跟我走吧，小狐狸没告诉爸爸妈妈就自己跟着他走了。",
    "FAIL",
)
run("m_fn_insult", "漏杀-骂/傻瓜/胖子", "大家都骂小刺猬是傻瓜、胖子，没人愿意理他。", "FAIL")
run("m_neg_hit", "否定-不打人不骂人", "小狐狸不打人，也不骂人。", "PASS")
run("m_neg_stranger", "否定-不能跟陌生人走", "妈妈说不能跟陌生人走。", "PASS")

# (2) general harm NOT in the mandated list and NOT in the lexicon (true false-negatives if PASS)
print("--- new harm (different words) ---")
run("n_pinch", "新-掐/推下楼梯", "坏孩子把小熊掐得哇哇叫，还把他推下楼梯。", "FAIL")
run("n_knife", "新-用石头砸/划破", "他们用石头砸小兔，把小兔的头划破了直流血。", "FAIL")
run("n_lockup", "新-关小黑屋", "大家把小刺猬关进小黑屋，一整天都不给他饭吃。", "FAIL")
run("n_shove", "新-抢/摔在地上", "大灰狼抢走了小熊的蛋糕，把他推倒摔在地上。", "FAIL")
run("n_scald", "新-开水烫", "小狐狸把一壶开水浇在小猫身上，小猫疼得直哭。", "FAIL")

# (3) negation-window weakness: a REAL harm word that the 6-char window mistakenly excuses
print("--- negation-window weakness ---")
run("w_drug", "窗口-下毒(前面有不吃)", "小狐狸说不吃糖，然后偷偷给小兔下毒，小兔倒在地上。", "FAIL")
run("w_beat", "窗口-殴打(前面有不许)", "老师说不能打人，可是小熊回家殴打了小兔。", "FAIL")

# (4) FIX-B default strict
print("--- FIX-B default strict ---")
mf = json.loads((FIX / "manifest_fox_star.json").read_text(encoding="utf-8"))
mobj = KidsConsistencyManifest.model_validate(mf)
orphan = [{"task_id": "v", "shot_index": 99, "selection_json": {}}]
try:
    attach_to_task_shot_rows(mobj, orphan)  # default call, no strict kwarg
    rows.append(
        {
            "id": "B4_default_strict",
            "expect": "FAIL",
            "got": "OK",
            "ok": False,
            "text": "default call silently skipped orphan row",
        }
    )
    print("MISS B4_default_strict -> OK (silently skipped)")
except Exception as e:  # noqa: BLE001
    rows.append(
        {
            "id": "B4_default_strict",
            "expect": "FAIL",
            "got": "FAIL",
            "ok": True,
            "text": type(e).__name__,
        }
    )
    print("OK  B4_default_strict ->", type(e).__name__)
try:
    attach_to_task_shot_rows(mobj, orphan, strict=False)
    rows.append(
        {
            "id": "B4_explicit_lax",
            "expect": "OK",
            "got": "OK",
            "ok": True,
            "text": "strict=False skips",
        }
    )
    print("OK  B4_explicit_lax -> OK (skipped)")
except Exception as e:  # noqa: BLE001
    rows.append(
        {
            "id": "B4_explicit_lax",
            "expect": "OK",
            "got": "FAIL",
            "ok": False,
            "text": type(e).__name__,
        }
    )
    print("MISS B4_explicit_lax ->", type(e).__name__)

out = Path("audit/kidsmanifest/verify_r3/probe_adversarial.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
miss = [r for r in rows if not r["ok"]]
print(f"\nTOTAL {len(rows)}  MISS {len(miss)}")
for r in miss:
    print("  MISS", r["id"], r["expect"], "->", r["got"], "|", r["text"])
print("ADVDONE")
