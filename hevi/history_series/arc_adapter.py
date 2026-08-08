"""history_series.arc_adapter —— §8 契约 → tongjian RunRequest 组装（G1a）。

P0 目标：用 stratum 冻结的 §8 契约数据（contracts/sample.sanjiafenjin.json 等
手工装配同形数据）跑通 hevi 消费路径，与真实 KU 实装后（G1b）逐字段对拍。

组装规则（HISTORY-TEXTBOOK-MAINLINE-CC-SPEC-001 §4，承 AII-HISTORY-KU-SPEC-001 §8）：
  source_name : 历史现场·<event.title>
  raw_text    : 主述 account 文言原文（教材 KU 实装后=教材述；G1a=古籍 mainline）
                + 并陈 account 原文（各标《书·篇》出处）
  conflicts   : presentation_hint=主线+角标 → 并陈角标素材追加进 raw_text
  registry    : persons/places/chronology → constitution 注入（角色别名/年代约束）

原文来源：G1a 用内置《CLASSICAL_TEXTS》表（手工占位，标 G1a-MANUAL）；
G1b 实装后由 stratum 段落级 ULID 提供（承 §D2），本表退役。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── G1a 手工文言原文表（G1b 由语料层段落级 ULID 取代）──────────────────
_CLASSICAL_TEXTS: dict[tuple[str, str], str] = {
    ("src:shiji", "赵世家"): (
        "知伯益驕，請地韓、魏，韓、魏與之。請地趙，趙弗與。知伯怒，遂率韓、魏攻趙。"
        "趙襄子懼，乃奔保晉陽。三國攻晉陽，歲餘，引汾水灌其城，城不浸者三版。"
        "城中懸釜而炊，易子而食。襄子夜使人見張孟同，陰與韓、魏約。"
        "韓、魏反，與趙合謀，攻滅知氏，盡并其地。"
    ),
    ("src:zztj", "周纪一"): (
        "智伯請地於韓康子，康子欲弗與。段規曰：「智伯好利而愎，不與，將伐我；不如與之。」"
        "康子曰：「善。」使使者致萬家之邑於智伯，智伯悅。又求地於魏桓子，桓子欲弗與。"
        "任章曰：「無故索地，諸大夫必懼；吾與之地，智伯必驕。彼驕而輕敵，此懼而相親。"
        "以相親之兵待輕敵之人，智氏之命必不長矣。」桓子曰：「善。」復與之萬家之邑一。"
        "智伯又求藺、皋狼之地於趙襄子，襄子弗與。智伯怒，帥韓、魏之甲以攻趙氏。"
        "趙襄子乃走晉陽。三國攻晉陽，引汾水灌之，城不浸者三版，城中巢居而處，懸釜而炊。"
        "襄子使張孟談潛出見韓、魏，韓、魏與趙合謀，反滅智伯，盡滅智氏之族，三分其地。"
    ),
    ("src:zhanguoce", "赵策一"): (
        "知伯帥趙、韓、魏而伐范、中行氏，滅之。休數年，使人請地於韓，韓康子欲勿與。"
        "知伯益驕，又請地於魏，魏桓子欲勿與。又請地於趙，趙襄子弗與。"
        "知伯陰結韓、魏，將以伐趙。趙襄子乃召張孟談而告之，走晉陽。"
        "三國之兵乘晉陽城，遂戰。三月不能拔，因舒軍而圍之，決晉水而灌之。"
        "城之不沈者三板耳。城中巢居而處，懸釜而炊，財食將盡，士卒病羸。"
        "張孟談乃潛行而出，見韓、魏之君，曰：「臣聞唇亡則齒寒。」"
        "韓、魏之君乃與孟談陰約，與之期日，反知氏，滅之。"
    ),
}


def _mainline_account(contract: dict[str, Any]) -> dict[str, Any]:
    """主述 account：event.mainline_account_ref 指向的那个。"""
    accounts = {a.get("account_id"): a for a in contract.get("accounts") or []}
    main_ref = (contract.get("event") or {}).get("mainline_account_ref")
    if main_ref and main_ref in accounts:
        return accounts[main_ref]
    # 兜底：第一个 account（契约保证有 mainline_decision）
    return next(iter(accounts.values()), {})


def _account_text(account: dict[str, Any]) -> str:
    """account → 文言原文：G1a 内置表按 (source_id, chapter) 取。"""
    src = account.get("source_id") or ""
    loc = (account.get("locator") or {})
    chapter = loc.get("chapter") or ""
    text = _CLASSICAL_TEXTS.get((src, chapter), "")
    if not text:
        # 兜底：extraction 白话 claims 拼装（无原文时的保底，标注非原文）。
        claims = (account.get("extraction") or {}).get("actor_claims") or []
        text = "；".join(claims)
        if text:
            text = f"[白话述（G1a 无原文兜底）]{text}"
    return text


def assemble_run_request(
    contract: dict[str, Any],
    *,
    textbook_text: str = "",
    target_duration_sec: int = 180,
    aspect_ratio: str = "16:9",
    pause_after: str | None = None,
) -> dict[str, Any]:
    """§8 契约 → tongjian RunRequest（POST /api/tongjian/run body）。

    textbook_text: 教材主述原文（D5；教材 KU 实装后传入，此时主述=教材，
    古籍 account 一律作并陈；G1a 传空 → 主述=契约 mainline account）。
    """
    event = contract.get("event") or {}
    accounts = contract.get("accounts") or []
    conflicts = contract.get("conflicts") or []
    registry = contract.get("registry_bundle") or {}

    main = _mainline_account(contract)
    main_text = textbook_text or _account_text(main)
    main_note = "（教材主述）" if textbook_text else f"（{_source_label(main)} 主述）"

    # 并陈 account：除主述外的其余 account（教材主述时含古籍 mainline）。
    exclude = set() if textbook_text else {main.get("account_id")}
    supplementary: list[str] = []
    for acct in accounts:
        if acct.get("account_id") in exclude:
            continue
        text = _account_text(acct)
        if text:
            supplementary.append(f"《{_source_label(acct)}》{text}")

    # 冲突角标（presentation_hint=主线+角标 → 追加并陈说明）。
    corner_notes: list[str] = []
    for cf in conflicts:
        hint = (cf.get("presentation_hint") or "")
        if "角标" in hint or "并陈" in hint:
            reason = (cf.get("independence_analysis") or {}).get("reasoning") or ""
            corner_notes.append(f"[并陈角标]{reason}")

    raw_parts = [f"{main_text}{main_note}"]
    raw_parts += [f"（并陈）{s}" for s in supplementary]
    raw_parts += corner_notes
    raw_text = "\n".join(p for p in raw_parts if p)

    # registry → constitution 注入（角色别名/年代/地点，供 L1/L2 消费）。
    persons = {p.get("person_id"): p for p in registry.get("persons") or []}
    layer_config: dict[str, Any] = {}
    if persons:
        layer_config["L1"] = {
            "character_refs": [
                {"ref": pid, "names": list((p.get("names_by_source") or {}).keys())}
                for pid, p in persons.items()
            ]
        }

    return {
        "source_name": f"历史现场·{event.get('title') or '历史事件'}",
        "raw_text": raw_text,
        "target_duration_sec": target_duration_sec,
        "aspect_ratio": aspect_ratio,
        "layer_config": layer_config,
        **( {"pause_after": pause_after} if pause_after else {}),
    }


def _source_label(account: dict[str, Any]) -> str:
    loc = account.get("locator") or {}
    book = loc.get("book") or account.get("source_id") or "?"
    chapter = loc.get("chapter") or ""
    return f"{book}·{chapter}" if chapter else book


def dump_g1a_report(contract: dict[str, Any], run_request: dict[str, Any]) -> dict[str, Any]:
    """G1a 对拍报告：契约输入 → RunRequest 组装摘要（供人审）。"""
    event = contract.get("event") or {}
    main = _mainline_account(contract)
    return {
        "contract_version": contract.get("contract_version"),
        "event_id": event.get("event_id"),
        "event_title": event.get("title"),
        "mainline_account": main.get("account_id"),
        "mainline_source": _source_label(main),
        "n_accounts": len(contract.get("accounts") or []),
        "n_conflicts": len(contract.get("conflicts") or []),
        "registry_persons": len((contract.get("registry_bundle") or {}).get("persons") or []),
        "source_name": run_request["source_name"],
        "raw_text_len": len(run_request["raw_text"]),
        "raw_text_head": run_request["raw_text"][:160].replace("\n", " ⏎ "),
        "layer_config_keys": list(run_request.get("layer_config", {}).keys()),
    }


__all__ = ["assemble_run_request", "dump_g1a_report"]
