"""R-hard(HEVI-N0-DUALAGENT-SPEC-001 §3) 单测——确定性硬门。
含故意违例稿：无 ref 数字(H3)/池 id 引用(H4)/quote 篡字(H2)/transition 超限(H8)。
"""

from __future__ import annotations

from hevi.n0.rhard import anchor_quotes, run_rhard


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
            # H9：valid 稿 shifu 论点跨 2 拍呈现，显式允许(否则 H9 判 thesis_ref 重复)；
            # 无 beat_roles → H9 拍-role 检跳过(混合拍)。
            "allow_thesis_repeat": ["thesis:shifu-modabizhe"],
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


def test_h9_thesis_repeat_without_allow_fails() -> None:
    """同一 thesis_ref 全稿 >1 次且 EpisodePlan 未显式允许 → H9 FAIL(N0-D-005)。"""
    draft, refs = _valid()
    del refs["episode_plan"]["allow_thesis_repeat"]  # 撤销允许 → shifu 2 次触发
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H9"] == "FAIL"
    assert any(f["gate"] == "H9" and "呈现" in f["reason"] for f in rep["failures"])


def test_h9_beat_role_mismatch_fails() -> None:
    """fact-role plan 拍出现 thesis 句 → H9 FAIL(拍-role 不一致)。"""
    draft, refs = _valid()
    refs["episode_plan"]["beat_roles"] = {"s1-b1": "fact", "s1-b2": "fact"}  # b1 声明 fact
    # valid 的 s1-b1 含 thesis 句(b1-2) → 与 fact-role 冲突
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H9"] == "FAIL"
    assert any(f["gate"] == "H9" and "拍-role" in f["reason"] for f in rep["failures"])


def test_h2_unmarked_quote_bypass_fails() -> None:
    """句中引号 span 未挂 quote 对象(未标引文绕行)→ H2 扩门 FAIL(N0-D-006)。"""
    draft, refs = _valid()
    # 把 b1-2 的师服论断改成含『』引文却不挂 quote 对象
    draft["beats"][0]["sentences"][1]["text"] = "师服断言：『本大而末小是以能固』，末大必折。"
    draft["beats"][0]["sentences"][1].pop("quote", None)  # 不标 quote
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H2"] == "FAIL"
    assert any(f["gate"] == "H2" and "未标引文" in f["reason"] for f in rep["failures"])


def test_h4_quote_internal_name_exempt() -> None:
    """引文 span 内未注册人名 → H4 豁免 PASS(N0-D-007，源内逐字 H2 已保真)。"""
    draft, refs = _valid()
    refs["corpus"]["u:x"] = "王使尹氏武氏助之"
    draft["beats"][1]["sentences"].append(
        {
            "sid": "s1-b2-x",
            "type": "fact",
            "fact_refs": ["ev:quwo-wugong-mie-yi"],
            "thesis_refs": [],
            "text": "王使『尹氏』助伐。",
            "quote": {"ulid": "u:x", "text": "尹氏"},
            "entities": ["尹氏"],
            "display": {"source_display": "《左传》"},
        }
    )
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H4"] == "PASS", [f for f in rep["failures"] if f["gate"] == "H4"]


def test_h8_onscreen_quote_not_counted_vo() -> None:
    """长引文标 onscreen → 本体不计 VO(N0-D-010)；同拍配 vo 转述 → H8 PASS。"""
    draft, refs = _valid()
    long_q = (
        "本大而末小是以能固故天子建國諸侯立家卿置側室大夫有貳宗士有隸子弟庶人工商各有分親皆有等衰"
    )
    refs["corpus"]["u:long"] = long_q
    # b2 加一拍：onscreen 长引文(0 VO) + vo 白话转述句(供 VO)。
    draft["beats"].append(
        {
            "beat_id": "s1-b2",  # 复用 plan 拍(对齐)
            "sentences": [
                {
                    "sid": "os-1",
                    "type": "thesis",
                    "presentation": "onscreen",
                    "thesis_refs": [],
                    "fact_refs": ["ev:quwo-wugong-mie-yi"],
                    "text": long_q,
                    "quote": {"ulid": "u:long", "text": long_q},
                    "display": {"attribution": "按"},
                },
                {
                    "sid": "os-2",
                    "type": "fact",
                    "text": "师服此言，谓大宗小宗本末倒置则国不能固久也。",
                    "fact_refs": ["ev:quwo-wugong-mie-yi"],
                    "display": {"source_display": "《左传》"},
                },
            ],
        }
    )
    from hevi.n0.rhard import _sent_vo_secs

    assert _sent_vo_secs(draft["beats"][-1]["sentences"][0]) == 0.0  # onscreen 计 0
    rep = run_rhard(draft, refs)
    # onscreen 拍 VO 仅转述句(~4.4s?)——保证 onscreen 那 45 字引文没被算成 22.5s 超窗
    os_fail = [f for f in rep["failures"] if f["gate"] == "H8" and "22" in f["reason"]]
    assert not os_fail, rep["failures"]


