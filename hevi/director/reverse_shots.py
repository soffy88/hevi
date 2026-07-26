"""双人对白正反打镜序生成(2026-07-25,治「辩论戏塌成静止双人镜」)。

**能力有、结构没接**:produce_v2 能双人同框(INC-003 验过)、happyhorse 只动说话人脸,但分镜层
从不产「正反打镜序」——1 对白行→1 镜,辩论被塞成一个静止双人镜(廷辩试跑实证)。这里在 V2
SceneScript 层把辩论场展开成电影级正反打:

    master(双人全景,建立轴线 + 定 A画左/B画右)
      → 逐对白轮 OTS 过肩反打:说话人恒在己侧、清晰;对手肩背虚焦入前景(身份不重要)
      → 反打机位过轴,但**人物左右位不翻**(side_convention,治双人对白最易崩的跳轴)

OTS 前景为什么不用 Subject3D 背视图:① 那条 per-view 管线没接进 V2;② 非正面 TripoSR 视图实测
削弱泛型脸身份(QNLR-EP0-CONF §)。前景是虚焦肩背,身份本就不重要,用文字描述 + 正面 canon 松
参考即可,不值得为它建管线。

顺带治 ④a 场景连续性:辩论被前端拆进相邻两场(王绾场/李斯场)时,`target_name` 指向对方 →
判为同一辩论,先合并再展开(否则每场只 1 speaker,识别不出辩论)。
"""

from __future__ import annotations

from typing import Any

from hevi.director.pipeline_schemas import SceneScript, SceneScriptSegment

_MASTER_DURATION_S = 2.5  # 建轴 master 镜时长(无对白,纯建立)
_OPP = {"画左": "画右", "画右": "画左"}

# 剪切镜 shot_type:另起视角/机位的独立镜。single 是同镜内的连续动作。见 `segment_continues_prior`。
CUT_SHOT_TYPES = frozenset({"master", "ots", "frontal"})


def segment_continues_prior(segment: SceneScriptSegment) -> bool:
    """这一段是否**接续上一段的动作/构图**(→ produce_v2 该拿上一段末帧作连续性参考)。

    ★★ "反打=剪切"电影常识第一次进 V2 生成逻辑(2026-07-25)。连续性规则**按镜头关系决定,不无差别
    传**:
      - 连续动作段(`shot_type=single`,同空间接着上一段演)→ **接**上一段末帧(动作/空间连续)。
      - 剪切镜(`master`/`ots`/`frontal`,另起视角/机位)→ **不接**,各自从 canon+场景独立起——它是
        CUT 不是 continuation。否则新镜会"接着上一镜构图往下演",复制上一镜的人物/左右位:反打翻不
        过去、机位切换被抹平(实证:李斯 OTS 拿王绾 OTS 末帧续接,渲成王绾在同侧,反打失效)。
    判据 = 同一 shot 内的连续 vs 跨 shot 的剪切,由 shot_type 编码。以后所有剪切镜都走这条规则。"""
    return getattr(segment, "shot_type", "single") not in CUT_SHOT_TYPES


def _speakers_in_order(segments: list[SceneScriptSegment]) -> list[str]:
    seen: list[str] = []
    for seg in segments:
        for d in seg.dialogue:
            if d.character_name and d.character_name not in seen:
                seen.append(d.character_name)
    return seen


def is_debate(scene_script: SceneScript) -> bool:
    """≥2 个不同对白 speaker → 辩论场。"""
    return len(_speakers_in_order(scene_script.segments)) >= 2


