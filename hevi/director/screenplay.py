"""SPEC-003 ②剧本 —— 锁定 Concept + 素材原文 → Screenplay 白话分场剧本草稿。

**核心要求:把小说语言改编成能拍成戏的剧本语言(2026-07-16 加厚)。** 这是整条链最上游、
最该下功夫的一环——数字人只能照剧本演:剧本只给"谁说了句什么",产出就是一个个大头念台词、
没动作没感情;剧本给了"骑马飞奔→跪拜→一口喝干水→掣剑欲自刎",才有场面、动作、情绪。故 prompt
强制:①把每个情节点展开成一连串可拍的物理动作+走位+环境+表情;②一场一情绪/动作拍点,不把多轮
对白挤进一个大头场;③narration 写成分镜级可拍画面(不是情节概要);④文言转白话但保住名句/意象/
语气分量。prompt 里带一段"小说一句→剧本四场"的张飞失徐州 few-shot 示范锚定粒度。

每场拆出"叙述"(narration,可拍画面)与"人物对白"(dialogue,带 speaker/target)两块,喂给
③设计清单/③.5 场面调度/④分镜。narration 越丰富,下游越能切出动作镜而非大头对白。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.pipeline_schemas import (
    Concept,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
)

logger = logging.getLogger(__name__)

_SCREENPLAY_PROMPT = """你是电影编剧。把下面的素材(常是文言小说)改编成**能直接拍成戏的剧本语言**——
不是复述情节,是把文字"排成一场场戏"。

**这是命门:小说语言 ≠ 剧本语言。** 小说一句"张飞报信",照搬只会拍成一个大头念台词、没动作没感情。
剧本必须把每个情节点**展开成一连串具体、可拍的动作 + 走位 + 环境 + 表情**,让镜头有东西拍。示范
(小说一句 → 剧本拆成几场):

  小说原文:"张飞引数十骑,直到盱眙来见玄德,具说曹豹与吕布里应外合,夜袭徐州。众皆失色。"
  剧本改编:
   第1场 官道·黄昏:残阳下一队骑兵卷尘狂奔,为首张飞满身征尘、眼眶通红,狠抽战马。(无对白,只有马蹄粗喘)
   第2场 凉亭外:张飞奔至猛勒缰,战马人立,他滚下马踉跄两步,嘶哑远喊"大哥——!",连滚带爬扑向凉亭。
   第3场 凉亭:刘备关羽起身相迎,张飞扑通跪地抱拳、肩膀剧烈起伏,刘备俯身扶起
        "三弟先坐下歇口气",三人落座。
   第4场 凉亭:下人端水,张飞一口喝干、抹脸,急得发抖脱口"大哥!昨夜曹豹跟吕布里应外合袭了城,徐州丢了!",
        众人失色、有人茶盏当啷落地。
  —— 一句小说,扩成四场;每场一个动作/情绪节拍,全是可拍的画面。

**据此严格做到:**
1. **补物理动作**:每个情节点找出可拍的身体动作(骑马/勒马/下马/奔跑/跪拜/扶起/落座/端水/一饮而尽/
   顿足/拔剑/夺剑…)写进叙述。**没有任何身体动作的纯大头对白场,是失败的。**
2. **一场一拍点**:一个情绪或动作节拍单独成一场,不要把好几轮对白挤进一个"大头说话"场。宁可多分几场。
   **节拍边界≠微反应边界**:一个节拍=一次真正的情势转变(说话人转换/动作发生质变/情绪整体
   切换/空间或时间跳转)。同一情势内的细微反应——喉结滚动、指节泛白、呼吸变化、眼神游移这类
   ——是这个节拍**内部的表演细节**,写进这一场的画面描述里让镜头有东西拍,不要因为写了这些
   细节就拆成新的一场。判断依据:还是同一个人、同一句话或同一个静止姿态期间,只是表情/小
   动作在变化,那仍是同一个节拍。
3. **叙述写成可拍的画面**:narration 写清楚谁在哪、朝向谁、做什么动作、什么表情、
   环境什么样(黄昏官道、临水凉亭…),可夹带镜头感(远景/近景/特写、谁切谁的反打)。
   **不是"众人商议"这种概要,是能照着拍的分镜级描述。**
4. **对白带情绪与身体状态**:每句台词点出说话时的情绪/动作(哭腔、低到几乎听不见、顿足怒吼…),
   写进台词或叙述。