def test_h8_onscreen_without_vo_reword_fails() -> None:
    """onscreen 引文拍缺白话转述(vo 口播句) → H8 FAIL(N0-D-010 画面有引文无人念)。"""
    draft, refs = _valid()
    long_q = (
        "本大而末小是以能固故天子建國諸侯立家卿置側室大夫有貳宗士有隸子弟庶人工商各有分親皆有等衰"
    )
    refs["corpus"]["u:long"] = long_q
    draft["beats"].append(
        {
            "beat_id": "s1-b2",
            "sentences": [
                {
                    "sid": "os-1",
                    "type": "thesis",
                    "presentation": "onscreen",
                    "thesis_refs": [],
                    "fact_refs": ["ev:quwo-wugong-mie-yi"],
                    "text": long_q,
                    "quote": {"ulid": "u:long", "text": long_q},
                    "display": {"attribution": "按"},
                },
            ],  # 只有 onscreen 引文、无 vo 转述
        }
    )
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H8"] == "FAIL"
    assert any(f["gate"] == "H8" and "转述" in f["reason"] for f in rep["failures"])


def test_failures_carry_executable_fix() -> None:
    """N0-D-011：每条 FAIL 带非空 fix 可执行修法。"""
    draft, refs = _valid()
    del draft["beats"][1]["sentences"][1]["number_refs"]  # H3
    draft["beats"][1]["sentences"][0]["quote"]["text"] = "逐翼侯於汾水"  # H2 篡字
    rep = run_rhard(draft, refs)
    assert rep["failures"], "应有失败"
    assert all(f.get("fix") for f in rep["failures"]), [
        f for f in rep["failures"] if not f.get("fix")
    ]


def test_h4_variant_normalized_pass_true_gap_fails() -> None:
    """N0-D-013：简繁变体(晉↔晋)归一后 PASS；真缺口(虢公)FAIL 且修法荐改述回避。"""
    draft, refs = _valid()
    refs["name_registry"].add("晋")  # 注册表存简体 canonical
    draft["beats"][0]["sentences"][0]["entities"] = ["晉", "虢公"]  # 晉=晋变体; 虢公真缺
    rep = run_rhard(draft, refs)
    h4names = [f["reason"].split(": ")[-1] for f in rep["failures"] if f["gate"] == "H4"]
    assert "晉" not in h4names, h4names  # 简繁变体归一命中 → 不报缺口
    fx = {f["reason"].split(": ")[-1]: f["fix"] for f in rep["failures"] if f["gate"] == "H4"}
    assert "虢公" in fx and "改述" in fx["虢公"], fx  # 真缺口 → 改述回避


def test_h8_fix_suggests_onscreen_for_long_quote() -> None:
    """H8 超窗且拍内有非 onscreen 长引文 → 修法首选标 onscreen + 补转述。"""
    draft, refs = _valid()
    long_q = (
        "本大而末小是以能固故天子建國諸侯立家卿置側室大夫有貳宗士有隸子弟庶人工商各有分親皆有等衰"
    )
    refs["corpus"]["u:long"] = long_q
    draft["beats"][0]["sentences"][0]["quote"] = {"ulid": "u:long", "text": long_q}
    draft["beats"][0]["sentences"][0]["text"] = long_q  # VO 长引文超窗
    rep = run_rhard(draft, refs)
    h8 = [f for f in rep["failures"] if f["gate"] == "H8" and "超窗" in f.get("fix", "")]
    assert h8 and "onscreen" in h8[0]["fix"], [f for f in rep["failures"] if f["gate"] == "H8"]