def _identify_axis_and_monarchs(
    speakers: list[str], segments: list[SceneScriptSegment]
) -> tuple[list[str], set[str]]:
    """廷议规则(复用所有廷议场,非本集特判):**主辩双方锁反打轴,君主/裁决者另处理**。

    ① 最强信号 = **互相驳斥的一对**(A 的对白 target B、B 的对白 target A):这对就是反打轴,其余
       (含君主/裁决者)另处理(2026-07-26:商鞅廷辩实证——卫鞅被甘龙+孝公都 target,按"被≥2人诉诸"
       会把主辩卫鞅误判成君主;而卫鞅↔甘龙 互相驳斥才是真轴)。
    ② 无互驳对 → 退回:君主 = 被 ≥2 人诉诸**且不是发言最多**的那个(发言最多的必是主辩,不是裁决者);
       主辩 = 其余首两名。
    ③ 仍识别不出双主辩 → 首两名 speaker 当轴、不拉君主(降级不崩)。"""
    targets_of: dict[str, set[str]] = {}
    turns: dict[str, int] = {}
    for seg in segments:
        for d in seg.dialogue:
            if d.character_name:
                turns[d.character_name] = turns.get(d.character_name, 0) + 1
                if d.target_name:
                    targets_of.setdefault(d.character_name, set()).add(d.target_name)

    # ① 互驳对(按 speakers 首现序取第一对)
    for i, a in enumerate(speakers):
        for b in speakers[i + 1 :]:
            if b in targets_of.get(a, ()) and a in targets_of.get(b, ()):
                return [a, b], {s for s in speakers if s not in (a, b)}

    # ② 君主 = 被≥2人诉诸且非发言最多者
    appealed_by: dict[str, set[str]] = {}
    for spk, tgts in targets_of.items():
        for t in tgts:
            appealed_by.setdefault(t, set()).add(spk)
    max_turns = max(turns.values(), default=0)
    monarchs = {
        s for s in speakers if len(appealed_by.get(s, ())) >= 2 and turns.get(s, 0) < max_turns
    }
    debaters = [s for s in speakers if s not in monarchs]
    if len(debaters) < 2:  # ③ 降级
        return speakers[:2], set()
    return debaters[:2], monarchs | set(debaters[2:])


def expand_debate_reverse_shots(
    scene_script: SceneScript, *, master_duration_s: float = _MASTER_DURATION_S
) -> SceneScript:
    """辩论场 → 正反打镜序。非辩论场原样返回(纯函数,零成本)。

    - 主辩双方(A/B)= 画左/画右锁死,全场不翻(side_convention);OTS 前景 = **对方主辩**(锁反打轴,
      不看 target——视觉轴在两名主辩之间)。
    - 君主/裁决者(见 `_identify_axis_and_monarchs`)不进反打轴:出**御座正面略仰独立镜**。"""
    speakers = _speakers_in_order(scene_script.segments)
    if len(speakers) < 2:
        return scene_script

    axis, _monarchs = _identify_axis_and_monarchs(speakers, scene_script.segments)
    a, b = axis[0], axis[1]  # 其余 speaker(含 _monarchs)不在 side → 走御座正面分支
    side = {a: "画左", b: "画右"}
    turns = [(d, seg) for seg in scene_script.segments for d in seg.dialogue]

    new: list[SceneScriptSegment] = [
        SceneScriptSegment(
            segment_id="sg001",
            order=1,
            t_start_s=0.0,
            t_end_s=master_duration_s,
            narrative_text=(
                f"全景建立轴线:{a}在{side[a]}、{b}在{side[b]},二人相对立于同一空间,"
                f"确立此后反打的左右位"
            ),
            shot_type="master",
            camera_movement="定场",
        )
    ]
    for i, (d, src) in enumerate(turns):
        spk = d.character_name
        dur = max(1.5, (src.t_end_s or 0.0) - (src.t_start_s or 0.0)) or master_duration_s
        base = {
            "segment_id": f"sg{i + 2:03d}",
            "order": i + 2,
            "t_start_s": 0.0,
            "t_end_s": dur,
            "dialogue": [d],
        }
        if spk in side:  # 主辩 → OTS,前景=对方主辩(锁轴)
            fg = b if spk == a else a
            s_side = side[spk]
            new.append(
                SceneScriptSegment(
                    **base,
                    narrative_text=(
                        f"过肩反打:前景是{fg}的肩背({_OPP[s_side]}侧,虚焦不清、只作前景遮挡),"
                        f"后景{spk}正面清晰、立于{s_side},面向{fg}说话"
                    ),
                    shot_type="ots",
                    speaker_side=s_side,
                    foreground_character=fg,
                    camera_movement="过肩反打",
                )
            )
        else:  # 君主/裁决者 → 御座正面略仰,独立成镜(不进反打轴)
            new.append(
                SceneScriptSegment(
                    **base,
                    narrative_text=(
                        f"御座正面略仰镜:{spk}居中端坐御座、略仰拍显威仪,独立成镜,不与臣子过肩反打"
                    ),
                    shot_type="frontal",
                    camera_movement="御座正面略仰",
                )
            )

    return SceneScript(
        scene_ref=scene_script.scene_ref,
        characters_present=scene_script.characters_present,
        segments=new,
        total_duration_s=sum((s.t_end_s or 0.0) - (s.t_start_s or 0.0) for s in new),
        no_cut_to=list(getattr(scene_script, "no_cut_to", []) or []),
    )


