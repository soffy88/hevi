"""SPEC-006 ②Scene Script 生成器 —— 锁定 Screenplay(单场)+ DesignList + World Bible →
Scene Script 草案(逐段时间轴,动作+摄像机行为一体)。

V2 核心反转的落点:场文档不再拆"动作字段"和"摄像机字段"分别描述,而是写成一段连续的
【这段发生了什么 + 摄像机怎么拍这一刻】自然语言。摄像机行为从 World Bible 的
`visual.camera_persona` 派生(prompt 里给出 persona 的 behavior_derivation_text 作为写作
规则),不产出逐段独立字段(避免变成新的"V1 式摄像机坐标字段"入口——Camera Persona 的落点
严格限定在 World Bible 那一份)。

**关键约束**:`scene_stage.py::_match_beats_for_shot` 靠 `beat.trigger == 台词文本`逐字
匹配镜头到 beat。本模块产出的 `dialogue.text` 必须与 narrative_text 里引述的台词逐字一致,
否则下游 SceneStage 抽取器(`scene_stage_extract.py`)产出的 beat 会跟既有 lint 对不上号,
静默失效。prompt 里显式要求这一点。

2026-07-19 打磨第二轮(场内链式生成):切段粒度从固定 2-4s 窗口改成**按戏剧节拍切**,每段
5-10s——链式生成时每段是一次独立 provider 调用,窗口太碎会让链条太长、太粗会让单次调用里
塞不下的动作被压扁。每段额外产出 `handoff_out`(这段收尾的可承接停留点)/`handoff_in`
(这段开场从何承接),供链式生成时段间"末帧条件传递"在文本层面也有对应描述,不只是图像层面
的末帧图片传递。

这是 G-V2 垂直切片(spec §5)②的生成器部分,纯文本 LLM 调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.design_list import _resolve_llm
from hevi.director.pipeline_schemas import (
    DesignList,
    SceneScript,
    SceneScriptDialogueLine,
    SceneScriptSegment,
    ScreenplayScene,
    WorldBible,
)

logger = logging.getLogger(__name__)


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    def _invoke() -> Any:
        return llm(messages=[{"role": "user", "content": prompt}], max_tokens=8192)

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


_SCENE_SCRIPT_PROMPT = """你是电影场记,在把一场戏写成"逐段时间轴"(不是分镜头剧本,是给
旗舰级视频生成模型看的连续场记描述,每段会被独立提交给模型生成一段视频,再链式拼接)。下面是
这场戏的剧本(叙述+对白)、出场人物的角色卷描述、这个场景的世界卷描述、全片的摄像机人格。

**按戏剧节拍切段,每段 3-5 秒,这一整场戏只挑最有戏剧张力的 1 个核心节拍**(不是覆盖这场戏
发生的每一件事,是挑这场戏"如果只留一瞬间,该留哪一瞬间"——比如"睁眼→咬下→咀嚼"这类完整
动作单元,选其中最关键的那个瞬间,不要为这场戏里的每个细节动作都单独成段)。**每一段必须是
【这一刻发生了什么动作 + 摄像机此刻怎么拍】融为一体的一段自然语言**,不要写成"动作:xxx。
镜头:xxx"这种拆开的两句话——摄像机怎么动是这一刻叙事的一部分,不是外挂参数。摄像机行为
必须体现下面给出的"摄像机人格行为规则"(比如如果这个人格是"朋友的DV",这段就该写"镜头
稍微跟晚了半拍,构图因为要追上她的动作而偏离中心"这种带人格感的运镜,不是"镜头平稳跟随"
这种没有个性的描述)。

**编写纪律(密度上限)**:每一段最多同时给 2-3 条具体指令(比如"镜头怎么动"+"人物做什么"+
"表情/细节"算三条),不要在一段里堆砌更多——模型一次处理不了太密的指令,堆多了会互相干扰,
执行出来是模糊的折中,不是精确的叠加。宁可多切一段,不要塞爆一段。