**白话要求(配音自然、观众听得懂):** 文言字词转现代口语,不要"之乎者也/尔汝/寡人"的文言腔,
也不半文半白。
**但忠实原文、不许削弱:** 原文说三层意思白话也说三层;**保留名句/比喻/意象**(如"得何足喜,失何足忧"、
"兄弟如手足,妻子如衣服")——说成人话但不丢掉这个意象本身;保留语气分量(该恳切/痛切/有气势)。
你是"翻译+口语化+排成戏",不是"缩写+改编"。宁可长而忠实,不要短而失神。

立意约束:主题「{theme}」,基调「{tone}」,风格「{style}」。

每场拆成两块:
- narration:**可拍的画面描述**(白话)——环境 + 谁在哪朝向谁 + 做什么动作 + 什么表情
  (可含镜头感),不是情节概要
- dialogue:人物开口说的话,每句标出谁说的(白话,保留原文意思与力度)+ 对谁说的(target_name,须本场在场;
  独白/对众留空)

只输出 JSON:
{{"scenes": [
  {{"scene_no": 1, "time": "时间(如 黄昏/三日后)", "location": "地点(具体化,如 盱眙城外临水凉亭)",
    "characters_present": ["人物名", ...],
    "narration": "可拍的画面:环境+谁在哪朝向谁+做什么动作+表情(可含镜头感),不是概要",
    "dialogue": [{{
      "character_name": "人物名", "text": "白话台词(含情绪/身体状态)",
      "target_name": "受话人物名或留空"}}],
    "event_summary": "该场事件概要"}}
]}}

素材:
{material_text}"""


# 剧本自审-修订(2026-07-16):初稿由同一模型一遍产出,常有"某场还是纯大头对白""narration 写成
# 概要而非画面""名句被冲淡""人物基础设定混进当前状态"等毛病。加一道审核员视角的二遍——拿初稿
# 逐场对清单挑毛病并**直接改好**,输出修订后的完整剧本。实测通常能补动作、拆大头场、还原名句。
_REVIEW_PROMPT = """你是资深剧本审核(比编剧更挑剔)。下面是初稿剧本 JSON 和素材原文。逐场按清单
挑出毛病并**直接改好**,输出修订后的**完整**剧本 JSON(同 schema,不要只写改动说明)。

审核清单(逐场过):
1. **每场必须有可拍的物理动作**——若某场是纯大头对白、没有任何身体动作/走位,给它补动作
   (骑马/勒马/下马/跪拜/扶起/端水/一饮而尽/顿足/拔剑/夺剑…)或拆成带动作的几场。
2. **节拍边界要准,不是拆得越细越好**——一个节拍=一次真正的情势转变(说话人转换/动作发生
   质变/情绪整体切换/空间或时间跳转)。若一场里挤了好几轮对白或多个节拍,拆成多场。**反过来:
   如果初稿里连续几场其实是同一个节拍内部的微反应在变化(喉结滚动、指节泛白、呼吸变化、眼神
   游移这类),合并成一场,把这些细节写进合并后那一场的画面描述里——不要因为反应写得细腻就
   认为该拆场。** 这条判断是双向的,查完拆分不够的场次,也要查有没有过度拆分的场次。
3. **narration 是可拍画面不是情节概要**——"众人商议""交代军情"这种概要,改写成"谁在哪、
   朝向谁、做什么动作、什么表情、环境什么样"的分镜级画面。
4. **对白带情绪与受话人**——每句台词点出说话时情绪/身体状态,target_name 填对谁说(须在场)。
5. **白话但忠实**——文言转口语,但**保留原文名句/比喻/意象**(如"得何足喜,失何足忧"),
   原文说几层意思就说几层,不许缩写、不许丢关键情节。
6. **人物基础设定不混进当前状态**——narration/对白可写当前状态,但别把"浴血/破损"当成人物恒定属性。

立意约束:主题「{theme}」,基调「{tone}」,风格「{style}」。

只输出修订后的完整剧本 JSON(schema 同初稿:{{"scenes":[{{"scene_no","time","location",
"characters_present","narration","dialogue":[{{"character_name","text","target_name"}}],
"event_summary"}}]}})。初稿已经不错的场次原样保留,别为改而改。

素材原文:
{material_text}