def test_h4_narration_name_strict() -> None:
    """同名(尹氏)出现在叙述句(无引文覆盖) → H4 严格 FAIL。"""
    draft, refs = _valid()
    draft["beats"][1]["sentences"].append(
        {
            "sid": "s1-b2-y",
            "type": "fact",
            "fact_refs": ["ev:quwo-wugong-mie-yi"],
            "thesis_refs": [],
            "text": "尹氏亦助伐翼。",
            "entities": ["尹氏"],
            "display": {"source_display": "《左传》"},
        }
    )
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H4"] == "FAIL"
    assert any(f["gate"] == "H4" and "尹氏" in f["reason"] for f in rep["failures"])


# ── N0-D-015 quote 自动锚定 ───────────────────────────────────────────────────
def _anchor_refs() -> dict:
    return {
        "corpus": {
            "u:shifu": "吾聞國家之立也本大而末小是以能固",
            "u:zheng": "夏五月鄭伯克段于鄢",
            "u:dup1": "本大而末小",  # 与 u:shifu 都含『本大而末小』→ 多命中
        }
    }


def _anchor_draft(text: str, sid: str = "s1") -> dict:
    sent = {"sid": sid, "type": "thesis", "text": text}
    return {"beats": [{"beat_id": "b1", "sentences": [sent]}]}


def test_anchor_unique_hit_auto_attaches() -> None:
    """引号内容 corpus 逐字唯一命中 → 自动挂 quote{ulid,text,auto_anchored},H2 过。"""
    refs = {"corpus": {"u:zheng": "夏五月鄭伯克段于鄢"}}
    draft = _anchor_draft("郑国亦上演『鄭伯克段于鄢』的兄弟相残。")
    anchored, reports = anchor_quotes(draft, refs)
    q = anchored["beats"][0]["sentences"][0]["quote"]
    q = q if isinstance(q, dict) else q[0]
    assert q["ulid"] == "u:zheng" and q["auto_anchored"] is True
    assert q["text"] == "鄭伯克段于鄢"  # 一字不改
    assert any(r["status"] == "anchored" and r["ulid"] == "u:zheng" for r in reports)
    # H2 扩门此前会 FAIL(未标引文)；锚定后过
    refs2 = {
        **refs,
        "ku_events": {},
        "theses": {"t": {}},
        "name_registry": [],
        "episode_plan": {"counterpoint_search_record": {"x": 1}},
    }
    assert run_rhard(anchored, refs2)["by_gate"]["H2"] == "PASS"


def test_anchor_zero_hit_strips_quotes_paraphrase() -> None:
    """N0-D-024 零命中剥引号：引号内容 corpus 零命中(白话概括)→ 自动剥引号转白话,不触 H2。
    只去引号标记、内容一字不改(同 N0-D-009)。"""
    refs = {
        "corpus": {"u:zheng": "夏五月鄭伯克段于鄢"},
        "ku_events": {},
        "theses": {},
        "name_registry": [],
        "episode_plan": {"counterpoint_search_record": {"x": 1}},
    }
    draft = _anchor_draft("他说了『这不是原文的句子』。")
    anchored, reports = anchor_quotes(draft, refs)
    s = anchored["beats"][0]["sentences"][0]
    assert "quote" not in s  # 未挂(非引文)
    assert "『" not in s["text"] and "』" not in s["text"]  # 引号已剥
    assert s["text"] == "他说了这不是原文的句子。"  # 内容一字不改,仅去引号
    assert any(r["status"] == "stripped_paraphrase" for r in reports)
    # 剥引号后 H2 不再 FAIL(引号 span 已消失,无未标引文绕行)
    assert run_rhard(anchored, refs)["by_gate"]["H2"] == "PASS"


