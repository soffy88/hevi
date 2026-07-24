"""W 撰稿 agent（HEVI-N0-DUALAGENT-SPEC-001 §4）——LLM 产出结构化 ScriptDraft。

红线：**输入之外无事实来源**——W 不得引入任何未在 KU 内的日期/数字/人名/情节。
深度来自论点层：throughline 驱动叙事骨架，counterpoint 制造张力，事实层供证。
照搬白文翻译即 R-soft 差评且通常伴随 H1 结构性 FAIL（无 thesis 句）。

产出交 R-hard（rhard.run_rhard）审判；W↔R 循环由 pilot 驱动（≤3 轮）。
"""

from __future__ import annotations

import json
from typing import Any

_SYSTEM = (
    "你是历史讲解视频的撰稿 agent(W)。你的稿子会被确定性代码(R-hard)逐句审判，"
    "写错即打回。铁律："
    "①只输出 JSON，无任何解释文字；"
    "②输入之外无事实来源——不得引入任何未在给定 KU 对象内的日期、数字、人名、情节；"
    "③每句必分型 fact|thesis|transition；fact 句必挂 ≥1 个 fact_ref(给定事件 id)、"
    "thesis 句必挂恰好 1 个 thesis_ref 且 display.attribution 用『按…』显式署我方；"
    "④引原文必逐字照抄给定 corpus 白文并填 quote{ulid,text}(text 是 corpus 的子串)；"
    "无引文的句**不写 quote 字段**(绝不留空 quote 占位如 ulid=''/text='')；"
    "⑤稿内任何日期/数量必来自给定 chronology/number_claims 并挂 number_refs，否则删；"
    "⑥transition 句(纯衔接)不带 ref 且全稿占比 ≤20%；"
    "⑦深度来自论点：throughline 驱动骨架、事实供证，不许照搬白文翻译；"
    "⑧通俗度：生僻人名/地名/术语(翼侯/汾隰/支庶/大宗)首现即用括号或短句即时解释；"
    "⑨文言引文后必接一句白话转译(引文作 quote 字幕、转译作口播句)，不留纯文言；"
    "⑩深度来自论点，事实供证，不照搬白文翻译。"
    "\n★引文规范(N0-D-008/010，四条硬规)："
    '\n(1) 引文呈现分离：**长引文(>约15字)标 `presentation:"onscreen"`(画面竹简/字幕卡'
    "呈现、不口播)，并必配一句白话转述句(presentation 默认 vo、口播)**——onscreen 句本体不计"
    "口播时长、转述句才是 VO。短引(≤约15字关键短语)可留 vo 内联(按字幕 2 字/s 计)。"
    "**绝不把长引文留作 vo 整段照抄**(H8 按 VO 实念计时会超窗 FAIL、退你重述)；"
    "\n(2) 引号必挂 quote：**凡文中出现 『』「」 引号，其内容必须是 corpus 逐字子串并填 quote"
    "对象**(ulid+text，繁体原样一字不改)；不想挂 quote 就别用引号(改白话叙述)——严禁未标引文；"
    "\n(3) S12 冲突必出角标：EpisodePlan.s12_conflicts 列出的 cf，相关拍的句必填 "
    "conflict_callouts=[该 cf id]，把两说并陈(不择一坐实)；"
    "\n(4) 名从注册表 canonical：entities 与叙述句人名/地名用 name_registry 列出的名字"
    "(短称如『武公』『庄伯』优先，勿造『曲沃庄伯』式全称若表内无)；**引文内的源内名字不受此限**"
    "(在 quote 里逐字照抄即可)。"
)

# R-hard 期望的 ScriptDraft JSON 形状（喂给 W，确保结构可审）。
_SCHEMA = """{
  "episode_ref": "<EpisodePlan.episode_id>",
  "beats": [
    {"beat_id": "<对齐 EpisodePlan.beat>",
     "sentences": [
       {"sid": "<唯一,如 b1-1>",
        "type": "fact | thesis | transition",
        "presentation": "vo(默认口播) | onscreen(长引文画面呈现、不口播,须另配 vo 转述句)",
        "text": "<该句成稿文字;onscreen 句 text=逐字引文本体>",
        "fact_refs": ["<type=fact 必填≥1,给定事件 id>"],
        "thesis_refs": ["<type=thesis 必填恰好1,给定 thesis id>"],
        "quote": {"ulid": "<corpus key>", "text": "<corpus 子串,逐字>"},
        "entities": ["<句中人名/地名,须在 name_registry>"],
        "number_refs": ["<句含日期/数量时挂 chronology/number_claims id>"],
        "display": {"attribution": "<thesis:『按…』署我方>", "source_display": "<fact:《X》体例>"}
       }
     ]}
  ],
  "meta": {"model": "", "prompt_ver": "n0w-v0.1", "cost": 0.0}
}"""


