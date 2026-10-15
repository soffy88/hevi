"""Independent counterexample probe for KIDSMANIFEST-R1 (verifier, not part of unit)."""
import copy, json, hashlib, subprocess, sys
from pathlib import Path

from hevi.kids.story_gate import kids_story_gate, gate_json
from hevi.kids.consistency_manifest import (
    KidsConsistencyManifest, validate_manifest, canonical_json,
    attach_to_task_shot_rows, read_specs_from_task_shot_rows,
)
from hevi.capabilities import get

FIX = Path("tests/fixtures/kids")
L = lambda n: json.loads((FIX / n).read_text(encoding="utf-8"))
rows = []


def rec(cid, desc, expect, got, detail):
    ok = (expect == got) if expect != "FAIL_OR_WARN" else got in ("FAIL", "WARN")
    rows.append({"id": cid, "desc": desc, "expect": expect, "got": got,
                 "verdict": "OK" if ok else "MISS", "detail": detail})


def gate_case(cid, desc, story, expect):
    try:
        r = kids_story_gate(story)
        bad = [f"{f.rule}@{f.location}" for f in r.findings if f.severity != "PASS"]
        rec(cid, desc, expect, r.status, bad)
    except Exception as e:  # validation error counts as reject
        rec(cid, desc, expect, "FAIL", f"exception:{type(e).__name__}:{str(e)[:160]}")


def man_case(cid, desc, m, expect):
    try:
        r = validate_manifest(m)
        bad = [f"{f.rule}@{f.location}:{f.message[:90]}" for f in r.findings if f.severity == "FAIL"]
        rec(cid, desc, expect, r.status, bad)
    except Exception as e:
        rec(cid, desc, expect, "FAIL", f"exception:{type(e).__name__}:{str(e)[:160]}")


fox = L("story_fox_star.json")
# ---- story gate ----
for n in ["story_fox_star.json", "story_slide.json", "story_brush_monster.json", "story_seed_sprout.json"]:
    gate_case("G0_" + n, "合法试点 story", L(n), "PASS")

s = copy.deepcopy(fox)
s["logline"] = "小狐狸夜里遇到会吃小孩的怪兽，血流满地，非常恐怖。"
s["theme"] = "恐怖与死亡"
s["beats"][1]["text"] = "黑暗里怪兽张开血盆大口要吃掉小狐狸！"
s["beats"][2]["text"] = "小狐狸拿起刀和枪去砍怪兽，到处是血。"
s["beats"][3]["text"] = "怪兽被杀死了，尸体倒在地上。"
gate_case("G1_scary", "惊吓/暴力主题（怪兽吃人/血/刀枪/死亡）", s, "FAIL")

s = copy.deepcopy(fox)
s["logline"] = "小狐狸和朋友一起喝酒抽烟，学会了谈恋爱。"
s["theme"] = "喝酒和恋爱"
s["beats"][3]["text"] = "大家一起喝啤酒、抽烟，然后亲嘴谈恋爱。"
gate_case("G2_adult", "成人主题（喝酒/抽烟/恋爱）", s, "FAIL")

s = copy.deepcopy(fox)
s["beats"][5]["text"] = "再见啦。"
gate_case("G3_no_question", "告别拍缺互动问句", s, "FAIL")

s = copy.deepcopy(fox)
s["spoken_language"] = "zh-CN"
for b in s["beats"]:
    b["text"] = "Hello kids, this is an English sentence about the fox."
gate_case("G4_lang_mismatch", "声明 zh-CN 但台词全英文（口语语言锁）", s, "FAIL")

s = copy.deepcopy(fox)
for b in s["beats"]:
    b["emotion"] = ""
gate_case("G5_no_emotion", "全部节拍情绪为空（R4 无法判定）", s, "FAIL_OR_WARN")

s = copy.deepcopy(fox)
s["fixed_characters"] = ["char_bear"]
gate_case("G6_char_not_in_story", "固定角色 char_bear 但全文只有小狐狸（角色一致性）", s, "FAIL_OR_WARN")

s = copy.deepcopy(fox)
s["theme"] = "分享、刷牙、勇敢、轮流和种子发芽"
gate_case("G7_multi_theme", "多主题（单集单主题）", s, "FAIL_OR_WARN")

s = copy.deepcopy(fox)
s["beats"][4]["text"] = "然后大家去睡觉了。"
gate_case("G8_recap_no_theme", "复述拍未复述主题、无动作", s, "FAIL_OR_WARN")