def _scenes_linked(prev: SceneScript, cur: SceneScript) -> bool:
    """相邻两场是否属**同一辩论**——合并条件从严,只治 ④a「一场辩论被拆散」,不误合并单主角多场:
    合并后多说话人(combined≥2),且**两个方向都有跨场对话**——prev 有对白 target 指向 cur 的 speaker,
    **且** cur 有对白 target 指向 prev 的 speaker。单方向或无跨场 target 不合并(2026-07-26 商鞅实证:
    廷辩 target 卫鞅、立木卫鞅无 target,单向不该把立木并进廷辩;拆散的辩论则双向都有跨场 target)。"""
    ps = set(_speakers_in_order(prev.segments))
    cs = set(_speakers_in_order(cur.segments))
    if not ps or not cs or len(ps | cs) < 2:
        return False
    prev_tgt = {d.target_name for seg in prev.segments for d in seg.dialogue if d.target_name}
    cur_tgt = {d.target_name for seg in cur.segments for d in seg.dialogue if d.target_name}
    return bool(prev_tgt & cs) and bool(cur_tgt & ps)


def _concat_scenes(prev: SceneScript, cur: SceneScript) -> SceneScript:
    present = list(prev.characters_present)
    for nm in cur.characters_present:
        if nm not in present:
            present.append(nm)
    return SceneScript(
        scene_ref=prev.scene_ref,
        characters_present=present,
        segments=list(prev.segments) + list(cur.segments),
        total_duration_s=(prev.total_duration_s or 0.0) + (cur.total_duration_s or 0.0),
        no_cut_to=list(getattr(prev, "no_cut_to", []) or []),
    )


def expand_scene_script_set_debates(scripts: list[SceneScript]) -> list[SceneScript]:
    """SceneScriptSet 级:先合并被拆散的同一辩论(④a),再逐场展开正反打(①)。scene_ref 重编号。"""
    merged: list[SceneScript] = []
    for sc in scripts:
        if merged and _scenes_linked(merged[-1], sc):
            merged[-1] = _concat_scenes(merged[-1], sc)
        else:
            merged.append(sc)

    out: list[SceneScript] = []
    for i, sc in enumerate(merged, start=1):
        expanded = expand_debate_reverse_shots(sc)
        out.append(
            SceneScript(
                scene_ref=i,
                characters_present=expanded.characters_present,
                segments=expanded.segments,
                total_duration_s=expanded.total_duration_s,
                no_cut_to=list(getattr(expanded, "no_cut_to", []) or []),
            )
        )
    return out


def summarize_shot_sequence(scripts: list[SceneScript]) -> list[dict[str, Any]]:
    """免费验证用:把镜序结构摊平成可打印清单(shot_type / speaker / side / 前景),不渲染。"""
    rows: list[dict[str, Any]] = []
    for sc in scripts:
        for seg in sc.segments:
            spk = seg.dialogue[0].character_name if seg.dialogue else ""
            rows.append(
                {
                    "scene": sc.scene_ref,
                    "seg": seg.segment_id,
                    "shot_type": seg.shot_type,
                    "speaker": spk,
                    "side": seg.speaker_side,
                    "fg": seg.foreground_character,
                    "line": (
                        seg.dialogue[0].text[:16] if seg.dialogue else seg.narrative_text[:16]
                    ),
                }
            )
    return rows