def build_prompt(episode_plan: dict, refs: dict, rhard_feedback: list[dict] | None = None) -> str:
    ku = {
        "events": refs.get("ku_events", {}),
        "accounts": refs.get("ku_accounts", {}),
        "theses": refs.get("theses", {}),
        "corpus_白文": refs.get("corpus", {}),
        "chronology": list(refs.get("chronology", {})),
        "number_claims": list(refs.get("number_claims", {})),
        "name_registry": sorted(refs.get("name_registry", ())),
        "e_tiers": refs.get("e_tiers", {}),
    }
    parts = [
        "# 任务：为下面这一集写 ScriptDraft（结构化句列表，非纯文本）。",
        "\n## EpisodePlan（定稿·你的唯一事实来源）\n"
        + json.dumps(episode_plan, ensure_ascii=False, indent=2),
        "\n## 可用 KU 对象（输入之外无事实来源）\n" + json.dumps(ku, ensure_ascii=False, indent=2),
        "\n## 必须严格产出的 JSON 形状\n" + _SCHEMA,
        "\n## 硬门要点（R-hard 会逐条查）："
        "\n- H1 fact 句挂 fact_ref、thesis 句挂 1 个 thesis_ref+『按』署源；"
        "\n- H2 quote.text 必是 corpus 白文逐字子串；"
        "\n- H3 任何日期/数量挂 number_refs（本集 counterpoint 为显式无，已附检索）；"
        "\n- H6 counterpoint 显式无（EpisodePlan 已附检索记录），不要硬塞对立论点；"
        "\n- H8 transition ≤20%、beat_id 对齐 EpisodePlan、每拍 VO 约 5–15s（约 25–75 汉字，"
        "onscreen 引文句不计入 VO、须同拍配 vo 白话转述句）。",
    ]
    if rhard_feedback:
        # N0-D-011：每条 FAIL 带 `fix` 可执行修法——**逐条照 fix 执行**是本轮首要任务。
        lines = [
            f"- [{f.get('gate')}] sid={f.get('sid')}｜实测: {f.get('reason')}"
            f"\n  → 修法: {f.get('fix') or '（见 reason）'}"
            for f in rhard_feedback
        ]
        parts.insert(
            1,  # 置于任务说明之后、KU 之前——修正指令是本轮首要输入，不只是"上轮失败了"
            "\n## ★本轮首要任务：按下列 R-hard 修正指令逐条修复★"
            "\n**外科式**：只改被点名 sid 的句、逐条照『修法』执行，其余句一字不动"
            "（重写全稿会引入新错、打地鼠）。修完重出完整 JSON。\n" + "\n".join(lines),
        )
    parts.append("\n只输出 JSON，不要任何解释。")
    return "\n".join(parts)


def _parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):  # 剥 code fence
        t = t.split("```", 2)[1]
        t = t[4:] if t.lower().startswith("json") else t
        t = t.rsplit("```", 1)[0] if "```" in t else t
    # 取第一个 { 到最后一个 }
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        t = t[i : j + 1]
    return json.loads(t)


async def write_draft(
    episode_plan: dict,
    refs: dict,
    *,
    llm: Any,
    model_name: str,
    max_tokens: int = 3000,
    rhard_feedback: list[dict] | None = None,
) -> tuple[dict, dict]:
    """调 LLM 出一版 ScriptDraft。返回 (draft, usage)。draft.meta 填 model/cost 由 pilot 补。"""
    prompt = build_prompt(episode_plan, refs, rhard_feedback)
    result = await llm(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        system=_SYSTEM,
    )
    choices = (result or {}).get("output", {}).get("choices", [])
    text = choices[0]["message"]["content"] if choices else ""
    draft = _parse_json(text)
    draft.setdefault("meta", {})
    draft["meta"]["model"] = model_name
    draft["meta"].setdefault("prompt_ver", "n0w-v0.1")
    return draft, (result or {}).get("usage", {}) or {}
