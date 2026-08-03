"""反压缩与素材全吸收升级 + 分章生成架构(>6 分钟)。

覆盖:
- 反压缩纪律挂进单次生成 prompt 末尾(权威位置)+ 素材吸收矩阵进 JSON 契约
- _should_chunk:>6 分钟(需求字数 >1500 字)切分章生成
- Step A 大纲 → Step B 逐章 cues → Step C 合并:step_id 重排、矩阵回填、hook 透传
- 单章 JSON 损坏自动重试,不浪费整支视频
- 素材吸收矩阵跨脚本版本并集去重
- ConceptExpansion 深度底线校验(deep_explanation ≥ 50 字,Prompt 要求 ≥150)
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from hevi.explainer.contracts import (
    ConceptExpansion,
    ExplainerCapabilityError,
    ExplainerScriptDraft,
)
from hevi.explainer.research import (
    _build_research_prompt,
    _coerce_outline,
    _extract_json,
    _llm_research,
    _llm_research_chunked,
    _normalise,
    _should_chunk,
)


def _deep() -> str:
    return "深" * 80


def _expansion(point: str) -> dict:
    return {"original_material_point": point, "deep_explanation": _deep()}


def _outline_json() -> str:
    """Step A 产物:4 章大纲 + 2 条素材吸收扩写 + 2 个版本元信息,无 cues。"""
    return json.dumps(
        {
            "research_summary": "调研结论:BBGKY 方程长期未被突破",
            "facts": [{"claim": "事实A", "source": "论文", "confidence": 0.9}],
            "hooks": [
                {
                    "hook_id": "H1",
                    "title": "灾难的根源",
                    "narrative_function": "opening_suspense",
                    "suggested_placement_s": 0.0,
                    "text": "为什么经典力学在 BBGKY 方程这里彻底失效？",
                    "associated_concepts": ["BBGKY 方程"],
                }
            ],
            "material_coverage_matrix": [
                _expansion("素材点1:BBGKY 方程的推导困境"),
                _expansion("素材点2:拓扑树上的重碰撞"),
            ],
            "chapters": [
                {
                    "chapter_id": "C1",
                    "title": "第一章 反常导入",
                    "goal": (
                        "本章要把素材点1背后被长期忽视的反常机制彻底讲透，"
                        "用数据与比喻层层展开并收束到核心结论"
                    ),
                    "expansions": [_expansion("素材点1:BBGKY 方程的推导困境")],
                },
                {
                    "chapter_id": "C2",
                    "title": "第二章 底层机制",
                    "goal": (
                        "本章要拆解素材点1的数学物理图景，"
                        "讲清为什么经典方法在这里失效并给出可视化解释"
                    ),
                    "expansions": [_expansion("素材点1:BBGKY 方程的推导困境")],
                },
                {
                    "chapter_id": "C3",
                    "title": "第三章 重碰撞死结",
                    "goal": (
                        "本章要讲透素材点2的拓扑树重碰撞，"
                        "用比喻把死结具象化并引出破解方向"
                    ),
                    "expansions": [_expansion("素材点2:拓扑树上的重碰撞")],
                },
                {
                    "chapter_id": "C4",
                    "title": "第四章 突破与收束",
                    "goal": (
                        "本章要收束到最终结论，把前几章的反常、原理与死结"
                        "串成完整逻辑链并给出突破图景"
                    ),
                    "expansions": [_expansion("素材点2:拓扑树上的重碰撞")],
                },
            ],
            "versions": [
                {
                    "id": "A",
                    "title": "版本 A",
                    "viewpoint": "数据派",
                    "hook": "H1",
                    "reasoning_depth": "先展开反常数据引出矛盾，再拆解底层原理，最后落到突破结论",
                },
                {
                    "id": "B",
                    "title": "版本 B",
                    "viewpoint": "原理派",
                    "hook": "H1",
                    "reasoning_depth": "从数学原理切入，用比喻讲透重碰撞，收束到调和分析突破",
                },
            ],
        },
        ensure_ascii=False,
    )


def _chapter_cues_json(chapter_id: str, version_id: str) -> str:
    return json.dumps(
        {
            "cues": [
                {
                    "step_id": 1,
                    "visual_type": "voiceover",
                    "text": f"{version_id}-{chapter_id} 旁白一",
                    "time_estimate_s": 8.0,
                }
            ]
        },
        ensure_ascii=False,
    )


class _SequenceLLM:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"content": self.contents.pop(0)}


# ── 反压缩纪律与素材矩阵进 prompt ────────────────────────────────────────


def test_single_shot_prompt_contains_anti_compression_and_matrix() -> None:
    prompt = _build_research_prompt("邓煜突破 BBGKY 方程", "1-3")
    # 反压缩纪律:展开而非总结、零遗漏、自主挖掘、4 步逻辑、字数纪律。
    assert "极其严格的反压缩与长文本纪律" in prompt
    assert "绝对禁止总结与精简" in prompt
    assert "零遗漏原则" in prompt
    assert "material_coverage_matrix" in prompt
    assert "至少 150 字" in prompt
    # 纪律挂在末尾 = 权威位置,不被基础契约稀释。
    assert prompt.rstrip().endswith("每一个 cue 的旁白都要极其丰满!")


def test_should_chunk_threshold() -> None:
    assert not _should_chunk("1-3")  # ≤1500 字:单次生成
    assert not _should_chunk("3-6")
    assert not _should_chunk("6")  # 恰好 6 分钟 = 1500 字,不超阈值
    assert _should_chunk("6-10")  # 上界超 6 分钟:分章
    assert _should_chunk("8")
    assert _should_chunk("10-15")
    assert _should_chunk("20")


# ── ConceptExpansion 深度底线校验 ─────────────────────────────────────────


def test_concept_expansion_requires_real_expansion() -> None:
    ok = ConceptExpansion(original_material_point="素材点", deep_explanation=_deep())
    assert ok.deep_explanation == _deep()
    # 一句话带过的“伪扩写”必须被 schema 拦下(深度底线 50 字)。
    with pytest.raises(ValidationError):
        ConceptExpansion(original_material_point="素材点", deep_explanation="太短")


def test_script_draft_accepts_material_coverage_matrix() -> None:
    draft = ExplainerScriptDraft(
        title="版本 A",
        material_coverage_matrix=[
            ConceptExpansion(original_material_point="点1", deep_explanation=_deep())
        ],
        cues=[{"visual_type": "voiceover", "text": "旁白"}],
    )
    assert draft.material_coverage_matrix[0].original_material_point == "点1"


# ── 分章生成:Step A → Step B → Step C 合并 ───────────────────────────────


@pytest.mark.asyncio
async def test_chunked_generation_merges_chapters_per_version() -> None:
    contents = [_outline_json()]
    for version in ("A", "B"):
        for chapter in ("C1", "C2", "C3", "C4"):
            contents.append(_chapter_cues_json(chapter, version))
    llm = _SequenceLLM(contents)
    raw = await _llm_research_chunked(llm, "邓煜突破 BBGKY 方程", "8")

    result = _normalise(raw, "邓煜突破 BBGKY 方程", "test")
    # 2 个版本 × 4 章:每版合并出 4 条 cues,step_id 连续重排。
    assert len(result.scripts) == 2
    for script in result.scripts:
        assert [cue.step_id for cue in script.cues] == [1, 2, 3, 4]
        assert [cue.text for cue in script.cues] == [
            f"{script.id}-C{i} 旁白一" for i in range(1, 5)
        ]
    # 素材吸收矩阵回填到每个版本 + 顶层并集。
    assert len(result.scripts[0].material_coverage_matrix) == 2
    assert len(result.material_coverage_matrix) == 2
    # Hook 矩阵 / facts / summary 透传。
    assert result.hooks[0].hook_id == "H1"
    assert result.hooks[0].narrative_function == "opening_suspense"
    assert result.facts[0].claim == "事实A"
    assert result.provider == "test"


@pytest.mark.asyncio
async def test_chunked_generation_uses_all_material_points_in_prompt() -> None:
    contents = [_outline_json()]
    for version in ("A", "B"):
        for chapter in ("C1", "C2", "C3", "C4"):
            contents.append(_chapter_cues_json(chapter, version))
    llm = _SequenceLLM(contents)
    await _llm_research_chunked(llm, "邓煜突破 BBGKY 方程", "8")
    # Step A 的每一章 prompt 都必须携带该章的深度扩写(素材全吸收)。
    chapter_prompts = [call["messages"][0]["content"] for call in llm.calls[1:]]
    assert len(chapter_prompts) == 8
    assert all("【深度扩写】" in prompt for prompt in chapter_prompts)
    assert all("反压缩与长文本纪律" in prompt for prompt in chapter_prompts)
    assert all("只返回 JSON" in prompt for prompt in chapter_prompts)


@pytest.mark.asyncio
async def test_chunked_generation_retries_broken_chapter_json() -> None:
    """单章 JSON 损坏时自动重试本章,不浪费整支视频。"""
    contents = [
        _outline_json(),
        _chapter_cues_json("C1", "A"),
        _chapter_cues_json("C2", "A"),
        "不是 JSON(损坏的第 3 章)",
        _chapter_cues_json("C3", "A"),  # 重试成功
        _chapter_cues_json("C4", "A"),
        _chapter_cues_json("C1", "B"),
        _chapter_cues_json("C2", "B"),
        _chapter_cues_json("C3", "B"),
        _chapter_cues_json("C4", "B"),
    ]
    llm = _SequenceLLM(contents)
    raw = await _llm_research_chunked(llm, "邓煜突破 BBGKY 方程", "8")
    result = _normalise(raw, "邓煜突破 BBGKY 方程", "test")
    assert len(result.scripts[0].cues) == 4


@pytest.mark.asyncio
async def test_llm_research_routes_to_chunked_for_long_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_llm_research 按 target_duration 路由:>6 分钟走分章,≤6 分钟走单次。"""
    contents = [_outline_json()]
    for version in ("A", "B"):
        for chapter in ("C1", "C2", "C3", "C4"):
            contents.append(_chapter_cues_json(chapter, version))
    llm = _SequenceLLM(contents)
    monkeypatch.setattr("hevi.explainer.research._default_llm", lambda: llm)
    raw = await _llm_research("邓煜突破 BBGKY 方程", "8")
    assert len(raw["scripts"]) == 2
    # 第一个调用是 Step A 大纲 prompt(不含“本章字数”字样)。
    assert "【本章字数与 Cue 数量】" not in llm.calls[0]["messages"][0]["content"]


