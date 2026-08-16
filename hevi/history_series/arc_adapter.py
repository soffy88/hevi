"""arc_adapter —— §8 契约 → tongjian RunRequest 组装 (G1a, P0 已验证)。"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CLASSICAL_TEXTS: dict[tuple[str, str], str] = {
    ("src:shiji", "赵世家"): (
        "知伯益驕，請地韓、魏，韓、魏與之。請地趙，趙弗與。知伯怒，遂率韓、魏攻趙。"
        "趙襄子懼，乃奔保晉陽。三國攻晉陽，歲餘，引汾水灌其城，城不浸者三版。"
        "城中懸釜而炊，易子而食。襄子夜使人見張孟同，陰與韓、魏約。"
        "韓、魏反，與趙合謀，攻滅知氏，盡并其地。"),
    ("src:zztj", "周纪一"): (
        "智伯請地於韓康子…又求地於魏桓子…又求藺、皋狼之地於趙襄子，襄子弗與。"
        "智伯怒，帥韓、魏之甲以攻趙氏。趙襄子乃走晉陽。三國攻晉陽，引汾水灌之…"
        "襄子使張孟談潛出見韓、魏…反滅智伯，盡滅智氏之族，三分其地。"),
    ("src:zhanguoce", "赵策一"): (
        "知伯帥趙、韓、魏而伐范、中行氏，滅之…又請地於趙，趙襄子弗與。"
        "知伯陰結韓、魏，將以伐趙。趙襄子乃召張孟談而告之，走晉陽。"
        "張孟談乃潛行而出…韓、魏之君乃與孟談陰約…反知氏，滅之。"),
}

def _mainline_account(contract: dict[str, Any]) -> dict[str, Any]:
    accounts = {a.get("account_id"): a for a in contract.get("accounts") or []}
    main_ref = (contract.get("event") or {}).get("mainline_account_ref")
    if main_ref:
        return accounts.get(main_ref) or {}
    return next(iter(accounts.values()), {})

def _account_text(account: dict[str, Any]) -> str:
    src, loc = account.get("source_id", ""), account.get("locator") or {}
    text = _CLASSICAL_TEXTS.get((src, loc.get("chapter", "")), "")
    if not text:
        claims = (account.get("extraction") or {}).get("actor_claims") or []
        text = "；".join(claims)
    return text

def _source_label(account: dict[str, Any]) -> str:
    loc = account.get("locator") or {}
    book, chapter = loc.get("book", ""), loc.get("chapter", "")
    return f"{book}·{chapter}" if chapter else book or account.get("source_id", "?")

def assemble_run_request(contract: dict[str, Any], *, textbook_text: str = "",
                         target_duration_sec: int = 120, aspect_ratio: str = "16:9",
                         pause_after: str | None = None) -> dict[str, Any]:
    event = contract.get("event") or {}
    accounts = contract.get("accounts") or []
    conflicts = contract.get("conflicts") or []
    registry = contract.get("registry_bundle") or {}
    main = _mainline_account(contract)
    main_note = "（教材主述）" if textbook_text else f"（{_source_label(main)} 主述）"
    main_text = textbook_text or _account_text(main)
    exclude = set() if textbook_text else {main.get("account_id")}
    supplementary = [
        f"（并陈）《{_source_label(acct)}》{t}"
        for acct in accounts
        if acct.get("account_id") not in exclude and (t := _account_text(acct))
    ]
    corner_notes = []
    for cf in conflicts:
        if "角标" in (cf.get("presentation_hint") or ""):
            reasoning = (cf.get("independence_analysis") or {}).get("reasoning", "")
            corner_notes.append(f"[并陈角标]{reasoning}")
    raw_parts = [f"{main_text}{main_note}", *supplementary, *corner_notes]
    layer_config: dict[str, Any] = {}
    persons = {p.get("person_id"): p for p in registry.get("persons") or []}
    if persons:
        layer_config["L1"] = {"character_refs": [
            {"ref": pid, "names": list((p.get("names_by_source") or {}).keys())}
            for pid, p in persons.items()]}
    req = {"source_name": f"历史现场·{event.get('title','')}",
           "raw_text": "\n".join(p for p in raw_parts if p),
           "target_duration_sec": target_duration_sec, "aspect_ratio": aspect_ratio,
           "layer_config": layer_config}
    if pause_after:
        req["pause_after"] = pause_after
    return req

def dump_g1a_report(contract: dict[str, Any], run_request: dict[str, Any]) -> dict[str, Any]:
    event = contract.get("event") or {}
    main = _mainline_account(contract)
    return {"contract_version": contract.get("contract_version"),
            "event_id": event.get("event_id"), "event_title": event.get("title"),
            "mainline_account": main.get("account_id"), "mainline_source": _source_label(main),
            "n_accounts": len(contract.get("accounts") or []),
            "n_conflicts": len(contract.get("conflicts") or []),
            "registry_persons": len((contract.get("registry_bundle") or {}).get("persons") or []),
            "source_name": run_request["source_name"],
            "raw_text_len": len(run_request["raw_text"])}
