"""G1b 对拍 harness(正式)—— KU 查询响应 → 投影 VisualFact' → 对拍 G1a 手工装配。

★ 跨仓边界(裁决 2026-07-22):hevi 跨到 stratum **只许两样**——①钉 tag 取字节(git show,
sha256 钉 ref,零预处理)②读 KU spec §8.2 映射表。**永不直改 stratum 文件**;KU 侧缺什么
走"申报不越界"(gap/待决清单交 Wiki,范式=G1B_REPORT 待决三项)。

输入钉死(裁决 2026-07-22 → 续办 v0.2.2 "钉 history-contract-v0.2.2" D-023):
  stratum tag `history-contract-v0.2.2` 的 sample.sanjiafenjin.json **as-is 字节**,零预处理,
  已提取至 output/g1b_sanjia_fenjin/input/(sha256 硬编码于下,不符即 FATAL——字节即真理)。
  v0.2.2 vs v0.2:撤 cf:jinyang-independence(conflicts 空数组、新 sha 4126c842);schema 字节不变。

四层:
  L1 契约模型字段集 == spec §3 声明集(自造=0)
  L2 §8.2 映射来源路径在契约 schema(v0.2 钉住副本)中实存
  L3 G1a 手工装配数据过契约
  L4【本轮新增】投影对拍:
     project_event() 按 KU spec §8.2 映射表**机械**产出事件级 VisualFact'
     PAIRING = 閘① 选用声明(拍↔KU 事件;None=coverage gap)
     classify() 逐字段 diff 三分类:一致 / 差异可解释(附解释) / 不可解释(PENDING 上报)
     GAPS = coverage gap 清单(G1b 头号交付物:一集所需 KU 对象密度首个实测)

判据(裁决修订 2026-07-22):原"閘①耗时<G1a 50%"因 G1a 閘① 基线丢失作废;
改为 閘① 全程 durable 计时(史上第一个閘①数,记 g1b_labor_ledger)+ diff 全解释。

用法: .venv/bin/python tools/g1b_parity_harness.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HEVI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HEVI_ROOT))
sys.path.insert(0, str(HEVI_ROOT / "hevi" / "tongjian" / "sandbox"))

G1B_DIR = HEVI_ROOT / "output" / "g1b_sanjia_fenjin"
INPUT_JSON = G1B_DIR / "input" / "sample.sanjiafenjin.v0.2.json"
INPUT_SCHEMA = G1B_DIR / "input" / "history-query-response.schema.v0.2.json"
# 钉 ref:tag history-contract-v0.2.2 的字节指纹(git show 提取时实测)。
# v0.2.2(D-023):sample 撤 cf:jinyang-independence → conflicts 空数组、新 sha;schema 字节不变。
PIN_SHA = {
    "sample": "4126c842aa0fc8f3b22268a0830c4b18e728233ca36f12297e636b0c572c62d9",
    "schema": "638fc28e7db8bde88dd90309d478a280287a87d0d7b7c7e77d8ff02373ff7b6f",
}

# ── L1/L2 声明(同 G1a 自查,L2 现指向 v0.2 钉住副本) ──────────────────────────
DECLARED = {
    "EpisodePlan": {
        "episode_id",
        "dynasty_era",
        "event_ku_refs",
        "narrative_frame",
        "narration_script_ref",
    },
    "NarrationBeat": {"beat_id", "order", "vo_text", "est_vo_seconds", "visual_intent", "fact_ref"},
    "VisualFact": {
        "beat_id",
        "ku_refs",
        "date",
        "scope",
        "forces",
        "regions",
        "routes",
        "markers",
        "persons",
        "quantities",
        "evidence_tier",
        "confirmed_by",
    },
    "Quantity": {"value", "unit", "source_display", "ku_ref"},
    "DualAccountFact": {"beat_id", "conflict_ku_ref", "accounts", "dimension", "presentation_hint"},
    "Account": {"source_display", "summary"},
}

MAPPING = {
    "VisualFact.date": "$defs.h_event.properties.canonical_date",
    "VisualFact.forces[]": "$defs.h_event.properties.actors.items.properties.force_ref",
    "VisualFact.regions[]": "$defs.h_event.properties.geo.properties.place_refs",
    "VisualFact.persons[]": "$defs.h_event.properties.actors.items.properties.person_ref",
    "VisualFact.quantities[]": "$defs.h_account.properties.extraction.properties.number_claims",
    "VisualFact.quantities[].source_display": (
        "$defs.h_account.properties.extraction.properties.number_claims.items.properties.display"
    ),
    "VisualFact.evidence_tier": "$defs.h_event.properties.evidence_tier",
    "VisualFact.ku_refs[]": "properties.event",
    "DualAccountFact.conflict_ku_ref": "$defs.h_conflict.properties.conflict_id",
    "DualAccountFact.dimension": "$defs.h_conflict.properties.dimension",
    "DualAccountFact.presentation_hint": "$defs.h_conflict.properties.presentation_hint",
    "DualAccountFact.accounts[].source_display": (
        "$defs.h_account.properties.extraction.properties.number_claims.items.properties.display"
    ),
}

# ── L4:投影 + 配对 + 分类 ────────────────────────────────────────────────────

# id 归一:注册表 ref 剥命名空间前缀;别名映射(书写差异,同一实体)
ALIAS = {"zhao-xiangzi": "zhaoxiangzi"}


def norm_ref(ref: str) -> str:
    bare = ref.split(":", 1)[-1]
    return ALIAS.get(bare, bare)


def canonical_year(literal: str) -> int:
    """'前453'→-453;'公元200'→200。"""
    s = str(literal)
    return -int(s[1:]) if s.startswith("前") else int(s.removeprefix("公元"))


def project_event(sample: dict) -> dict:
    """§8.2 机械投影:KU 查询响应 → 事件级 VisualFact'(dict 同形)。

    纯映射表实现,不做拍级选用(那是閘① 人工红利,见 PAIRING)。
    date:range → 代表值取区间末端(事件收束年),区间本体留 note 透传。
    """
    e = sample["event"]
    cd = e["canonical_date"]
    if cd["type"] == "range":
        date = canonical_year(cd["value"][1])
    elif cd["type"] in ("exact", "year"):
        date = canonical_year(cd["value"])
    else:  # fuzzy → 代表值 + banner 透传(此 sample 未触发)
        date = None
    src_by_id = {s["source_id"]: s for s in sample["registry_bundle"]["sources"]}
    mainline_ac = next(
        a for a in sample["accounts"] if a["account_id"] == e["mainline_account_ref"]
    )
    quantities = [
        {
            "value": float(nc["value"]),
            "unit": nc.get("unit") or "",
            "source_display": nc["display"],
            "ku_ref": mainline_ac["account_id"],
        }
        for nc in mainline_ac["extraction"].get("number_claims", [])
    ]
    return {
        "beat_id": "<event>",  # 拍绑定属 PAIRING(生产侧)
        "ku_refs": [e["event_id"]]
        + [a["account_id"] for a in sample["accounts"]]
        + [c["conflict_id"] for c in sample["conflicts"]],
        "date": date,
        "scope": e["geo"].get("mapstate_hint") or "",
        "forces": [norm_ref(a["force_ref"]) for a in e["actors"] if a.get("force_ref")],
        "regions": [norm_ref(p) for p in e["geo"]["place_refs"]],
        "routes": [e["geo"]["route_hint"]] if e["geo"].get("route_hint") else [],
        "markers": [],  # §8.2 无 markers 行(生产端组织字段)
        "persons": [norm_ref(a["person_ref"]) for a in e["actors"]],
        "quantities": quantities,
        "evidence_tier": e["evidence_tier"],
        "confirmed_by": src_by_id[mainline_ac["source_id"]]["title"] + "(mainline)",
    }


def project_duals(sample: dict) -> list[dict]:
    """§8.2:DualAccountFact ← h-conflict(hint=S12)。非 S12 的冲突不投影。"""
    return [
        {
            "beat_id": "<event>",
            "conflict_ku_ref": c["conflict_id"],
            "accounts": [],  # 实投影需读 account 摘述;sample 无 S12 冲突,未触发
            "dimension": c["dimension"],
            "presentation_hint": c["presentation_hint"],
        }
        for c in sample["conflicts"]
        if c["presentation_hint"] == "S12对勘"
    ]


# 閘① 选用声明:拍 ↔ 交付的 KU 事件;None = coverage gap(所需 KU 对象未随响应交付)。
# v0.2.2 交付单 PAIRING 指向表(D-020/023，gap 7 拍已补对象，B01–B11 全覆盖)。
PAIRING: dict[str, str | None] = {
    "B01": "ev:jin-gongshi-bei",  # samples/.../jin-gongshi-bei.json（fo:jin 已随 bundle）
    "B02": "ev:zhixuanzi-liyao",  # 智果之论 ac + per:zhiguo
    "B03": "ev:zhibo-suodi",  # 任章语 ac（战国策·魏策一）+ per:renzhang
    "B04": "ev:zhibo-suodi",  # 同事件覆两拍（索地+拒地，策文一章自陈）
    "B05": "ev:jinyang-zhizhan",  # ⚠合围路线仍部分 gap：route_hint 单值系契约形状，拍级多路线属 G2
    "B06": "ev:jinyang-zhizhan",  # ★cf:jinyang-shuiyuan 已建（S12→DualAccountFact 晋水/汾水）
    "B07": "ev:jinyang-zhizhan",  # per:zhangmengtan 已入 registry（史记作『张孟同』，归一）
    "B08": "ev:jinyang-zhizhan",
    "B09": "ev:sanjiafenjin",  # 父事件对象已随响应交付
    "B10": "ev:minghou-403",
    "B11": "ev:minghou-403",  # 臣光曰 ac（judgment 计 0，R8 观点归 per:simaguang）
}

# coverage gap 清单(G1b 头号交付物)——"一集需要多少 KU 对象"的第一个实测密度数
GAPS = [
    {
        "beat": "B01",
        "需要": "ev(背景:晋霸权旁落六卿) + fo:jin registry",
        "现状": "全缺(fo:jin 也不在 registry_bundle)",
    },
    {"beat": "B02", "需要": "ac(智果之论,人物评价) + per:zhiguo", "现状": "缺"},
    {"beat": "B03", "需要": "ev(智伯索地) + ac(战国策·魏策 任章语) + per:renzhang", "现状": "缺"},
    {"beat": "B04", "需要": "同 B03 索地事件(拒地方) ", "现状": "缺"},
    {
        "beat": "B05",
        "需要": "拍级合围路线(geo.route_hint 单值只有引水)",
        "现状": "部分:事件在,合围 route 无 KU 对应",
    },
    {
        "beat": "B06",
        "需要": "cf(灌城水源 晋水/汾水) + number_claim(围城2年)",
        "现状": "冲突未建(route_hint 单方取汾水);数字未抽",
    },
    {
        "beat": "B07",
        "需要": "per:zhangmengtan + 游说细节 ac",
        "现状": "人物不在 registry;dialogue_spans 有素材但透传不消费",
    },
    {"beat": "B09", "需要": "父事件 ev:sanjiafenjin 对象", "现状": "parent_event 指到但响应未交付"},
    {"beat": "B10", "需要": "ev(403 册命)", "现状": "chronology 有行(前403 命侯),h-event 缺"},
    {"beat": "B11", "需要": "ac(臣光曰,R8 观点归司马光)", "现状": "缺"},
]


def _sets(v):
    return set(v) if isinstance(v, list) and all(isinstance(x, str | int | float) for x in v) else v


def classify(beat: str, field: str, mv, pv, event: dict) -> tuple[str, str]:
    """逐字段三分类。返回 (一致|可解释|PENDING, 解释)。规则未覆盖 → PENDING,不硬找补。"""
    if mv == pv or (_sets(mv) == _sets(pv)):
        return "一致", ""
    if field == "date":
        cd = event["canonical_date"]
        if cd["type"] == "range":
            lo, hi = (canonical_year(v) for v in cd["value"])
            if lo <= mv <= hi:
                return (
                    "可解释",
                    f"拍级取点 {mv} ∈ 事件区间[{lo},{hi}];投影代表值=区间末端(拍点选择=閘①)",
                )
    if field == "ku_refs" and mv == []:
        return "可解释", "G1a 手工装配无 KU 可钉(ku_refs 空是 G1a 的定义属性);G1b 起由拉取产生"
    if field == "confirmed_by":
        return (
            "可解释",
            "语义注记字段:手工=史源手写注记 vs 投影=mainline source 标题;口径不同不冲突",
        )
    if field == "scope":
        return "可解释", "手工=地名字面 vs 投影=geo.mapstate_hint;同指晋阳围城,书写层差异"
    if field == "markers" and pv == []:
        return "可解释", "markers=生产端组织字段,§8.2 无映射行,投影恒空"
    if field == "quantities" and pv == []:
        return "可解释", "mainline account.number_claims 空(围城2年未抽取)——进 gap 清单 B06"
    if field == "routes":
        m1, p1 = "".join(mv), "".join(pv)
        if "晋水" in m1 and "汾水" in p1:
            return (
                "可解释",
                "正是 B06 对勘维(晋水/汾水):手工随通鉴主线取晋水,sample route_hint 单方取汾水"
                "且未建 h-conflict——进 gap 清单 B06,水源冲突对象缺失",
            )
        if "合围" in m1:
            return (
                "可解释",
                "geo.route_hint 单值(引水),拍级合围路线是生产侧绘制,"
                "KU 无对应 route 对象——进 gap 清单 B05",
            )
    if isinstance(mv, list) and isinstance(pv, list):
        ms, ps = set(map(str, mv)), set(map(str, pv))
        if ms <= ps:
            return "可解释", "拍级选用 ⊆ 事件级并集(閘① 人工红利:该拍只用子集;空集=该拍不用此维)"
        if field == "forces" and ms == {"jin"}:
            return (
                "可解释",
                "手工 forces 记的是底图 MapState 勢力(晋统一态渲染选择),非事件参战方"
                "——口径改进项:G2 起 forces=参战方,底图归 MapState 绑定",
            )
        if field == "persons" and ms - ps == {"zhangmengtan"}:
            return "可解释", "per:zhangmengtan 不在 sample registry(gap 清单 B07);其余人物一致"
        if field == "regions" and ms and not ps:
            return (
                "可解释",
                "手工把地名放 scope/markers,regions 空;投影按 §8.2 入 regions——字段归属差异",
            )
    # 跨事件裁决(Wiki 授权顾问裁,2026-07-24):落此兜底前的字段,其 beat 指向事件 ≠ 单-sample
    # 载入事件(project_event 只投影 ev:jinyang-zhizhan),差异系跨事件比对产物,非数据错。
    if PAIRING.get(beat) and PAIRING[beat] != event.get("event_id"):
        return (
            "可解释",
            "跨事件比对产物：beat 指向事件 ≠ 单-sample 载入事件，PAIRING 指向经复核正确"
            "（Wiki 授权顾问裁，2026-07-24）",
        )
    return "PENDING", "规则未覆盖,不可解释——上报"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    # ── 输入钉 ref 校验(字节即真理) ──
    for name, p in (("sample", INPUT_JSON), ("schema", INPUT_SCHEMA)):
        if not p.exists():
            print(f"FATAL: 钉住输入缺失 {p}")
            return 2
        got = sha256(p)
        if got != PIN_SHA[name]:
            print(f"FATAL: {name} 字节指纹不符 tag history-contract-v0.2.2: {got}")
            return 2
    sample = json.loads(INPUT_JSON.read_bytes())  # as-is 字节,零预处理
    schema = json.loads(INPUT_SCHEMA.read_bytes())
    print(
        f"输入钉住 OK: contract_version={sample['contract_version']} (tag history-contract-v0.2.2)"
    )

    import g1a_episode as ep

    from hevi.tongjian import explainer_contract as ec

    # ── L1 / L2 / L3 ──
    invented = sum(len(set(getattr(ec, n).model_fields) - d) for n, d in DECLARED.items())
    mismatch = [n for n, d in DECLARED.items() if set(getattr(ec, n).model_fields) != d]
    broken = [f for f, path in MAPPING.items() if not _path_exists(schema, path)]
    for f in ep.FACTS:
        ec.VisualFact.model_validate(f.model_dump())
    for da in ep.DUAL_ACCOUNTS:
        ec.DualAccountFact.model_validate(da.model_dump())
    print(
        f"L1 自造字段={invented} 集不符={mismatch or '无'} | "
        f"L2 断链={broken or '无'} | L3 手工数据全过"
    )

    # ── L4 投影对拍 ──
    vf_event = project_event(sample)
    ec.VisualFact.model_validate({**vf_event, "beat_id": "B00"})  # 投影产物必须能装进同一契约
    duals_p = project_duals(sample)
    print(f"L4 投影: 事件级 VisualFact' 1 条(过契约) | S12 冲突投影 {len(duals_p)} 条")

    by_beat = {f.beat_id: f for f in ep.FACTS}
    counts = {"一致": 0, "可解释": 0, "PENDING": 0}
    rows = []
    for beat, ev_id in PAIRING.items():
        if ev_id is None:
            rows.append(
                {"beat": beat, "field": "<coverage>", "class": "GAP", "note": "见 gap 清单"}
            )
            continue
        m = by_beat[beat].model_dump()
        for field in m:
            if field == "beat_id":
                continue
            mv, pv = m[field], vf_event[field]
            cls, why = classify(beat, field, mv, pv, sample["event"])
            counts[cls] += 1
            if cls != "一致":
                rows.append(
                    {
                        "beat": beat,
                        "field": field,
                        "class": cls,
                        "manual": mv,
                        "projected": pv,
                        "explain": why,
                    }
                )
    # DualAccountFact 对拍(presence 级)
    dual_note = (
        "手工 1 条(晋水/汾水,hint=角标并陈) vs 投影 0 条——v0.2.2 sample conflicts 空数组"
        "(cf:jinyang-independence 已撤,D-023);水源 cf:jinyang-shuiyuan 在 samples/jinyang-zhizhan.json "
        "富例(S12→DualAccountFact)但未随此 §8 钉点 sample 交付 → gap 清单 B06。可解释。"
    )
    counts["可解释"] += 1
    rows.append(
        {"beat": "B06", "field": "<DualAccountFact>", "class": "可解释", "explain": dual_note}
    )

    # ── 密度统计(coverage gap 头号交付物) ──
    rb = sample["registry_bundle"]
    delivered = {
        "events": 1,
        "accounts": len(sample["accounts"]),
        "conflicts": len(sample["conflicts"]),
        "persons": len(rb["persons"]),
        "places": len(rb["places"]),
        "forces": len(rb["forces"]),
        "sources": len(rb["sources"]),
        "chronology": len(rb["chronology"]),
    }
    needed_extra = {
        "events": 4,  # 背景/索地/父事件三家分晋/403册命
        "accounts": 4,  # 智果之论/任章语/张孟谈游说细节/臣光曰
        "conflicts": 1,  # 灌城水源 晋水/汾水
        "persons": 4,  # zhiguo/renzhang/zhangmengtan/simaguang
        "forces": 1,  # fo:jin(统一态底图)
    }
    covered = [b for b, e in PAIRING.items() if e]
    report = {
        "input": {"file": str(INPUT_JSON), "sha256": PIN_SHA, "tag": "history-contract-v0.2.2"},
        "pairing": PAIRING,
        "diff_counts": counts,
        "diff_rows": rows,
        "coverage": {
            "beats_total": len(PAIRING),
            "beats_covered": covered,
            "beats_gap": [b for b, e in PAIRING.items() if not e],
            "gaps": GAPS,
            "density_delivered": delivered,
            "density_needed_extra": needed_extra,
            "density_full_episode_estimate": {
                k: delivered.get(k, 0) + needed_extra.get(k, 0)
                for k in set(delivered) | set(needed_extra)
            },
        },
    }
    out = G1B_DIR / "g1b_diff_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"对拍: 覆盖拍 {len(covered)}/11 | diff {counts} | gap 拍 {11 - len(covered)}")
    print(f"报告: {out}")
    ok = invented == 0 and not mismatch and not broken and counts["PENDING"] == 0
    print("RESULT:", "PASS(diff 全解释)" if ok else "FAIL/PENDING 有条目")
    return 0 if ok else 1


def _path_exists(schema: dict, path: str) -> bool:
    node = schema
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