**运镜由"这一刻发生了什么"决定,不靠"避免和上一段雷同"**:每段给一个 `camera_movement`
分类标签。**先看这段的内容属于下面哪一类,就用对应的运镜**(内容→运镜映射,标签用词不必
逐字照抄,但要清楚属于哪一类):
- 场景/地点在全片里**首次出现**、需要建立空间 → "定场推"(缓慢推近建立环境)
- 两人**对白一来一回**、靠表演和台词撑戏 → 在"静态对话"(机位不动)和"反应插入"(切到听者
  反应)之间**交替**,**不要连续两三段都写"静态对话"**——同是对白段,这一段静态,下一段就切
  反应插入;有轻微走位就顺势用横移/跟随。静态对话是最容易被滥用的默认值,全片用量必须压在半数以内
- 人物在空间里**走动/位置变化** → "跟随"或"横移"(镜头随人物平移)。**强运动×身份互斥(实测边界):
  横移/跟随/摇这类大运动段不承担身份识别——不要写主角面部特写、不要求这段认出脸(镜头动得猛脸必然糊,
  和 provider 物理边界对着干没用);写成主角背身/侧身/中远景带过,重点放运动和环境/动作,身份靠前后
  静态段建立。** 别在运动段里锁脸。
- **全片仅有的那 1-2 个真正情绪最高点**的那一瞬 → "峰值轻推"(极轻微推近强调)。**注意:
  绝大多数对白段即使带情绪起伏也不算"峰值",一律走静态对话/反应插入——"峰值轻推"是全片省着
  用的稀缺资源,只留给最关键的一两处,不是每个有情绪的段都能用。**
- 这段动作是被**画外声音触发**的反应 → "摇向声源"(镜头朝画外事件方向摇)
- 都不贴切时,选这一刻最能服务叙事的运镜——**但绝不要默认写"静态对话"当省事的兜底**。
按内容选出来是什么就写什么,不要因为"上一段用过"就刻意回避:真实一场戏里同类运镜本来
就会重复,**重复不是问题,全片单一才是问题**——所以下面这条全片配比才是硬约束。

**全片运镜配比(硬约束,优先级高于上面的内容映射)**:{camera_budget_status}
预算里**带【】方括号的指令是硬性覆盖**,必须无条件服从——哪怕按内容映射这段"像"情绪峰值,
只要预算说"推近类已用满",就不许再选带"推"的,改选反应插入/横移/摇向声源这类非推近类型。
最终以满足"全片至少 3-4 种运镜、静态不过半、推近不超四分之一"为准。

**接缝设计(链式生成的关键)**:每段结尾要在 `handoff_out` 里写清楚这段收尾时人物的可承接
停留点——位置(画面左/中/右)、朝向、动作收束到了什么状态(不是动作中途,是一个能被"接住"
的静止/半静止瞬间)。下面给出的"上一场收尾状态"(如果非空)就是上一场最后一段的
`handoff_out`——这一场第一段的 `handoff_in` 必须明确呼应它、从这个状态接着演,不能另起
一个不相关的开场,而且**动作要立即启动**(这一段的第一个指令就该是接手上一段收尾状态之后
马上发生的动作,不要在开场先来一段静止的过渡缓冲——链式拼接时每段本身已经会在接缝处留一点
静止余量,segment 内部不需要再自己重复留白)。如果"上一场收尾状态"是空的(这是全片第一场),
`handoff_in` 留空。

上一场收尾状态:{prev_handoff_out}

**台词处理(关键约束,不能违反)**:如果这一段里有人说话,dialogue 字段里的 text 必须跟
narrative_text 里引述的台词**逐字一致**,不能改写、不能转述、不能加动作旁注混进 text——
narrative_text 里怎么引用这句台词,dialogue.text 就必须是那几个字,一字不差。

**时长要留够说完这句话(链式打磨第二轮新增)**:如果这段有台词,`t_end_s - t_start_s`
必须留出"把这句台词说完"的时间(中文语速按约 4-5 字/秒估算)再加 0.5-1 秒余量,不能卡着
台词字数长度贴地切——装配阶段音频是独立配音贴上去的,时长不够会导致台词被截断或画面剪辑
时无处下刀。