# ── _normalise 素材矩阵跨版本并集去重 ────────────────────────────────────


def test_normalise_deduplicates_matrix_across_versions() -> None:
    cue = {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "旁白"}
    raw = {
        "facts": [{"claim": "事实"}],
        "hooks": [{"text": "Hook"}],
        "scripts": [
            {
                "id": "A",
                "title": "版本 A",
                "hook": "Hook",
                "material_coverage_matrix": [_expansion("点1"), _expansion("点2")],
                "cues": [cue],
            },
            {
                "id": "B",
                "title": "版本 B",
                "hook": "Hook",
                "material_coverage_matrix": [
                    _expansion("点1"),  # 与版本 A 重复,应去重
                    _expansion("点3"),
                ],
                "cues": [cue],
            },
        ],
    }
    result = _normalise(raw, "测试", "test")
    assert [entry.original_material_point for entry in result.material_coverage_matrix] == [
        "点1",
        "点2",
        "点3",
    ]


# ── JSON 多层防御提取(尾随散文/尾随逗号/注释/围栏) ───────────────────────


def test_extract_json_recovers_trailing_comma_and_comment() -> None:
    """用户报错同族:尾随逗号 + 字符串外行注释 → 清洗后照常解析。"""
    raw = '{\n  "a": 1, // 行注释\n  "b": [1, 2,],\n  "c": {"d": 3,}\n}'
    assert _extract_json(raw) == {"a": 1, "b": [1, 2], "c": {"d": 3}}


