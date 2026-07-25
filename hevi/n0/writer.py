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
    "\n(2b) 引文连续单句(N0-D-021)：**长引文优先整段标 onscreen 呈现,不在 vo 里嵌引**;确需在 vo 引"
    "则**短引单句、不跨段、不嵌套**——严禁『A……B』式用省略号拼接跨段原文(拼接=篡改原文顺序,同禁"
    "截断);多段各引须拆成多条独立 quote(各锚各自 ULID 连续子串);"
    "\n(3) S12 冲突必出角标：EpisodePlan.s12_conflicts 列出的 cf，相关拍的句必填 "
    "conflict_callouts=[该 cf id]，把两说并陈(不择一坐实)；"
    "\n(4) 名从注册表 canonical：entities 与叙述句人名/地名用 name_registry 列出的名字"
    "(短称如『武公』『庄伯』优先，勿造『曲沃庄伯』式全称若表内无)；**引文内的源内名字不受此限**"
    "(在 quote 里逐字照抄即可)。"
)

# ★叙事取向·白话优先（实验，opt-in，N0-D-022/023）——仅当 narrative_style="baihua" 时叠加，
# 默认不启用（s1/s3 及所有默认调用不受影响；Wiki 认可前不推广）。硬门 H1–H9 全不变。
_NARRATIVE_BAIHUA = (
    "\n★叙事取向·白话优先(N0-D-022，实验取向，不改任何硬门)："
    "\n(甲) 白话为主：正文 vo 用**现代白话**讲清人物处境、动机、因果，讲人话；"
    "**文言引文默认标 presentation=onscreen(画面呈现、不口播)**，且**其前必先有一句白话转述(vo)"
    "把大意讲明**，再上屏原文——vo 里不堆文言、不整段照抄古文。仅极短关键短语(≤约8字)可内联 vo；"
    "整段或多句文言一律 onscreen 呈现+白话先行。宁少引精引，不堆砌未消化的原文。"
    "\n★吕祖谦掩卷自思框架(N0-D-023，结构建议、非强制、非门)："
    "\n每集**至多择一个**关键抉择点，可用『呈现处境与选项(此人此刻面对什么、有哪几条路)"
    "→留一句设身处地的自问(换作是你，会怎么选)→揭古人的实际选择与后果』来处理，令观众先代入再回望。"
    "**用得自然则用、生硬则不用——宁可不用，不可硬套**；不要每拍都塞、不要为框架而框架、不要滥用反问。"
    "\n(丙) 表达建议(R-soft 白话维度回馈、软性参考、非硬性)：①开场给具体钩子(画面/悬念/人性切口)，"
    "勿平铺『始于…之事』；②生僻术语用生活化类比即时点破(如『公族屏藩』≈『自家兄弟守边、外人当不了封疆大吏』)；"
    "③史料勿沦为标签——引《左传》《史记》时顺带一句『为何可信/为何有意思』，把史料化成叙事动能；"
    "④名实可点破(如『骊姬乱嫡』实为权力再分配)。这些是提味建议，服从上面白话为主与所有硬门。"
)

# ★R-soft 白话优先评审维度（N0-D-022，软评、出意见、不进 R-hard、不打回）。
# 供 pilot 的 R-soft 调用叠加；纯观感建议，不影响 9/9 判定。
RSOFT_BAIHUA_DIM = (
    "\n【白话优先维度(软评，不判 FAIL，只出改进意见)】另就下列各点给意见："
    "①正文文言引文占比是否过高(vo 里堆文言)？②文言是否缺白话转述先行(未先讲明大意就上原文)？"
    "③是否原文堆砌未消化(照抄古文、没讲成人话)？④吕祖谦抉择点框架若用了，是否自然(有无生硬硬套)？"
    "对每条给『可保留/建议改』+一句理由，不给分、不阻断。"
)


def _system_for(narrative_style: str | None) -> str:
    """默认返回原 _SYSTEM；narrative_style="baihua" 时叠加白话优先取向（opt-in，不推广）。"""
    if narrative_style == "baihua":
        return _SYSTEM + _NARRATIVE_BAIHUA
    return _SYSTEM


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


