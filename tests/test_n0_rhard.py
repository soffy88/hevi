"""R-hard(HEVI-N0-DUALAGENT-SPEC-001 §3) 单测——确定性硬门。
含故意违例稿：无 ref 数字(H3)/池 id 引用(H4)/quote 篡字(H2)/transition 超限(H8)。
"""

from __future__ import annotations

from hevi.n0.rhard import run_rhard


def _valid() -> tuple[dict, dict]:
    """s1 曲沃代翼 合规 ScriptDraft + refs（应全门 PASS）。"""
    refs = {
        "corpus": {
            "u:0205": "惠之二十四年晉始亂封桓叔於曲沃欒賓傅之",
            "u:0217": "曲沃武公伐翼逐翼侯於汾隰",
        },
        "ku_events": {"ev:quwo-feng-huanshu": {}, "ev:quwo-wugong-mie-yi": {}},
        "ku_accounts": {},
        "theses": {"thesis:shifu-modabizhe": {}},
        "chronology": {},
        "number_claims": {"nc:quwo-67years": {}},
        "name_registry": {"桓叔", "武公", "翼", "曲沃", "汾隰", "栾宾", "师服"},
        "pool_ids": {"cand:pool-orphan"},
        "e_tiers": {"ev:quwo-feng-huanshu": "E2", "ev:quwo-wugong-mie-yi": "E2"},
        "episode_plan": {
            "beat_ids": ["s1-b1", "s1-b2"],
            "counterpoint_theses": [],
            "counterpoint_search_record": {"claim": "源内仅师服一说", "searched": ["左传桓2"]},
            "s12_conflicts": [],
            "beat_events": {
                "s1-b1": ["ev:quwo-feng-huanshu"],
                "s1-b2": ["ev:quwo-wugong-mie-yi"],
            },
        },
    }
    draft = {
        "episode_ref": "ep:jin-decline-s1",
        "beats": [
            {
                "beat_id": "s1-b1",
                "sentences": [
                    {
                        "sid": "s1-b1-1",
                        "type": "fact",
                        "text": "晋始乱，封桓叔于曲沃，栾宾傅之。",
                        "fact_refs": ["ev:quwo-feng-huanshu"],
                        "thesis_refs": [],
                        "quote": {"ulid": "u:0205", "text": "封桓叔於曲沃"},
                        "entities": ["桓叔", "曲沃", "栾宾"],
                        "display": {"source_display": "《左传·桓公二年》"},
                    },
                    {
                        "sid": "s1-b1-2",
                        "type": "thesis",
                        "text": "按师服，本大末小则固，晋建国而本弱其能久乎，末大必折。",
                        "fact_refs": [],
                        "thesis_refs": ["thesis:shifu-modabizhe"],
                        "entities": ["师服"],
                        "display": {"attribution": "我方按（师服·左传）"},
                    },
                ],
            },
            {
                "beat_id": "s1-b2",
                "sentences": [
                    {
                        "sid": "s1-b2-1",
                        "type": "fact",
                        "text": "曲沃武公伐翼，逐翼侯于汾隰，终并大宗。",
                        "fact_refs": ["ev:quwo-wugong-mie-yi"],
                        "thesis_refs": [],
                        "quote": {"ulid": "u:0217", "text": "逐翼侯於汾隰"},
                        "entities": ["武公", "翼", "汾隰"],
                        "display": {"source_display": "《左传·桓公三年》"},
                    },
                    {
                        "sid": "s1-b2-2",
                        "type": "thesis",
                        "text": "曲沃三世历六十七年终并大宗，末大必折之应也。",
                        "fact_refs": [],
                        "thesis_refs": ["thesis:shifu-modabizhe"],
                        "number_refs": ["nc:quwo-67years"],
                        "entities": [],
                        "display": {"attribution": "我方按"},
                    },
                    {
                        "sid": "s1-b2-3",
                        "type": "transition",
                        "text": "下启六卿坐大。",
                        "fact_refs": [],
                        "thesis_refs": [],
                    },
                ],
            },
        ],
        "meta": {"model": "test", "prompt_ver": "v0", "cost": 0.0},
    }
    return draft, refs


def test_valid_draft_all_pass() -> None:
    draft, refs = _valid()
    rep = run_rhard(draft, refs)
    assert rep["pass"] is True, rep["failures"]
    assert all(v == "PASS" for v in rep["by_gate"].values())


def test_h3_number_without_ref_fails() -> None:
    """故意违例：句含非引文数字(六十七)但去掉 number_refs → H3 FAIL。"""
    draft, refs = _valid()
    del draft["beats"][1]["sentences"][1]["number_refs"]  # 去数字 ref
    rep = run_rhard(draft, refs)
    assert rep["pass"] is False
    assert rep["by_gate"]["H3"] == "FAIL"
    assert any(f["gate"] == "H3" and f["sid"] == "s1-b2-2" for f in rep["failures"])


def test_h4_pool_id_reference_fails() -> None:
    """故意违例：fact_ref 引用原料池 id(OP-D-054 不可引) → H4 FAIL。"""
    draft, refs = _valid()
    draft["beats"][0]["sentences"][0]["fact_refs"] = ["cand:pool-orphan"]
    rep = run_rhard(draft, refs)
    assert rep["pass"] is False
    assert rep["by_gate"]["H4"] == "FAIL"
    assert any(f["gate"] == "H4" and "原料池" in f["reason"] for f in rep["failures"])


def test_h2_quote_tampered_fails() -> None:
    """故意违例：quote 篡字(汾隰→汾水) → 不逐字命中语料 → H2 FAIL。"""
    draft, refs = _valid()
    draft["beats"][1]["sentences"][0]["quote"]["text"] = "逐翼侯於汾水"
    rep = run_rhard(draft, refs)
    assert rep["pass"] is False
    assert rep["by_gate"]["H2"] == "FAIL"
    assert any(f["gate"] == "H2" and f["sid"] == "s1-b2-1" for f in rep["failures"])


def test_h8_transition_over_limit_fails() -> None:
    """故意违例：加 transition 句使占比 >20% → H8 FAIL。"""
    draft, refs = _valid()
    extra = [
        {"sid": "x1", "type": "transition", "text": "又。", "fact_refs": [], "thesis_refs": []},
        {"sid": "x2", "type": "transition", "text": "再。", "fact_refs": [], "thesis_refs": []},
    ]
    draft["beats"][1]["sentences"].extend(extra)  # 3/7 transition ≈43%
    rep = run_rhard(draft, refs)
    assert rep["pass"] is False
    assert rep["by_gate"]["H8"] == "FAIL"
    assert any(f["gate"] == "H8" and "transition" in f["reason"] for f in rep["failures"])


def test_h1_thesis_missing_attribution_fails() -> None:
    """附加：thesis 句缺 attribution → H1 FAIL(R8/R10 双溯源)。"""
    draft, refs = _valid()
    draft["beats"][0]["sentences"][1]["display"] = {}
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H1"] == "FAIL"
    assert any(f["gate"] == "H1" and "attribution" in f["reason"] for f in rep["failures"])


def test_h6_counterpoint_no_search_record_fails() -> None:
    """附加：counterpoint 空且无检索记录 → H6 FAIL(OP-D-045)。"""
    draft, refs = _valid()
    del refs["episode_plan"]["counterpoint_search_record"]
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H6"] == "FAIL"
