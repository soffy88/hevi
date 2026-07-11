"""L5 角色卡 —— script + chapter_ir + constitution → character_bible.json。见 HEVI-SPEC-01 §5。

spec §5.1 的 4 个步骤:
  1. 从 script 统计有戏份的角色(_characters_with_dramatic_role)
  2. LLM 依据 chapter_ir + 宪法 visual_style 生成外形描述(generate_character_bible,纯文本)
  3. 本地 SDXL 文生图产出候选立绘(generate_reference_images,每角色 N 个候选,不同种子)
  4. VLM(本地 qwen2.5vl)年代审逐个候选,首个通过者锁定 ref_image + gen_lock
     {"seed":..., "ip_adapter_weight":...}(该权重供 L6 逐镜头用 IP-Adapter 条件生成时用,
     本步骤只锁定数值,不在此调用 IP-Adapter)。

voice_id 留空,等 L3 多声线(P1)接入后再补。
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json, _extract_json_obj
from hevi.tongjian.schemas import (
    ChapterIR,
    CharacterBible,
    CharacterBibleEntry,
    CharacterIR,
    Constitution,
    GateResult,
    Script,
)

logger = logging.getLogger(__name__)

# 年代错误词起始黑名单(起始版,遇到新违规词直接往里加,不必等 RFC;同 L2 违禁词黑名单的惯例)。
_ANACHRONISM_BLACKLIST = [
    "西装",
    "手机",
    "眼镜",
    "唐装",
    "旗袍",
    "中山装",
    "幞头",
    "龙袍",
    "高跟鞋",
]

_CHARACTER_BIBLE_PROMPT_TEMPLATE = """你是历史短片的角色造型设计师。基于下面每个人物在史料中的身份信息和
整体美术风格,为每个人物写一句话外形描述,并给出时代服制校验说明。

美术风格: {art_direction}
色彩基调: {palette}

人物列表:
{character_lines}

只输出一个 JSON 对象:
{{"characters": [
  {{"character_id": "...", "appearance": "外形描述(年龄/体态/服饰/神情,需符合时代)",
    "era_check": "时代服制校验依据(如:战国早期服制:深衣、束发、无幞头)"}}
]}}

硬性规则:
1. 服饰/器物必须符合人物所处历史时期,不得出现后世朝代元素(如唐装/幞头出现在战国场景)。
2. character_id 必须逐一对应上面人物列表里给出的 character_id,不得遗漏、不得杜撰新角色。
"""


def _characters_with_dramatic_role(script: Script, chapter_ir: ChapterIR) -> list[CharacterIR]:
    """spec §5.1 步骤1:"从 script 统计出有戏份的角色(出现在 dialogue 或 visual_hint 中)"。"""
    speaker_ids = {ln.speaker for ln in script.lines if ln.type == "dialogue"}
    result = []
    for c in chapter_ir.characters:
        names = [c.canonical_name, *c.aliases]
        mentioned_in_visual_hint = any(
            ln.visual_hint and any(name in ln.visual_hint for name in names) for ln in script.lines
        )
        if c.character_id in speaker_ids or mentioned_in_visual_hint:
            result.append(c)
    return result


def _build_prompt(characters: list[CharacterIR], constitution: Constitution) -> str:
    character_lines = "\n".join(
        f"{c.character_id}: {c.canonical_name}"
        f"(role={c.role_in_chapter or '未知'}, faction={c.faction or '未知'}, fate={c.fate or '未知'})"
        for c in characters
    )
    return _CHARACTER_BIBLE_PROMPT_TEMPLATE.format(
        art_direction=constitution.visual_style.art_direction,
        palette=", ".join(constitution.visual_style.palette),
        character_lines=character_lines,
    )


def _coerce_character_bible(draft: dict[str, Any], characters: list[CharacterIR]) -> CharacterBible:
    by_id = {c.character_id: c for c in characters}
    drafted: dict[str, dict[str, str]] = {}
    for item in draft.get("characters") or []:
        cid = str(item.get("character_id") or "")
        if cid in by_id:
            drafted[cid] = {
                "appearance": str(item.get("appearance") or ""),
                "era_check": str(item.get("era_check") or ""),
            }

    entries = []
    for c in characters:
        info = drafted.get(c.character_id, {})
        entries.append(
            CharacterBibleEntry(
                character_id=c.character_id,
                name=c.canonical_name,
                appearance=info.get("appearance", ""),
                era_check=info.get("era_check", ""),
            )
        )
    return CharacterBible(characters=entries)


async def generate_character_bible(
    script: Script, chapter_ir: ChapterIR, constitution: Constitution, *, llm: Any = None
) -> CharacterBible:
    """script + chapter_ir + constitution → 角色外形描述(文本部分)。LLM 调用失败 →
    返回只有 character_id/name、外形字段为空的壳(降级,G5 会把这标成 error 而不是崩溃)。
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    characters = _characters_with_dramatic_role(script, chapter_ir)
    if not characters:
        return CharacterBible(characters=[])

    prompt = _build_prompt(characters, constitution)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("character_bible 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}
    return _coerce_character_bible(draft, characters)


def gate_character_bible(bible: CharacterBible) -> GateResult:
    """G5 门:外形描述非空 + 年代错误词扫描 + ref_image 缺失情况(warning,不阻塞——
    可能是候选图全部未过 VLM 年代审,需要人工介入,而非流程性错误)。
    """
    errors: list[str] = []
    warnings: list[str] = []
    filled = 0

    for entry in bible.characters:
        if not entry.appearance:
            errors.append(f"角色 {entry.character_id} 缺少外形描述(LLM 遗漏)")
        else:
            filled += 1
        for term in _ANACHRONISM_BLACKLIST:
            if term in entry.appearance or term in entry.era_check:
                errors.append(f"角色 {entry.character_id} 外形描述命中疑似年代错误词 {term!r}")
        if entry.ref_image is None:
            warnings.append(
                f"角色 {entry.character_id} 尚无权威参考图"
                "(候选立绘未生成,或全部候选未通过 VLM 年代审,见 SPEC-01 §5.1 步骤3-4)"
            )

    coverage = (filled / len(bible.characters)) if bible.characters else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)