def test_extract_json_keeps_url_and_braces_inside_strings() -> None:
    """清洗扫描是字符串感知的:URL 的 //、文案里的 ,} 与 { } 一律不误伤。"""
    raw = (
        '{"target_url": "https://example.gov.cn/report?a=1//keep",'
        ' "text": "他说 {X} 是重点,}", "n": 2}'
    )
    value = _extract_json(raw)
    assert value["target_url"] == "https://example.gov.cn/report?a=1//keep"
    assert value["text"] == "他说 {X} 是重点,}"


def test_extract_json_takes_first_object_when_trailing_prose_has_brace() -> None:
    """旧版贪心 `{.*}` 的死穴:尾随散文含 } 会把解析窗口拖进垃圾区。"""
    raw = '好的，以下是结果：{"a": 1, "text": "正文"} 以上是全部内容，结束。}'
    assert _extract_json(raw) == {"a": 1, "text": "正文"}


def test_extract_json_takes_first_of_multiple_blocks() -> None:
    assert _extract_json('{"a": 1} {"b": 2}') == {"a": 1}


def test_extract_json_strips_markdown_fence() -> None:
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_strips_block_comment() -> None:
    assert _extract_json('{"a": 1 /* 块注释 */ , "b": 2}') == {"a": 1, "b": 2}


