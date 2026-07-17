"""L0 输出契约 chapter_ir —— 见 HEVI-SPEC-01 §1.2。pydantic 模型天然给 G0 的
"结构校验: JSON Schema 强校验"那一条,不用另写校验器。

source_span 是 [start, end) 字符下标,指向 meta 之外传入的原文(raw_text)。这些下标
**由代码算,不由 LLM 报**——LLM 抽"确切引文原句",代码用确定性字符串查找定位下标,
避免 LLM 数字符的老毛病(小模型对着长文本数下标几乎必错)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LayerConfig(BaseModel):
    """通鉴流水线**单层的模型选择 + 可调参数**——每层(L0..L8)可独立配置,便于全自动生成
    有偏差时逐层调参重跑。`model=None` 走该层默认模型;`params` 覆盖该层默认参数(具体键值
    由各层 build_* 自行解释,见各层 docstring)。前端 RunRequest 表单直接填这个结构。"""

    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class CharacterIR(BaseModel):
    character_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    role_in_chapter: str = ""  # protagonist/antagonist/supporting/anonymous...
    faction: str | None = None
    fate: str | None = None
    source_spans: list[tuple[int, int]] = Field(default_factory=list)


class EventIR(BaseModel):
    event_id: str
    summary: str
    actors: list[str] = Field(default_factory=list)  # character_id 列表
    location: str | None = None
    year: int | None = None  # 公元纪年,负数=公元前
    causes: list[str] = Field(default_factory=list)  # event_id 列表
    effects: list[str] = Field(default_factory=list)  # event_id 列表
    dramatic_weight: int = 3  # 1-5,戏剧性权重,决定该事件是否必入某一幕(G1 用)
    source_span: tuple[int, int] = (0, 0)


class QuoteIR(BaseModel):
    quote_id: str
    speaker: str  # character_id
    original: str  # 原文引语(未经改写,dialogue 只准改写自这里 —— 全流水线的史实红线)
    modern: str = ""  # 白话译文(供 L2 剧本改写参考)
    event_id: str | None = None
    emotion: str = ""


class LocationHint(BaseModel):
    scene_hint_id: str
    name: str
    type: str = ""  # 城池/宫殿/战场...
    events: list[str] = Field(default_factory=list)  # event_id 列表


class ChapterMeta(BaseModel):
    source: str  # 如"资治通鉴·周纪一"
    year_range: tuple[int, int] | None = None
    char_count: int = 0


class ChapterIR(BaseModel):
    meta: ChapterMeta
    characters: list[CharacterIR] = Field(default_factory=list)
    events: list[EventIR] = Field(default_factory=list)
    quotes: list[QuoteIR] = Field(default_factory=list)
    locations: list[LocationHint] = Field(default_factory=list)


class GateResult(BaseModel):
    """各层校验门(G0/G1/...)的统一返回形状。"""

    passed: bool
    coverage: float = 1.0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── L1 立意(constitution.json)—— HEVI-SPEC-01 §2.1 ──────────────────────


class VisualStyle(BaseModel):
    art_direction: str = ""
    palette: list[str] = Field(default_factory=list)
    aspect_ratio: str = "16:9"
    negative_style: list[str] = Field(default_factory=list)


class Act(BaseModel):
    act: int
    title: str = ""
    events: list[str] = Field(default_factory=list)  # event_id 列表,引用 chapter_ir.events
    emotion_curve: str = ""


class Constitution(BaseModel):
    thesis: str = ""
    logline: str = ""
    narrative_stance: str = ""
    tone: list[str] = Field(default_factory=list)
    visual_style: VisualStyle = Field(default_factory=VisualStyle)
    act_structure: list[Act] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    target_duration_sec: int = 180
    bgm_mood_arc: list[str] = Field(default_factory=list)


# ── L2 剧本(script.json)—— HEVI-SPEC-01 §3.2 ─────────────────────────────


class ScriptLine(BaseModel):
    line_id: str
    act: int = 1
    type: str = "narration"  # narration/dialogue/commentary
    speaker: str = "NARRATOR"
    text: str = ""
    event_id: str | None = None
    quote_id: str | None = (
        None  # dialogue 行:引用 chapter_ir.quotes 里真实存在的 quote_id(逐字引语改写)
    )
    # dramatized=True 表示"戏剧化改编"台词:原文该事件无直接引语,由编剧为真实事件创作符合时代
    # 口吻的对白(忠于事件,措辞是创作)。这类行 quote_id 可为空,不受"逐字引语"红线约束,
    # 但仍受 G2 事实幻觉门约束(不得编造原文没有的情节/官职/称谓)。
    dramatized: bool = False
    emotion: str = ""
    visual_hint: str = ""
    target: str = ""  # INC-001 §H 受话对象(对谁说)→ L6 关键帧 eyeline(说话者目光看向该角色)


class Script(BaseModel):
    lines: list[ScriptLine] = Field(default_factory=list)


# ── L3 配音时间轴(timeline.json)—— HEVI-SPEC-01 §4.3 ────────────────────


class AudioSegment(BaseModel):
    """一行剧本对应的 TTS 音频片段。"""

    line_id: str
    file: str = ""  # 相对路径,如 "audio/ln001_a3f8.wav"
    duration_ms: int = 0
    t_start_ms: int = 0
    t_end_ms: int = 0


class TimelineGap(BaseModel):
    """幕间/段间空隙(音乐呼吸位)。"""

    after_line: str
    duration_ms: int = 1500
    purpose: str = "act_transition"


class Timeline(BaseModel):
    audio_segments: list[AudioSegment] = Field(default_factory=list)
    total_duration_ms: int = 0
    gaps: list[TimelineGap] = Field(default_factory=list)


# ── L4 分镜(shotlist.json)—— HEVI-SPEC-01 §6.2 ──────────────────────────


class ShotCamera(BaseModel):
    """镜头景别与运镜。"""

    shot_size: str = "medium"  # wide/medium/medium_close/close_up/extreme_close
    movement: str = (
        "static"  # static/slow_push_in/slow_pull_out/pan_left/pan_right/tilt_up/tilt_down
    )


class Shot(BaseModel):
    shot_id: str
    line_ids: list[str] = Field(default_factory=list)
    t_start_ms: int = 0
    t_end_ms: int = 0
    scene_id: str = ""
    characters: list[str] = Field(default_factory=list)  # character_id 列表
    camera: ShotCamera = Field(default_factory=ShotCamera)
    visual_prompt: str = ""
    motion_mode: str = "ken_burns"  # ken_burns / img2video / static
    is_transition: bool = False  # True = 覆盖 timeline.gaps 的过场镜头,非台词镜头
    # INC-001 §B 动作弧拍点(见 ShotListItem.action_beats);L6 kf2v 首帧抓 trigger、
    # (3point)关键帧抓 peak、尾帧抓 aftermath。为空则退回现状(单帧微动/visual_prompt 切片)。
    action_beats: list[str] = Field(default_factory=list)
    # 走位(见 ShotListItem.blocking):每条已格式化为"角色:画面位置,朝向"的短句。此前 shot_list
    # 精心生成的走位在桥接层被整个丢弃,多角色关键帧只说"合成到同一画面"、不说谁站哪面朝谁,
    # 渲染器只能瞎摆——这是"走位乱七八糟"的直接根因。透传到 L6 关键帧指令里定位每个人。
    blocking: list[str] = Field(default_factory=list)
    # INC-002 时序提示词:performance_track 已在桥接层编译成的逐段时间窗自然语言(见
    # director/performance_track.py::compile_temporal_prompt),拼在基础提示词之后喂 L6 时序渲染。
    # 空 = 未填 performance_track(inert,行为不变)。
    temporal_prompt: str = ""
    # INC-002 §1.1 phase→beat 映射:表演时间轴按 first/peak/aftermath 三时刻切片,注入渲染对应
    # 关键帧(首/关键/尾帧)。{} = 未填(inert)。见 performance_track.py::beat_slices。
    temporal_by_role: dict[str, str] = Field(default_factory=dict)
    # INC-002 v0.2:从 schema 自动派生的负面约束(注入 sdxl 关键帧 negative_prompt),空 = inert。
    negative_prompt: str = ""
    # INC-002 v0.2:编译好的声音提示词(第四层)。当前 funded 栈无 foley 引擎消费,先随 Shot 备着,
    # 有音频能力的 provider(如 Veo3)接入即用。空 = inert。
    audio_prompt: str = ""


class ShotList(BaseModel):
    shots: list[Shot] = Field(default_factory=list)


# ── L5 角色卡(character_bible.json)—— HEVI-SPEC-01 §5.2 ─────────────────
# voice_id 待 L3 多声线(P1)接入后再填。


class CharacterBibleEntry(BaseModel):
    character_id: str
    name: str
    appearance: str = ""
    era_check: str = ""
    ref_image: str | None = None  # 步骤3-4 锁定的候选立绘路径
    # Subject3D 多机位渲染帧(HEVI-ARCHITECTURE.md v3.0 §5.7.0 机位驱动渲染,2026-07-13
    # 探路落地),{"front"/"left"/"right"/"back": path}。目前只是数据透传——消费侧
    # (build_frame_manifest_avatar)还没有"这一镜是什么机位"的信息(ShotCamera 只有
    # shot_size/movement,没有方位角),按机位选用对应视图是后续工作,不在这次范围。
    ref_image_views: dict[str, str] | None = None
    gen_lock: dict | None = None  # {"seed":..., "ip_adapter_weight":...}
    voice_id: str | None = None  # 待 L3 TTS 接入后填入


class CharacterBible(BaseModel):
    characters: list[CharacterBibleEntry] = Field(default_factory=list)


# ── L6 场景与画面生成(帧资产)—— HEVI-SPEC-01 §7 ─────────────────────────


class SceneAsset(BaseModel):
    """场景底图(不含角色):同 scene_id 的多个 shot 共用一张,省成本+保证背景一致。"""

    scene_id: str
    image_path: str = ""
    prompt: str = ""
    seed: int = 0


class ShotFrame(BaseModel):
    shot_id: str
    scene_id: str
    frame_path: str = ""
    # avatar 渲染模式(cloud_avatar)下,这一镜是一段**自带配音+口型+动作**的 talking 视频
    # (happyhorse 数字人),clip_path 指向该 mp4;L8 装配时识别到 clip_path 就直接拼这段
    # (不再走"静帧 Ken Burns + 另配旁白"那条)。frame_path 仍存该 clip 的首帧供门禁打分。
    clip_path: str = ""
    characters: list[str] = Field(default_factory=list)
    clip_score: float = 0.0  # 生成帧 vs visual_prompt 的 CLIP 文本-图像相似度
    character_consistency: float | None = (
        None  # 帧 vs 角色 ref_image 的 CLIP 相似度(P1 简化:非人脸专用向量)
    )
    passed_vlm_audit: bool | None = None  # 本地 VLM 年代穿帮审核
    degraded: bool = False  # True = 走了降级链(丢角色/复用相邻场景),非首选路径产出
    degrade_reason: str = ""
    # INC-001 §K 可观察性:这一镜关键帧编译的 decision_trail(实际用的风格/情绪/动作弧阶段/
    # 视线/轴线),排查"为什么生成成这样";前端关键帧预览可直接展示,保证所见=实际所用。
    debug_context: dict[str, Any] = Field(default_factory=dict)
    quality_checks: dict[str, Any] = Field(default_factory=dict)


class FrameManifest(BaseModel):
    scenes: list[SceneAsset] = Field(default_factory=list)
    frames: list[ShotFrame] = Field(default_factory=list)


# ── L7 音乐与音效(music_plan.json)—— HEVI-SPEC-01 §8 ───────────────────


class MusicCue(BaseModel):
    """一幕的 BGM 选曲 + 该幕在 timeline 上的时间范围(供装配时定位交叉淡入淡出点)。"""

    act: int
    mood: str = ""
    bgm_path: str = ""
    t_start_ms: int = 0
    t_end_ms: int = 0


class SfxCue(BaseModel):
    shot_id: str
    sfx_name: str
    sfx_path: str = ""
    t_start_ms: int = 0


class MusicPlan(BaseModel):
    cues: list[MusicCue] = Field(default_factory=list)
    sfx: list[SfxCue] = Field(default_factory=list)


# ── L8 字幕与剪辑合成(final.mp4)—— HEVI-SPEC-01 §9 ─────────────────────


class FinalVideo(BaseModel):
    video_path: str = ""
    cover_path: str = ""
    srt_path: str = ""
    duration_ms: int = 0