初稿剧本:
{draft_json}"""


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    # 见 concept.py 同名函数注释:qwen_cloud 适配器构造时同步发 HTTP 请求,不放线程池
    # 会把单线程 event loop 卡住到调用返回为止。
    def _invoke() -> Any:
        return llm(messages=[{"role": "user", "content": prompt}], max_tokens=8192)

    # 剧本是全链最重的一次 LLM 调用:加厚 prompt 后 qwen 常产出 10+ 场丰富内容,实测 ~47s,
    # 旧的 45s 超时线会在临门一脚砍掉整份剧本 → 静默吃兜底(1 场=原文照抄)。这一步是同步
    # HTTP 阶段(POST /screenplay 直接 await),上游 Cloudflare ~100s 会先 524,故内部超时设
    # 90s(~1.9x 余量稳过正常调用,病态慢调用在 524 之前就干净兜底,不设 >100s 的无效值)。
    obj = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=90.0)
    resp = await obj if hasattr(obj, "__await__") else obj
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _resolve_llm(llm: Any) -> Any:
    if llm is not None:
        return llm
    from obase.provider_registry import ProviderRegistry

    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        return ProviderRegistry.get().llm("default")


async def generate_screenplay_draft(
    *, concept: Concept, material_text: str, llm: Any = None
) -> Screenplay:
    """锁定 Concept + 素材原文 → Screenplay 草稿。LLM 失败/解析失败 → 返回单场的兜底剧本
    (叙述=原文本身,人审核阶段可以手工补,不因草稿生成失败阻断流程)。"""
    resolved_llm = _resolve_llm(llm)
    prompt = _SCREENPLAY_PROMPT.format(
        theme=concept.theme or "(未定)",
        tone=concept.tone or "(未定)",
        style=concept.style or "(未定)",
        material_text=material_text,
    )
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning("screenplay draft LLM failed, using fallback: %s", e)
        data = {}

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        return Screenplay(
            scenes=[ScreenplayScene(scene_no=1, narration=material_text, event_summary="")]
        )

    # 二遍:LLM 自审-修订。审核失败/输出不合法 → 保留初稿,不阻断。
    from hevi.core.config import settings

    if settings.screenplay_llm_review:
        try:
            review_prompt = _REVIEW_PROMPT.format(
                theme=concept.theme or "(未定)",
                tone=concept.tone or "(未定)",
                style=concept.style or "(未定)",
                material_text=material_text,
                draft_json=json.dumps(data, ensure_ascii=False),
            )
            revised = await _call_llm_json(resolved_llm, review_prompt)
            revised_scenes = revised.get("scenes")
            if isinstance(revised_scenes, list) and revised_scenes:
                raw_scenes = revised_scenes
                logger.info(
                    "screenplay 自审-修订完成:%d 场 → %d 场",
                    len(data["scenes"]),
                    len(revised_scenes),
                )
        except Exception as e:
            logger.warning("screenplay 自审-修订失败,保留初稿: %s", e)

    scenes: list[ScreenplayScene] = []
    for i, raw in enumerate(raw_scenes):
        if not isinstance(raw, dict):
            continue
        raw_dialogue = raw.get("dialogue") or []
        dialogue = [
            ScreenplayDialogueLine(
                character_name=str(d.get("character_name") or "").strip(),
                text=str(d.get("text") or "").strip(),
                target_name=str(d.get("target_name") or "").strip(),
            )
            for d in raw_dialogue
            if isinstance(d, dict) and str(d.get("text") or "").strip()
        ]
        scenes.append(
            ScreenplayScene(
                scene_no=int(raw.get("scene_no") or i + 1),
                time=str(raw.get("time") or "").strip(),
                location=str(raw.get("location") or "").strip(),
                characters_present=[
                    str(c).strip() for c in (raw.get("characters_present") or []) if str(c).strip()
                ],
                narration=str(raw.get("narration") or "").strip(),
                dialogue=dialogue,
                event_summary=str(raw.get("event_summary") or "").strip(),
            )
        )
    scenes = scenes or [ScreenplayScene(scene_no=1, narration=material_text)]
    # 测试用场数上限:只取前 N 场(见 settings.director_max_scenes 注释)。下游全派生自剧本,
    # 一处截断即限住整条链的镜头数/渲染量。None/0 = 不限。
    from hevi.core.config import settings

    cap = settings.director_max_scenes
    if cap and cap > 0:
        scenes = scenes[:cap]
    return Screenplay(scenes=scenes)