def test_extract_json_unrecoverable_error_reports_snippet() -> None:
    """结构性损坏修不了(缺逗号已被容错解析修复,这里用真正的坏输入):
    报错必须带原文片段,方便定位模型输出。"""
    with pytest.raises(ExplainerCapabilityError, match="无法解析") as exc:
        _extract_json('{"a": 1 "b": }')
    assert "出错附近原文" in exc.value.message


def test_extract_json_rejects_pure_array() -> None:
    """纯数组解析出来不是 JSON 对象 → 报错;数组包着对象则能恢复内层。"""
    with pytest.raises(ExplainerCapabilityError, match="不是 JSON 对象"):
        _extract_json("[1, 2, 3]")
    # 模型把结果包成单元素数组时,直接取内层对象。
    assert _extract_json('[{"a": 1}]') == {"a": 1}


# ── 容错流解析器(最终防线:缺逗号/全角标点/内嵌引号/裸换行/True|None) ──


def test_tolerant_parser_fixes_missing_comma_between_fields() -> None:
    """换行分隔字段(缺逗号)是本地模型的头号死因 → 容错解析补齐。"""
    assert _extract_json('{\n  "a": 1\n  "b": 2\n}') == {"a": 1, "b": 2}


def test_tolerant_parser_accepts_full_width_punctuation() -> None:
    """中文模型把结构分隔符打成全角 ,/： → 照常解析。"""
    assert _extract_json('{"a": 1，"b"：2}') == {"a": 1, "b": 2}


def test_tolerant_parser_recovers_embedded_ascii_quotes() -> None:
    """解说词给术语加 ASCII 引号忘了转义 → 内嵌引号保留。"""
    value = _extract_json('{"text": "他说"BBGKY"很关键"}')
    assert value["text"] == "他说" + '"BBGKY"' + "很关键"


def test_tolerant_parser_keeps_raw_newlines_and_python_literals() -> None:
    """字符串内裸换行 + True/None 字面量 → 全部容错。"""
    value = _extract_json('{"ok": True, "none_val": None, "text": "第一行\n第二行"}')
    assert value == {"ok": True, "none_val": None, "text": "第一行\n第二行"}


def test_tolerant_parser_handles_single_quotes_and_unquoted_keys() -> None:
    assert _extract_json("{'a': 1, step_id: 2, 'text': '旁白'}") == {
        "a": 1,
        "step_id": 2,
        "text": "旁白",
    }


def test_tolerant_parser_recovers_big_combined_defective_output() -> None:
    """还原真实 120 行报错场景:缺逗号 + 全角标点 + 内嵌引号 + 裸换行 + True/None 全叠一起。"""
    lines = ["{"]
    for index in range(1, 60):
        lines.append(f'  "key_{index}": "第{index}段旁白 他说\\"BBGKY\\" 很关键",')
    lines.extend(
        [
            '  "cues": [',
            '    {"step_id": 1, "visual_type": "voiceover", "text": "第一行',
            '第二行旁白\\"带引号\\"继续"}',
            '    {"step_id": 2, "visual_type": "remotion_chart", "chart_data": {"type": "bar"}}',
            '  ],',
            '  "ok": True,',
            '  "none_val": None，',
            '  "full_width"：2',
            "}",
        ]
    )
    value = _extract_json("\n".join(lines))
    assert len(value["cues"]) == 2
    assert value["cues"][0]["text"] == "第一行\n第二行旁白\"带引号\"继续"
    assert value["cues"][1]["chart_data"] == {"type": "bar"}
    assert value["ok"] is True and value["none_val"] is None and value["full_width"] == 2
    assert value["key_1"] == "第1段旁白 他说\"BBGKY\" 很关键"