def test_anchor_hit_still_attaches_not_stripped() -> None:
    """N0-D-024 边界：命中的引号照挂 quote(不误剥),只有零命中才剥。"""
    refs = {"corpus": {"u:zheng": "夏五月鄭伯克段于鄢"}}
    # 一句里:命中『鄭伯克段于鄢』应挂;零命中『这是白话』应剥
    draft = _anchor_draft("郑国『鄭伯克段于鄢』,后人评『这是白话概括』。")
    anchored, reports = anchor_quotes(draft, refs)
    s = anchored["beats"][0]["sentences"][0]
    q = s["quote"]
    q = q if isinstance(q, dict) else q[0]
    assert q["ulid"] == "u:zheng" and q["text"] == "鄭伯克段于鄢"  # 命中照挂
    assert "鄭伯克段于鄢" in s["text"]  # 命中引号保留(挂了 quote)
    assert "这是白话概括" in s["text"] and "『这是白话概括』" not in s["text"]  # 零命中被剥
    assert any(r["status"] == "anchored" for r in reports)
    assert any(r["status"] == "stripped_paraphrase" for r in reports)


def test_anchor_multi_hit_not_stripped_still_ambiguous() -> None:
    """N0-D-024 边界:多命中不剥,仍报回消歧(N0-D-021)——剥引号只对零命中。"""
    draft = _anchor_draft("师服说『本大而末小』。")
    anchored, reports = anchor_quotes(draft, _anchor_refs())
    assert any(r["status"] == "ambiguous" for r in reports)
    assert not any(r["status"] == "stripped_paraphrase" for r in reports)
    assert "『本大而末小』" in anchored["beats"][0]["sentences"][0]["text"]  # 多命中引号不剥


def test_force_long_vo_quote_onscreen() -> None:
    """N0-D-025 长 vo 引强制 onscreen:vo 句含逐字引 >阈长 → 翻 onscreen(不计 VO);短引不翻。"""
    from hevi.n0.rhard import force_long_vo_onscreen

    long_q = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉"  # 18 字 >15 阈
    draft = {
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {
                        "sid": "s1",
                        "type": "fact",
                        "text": long_q,
                        "quote": {"ulid": "u", "text": long_q},
                    },
                    {
                        "sid": "s2",
                        "type": "fact",
                        "text": "曰『短引』。",
                        "quote": {"ulid": "u2", "text": "短引"},
                    },
                ],
            }
        ]
    }
    out, reports = force_long_vo_onscreen(draft)
    ss = out["beats"][0]["sentences"]
    assert ss[0]["presentation"] == "onscreen"  # 长引强制 onscreen
    assert ss[1].get("presentation") != "onscreen"  # 短引不翻
    assert any(r["sid"] == "s1" and r["forced"] == "onscreen" for r in reports)
    # 已是 onscreen 的不重复处理、无 quote 的 vo 句不翻
    draft2 = {
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {"sid": "s3", "type": "fact", "text": "纯白话没有引文的长句子铺陈铺陈铺陈"}
                ],
            }
        ]
    }
    _, r2 = force_long_vo_onscreen(draft2)
    assert not r2


def test_anchor_multi_hit_reports_not_guess() -> None:
    """引号内容多处命中 → 报回不猜(ambiguous),不自动挂。"""
    draft = _anchor_draft("师服说『本大而末小』。")
    anchored, reports = anchor_quotes(draft, _anchor_refs())
    amb = [r for r in reports if r["status"] == "ambiguous"]
    assert amb and set(amb[0]["ulids"]) == {"u:shifu", "u:dup1"}
    assert "quote" not in anchored["beats"][0]["sentences"][0]  # 不猜不挂


def test_anchor_idempotent_skips_already_quoted() -> None:
    """已挂 quote 的引号不重复锚定(幂等)。"""
    refs = {"corpus": {"u:zheng": "夏五月鄭伯克段于鄢"}}
    draft = _anchor_draft("『鄭伯克段于鄢』")
    draft["beats"][0]["sentences"][0]["quote"] = {"ulid": "u:zheng", "text": "鄭伯克段于鄢"}
    _, reports = anchor_quotes(draft, refs)
    assert not any(r["status"] == "anchored" for r in reports)  # 已挂,不再锚


def test_h4_institutional_terms_whitelist_exempt() -> None:
    """N0-D-019：制度类目集合名词(卿族/六卿/三军)豁免 H4;真造名仍 FAIL。"""
    draft, refs = _valid()
    draft["beats"][1]["sentences"].append(
        {
            "sid": "s1-b2-inst",
            "type": "fact",
            "fact_refs": ["ev:quwo-wugong-mie-yi"],
            "thesis_refs": [],
            "text": "卿族坐大、六卿掌三军。",
            "entities": ["卿族", "六卿", "三军"],
            "display": {"source_display": "《左传》"},
        }
    )
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H4"] == "PASS", [f for f in rep["failures"] if f["gate"] == "H4"]
    # 造名仍抓
    draft["beats"][1]["sentences"][-1]["entities"] = ["卿族", "张三丰"]
    rep2 = run_rhard(draft, refs)
    assert rep2["by_gate"]["H4"] == "FAIL"
    assert any(f["gate"] == "H4" and "张三丰" in f["reason"] for f in rep2["failures"])


