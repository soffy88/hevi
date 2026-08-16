"""镜头准备状态机与候选确认 —— 补 hevi 缺失的"镜头准备台"(Jellyfish 参考)。

hevi 的短剧/导演通道:手稿 → season_plan → episode → M 管线自动生成,但
**镜头级的人工确认/候选收编**缺失(INC-001 §A/§G/§I/§L 依赖的"交互式准备台+
候选表"被跳过)。本模块补上:

  1. shot 状态机: pending(候选未确认)→ ready(确认完成或明确跳过);
  2. 候选提取(全确定性,零 LLM):
     - 资产候选(角色/场景/道具/服装,从剧本摘句/对白/prompt 提取)
     - 对白候选(每行对白一条,可 accept/ignore)
     - action_beats 三段推断(trigger/peak/aftermath,关键词表,零成本)
  3. 确认接口: accept / ignore 候选、人工修正 beats、链接实体。

存储零迁移:挂在 shot_states.selection_json["preparation"] 子字段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── 动作节拍关键词表(确定性推断,INC-001 §B 的零成本版) ─────────────────────

_TRIGGER_KEYS = (
    "听到", "看到", "看见", "发现", "察觉", "突然", "骤然", "猛地", "传来",
    "响起", "回头", "转身", "抬头", "停下", "愣住", "一惊", "闯入", "出现",
)
_PEAK_KEYS = (
    "冲向", "扑向", "挥刀", "挥剑", "砸", "砍", "击", "爆发", "怒吼", "咆哮",
    "飞起", "摔倒", "撞", "踢", "撕", "挣", "奔", "杀", "追", "燃", "炸",
    "夺门", "拍案", "厉喝", "震怒", "狂奔",
)
_AFTERMATH_KEYS = (
    "倒地", "跪下", "沉默", "凝视", "久久", "垂下", "落幕", "离去", "熄灭",
    "停止", "收刀", "喘息", "相视", "静默", "回望", "落泪", "俯身", "长叹",
)


def infer_action_beats(text: str) -> dict[str, str]:
    """从剧本摘句/对白推断 (trigger, peak, aftermath) 三段文本。

    规则(确定性,可测):
      - 首句命中触发词 → trigger;否则首句。
      - 中间命中峰值动词最密的一句 → peak;否则第二句。
      - 末句命中收束词 → aftermath;否则末句。
    不足三句时按序补齐(允许同句复用)。
    """
    sentences = [s.strip() for s in re.split(r"[。！？!?；;\n]", text) if s.strip()]
    if not sentences:
        return {"trigger": "", "peak": "", "aftermath": ""}
    if len(sentences) == 1:
        return {
            "trigger": sentences[0], "peak": sentences[0], "aftermath": sentences[0],
        }

    def _score(s: str, keys: tuple[str, ...]) -> int:
        return sum(1 for k in keys if k in s)

    trigger = next(
        (s for s in sentences if _score(s, _TRIGGER_KEYS) > 0), sentences[0]
    )
    aftermath = next(
        (s for s in reversed(sentences) if _score(s, _AFTERMATH_KEYS) > 0), sentences[-1]
    )
    middle = [s for s in sentences if s != trigger and s != aftermath]
    if middle:
        peak = max(middle, key=lambda s: _score(s, _PEAK_KEYS))
        if _score(peak, _PEAK_KEYS) == 0:
            peak = middle[0]
    else:
        peak = sentences[len(sentences) // 2]
    return {"trigger": trigger, "peak": peak, "aftermath": aftermath}


# ── 资产候选提取(确定性词表 + 已知实体匹配) ────────────────────────────────

#: 常用道具词表(剧本里"手持/握着/带着 X"等语境常用)。
_PROP_KEYS = (
    "刀", "剑", "枪", "斧", "锤", "弓", "箭", "书", "卷", "信", "令牌", "官印",
    "钱袋", "火把", "灯笼", "茶", "酒", "碗", "锄", "锤", "戟", "鞭", "链",
    "玉佩", "珠", "伞", "扇", "杖", "印", "弩", "盾",
)
#: 常用服装词表(着/穿/披/戴 语境)。
_COSTUME_KEYS = (
    "袍", "甲", "冠", "裙", "衫", "裘", "氅", "巾", "带", "靴", "履",
    "衮服", "盔", "披风", "斗篷", "蓑衣", "襦",
)


#: 动词前缀(挥刀/持剑/握笔…)—— 道具名应取名词部分,丢掉动作动词。
_PREFIX_SKIP = frozenset(
    "挥持握拿扛背佩带执举提挎拔抽扬抡捧托端抱"
)


def _extract_by_keys(text: str, keys: tuple[str, ...]) -> list[str]:
    """在 text 里找词表命中,取"名词性"候选(前缀 1 字 + 关键词的 2 字词;
    动词前缀(挥/持/握…)跳过;关键词单独成词时用其本身)。去重保序。"""
    out: list[str] = []
    seen: set[str] = set()
    for k in keys:
        # 2 字词:前缀 1 字 + 关键词(如 石斧/令牌/火把/大刀)
        for m in re.finditer(f"[\u4e00-\u9fff]{re.escape(k)}", text):
            word = m.group(0)
            if word[0] in _PREFIX_SKIP:
                continue  # 挥刀/持剑 → 跳过,找名词性出现
            if word not in seen:
                seen.add(word)
                out.append(word)
        # 关键词单独成词(刀/剑/书…孤立出现)
        for _m in re.finditer(f"(?:^|[^\u4e00-\u9fff]){re.escape(k)}(?:[^\u4e00-\u9fff]|$)", text):
            if k not in seen:
                seen.add(k)
                out.append(k)
        if len(out) >= 8:
            break
    return out


def extract_asset_candidates(
    *,
    text: str,
    known_characters: list[str] | None = None,
    known_scenes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """从剧本摘句/对白提取资产候选(角色/场景/道具/服装)。全确定性。"""
    candidates: list[dict[str, Any]] = []

    def _add(type_: str, name: str) -> None:
        name = name.strip()
        if not name:
            return
        for c in candidates:
            if c["type"] == type_ and c["name"] == name:
                return
        candidates.append(
            {
                "id": f"{type_}_{len(candidates)}",
                "type": type_,
                "name": name,
                "source": "script",
                "status": "pending",
            }
        )

    for ch in known_characters or []:
        if ch and ch in text:
            _add("character", ch)
    for sc in known_scenes or []:
        if sc and sc in text:
            _add("scene", sc)
    for p in _extract_by_keys(text, _PROP_KEYS):
        _add("prop", p)
    for c in _extract_by_keys(text, _COSTUME_KEYS):
        _add("costume", c)
    return candidates


def extract_dialogue_candidates(
    text: str, *, speaker: str = ""
) -> list[dict[str, Any]]:
    """对白候选:仅来自引号内容(真正台词);叙述句不算对白。"""
    lines = [
        m.group(1).strip()
        for m in re.finditer(r"[“\"]([^”\"]{2,80})[”\"]", text)
    ]
    out: list[dict[str, Any]] = []
    for i, ln in enumerate(lines[:20]):
        out.append(
            {
                "id": f"dlg_{i}",
                "text": ln[:120],
                "speaker": speaker,
                "status": "pending",
            }
        )
    return out


# ── 镜头准备状态 ──────────────────────────────────────────────────────────


@dataclass
class ShotPreparation:
    """一个镜头的准备状态(挂 shot_states.selection_json["preparation"])。"""

    status: str = "pending"  # pending | ready
    candidates: list[dict[str, Any]] = field(default_factory=list)
    dialogue_candidates: list[dict[str, Any]] = field(default_factory=list)
    action_beats: dict[str, str] = field(default_factory=dict)
    entity_links: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidates": self.candidates,
            "dialogue_candidates": self.dialogue_candidates,
            "action_beats": self.action_beats,
            "entity_links": self.entity_links,
        }

    @property
    def pending_count(self) -> int:
        return sum(
            1
            for c in [*self.candidates, *self.dialogue_candidates]
            if c.get("status") == "pending"
        )

    @property
    def ready(self) -> bool:
        return self.status == "ready" or self.pending_count == 0


def build_shot_preparation(
    *,
    script_excerpt: str,
    known_characters: list[str] | None = None,
    known_scenes: list[str] | None = None,
    speaker: str = "",
) -> ShotPreparation:
    """一个镜头 → 初始准备状态(候选提取 + beats 推断,零 LLM)。"""
    prep = ShotPreparation(
        candidates=extract_asset_candidates(
            text=script_excerpt,
            known_characters=known_characters,
            known_scenes=known_scenes,
        ),
        dialogue_candidates=extract_dialogue_candidates(script_excerpt, speaker=speaker),
        action_beats=infer_action_beats(script_excerpt),
    )
    if not prep.candidates and not prep.dialogue_candidates:
        # 无可确认项 → 直接 ready(明确跳过提取,Jellyfish 同语义)。
        prep.status = "ready"
    return prep


def confirm_candidate(
    prep: ShotPreparation,
    *,
    candidate_id: str,
    decision: str,
    scope: str = "assets",  # assets | dialogue
) -> ShotPreparation:
    """accept / ignore 一个候选。全部处理完 → status=ready。"""
    pool = prep.candidates if scope == "assets" else prep.dialogue_candidates
    for c in pool:
        if c.get("id") == candidate_id:
            c["status"] = "accepted" if decision == "accept" else "ignored"
            if decision == "accept" and c.get("type") in ("prop", "costume"):
                prep.entity_links.append(
                    {"type": c["type"], "name": c["name"], "linked": True}
                )
            break
    if prep.pending_count == 0:
        prep.status = "ready"
    return prep


def upsert_preparation(shot_row: dict[str, Any], prep: ShotPreparation) -> dict[str, Any]:
    """把准备状态写回 shot_states 行(selection_json.preparation,零迁移)。"""
    sel = dict(shot_row.get("selection_json") or {})
    sel["preparation"] = prep.to_dict()
    shot_row["selection_json"] = sel
    return shot_row


def read_preparation(shot_row: dict[str, Any]) -> ShotPreparation | None:
    """从 shot_states 行读取准备状态(无则 None,调用方决定是否构建)。"""
    sel = shot_row.get("selection_json") or {}
    raw = sel.get("preparation")
    if not raw:
        return None
    return ShotPreparation(
        status=str(raw.get("status") or "pending"),
        candidates=list(raw.get("candidates") or []),
        dialogue_candidates=list(raw.get("dialogue_candidates") or []),
        action_beats=dict(raw.get("action_beats") or {}),
        entity_links=list(raw.get("entity_links") or []),
    )


__all__ = [
    "ShotPreparation",
    "build_shot_preparation",
    "confirm_candidate",
    "extract_asset_candidates",
    "extract_dialogue_candidates",
    "infer_action_beats",
    "read_preparation",
    "upsert_preparation",
]