**这段对应哪个节拍(必填)**:`beat_description` 一句话点名这段具体对应上面"只挑1个核心
节拍"里的哪一瞬间(如"王生额头触地的一瞬"),不能留空、不能是泛泛的场景描述——这是让"是否
真的只写了一个节拍"这件事变得可核查,不是走过场的字段。

**首帧契约:分时衰减**:`handoff_out`/`handoff_in` 写作时按这份清单逐项过一遍——脸/体型/
服装/道具/姿态/座位/前景/背景/光线方向。承接窗(这段开场 0-2s)按这份清单严格保持跟上一段
`handoff_out` 一致;2s 后只需要保持身份/服装/发型/体型的延续,允许有掩护的构图变化(不再
锁死开场那一刻的精确构图)——链式生成时这份清单也会被观察态从上一段真实末帧提取后回填,
这里的写作是给这套机制打的底子。

**有掩护的景别变化**:如果这段内部构图/景别需要变化,必须带"掩护"手法——短暂虚焦再回焦、
手持摇晃、前景遮挡扫过——不能是没有理由的硬切构图,那样会显得跳。

**禁切清单**:结合剧本内容,给这场戏一份 `no_cut_to`(场级,不是逐段)——这场戏不该切到
的画外空间、不该用的景别(比如"不切到门外的街道""不切侧脸大特写"),写 narrative_text 时
主动避开这些内容。没有明显该禁的就给空数组,不要硬凑。

**画外事件驱动反应**:如果这段的动作是被画外的声音触发的反应(比如"画外传来脚步声,角色
转头"),`offscreen_trigger` 填触发源,`narrative_text` 里要写出"触发→反应"的链条(转向
画外、表情随触发变化),焦点保持在角色的反应上,不用真的显示画外那个东西。没有画外触发就
留空。