# ---- manifest ----
mf = L("manifest_fox_star.json")
man_case("M0_ok", "合法 manifest_fox_star", copy.deepcopy(mf), "OK")
man_case("M0_ok2", "合法 manifest_slide", L("manifest_slide.json"), "OK")
m = copy.deepcopy(mf); m["shots"][0]["shot_spec"]["template"] = "no_such_template"
man_case("M1_tpl", "未知 template", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][0]["shot_spec"]["sfx"] = [{"id": "no_such_sfx", "offset": 0}]
man_case("M2_sfx", "未知 sfx", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][0]["shot_spec"]["transition_in"] = "no_such_tr"
man_case("M3_tr", "未知 transition_in", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][0]["shot_spec"]["style"] = "no_such_style"
man_case("M4_style", "未知 style", m, "FAIL")
m = copy.deepcopy(mf); m["style_bible"]["negative"] = ""
man_case("M5_sb", "Style Bible 缺 negative", m, "FAIL")
m = copy.deepcopy(mf); del m["style_bible"]
man_case("M5b_sb_absent", "完全缺 style_bible 字段", m, "FAIL")
m = copy.deepcopy(mf); m["transition_table"] = m["transition_table"][1:]
man_case("M6_tt", "缺 S1->S2 切点", m, "FAIL")
m = copy.deepcopy(mf); m["transition_table"][1]["prev_out"] = "Frame holds steady"
man_case("M6b_hold", "中间切点 frame holds steady", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][2]["line"] = "@char_bear 来了"
man_case("M7_ref", "line 引用不存在的角色 @char_bear", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][2]["camera"] = "跟拍 @char_bear"
man_case("M7b_ref_camera", "镜头 camera 字段引用不存在角色 @char_bear", m, "FAIL")
m = copy.deepcopy(mf); m["theme"]["closing_action"] = "和 @char_bear 击掌"
man_case("M7c_ref_theme", "theme.closing_action 引用不存在角色", m, "FAIL")
m = copy.deepcopy(mf)
for sh in m["shots"]:
    sh["duration"] = 2.6; sh["shot_spec"]["duration"] = 2.6
man_case("M8_avg", "单镜≥2.5 但平均 2.6<3.5", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][0]["duration"] = 2.4; m["shots"][0]["shot_spec"]["duration"] = 2.4
man_case("M8b_short", "duration 2.4<2.5", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][0]["shot_spec"]["duration"] = 1.0
man_case("M9_dur_mismatch", "shot.duration=4.0 但 shot_spec.duration=1.0（绑定不一致，实际渲染 1s）", m, "FAIL")
m = copy.deepcopy(mf); m["characters"][0]["anchor_ref"] = None; m["characters"][0]["seed"] = None; m["characters"][0]["voice_ref"] = None
man_case("M10_no_anchor", "固定角色缺 anchor_ref/seed/voice_ref（缺角色锚点）", m, "FAIL")
m = copy.deepcopy(mf); m["spoken_language"][2]["language"] = "en-US"
man_case("M11_lang", "说话镜语言 en-US 与 audience zh-CN 冲突", m, "FAIL")
m = copy.deepcopy(mf); m["spoken_language"] = m["spoken_language"][:-1]
man_case("M11b_lang_missing", "说话镜 S6 缺口语语言条目", m, "FAIL")
m = copy.deepcopy(mf); m["shots"][1]["shot_index"] = 1
man_case("M12_dup_idx", "shot_index 重复（两个 S1）", m, "FAIL")
m = copy.deepcopy(mf); m["scenes"][0]["palette"] = ["#FF0000", "#000000"]; m["style_bible"]["color_grade"] = "明亮柔和马卡龙调，单一暖色基准"
man_case("M13_palette", "场景色板黑红与 color_grade 马卡龙冲突（K1 未要求，参考）", m, "FAIL_OR_WARN")
m = copy.deepcopy(mf); m["shots"][0]["shot_spec"]["tempalte"] = "no_such_template"
man_case("M14_typo_field", "shot_spec 未知字段 tempalte（拼写错误静默忽略?）", m, "FAIL")
m = copy.deepcopy(mf); m["audience"]["age_max"] = 18
man_case("M15_age", "audience age_max=18（非幼儿）", m, "FAIL_OR_WARN")

# ---- binding: changing manifest changes result; manifest -> rows -> back ----
mobj = KidsConsistencyManifest.model_validate(mf)
rows_in = [{"task_id": "verify", "shot_index": sh.shot_index, "selection_json": {}} for sh in mobj.shots]
w = attach_to_task_shot_rows(mobj, rows_in)
back = read_specs_from_task_shot_rows(w)
eq = all(b.to_dict() == sh.shot_spec.to_dict() for b, sh in zip(back, mobj.shots))
rec("B1_roundtrip", "manifest→shot_states.selection_json→回读一致", True, eq, w[0]["selection_json"])
mf2 = copy.deepcopy(mf); mf2["shots"][0]["shot_spec"]["effect"] = "vignette" if True else None
try:
    m2 = KidsConsistencyManifest.model_validate(mf2)
    w2 = attach_to_task_shot_rows(m2, [dict(r, selection_json={}) for r in rows_in])
    rec("B2_change_propagates", "改 manifest effect 后写回行随之改变", True,
        w2[0]["selection_json"]["shot_spec"]["effect"] != w[0]["selection_json"]["shot_spec"]["effect"], w2[0]["selection_json"]["shot_spec"]["effect"])