def build_prompt(
    episode_plan: dict,
    refs: dict,
    rhard_feedback: list[dict] | None = None,
    frozen: list[dict] | None = None,
) -> str:
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
        # N0-D-011/012：分门迭代——本轮**只修下列门的点名 sid**，其余句(尤其冻结清单)一字不动。
        lines = [
            f"- [{f.get('gate')}] sid={f.get('sid')}｜实测: {f.get('reason')}"
            f"\n  → 修法: {f.get('fix') or '（见 reason）'}"
            for f in rhard_feedback
        ]
        target_gates = sorted({f.get("gate") for f in rhard_feedback})
        block = (
            f"\n## ★本轮首要任务：仅修复门 {target_gates}，按修法逐条改★"
            "\n**外科式**：只改下列被点名 sid 的句、逐条照『修法』执行；未点名句**一字不动**"
            "（重写全稿会打地鼠、破坏已过门）。修完重出完整 JSON。\n" + "\n".join(lines)
        )
        if frozen:
            # N0-D-012：已过门所在拍整句冻结——text + conflict_callouts/presentation/e_banner
            # 逐字逐字段保留（只锁 text 会丢角标使 H5 回退，故连门相关字段一并冻结）。
            def _fz_line(fz: dict) -> str:
                extra = "".join(
                    f" [{k}={fz[k]}]"
                    for k in ("conflict_callouts", "presentation", "e_banner")
                    if fz.get(k)
                )
                return f"- sid={fz.get('sid')}: {fz.get('text', '')}{extra}"

            block = (
                "\n## ★已过门·冻结清单（下列句已通过硬门，**整句连同 [ ] 内字段逐字原样保留、"
                "严禁改动**）★\n"
                + "\n".join(_fz_line(fz) for fz in frozen)
                + "\n（改动冻结句文字**或 conflict_callouts/presentation 字段**都会使已过门回退"
                "——只动下面『本轮任务』点名的 sid）\n" + block
            )
        parts.insert(1, block)  # 置于任务说明后、KU 前——修正指令是本轮首要输入
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
    frozen: list[dict] | None = None,
    narrative_style: str | None = None,
) -> tuple[dict, dict]:
    """调 LLM 出一版 ScriptDraft。返回 (draft, usage)。draft.meta 填 model/cost 由 pilot 补。"""
    prompt = build_prompt(episode_plan, refs, rhard_feedback, frozen)
    result = await llm(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        system=_system_for(narrative_style),
    )
    choices = (result or {}).get("output", {}).get("choices", [])
    text = choices[0]["message"]["content"] if choices else ""
    draft = _parse_json(text)
    draft.setdefault("meta", {})
    draft["meta"]["model"] = model_name
    draft["meta"].setdefault("prompt_ver", "n0w-v0.1")
    return draft, (result or {}).get("usage", {}) or {}


def build_beat_prompt(beat: dict, beat_failures: list[dict], refs: dict, episode_plan: dict) -> str:
    """拍级重写 prompt（N0-D-014）——只交单拍 + 该拍全部 FAIL+修法，令 W 只重写这一拍。
    纠缠限一拍内：W 看不到别拍、改不了别拍。"""
    ku = {
        "events": refs.get("ku_events", {}),
        "theses": refs.get("theses", {}),
        "corpus_白文": refs.get("corpus", {}),
        "chronology": list(refs.get("chronology", {})),
        "name_registry": sorted(refs.get("name_registry", ())),
        "s12_conflict_hints": episode_plan.get("s12_conflict_hints", {}),
    }
    fixes = "\n".join(
        f"- [{f.get('gate')}] sid={f.get('sid')}｜{f.get('reason')}\n  → 修法: {f.get('fix') or ''}"
        for f in beat_failures
    )
    return "\n".join(
        [
            f"# 任务：**只重写下面这一拍**（beat_id={beat.get('beat_id')}），"
            "修好它的全部硬门失败。",
            '只输出这一拍的 JSON（形如 {"beat_id":..., "sentences":[...]}），'
            "不得改动或输出别的拍。",
            "\n## 当前这一拍（待修）\n" + json.dumps(beat, ensure_ascii=False, indent=2),
            "\n## 这一拍的 R-hard 失败与修法（逐条修好）\n" + fixes,
            "\n## 可用 KU（输入之外无事实来源）\n" + json.dumps(ku, ensure_ascii=False, indent=2),
            "\n## 句结构同全稿规范（type/fact_refs/thesis_refs/quote/entities/presentation/"
            "conflict_callouts/display）。长引文标 presentation=onscreen 并配 vo 白话转述；"
            "引号内容必挂 quote；名从 name_registry（未注册的源内泛称如尹氏/虢公须放进 quote "
            "引文内，或改述回避，不得作叙述句 entities）。",
            "\n只输出这一拍的 JSON，不要任何解释。",
        ]
    )


async def rewrite_beat(
    beat: dict,
    beat_failures: list[dict],
    refs: dict,
    episode_plan: dict,
    *,
    llm: Any,
    max_tokens: int = 1800,
    narrative_style: str | None = None,
) -> tuple[dict, dict]:
    """单拍 API：交一拍 + 其 FAIL+修法，W 返回重写后的该拍。返回 (new_beat, usage)。"""
    prompt = build_beat_prompt(beat, beat_failures, refs, episode_plan)
    result = await llm(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        system=_system_for(narrative_style),
    )
    choices = (result or {}).get("output", {}).get("choices", [])
    text = choices[0]["message"]["content"] if choices else ""
    new_beat = _parse_json(text)
    return new_beat, (result or {}).get("usage", {}) or {}