**人类迟滞 + Persona 收尾**:反应类的段(尤其 `camera_movement` 写"反应插入"的)要带半拍
的人类延迟感("晚半拍才察觉"),不要写成即时反应——即时=机器感,迟滞=自然感。如果这段是
整场戏的最后一段,收尾方式可以呼应上面的"摄像机人格行为规则"本身的性格(比如人格是"朋友的
DV"就可以写"镜头停住,仿佛朋友放下了摄像机"这类,不是每场都要用,只在贴切时用)。

**运动预算显式分配**:除了写"什么在动",也要点名"什么明确不动"(比如"只有帽檐边缘和几缕
发丝被风吹动,其余画面静止"),把运动感集中到这一刻真正的关键动作上,不要让全画面同时轻微
飘动——那样关键动作反而不突出。

**避免可读文字特写(绕开生成模型边界,不硬修)**:视频生成模型渲不出连贯可读的汉字——竹简、
木牍、匾额、告示、书卷上的字给特写,必然是一堆乱码(实测:商鞅立木"徙木立信"竹简特写出来是
"揲草令"),反而出戏。所以**不要把有文字的道具(竹简/木牍/匾额/告示/印章)推成能看清字的特写**;
这类道具只作中远景环境元素带过、或让文字被遮挡/虚焦/侧角,焦点放在人物动作和表情上。文字信息
靠台词/旁白/后期字幕传达,不靠画面里的字。

上一场禁切清单(如果非空,这场沿用,不重新定义除非剧情明确需要新增):{prev_no_cut_to}

只输出 JSON(这一场只给 1 个 segment,不要给多个;`no_cut_to` 是场级字段,只出现一次,
不是每个 segment 里都要):
{{"no_cut_to": ["这场戏禁切的画外空间或景别,没有就给空数组"],
  "segments": [
  {{"t_start_s": 0.0, "t_end_s": 4.0,
    "narrative_text": "【动作+摄像机行为一体】的一段连续描述(2-3条指令密度,动作立即启动)",
    "camera_movement": "这段的运镜分类标签(不能跟上一段雷同)",
    "beat_description": "这段对应的具体节拍,一句话",
    "handoff_out": "收尾停留点(按清单:脸/体型/服装/道具/姿态/座位/前景/背景/光线方向)",
    "handoff_in": "这段开场从何承接(呼应上一段 handoff_out,第一段留空)",
    "offscreen_trigger": "画外触发源,没有就留空",
    "dialogue": [{{"character_name": "说话人", "text": "逐字台词", "target_name": "受话人或空"}}]}}
]}}

摄像机人格行为规则:{camera_persona_id} —— {camera_persona_rule}

出场人物:
{characters_text}

场景:{scene_desc}

第{scene_no}场 {time} {location}
出场:{characters_present}
叙述:{narration}
对白:
{dialogue_text}"""


def _characters_text(scene: ScreenplayScene, world_bible: WorldBible) -> str:
    present = set(scene.characters_present or [])
    entries = [c for c in world_bible.characters if c.name in present]
    if not entries:
        return "、".join(present) or "(无)"
    return "\n".join(f"{c.name}:{c.profile_text} {c.identity_lock_sentence}" for c in entries)


def _scene_desc(scene: ScreenplayScene, world_bible: WorldBible) -> str:
    entry = next((w for w in world_bible.world if w.name == scene.location), None)
    if entry:
        return entry.profile_text
    return scene.location or "(无)"


def _dialogue_text(scene: ScreenplayScene) -> str:
    if not scene.dialogue:
        return "(本场无对白)"
    return "\n".join(
        f"{d.character_name}对{d.target_name or '(无特定对象)'}:{d.text}" for d in scene.dialogue
    )


def _fallback_segments(scene: ScreenplayScene) -> list[SceneScriptSegment]:
    """LLM 失败时的确定性兜底:叙述整体一段,每句对白各自一段,顺序拼接,粗时长估算。
    空描述好过整体失败(照既有惯例)。"""
    segments: list[SceneScriptSegment] = []
    t = 0.0
    _FALLBACK_BEAT = "（兜底段,未标注节拍）"
    if scene.narration:
        dur = max(2.0, min(4.0, len(scene.narration) * 0.15))
        segments.append(
            SceneScriptSegment(
                order=1,
                t_start_s=t,
                t_end_s=t + dur,
                narrative_text=scene.narration,
                beat_description=_FALLBACK_BEAT,
            )
        )
        t += dur
    for d in scene.dialogue:
        dur = max(2.0, min(4.0, len(d.text) * 0.2))
        segments.append(
            SceneScriptSegment(
                order=len(segments) + 1,
                t_start_s=t,
                t_end_s=t + dur,
                narrative_text=f"{d.character_name}:{d.text}",
                beat_description=_FALLBACK_BEAT,
                dialogue=[
                    SceneScriptDialogueLine(
                        character_name=d.character_name, text=d.text, target_name=d.target_name
                    )
                ],
            )
        )
        t += dur
    for i, seg in enumerate(segments):
        seg.segment_id = f"sg{i + 1:03d}"
    return segments


_PUSH_IN_MARKER = "推"  # "定场推"/"峰值轻推"这类带"推"字的运镜标签算 push-in
_STATIC_MARK = "静态"


def _camera_budget_status(camera_tally: list[str] | None, total_scenes: int) -> str:
    """把"全片已选运镜 + 总段数"编成给 LLM 的实时配比预算(2026-07-23,改绝对配比不依赖
    相邻比较——单段场景也有约束可依)。总段数未知(0)时退成不带数字的软指引。"""
    tally = [c for c in (camera_tally or []) if c]
    push_used = sum(1 for c in tally if _PUSH_IN_MARKER in c)
    static_used = sum(1 for c in tally if _STATIC_MARK in c)
    distinct = sorted(set(tally))
    used = "、".join(f"{t}×{tally.count(t)}" for t in distinct) if tally else "(还没有,这是第一段)"
    if total_scenes <= 0:
        return (
            f"已选运镜:{used}。全片目标:推近类(带'推')不超过四分之一、静态对话不过半、"
            f"至少出现 3-4 种不同运镜类型。已出现 {len(distinct)} 种。"
        )
    push_cap = max(1, total_scenes // 4)
    static_cap = max(1, total_scenes // 2)
    flags = []
    if push_used >= push_cap:
        flags.append("【推近类已用满,这段不要再选带'推'的】")
    if static_used >= static_cap:
        flags.append("【静态对话已用满,这段必须选非静态类型】")
    if len(distinct) < 3:
        flags.append(
            f"【全片至今只出现 {len(distinct)} 种运镜,优先选还没出现过的类型补足到 3-4 种】"
        )
    return (
        f"全片共 {total_scenes} 段,已选运镜:{used}(推近 {push_used}/{push_cap} 段、"
        f"静态 {static_used}/{static_cap} 段、已出现 {len(distinct)} 种)。"
        f"硬上限:推近类 ≤{push_cap} 段、静态对话 ≤{static_cap} 段、全片至少 3-4 种不同类型。"
        + ("".join(flags) if flags else "")
    )


async def generate_scene_script_draft(
    *,
    scene: ScreenplayScene,
    design_list: DesignList,
    world_bible: WorldBible,
    llm: Any = None,
    prev_handoff_out: str = "",
    prev_camera_movement: str = "",
    prev_no_cut_to: list[str] | None = None,
    camera_tally: list[str] | None = None,
    total_scenes: int = 0,
) -> SceneScript:
    """锁定 Screenplay(单场)+ DesignList + World Bible → Scene Script 草案。LLM 失败 →
    确定性兜底(叙述整体一段+每句对白各自一段),不阻断。

    `prev_handoff_out`(打磨第二轮新增):上一场最后一段的 `handoff_out` 文本——每场是
    独立 LLM 调用,不传这个参数的话,这一场压根不知道"上一场"收尾在什么状态,写出来的
    `handoff_in` 只能是空的或瞎编的。调用方(逐场循环生成时)应该把上一场结果的最后一段
    `handoff_out` 传进来。空串 = 这是全片第一场,没有上一场可承接。

    `prev_camera_movement`:**2026-07-23 起 prompt 不再用它做"相邻段不雷同"的主约束**——
    单段场景相邻比较无处着力,实测生成器仍产出 13/14 静态。改由 `camera_tally`+`total_scenes`
    的全片绝对配比 + 内容→运镜映射驱动。参数保留(调用方仍传,`lint_camera_movement_variety`
    事后检查照旧),但不再进 prompt。

    `camera_tally`/`total_scenes`(2026-07-23):全片到这一场为止已选的 camera_movement 列表
    + 全片总段数,调用方逐场累加传入——`_camera_budget_status` 据此给这一段一份实时配比
    预算(推近 ≤¼、静态 ≤½、≥3-4 种),让单段场景也有绝对约束可依,不靠相邻比较。

    `prev_no_cut_to`(SPEC-007 §6.3 新增):上一场的禁切清单,同样需要调用方逐场传递并把
    这一场返回的 `no_cut_to` 传给下一场——prompt 里默认沿用上一场的清单(除非剧情明确
    需要新增),避免同一部戏里禁切范围场与场之间自相矛盾。"""
    resolved_llm = _resolve_llm(llm)
    persona = world_bible.visual.camera_persona
    prompt = _SCENE_SCRIPT_PROMPT.format(
        camera_persona_id=persona.persona_id,
        camera_persona_rule=persona.behavior_derivation_text or "(未定义,按稳定专业运镜处理)",
        characters_text=_characters_text(scene, world_bible),
        scene_desc=_scene_desc(scene, world_bible),
        scene_no=scene.scene_no,
        time=scene.time,
        location=scene.location,
        characters_present="、".join(scene.characters_present),
        narration=scene.narration or "(无)",
        dialogue_text=_dialogue_text(scene),
        prev_handoff_out=prev_handoff_out or "(无,这是全片第一场)",
        prev_no_cut_to=("、".join(prev_no_cut_to) if prev_no_cut_to else "(无,这是全片第一场)"),
        camera_budget_status=_camera_budget_status(camera_tally, total_scenes),
    )
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning("scene script draft LLM failed, using fallback: %s", e)
        data = {}

    raw_segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    segments: list[SceneScriptSegment] = []
    for s in raw_segments:
        if not isinstance(s, dict) or not str(s.get("narrative_text") or "").strip():
            continue
        dialogue = [
            SceneScriptDialogueLine(
                character_name=str(d.get("character_name") or "").strip(),
                text=str(d.get("text") or "").strip(),
                target_name=str(d.get("target_name") or "").strip(),
            )
            for d in (s.get("dialogue") or [])
            if isinstance(d, dict) and str(d.get("character_name") or "").strip()
        ]
        segments.append(
            SceneScriptSegment(
                segment_id=f"sg{len(segments) + 1:03d}",
                order=len(segments) + 1,
                t_start_s=float(s.get("t_start_s") or 0.0),
                t_end_s=float(s.get("t_end_s") or 0.0),
                narrative_text=str(s.get("narrative_text") or "").strip(),
                dialogue=dialogue,
                handoff_out=str(s.get("handoff_out") or "").strip(),
                handoff_in=str(s.get("handoff_in") or "").strip(),
                camera_movement=str(s.get("camera_movement") or "").strip(),
                offscreen_trigger=str(s.get("offscreen_trigger") or "").strip(),
                beat_description=str(s.get("beat_description") or "").strip(),
            )
        )

    if not segments:
        segments = _fallback_segments(scene)

    no_cut_to_raw = data.get("no_cut_to")
    no_cut_to = (
        [str(x).strip() for x in no_cut_to_raw if str(x).strip()]
        if isinstance(no_cut_to_raw, list)
        else list(prev_no_cut_to or [])
    )

    total = segments[-1].t_end_s if segments else 0.0
    return SceneScript(
        scene_ref=scene.scene_no,
        characters_present=list(scene.characters_present or []),
        segments=segments,
        total_duration_s=total,
        no_cut_to=no_cut_to,
    )


def lint_camera_movement_variety(segments: list[SceneScriptSegment]) -> list[str]:
    """链式打磨第一轮新增,零成本确定性检查(不经 LLM)——不是 `scene_stage_lint.py` 那套
    L1-L6 体系(那套吃的是 SceneStage/ShotList,查的是场面调度矛盾),这里查的是
    `camera_movement` 标签本身的纪律,输入可以是任意顺序拼接起来的一串 segment(比如跨场
    链式拼接后的完整链条),不要求来自同一个 SceneScript。

    2026-07-20 重新定义(soffy 诊断):"相邻标签不能雷同"这条旧规则实测在平静内省戏上
    100% 假警报(16/16 段全判"雷同"——连续用同一个静态标签在这类戏里本来就是合理的,
    不该强行判错制造假多样性)。真正该抓的是**无意义的重复推拉**(第一轮链式生成真机撞见
    的病:连续 push-in 导致机位跳变),不是"标签不能连续相同"这个过泛的规则。现在拆三种
    情况:

    1. **连续 push-in 重复**(标签都含"推"字)→ 报(`[警告]` 前缀)——这是真病,机位会跳。
    2. **非 push-in 类标签重复,但有客观信号显示这里有情势转变**(相邻两段说话人不同,或
       后一段有 `offscreen_trigger`)→ 软提示(`[提示]` 前缀),不是失败,只是提醒复核。
    3. **非 push-in 类标签重复且没有上述信号**→ 不报——这就是"平静戏连续静态"的合理情况。
    4. 全链里 push-in 类占比超过 1/4 → 仍报(`[警告]` 前缀,这条判据没变)。

    返回违规/提示描述的字符串列表,空列表 = 全部合规。标签为空(未标注)的段不参与判定。
    """
    findings: list[str] = []
    labeled = [(i, s) for i, s in enumerate(segments) if s.camera_movement.strip()]

    for (i, cur_seg), (_, prev_seg) in zip(labeled[1:], labeled[:-1], strict=False):
        cur = cur_seg.camera_movement.strip()
        prev = prev_seg.camera_movement.strip()
        label = cur_seg.segment_id or str(i)
        if _PUSH_IN_MARKER in cur and _PUSH_IN_MARKER in prev:
            findings.append(
                f"[警告] segment[{i}]({label}) 连续推近类运镜「{prev}」→「{cur}」,"
                "是无意义的重复推拉,机位会显得跳"
            )
            continue
        if cur.lower() != prev.lower():
            continue
        cur_speaker = cur_seg.dialogue[0].character_name if cur_seg.dialogue else ""
        prev_speaker = prev_seg.dialogue[0].character_name if prev_seg.dialogue else ""
        speaker_changed = bool(cur_speaker) and bool(prev_speaker) and cur_speaker != prev_speaker
        if speaker_changed or cur_seg.offscreen_trigger.strip():
            findings.append(
                f"[提示] segment[{i}]({label}) 说话人变化或有画外触发,但运镜仍是「{cur}」"
                "跟上一段相同,确认是否该让运镜服务这次转折"
            )

    if labeled:
        push_in_count = sum(1 for _, s in labeled if _PUSH_IN_MARKER in s.camera_movement)
        ratio = push_in_count / len(labeled)
        if ratio > 0.25:
            findings.append(
                f"[警告] push-in 类运镜占比 {push_in_count}/{len(labeled)} = {ratio:.0%},"
                "超过 1/4 上限"
            )
    return findings


def _budget_substitute(seg: SceneScriptSegment) -> str:
    """给一个被兜底改判的段挑一个内容贴切的非静态、非推近运镜——用段内已有的内容信号选,
    保持"内容驱动"(不是无脑贴一个标签):有画外触发→摇向声源;有对白→反应插入(切到听者);
    其余(旁白/动作段)→横移(镜头缓慢横移扫过所述场景,始终成立且非推近)。"""
    if seg.offscreen_trigger.strip():
        return "摇向声源"
    if seg.dialogue:
        return "反应插入"
    return "横移"


def enforce_camera_budget(
    segments: list[SceneScriptSegment], total_scenes: int
) -> list[dict[str, Any]]:
    """LLM 按内容选完运镜后,代码兜底强制全片硬配比(2026-07-23)。实测:改绝对配比 prompt 后
    LLM 能产出 3-4 种运镜、能压住推近类,但**守不住"静态≤½"**——对白/旁白密集的戏它一路默认
    "静态对话",连预算里的硬 flag 都不理(三次免费迭代 ~71-79% 静态)。这里把超出上限的
    "静态对话"段(和超 ¼ 的推近段)确定性改判成 `_budget_substitute` 按段内信号选出的非静态、
    非推近运镜——改判用段自己的内容信号(画外触发/对白/旁白),不是无脑贴标签。按等距抽样挑
    要改的段,不聚在片尾。就地改 `segment.camera_movement`,返回改判记录(供落库/审计)。"""
    static_cap = max(1, total_scenes // 2)
    push_cap = max(1, total_scenes // 4)
    reassigned: list[dict[str, Any]] = []

    def _flip_excess(marker: str, cap: int, why: str) -> None:
        idxs = [i for i, s in enumerate(segments) if marker in s.camera_movement]
        excess = len(idxs) - cap
        if excess <= 0:
            return
        ratio = len(idxs) / excess
        picks = sorted({idxs[min(len(idxs) - 1, int(k * ratio))] for k in range(excess)})
        for i in picks:
            old = segments[i].camera_movement
            new = _budget_substitute(segments[i])
            if new == old:
                continue
            segments[i].camera_movement = new
            reassigned.append({"index": i, "from": old, "to": new, "why": why})

    _flip_excess(_STATIC_MARK, static_cap, "static_over_cap")
    _flip_excess(_PUSH_IN_MARKER, push_cap, "push_over_cap")
    return reassigned


_CHARS_PER_SECOND = 4.5  # 中文语速经验值,粗估台词 TTS 时长用,不是精确值
_MIN_HANDLE_S = 0.5  # 说完台词后至少留的剪辑余量
_MAX_DIALOGUE_SEG_S = 13.0  # 单段延长上限(留在 provider _DURATION_MAX_S=15 之下的头)


def enforce_dialogue_duration(segments: list[SceneScriptSegment]) -> list[dict[str, Any]]:
    """代码兜底:含台词的段,若 `t_end_s - t_start_s` 装不下"估算 TTS + 剪辑余量",**上游就把
    这段时长撑够**(2026-07-23)。此前只有 `lint_dialogue_segment_alignment` 估算但**从没进过
    生成路径**(实测:该 lint 在 produce_v2/router 零调用),对白超时全靠 produce_v2 生成后 QC
    重掷时被动加时——费一次重掷,且重掷预算用尽仍不够就落成 L5"对白时长"fail(基线 s3=50字/
    s12=56字实证)。这里改成**生成前**按估算把 t_end_s 撑到 required,零成本、免掉那次重掷,
    也堵住重掷耗尽的漏。超过单段上限(13s)则撑到上限并记警告(这句太长,真正该拆节拍,留信号)。
    就地改 `segment.t_end_s`,返回调整记录。"""
    adjustments: list[dict[str, Any]] = []
    for seg in segments:
        if not seg.dialogue:
            continue
        total_chars = sum(len(d.text) for d in seg.dialogue)
        required = total_chars / _CHARS_PER_SECOND + _MIN_HANDLE_S
        cur = seg.t_end_s - seg.t_start_s
        if cur >= required:
            continue
        target = min(required, _MAX_DIALOGUE_SEG_S)
        if target <= cur:
            continue
        old_end = seg.t_end_s
        seg.t_end_s = round(seg.t_start_s + target, 1)
        adjustments.append(
            {
                "segment_id": seg.segment_id or seg.order,
                "from_s": round(cur, 1),
                "to_s": round(target, 1),
                "chars": total_chars,
                "still_short": required > _MAX_DIALOGUE_SEG_S,  # 撑到上限仍不够=该拆节拍
                "old_end_s": old_end,
            }
        )
    return adjustments


def lint_dialogue_segment_alignment(segments: list[SceneScriptSegment]) -> list[str]:
    """链式打磨第二轮新增,零成本确定性检查(不经 LLM、不真的调 TTS)——检查含台词的 segment
    时长是否留够"说完这句话 + 剪辑余量"。用字符数 × 经验语速估算 TTS 时长,不是精确值(真实
    TTS 时长受标点停顿/语气影响会有出入),这里只做"明显装不下"的粗筛,不是精确校验。

    装配阶段用独立 TTS 配音(音频主导),这里不够会导致真实合成的台词音频比这段视频还长,
    要么被截断要么迫使装配层强行拉伸——生成前先筛掉这类段,比生成后再发现划算。
    """
    findings: list[str] = []
    for seg in segments:
        if not seg.dialogue:
            continue
        total_chars = sum(len(d.text) for d in seg.dialogue)
        est_tts_s = total_chars / _CHARS_PER_SECOND
        seg_dur = seg.t_end_s - seg.t_start_s
        required = est_tts_s + _MIN_HANDLE_S
        if seg_dur < required:
            findings.append(
                f"segment {seg.segment_id or seg.order} 时长 {seg_dur:.1f}s,台词共 {total_chars} 字"
                f"估算需要 {est_tts_s:.1f}s + 至少 {_MIN_HANDLE_S}s 余量 = {required:.1f}s,不够"
            )
    return findings


def lint_beat_and_dialogue_boundary(segments: list[SceneScriptSegment]) -> list[str]:
    """SPEC-007 段边界双约束——"戏剧节拍边界"本身是语义判断,没法公式化验证,但
    `beat_description` 字段(见 `pipeline_schemas.py::SceneScriptSegment`)把它变成了一个
    可查信号:每段是否显式点名了自己对应的节拍。这条 lint 把这个信号跟已有的
    `lint_dialogue_segment_alignment`(语句边界条件)放在同一批 segments 上联合检查,
    分别报告"缺哪一个条件"——不是重新发明判据,是把两条各自独立存在的检查第一次同时跑在
    同一视角下。"""
    findings: list[str] = []
    dialogue_findings = set(lint_dialogue_segment_alignment(segments))
    for seg in segments:
        label = seg.segment_id or str(seg.order)
        missing_beat = not seg.beat_description.strip()
        missing_dialogue_fit = any(f.startswith(f"segment {label} ") for f in dialogue_findings)
        if missing_beat and missing_dialogue_fit:
            findings.append(f"segment {label}:节拍边界和语句边界两个条件都不满足")
        elif missing_beat:
            findings.append(f"segment {label}:缺 beat_description,节拍边界条件不满足")
        elif missing_dialogue_fit:
            findings.append(f"segment {label}:语句边界条件不满足(时长装不下台词)")
    return findings