def test_tolerant_parser_does_not_swallow_document_via_missing_comma() -> None:
    """缺逗号 + 相邻字符串字段:收尾引号后紧跟下一个 key 的开引号时,
    绝不允许把整个文档吞进当前字符串(unterminated string 的头号死因)。"""
    raw = (
        '{"research_summary": "邓煜团队通过调和分析与相干抵消" '
        '"facts": [{"claim": "邓煜突破", "confidence": 0.9}], '
        '"hooks": [{"text": "钩子"}]}'
    )
    value = _extract_json(raw)
    assert value["research_summary"] == "邓煜团队通过调和分析与相干抵消"
    assert value["facts"][0]["claim"] == "邓煜突破"
    assert value["hooks"][0]["text"] == "钩子"


def test_tolerant_parser_salvages_truncated_output() -> None:
    """输出被 max_tokens 截断(字符串/数组/对象没写完):就地收束,
    抢救已生成的 research_summary / facts / hooks / scripts 部分内容。"""
    full = json.dumps(
        {
            "research_summary": "调研结论很长",
            "facts": [{"claim": "事实A", "source": "论文", "confidence": 0.9}],
            "hooks": [{"hook_id": "H1", "text": "为什么失效?"}],
            "scripts": [
                {
                    "id": "A",
                    "title": "版本A",
                    "hook": "H1",
                    "cues": [
                        {"step_id": 1, "visual_type": "voiceover", "text": "旁白一"}
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )
    truncated = full[:-30]  # 砍在 cues 字符串中间
    value = _extract_json(truncated)
    assert value["research_summary"] == "调研结论很长"
    assert value["facts"][0]["claim"] == "事实A"
    assert value["hooks"][0]["hook_id"] == "H1"
    assert len(value["scripts"]) == 1  # 部分脚本被抢救,交给 _normalise 校验


# ── 分章大纲容错规整(_coerce_outline:Step A 产出不规范/被截断时抢救) ────


def _broken_outline_json() -> str:
    """复刻真实报错:非法 narrative_function + 缺 deep_explanation + 缺 versions。"""
    return json.dumps(
        {
            "research_summary": "邓煜团队通过调和分析与相干抵消突破 BBGKY 方程",
            "facts": ["邓煜用调和分析突破 BBGKY", {"claim": "拓扑树重碰撞", "confidence": 0.8}],
            "hooks": [
                {"hook_id": "H1", "text": "为什么经典力学失效?",
                 "narrative_function": "opening_suspense"},
                {"hook_id": "H2", "text": "拓扑树死结", "narrative_function": "mid_conflict"},
                {"hook_id": "H3", "text": "调和分析钥匙",
                 "narrative_function": "climax_breakthrough"},
                {"hook_id": "H4", "text": "哲学启示", "narrative_function": "philosophical_lesson"},
            ],
            "material_coverage_matrix": [
                {"original_material_point": "BBGKY 方程", "deep_explanation": "深" * 80},
            ],
            "chapters": [
                {"chapter_id": "C1", "title": "反常导入",
                 "goal": "本章要把 BBGKY 方程被长期忽视的反常机制彻底讲透并用比喻层层展开",
                 "expansions": [{"original_material_point": "BBGKY 方程",
                                 "deep_explanation": "深" * 80}]},
                {"chapter_id": "C2", "title": "底层机制",
                 "goal": "本章要拆解调和分析的数学物理图景讲清经典方法失效的根源并可视化",
                 "expansions": [{"original_material_point": "相干抵"}]},  # 缺 deep_explanation
                {"chapter_id": "C3", "title": "突破收束",
                 "goal": "本章收束到最终结论把反常原理死结串成完整逻辑链给出突破图景",
                 "expansions": [{"original_material_point": "调和分析",
                                 "deep_explanation": "深" * 80}]},
            ],
            # versions 整个缺失(大纲末字段被 max_tokens 截掉)
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_coerce_outline_salvages_broken_step_a() -> None:
    """非法档位 → 轮换合法档位;缺扩写 → 占位扩写;缺 versions → 合成默认版本。"""
    contents = [_broken_outline_json()]
    for chapter in ("C1", "C2", "C3"):
        contents.append(_chapter_cues_json(chapter, "A"))
    llm = _SequenceLLM(contents)
    raw = await _llm_research_chunked(llm, "邓煜突破 BBGKY 方程", "8")
    result = _normalise(raw, "邓煜突破 BBGKY 方程", "test")
    # 非法 narrative_function 已轮换为合法档位
    assert result.hooks[3].narrative_function == "opening_suspense"
    # 合成默认版本保底产出完整脚本
    assert len(result.scripts) == 1
    assert result.scripts[0].hook == "H1"
    assert len(result.scripts[0].cues) == 3
    # 占位扩写被回填到素材矩阵
    assert result.material_coverage_matrix
    # 纯文本 facts 也被包装
    assert result.facts[0].claim == "邓煜用调和分析突破 BBGKY"


def test_coerce_outline_wraps_string_hooks_and_pads_short_goal() -> None:
    """纯文本 hook 包装成合法节点;过短章目标/缺 title 补齐下限。"""
    raw = _coerce_outline(
        {
            "research_summary": "结论",
            "hooks": ["为什么失效?"],
            "chapters": [{"title": "短章", "goal": "太短", "expansions": []}],
        },
        "测试选题",
    )
    assert raw["hooks"][0]["hook_id"] == "H1"
    assert raw["hooks"][0]["text"] == "为什么失效?"
    assert len(raw["chapters"][0]["goal"]) >= 20
    # 整章扩写丢失 → 章目标合成占位扩写
    assert len(raw["chapters"][0]["expansions"]) == 1
    assert len(raw["chapters"][0]["expansions"][0]["deep_explanation"]) >= 50
    # versions 合成
    assert raw["versions"][0]["id"] == "A"


# ── _normalise 脚本级容错:丢废 cue / 空脚本剔除 / visual_type 兑底 ──────


def test_normalise_drops_textless_cue_instead_of_killing_research() -> None:
    """脚本里单个 cue 缺 text(截断/漏字段) → 丢掉那一个,保留其余有效 cue。"""
    good = {"time_range": "00:00-06.0s", "visual_type": "voiceover", "text": "开场旁白"}
    bad = {"step_id": 2, "visual_type": "remotion_chart"}  # 缺 text
    good3 = {"visual_type": "broll_news", "text": "第三节旁白", "time_estimate_s": 7.5}
    raw = {
        "facts": [{"claim": "事实", "confidence": 0.9}],
        "hooks": [{"text": "Hook"}],
        "scripts": [
            {"id": "A", "title": "版本A", "hook": "Hook",
             "cues": [good, bad, good3]},
        ],
    }
    result = _normalise(raw, "测试", "test")
    assert [cue.text for cue in result.scripts[0].cues] == ["开场旁白", "第三节旁白"]


def test_normalise_drops_script_whose_cues_are_all_textless() -> None:
    """整本脚本 cues 全废 → 整本剔除;另一本保底。"""
    good = {"time_range": "00:00-06.0s", "visual_type": "voiceover", "text": "旁白"}
    raw = {
        "facts": [], "hooks": [{"text": "Hook"}],
        "scripts": [
            {"id": "X", "title": "全废", "hook": "Hook",
             "cues": [{"visual_type": "voiceover"}, {"text": "   "}]},
            {"id": "A", "title": "版本A", "hook": "Hook", "cues": [good]},
        ],
    }
    result = _normalise(raw, "测试", "test")
    assert [script.id for script in result.scripts] == ["A"]


def test_normalise_rejects_when_all_scripts_empty() -> None:
    """全部脚本都掏空 → “至少需要包含 1 个脚本版本”(保留最后防线)。"""
    raw = {
        "facts": [], "hooks": [{"text": "Hook"}],
        "scripts": [
            {"id": "A", "title": "t", "hook": "Hook", "cues": [{"visual_type": "voiceover"}]},
        ],
    }
    with pytest.raises(ExplainerCapabilityError, match="至少需要包含 1 个脚本版本"):
        _normalise(raw, "x", "t")


def test_normalise_defaults_invalid_visual_type_to_voiceover() -> None:
    """visual_type 越界(如 'avatar') → 兑底 voiceover,不让一个坏值废全本。"""
    raw = {
        "facts": [], "hooks": [{"text": "Hook"}],
        "scripts": [
            {"id": "A", "title": "t", "hook": "Hook",
             "cues": [{"text": "旁白", "visual_type": "avatar"}]},
        ],
    }
    result = _normalise(raw, "x", "t")
    assert result.scripts[0].cues[0].visual_type == "voiceover"