except Exception as e:
    rec("B2_change_propagates", "改 manifest effect", True, False, str(e)[:200])
# row tampered with an invalid spec -> read back must reject
bad_row = copy.deepcopy(w[0]); bad_row["selection_json"]["shot_spec"]["transition_in"] = "zzz"
try:
    read_specs_from_task_shot_rows([bad_row]); rec("B3_bad_row", "行内非法 spec 回读须拒", "FAIL", "OK", "accepted")
except Exception as e:
    rec("B3_bad_row", "行内非法 spec 回读须拒", "FAIL", "FAIL", type(e).__name__)
# rows whose shot_index not in manifest get silently skipped?
orphan = attach_to_task_shot_rows(mobj, [{"task_id": "verify", "shot_index": 99, "selection_json": {}}])
rec("B4_orphan_row", "任务行 shot_index=99 不在 manifest（应报错/告警）", "FAIL_OR_WARN",
    "OK" if orphan[0]["selection_json"] == {} else "?", "silently skipped" if orphan[0]["selection_json"] == {} else orphan)

# ---- registry ----
cap = get("kids.consistency_manifest")
out = Path(".tmp/verify_cap"); out.mkdir(parents=True, exist_ok=True)
r_ok = cap.render({"manifest": mf}, out, duration=1, aspect="9:16", seed=1).qa["status"]
r_bad = cap.render({"manifest": json.loads(json.dumps(mf).replace("chime_soft", "nope_sfx"))}, out, duration=1, aspect="9:16", seed=1).qa["status"]
rec("R1_registry_manifest", "registry 调 manifest：合法 OK / 改坏 FAIL", "OK/FAIL", f"{r_ok}/{r_bad}", "")
try:
    cap.render({"wrong": 1}, out, duration=1, aspect="9:16", seed=1)
    rec("R2_illegal_params", "registry 非法参数（缺 manifest）须报错", "FAIL", "OK?", "no exception")
except Exception as e:
    rec("R2_illegal_params", "registry 非法参数（缺 manifest）须报错", "FAIL", "FAIL", type(e).__name__)
try:
    res = get("kids.story_gate").render({"story": "not a dict"}, out, duration=1, aspect="9:16", seed=1)
    rec("R3_illegal_story", "story_gate 非法参数 story=str", "FAIL", res.qa.get("status"), str(res.qa)[:150])
except Exception as e:
    rec("R3_illegal_story", "story_gate 非法参数 story=str", "FAIL", "FAIL", type(e).__name__ + ":" + str(e)[:100])

# ---- API route ----
try:
    from hevi.api.main import app
    paths = sorted({getattr(r, "path", "") for r in app.routes if "capabilit" in getattr(r, "path", "")})
    rec("A1_api_route", "GET /api/capabilities 路由存在", True, "/api/capabilities" in paths, paths)
except Exception as e:
    rec("A1_api_route", "GET /api/capabilities 路由存在", True, False, f"import app failed: {e}"[:200])

# ---- determinism across processes ----
code = ("import json,hashlib;from hevi.kids.story_gate import gate_json;from hevi.kids.consistency_manifest import *;"
        "s=json.load(open('tests/fixtures/kids/story_fox_star.json'));m=KidsConsistencyManifest.model_validate(json.load(open('tests/fixtures/kids/manifest_fox_star.json')));"
        "print(hashlib.sha256(gate_json(s).encode()).hexdigest(),hashlib.sha256(canonical_json(m).encode()).hexdigest())")
h = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() for _ in range(2)]
rec("D1_determinism_xproc", "两个独立进程哈希一致", True, h[0] == h[1] and len(h[0]) > 100, h)
docs = hashlib.sha256(Path("docs/kids/manifests/manifest_fox_star.json").read_bytes()).hexdigest()
rec("D2_docs_hash", "docs manifest_fox_star.json 哈希 = DONE 所贴 720b84d8…", True, docs.startswith("720b84d8"), docs)

json.dump(rows, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for r in rows:
    print(r["verdict"], r["id"], "expect", r["expect"], "got", r["got"], "|", r["desc"], "|", str(r["detail"])[:220])