# ── 步骤3-4:候选立绘生成 + VLM 年代审 + 锁定 ref_image/gen_lock ────────────

_REFERENCE_IMAGE_PROMPT_TEMPLATE = (
    "{art_direction}风格历史人物肖像,{appearance}。{era_check}。半身像,背景简洁,光线柔和。"
)

_ERA_AUDIT_PROMPT_TEMPLATE = """你是历史短片年代服装审核员。参考下面的时代服制要求,判断这张图片是否
存在年代错误(如后世朝代服饰、现代物品、不合时宜的发型妆造等)。

时代服制要求: {era_check}
人物外形描述: {appearance}

只输出 JSON: {{"passes": true/false, "violations": ["..."]}}"""

# 供 L6 逐镜头用 IP-Adapter 条件生成参考强度的默认值(本步骤只锁定数值,不调用 IP-Adapter)。
_DEFAULT_IP_ADAPTER_WEIGHT = 0.6
_NUM_REFERENCE_CANDIDATES = 3


def _seed_for_candidate(character_id: str, variant: int) -> int:
    digest = hashlib.sha256(f"{character_id}:{variant}".encode()).hexdigest()
    return int(digest[:8], 16)


async def _call_vlm_json(vlm: Any, prompt: str, image_path: Path) -> dict[str, Any]:
    resp = await vlm(
        messages=[{"role": "user", "content": prompt}],
        image_paths=[str(image_path)],
        max_tokens=300,
    )
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    return _extract_json_obj(content)


async def generate_reference_images(
    bible: CharacterBible,
    constitution: Constitution,
    *,
    output_dir: Path,
    image_gen: Any = None,
    vlm: Any = None,
    num_candidates: int = _NUM_REFERENCE_CANDIDATES,
) -> CharacterBible:
    """spec §5.1 步骤3-4:候选立绘(不同种子) → 逐个 VLM 年代审 → 锁定首个通过者。

    已有 ref_image 或外形描述为空的条目跳过(前者已锁定,后者没有可用的生成依据)。
    全部候选都生成失败或未通过年代审 → ref_image 保持 None,G5 报 warning 交人工介入。
    """
    if image_gen is None:
        from obase.provider_registry import ProviderRegistry

        image_gen = ProviderRegistry.get().image_gen("sdxl_local")
    if vlm is None:
        from obase.provider_registry import ProviderRegistry

        vlm = ProviderRegistry.get().vlm("default")

    output_dir.mkdir(parents=True, exist_ok=True)
    updated: list[CharacterBibleEntry] = []

    for entry in bible.characters:
        if entry.ref_image or not entry.appearance:
            updated.append(entry)
            continue

        prompt = _REFERENCE_IMAGE_PROMPT_TEMPLATE.format(
            art_direction=constitution.visual_style.art_direction,
            appearance=entry.appearance,
            era_check=entry.era_check,
        )
        audit_prompt = _ERA_AUDIT_PROMPT_TEMPLATE.format(
            era_check=entry.era_check,
            appearance=entry.appearance,
        )

        locked_path: Path | None = None
        locked_seed: int | None = None
        for i in range(num_candidates):
            candidate_path = output_dir / f"{entry.character_id.lower()}_v{i}.png"
            seed = _seed_for_candidate(entry.character_id, i)
            try:
                await image_gen(prompt=prompt, output_path=candidate_path, seed=seed, extra={})
            except Exception as e:
                logger.warning("角色 %s 候选图 v%d 生成失败: %s", entry.character_id, i, e)
                continue

            try:
                audit = await _call_vlm_json(vlm, audit_prompt, candidate_path)
            except Exception as e:
                logger.warning(
                    "角色 %s 候选图 v%d VLM 年代审调用失败: %s", entry.character_id, i, e
                )
                continue

            if audit.get("passes") is True:
                locked_path = candidate_path
                locked_seed = seed
                break
            logger.info(
                "角色 %s 候选图 v%d 未通过年代审: %s",
                entry.character_id,
                i,
                audit.get("violations"),
            )

        if locked_path is None:
            logger.warning(
                "角色 %s 全部候选图均未通过年代审或生成失败,ref_image 留空", entry.character_id
            )
            updated.append(entry)
        else:
            updated.append(
                entry.model_copy(
                    update={
                        "ref_image": str(locked_path),
                        "gen_lock": {
                            "seed": locked_seed,
                            "ip_adapter_weight": _DEFAULT_IP_ADAPTER_WEIGHT,
                        },
                    }
                )
            )

    return CharacterBible(characters=updated)