# ── N0-D-021 锚定器增强 ───────────────────────────────────────────────────────
def test_anchor_ellipsis_splice_rejected() -> None:
    """N0-D-021c：引号含省略号=跨段拼引 → 不锚定,H2 FAIL 且修法提示分两条/改述。"""
    refs = {
        "corpus": {"u:1": "冬楚子圍宋於是乎蒐于被廬作三軍謀元帥趙衰曰郤縠可乃使郤縠將中軍"},
        "ku_events": {},
        "theses": {},
        "name_registry": [],
        "episode_plan": {"counterpoint_search_record": {"x": 1}},
    }
    draft = _anchor_draft("《左传》载：「蒐于被廬作三軍……乃使郤縠將中軍」。")
    anchored, reports = anchor_quotes(draft, refs)
    assert any(r["status"] == "ellipsis_splice" for r in reports)
    assert "quote" not in anchored["beats"][0]["sentences"][0]  # 不拼接锚定
    rep = run_rhard(anchored, refs)
    assert rep["by_gate"]["H2"] == "FAIL"
    assert any(f["gate"] == "H2" and "拼接" in f["fix"] for f in rep["failures"])


def test_anchor_multihit_disambiguated_by_beat_event() -> None:
    """N0-D-021b：短句多命中 → 缩到该拍 event 所属 account 的 ULID 域,唯一则锚。"""
    refs = {
        "corpus": {"u:A": "作三軍謀元帥趙衰曰郤縠可", "u:B": "他處亦載郤縠可之語別是一事"},
        "event_ulids": {"ev:sanjun": ["u:A"]},
        "episode_plan": {"beat_events": {"b1": ["ev:sanjun"]}},
    }
    draft = {
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [{"sid": "s1", "type": "fact", "text": "赵衰曰『郤縠可』。"}],
            }
        ]
    }
    anchored, reports = anchor_quotes(draft, refs)
    q = anchored["beats"][0]["sentences"][0].get("quote")
    assert q and (q["ulid"] if isinstance(q, dict) else q[0]["ulid"]) == "u:A"  # 消歧取拍 event 域
    assert any(r["status"] == "anchored" and r["ulid"] == "u:A" for r in reports)


def test_anchor_nested_inner_independent() -> None:
    """N0-D-021a：外层因不连续失配,内层小引文仍独立锚定。"""
    refs = {"corpus": {"u:in": "郤縠可"}}
    # 外层含省略号(跨段)失配,内层『郤縠可』独立命中 u:in
    draft = {
        "beats": [
            {
                "beat_id": "b1",
                "sentences": [
                    {"sid": "s1", "type": "fact", "text": "赵衰曰：『郤縠可』，遂用之。"}
                ],
            }
        ]
    }
    _, reports = anchor_quotes(draft, refs)
    assert any(r["status"] == "anchored" and r["ulid"] == "u:in" for r in reports)


def test_h2_attached_quote_ellipsis_splice_fix() -> None:
    """N0-D-021c 接挂 quote：quote.text 含省略号=跨段拼引 → H2 FAIL 且修法提示拆两条/改述。"""
    draft, refs = _valid()
    refs["corpus"]["u:long"] = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥"
    draft["beats"][1]["sentences"].append(
        {
            "sid": "s1-b2-sp",
            "type": "fact",
            "fact_refs": ["ev:quwo-wugong-mie-yi"],
            "thesis_refs": [],
            "text": "史载其事。",
            "quote": {"ulid": "u:long", "text": "甲乙丙……午未申"},
            "display": {"source_display": "《左传》"},
        }
    )
    rep = run_rhard(draft, refs)
    assert rep["by_gate"]["H2"] == "FAIL"
    assert any(f["gate"] == "H2" and "拼接" in f["fix"] for f in rep["failures"])
