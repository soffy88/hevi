"""SPEC-007 新缺口③的修复:装配层改造——原声为对白权威源,TTS 降级为逐段 fallback。

**背景(2026-07-20 G-FINAL 真机撞见)**:happyhorse-1.1-r2v 这类 reference-to-video
provider 会把 prompt 里写明的台词渲染成带口型的真人语音,直接烧进生成视频的音轨里
(`multirole_reference.py::_action_text` 把 `dialogue[].text` 拼进了 prompt)。此前的
装配脚本假设"视频无声、音轨全靠单独 TTS 配"这个前提是错的——同一句台词被念了两遍
(原声 + 独立 edge-tts),`build_ambient_bed` 又把带着原声台词的整条 AAC 当"环境音"喂了
进去,三方叠在一起变成成片里的回声/双人声。

**这次的修法**:原声是权威源,只有原声缺失/念错/音色跟角色对不上时才退化到 TTS(退化
要显式标记,不能默默换轨)。三步都是纯函数或显式依赖注入(镜像 `segment_qc.py`/
`multirole_reference.py` 的 `tts_fn`/`gen_fn` 约定,不用 `unittest.mock.patch`):

1. `probe_native_dialogue`——ASR 转写原始 clip,拿到"人物真的开口的时间窗口"+ 转写文本。
2. `decide_dialogue_source`——拼音级发音错误率(过滤 ASR 同音字混淆,只看真发音是否对)+
   跟角色已确认原声的音色相似度(`CharacterVoiceRegistry`),两条都过 → `native`,
   任一条不过或原声压根没测到开口 → `fallback`(调用方据此另外真实合成 TTS,不复用
   `segment_qc.py` 探测阶段缓存的 `_qc_tts_*.mp3`——探测件和成片件混用正是双轨并存的
   直接通道,职能必须分开)。
3. `extract_native_dialogue_audio`/`strip_dialogue_from_track`——原声段落从整条音轨里
   切出来当对白;整条音轨反过来把开口窗口静音掉,剩下的才是真正干净的环境床,喂给
   `dialogue_track.py::build_ambient_bed`(那个函数本身是通用的 acrossfade 混轨器,没
   有错;错的是调用方过去直接拿整条带台词的 AAC 喂给它)。

**第③步不能替代最后一道闸**:上面三步是"装配过程按规则应该对",但装配脚本本身可能有
bug(这次会话就撞见过两次:`register_all_providers()` 漏调、`dialogue.text` 混进舞台
指示)——过程正确不等于结果正确。`verify_no_duplicate_dialogue_renders` 直接 ASR **成片
最终混出来的那条音轨**,独立核实"每句台词的文本在成片里只被清楚地念出来一次",不管走的
是 native 还是 fallback、不管装配脚本内部算得对不对,这道闸都在——它抓的是"两次可分辨的
独立渲染"(比如装配逻辑 bug 把同一句台词的 native cue 和 fallback cue 都塞进了
dialogue_track,各自有自己的起止时间),不依赖两次渲染离多近。

**已知边界(2026-07-20 真机验证过,不是臆测)**:这道闸对 v1 那次真实回声 bug(原声 +
独立 TTS 几乎同时叠在一起播)**实测没有报警**——两条音轨挨得太近,单说话人 ASR 没能
把它们拆成两个干净的 cue,而是转写成一整段里的口吃式重复("……可明日就要别了，就要
别了别……"),不落在任何一个 cue 的边界上,现在的逐 cue 比对抓不到这种"融进同一段转写
里的内部重复"。这道闸能可靠抓"两次界限分明的独立渲染"(重复片段/装配逻辑重复入队这类),
抓不住"两个音源真实叠在一起、糊成一段"这种声学层面的重叠——那需要能量/指纹级别的检测
(比如验证 `strip_dialogue_from_track` 产出的环境床在已知对白窗口内是否真的接近静音),
这次没有做,是明确的已知缺口,不是隐瞒的假设。这次会话的 v1 bug 已经被②的原声优先架构
从根上堵死(每段只会选一个音源,不会出现两个音源真实同时播放),这道闸是防"以后又出现
新的重复渲染成因"的第二道防线,不是重新验证 v1 那个已经结构性修复的旧 bug。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obase.ffmpeg import run as ffmpeg_run

from hevi.subjects.subject_embed import cosine_similarity

_DEFAULT_PER_THRESHOLD = 0.15  # 拼音级发音错误率超过这个就判"念错了",不能拿原声当权威源
_DEFAULT_VOICE_SIM_THRESHOLD = 0.75  # 跟该角色已确认原声的音色相似度低于这个就判"不像同一个人"
_WINDOW_PAD_S = 0.15  # 抽取/静音窗口各自留的余量,ASR 的开口边界不是采样级精确


_STAGE_DIRECTION_RE = re.compile(r"[（(][^）)]*[）)]")


def _strip_stage_directions(s: str) -> str:
    """`dialogue[].text` 按项目既定约定只留纯台词,舞台指示应该已经转进
    `narrative_text`——但 2026-07-20 真机撞见过一次没守住这个约定(手动机械拆句时把
    "（酒气混着水腥味，字字缓而沉）"这类指示留在了台词字段里)。舞台指示不会被念出来,
    ASR 转写也不会包含,留在 ref 里只会把发音错误率算爆(角括号本身会被 `_norm_zh` 滤掉,
    但括号**里的中文**不会,必须整段先摘掉)。"""
    return _STAGE_DIRECTION_RE.sub("", s)


def _norm_zh(s: str) -> str:
    return re.sub(r"[^一-鿿]", "", s)


def _edit_distance(ref: list[Any], hyp: list[Any]) -> int:
    n, m = len(ref), len(hyp)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            cur = dp[j]
            dp[j] = prev if ref[i - 1] == hyp[j - 1] else 1 + min(prev, dp[j], dp[j - 1])
            prev = cur
    return dp[m]


def pinyin_error_rate(ref_text: str, hyp_text: str) -> float:
    """拼音级(不分声调)发音错误率——同音字先转成同一个拼音再比,过滤掉纯 ASR 同音字
    混淆(比如"许兄"听成"徐兄"这种,拼音一样,不算真发音错误),只留"拼音本身就不一样"
    的真实发音级错误(念错字/吞字/加字)。`ref_text` 为空 → 0.0(没什么好比的)。"""
    from pypinyin import lazy_pinyin

    ref, hyp = _norm_zh(_strip_stage_directions(ref_text)), _norm_zh(hyp_text)
    if not ref:
        return 0.0
    ref_py, hyp_py = lazy_pinyin(ref), lazy_pinyin(hyp)
    return _edit_distance(ref_py, hyp_py) / len(ref_py)


async def probe_native_dialogue(
    clip: Path,
    *,
    tmp_wav: Path,
    transcribe_fn: Any = None,
) -> tuple[list[tuple[float, float]], str]:
    """ASR 转写 `clip` 的原始音轨,回报(人物真实开口的时间窗口列表 [单位:秒,clip 内部
    时间轴], 拼起来的转写文本)。转写不到任何内容(静音/纯环境音/ASR 失败)→ 空窗口 +
    空文本,调用方据此判 fallback,这里不做判断。

    `transcribe_fn` 默认 `hevi.assembly.subtitle_align.transcribe_to_cues`(同步
    faster-whisper 调用,在线程池跑,不阻塞事件循环)——显式参数注入,供测试替身。
    """
    import asyncio

    if transcribe_fn is None:
        from hevi.assembly.subtitle_align import transcribe_to_cues

        transcribe_fn = transcribe_to_cues

    await ffmpeg_run(
        args=[
            "-i",
            str(clip),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(tmp_wav),
        ],
        expected_output=tmp_wav,
    )
    cues = await asyncio.to_thread(transcribe_fn, tmp_wav, language="zh")
    windows = [(c.start, c.end) for c in cues]
    text = "".join(c.text for c in cues)
    return windows, text


@dataclass(frozen=True)
class DialogueSourceDecision:
    segment_id: str
    source: str  # "native" / "fallback" / "none"(本来就没有台词)
    reason: str
    native_windows_s: tuple[tuple[float, float], ...] = ()
    per: float | None = None
    voice_sim: float | None = None


def decide_dialogue_source(
    *,
    segment_id: str,
    expected_text: str,
    hyp_text: str,
    native_windows_s: list[tuple[float, float]],
    voice_sim: float | None,
    per_threshold: float = _DEFAULT_PER_THRESHOLD,
    voice_sim_threshold: float = _DEFAULT_VOICE_SIM_THRESHOLD,
) -> DialogueSourceDecision:
    """纯函数,零成本——拼音级发音错误率 + 音色相似度两道闸门,任一没过就退 `fallback`。

    `voice_sim=None`(该角色还没攒出参考音色,比如这是它第一次开口)→ 跳过音色这道闸门,
    不能拿"没有参考"当"不通过"——那是另一个错误的默认,会把每个角色的第一段都错杀成
    fallback。
    """
    if not expected_text.strip():
        return DialogueSourceDecision(segment_id=segment_id, source="none", reason="本段没有台词")
    if not native_windows_s or not hyp_text.strip():
        return DialogueSourceDecision(
            segment_id=segment_id, source="fallback", reason="原声轨里没测到人物开口"
        )

    per = pinyin_error_rate(expected_text, hyp_text)
    if per > per_threshold:
        return DialogueSourceDecision(
            segment_id=segment_id,
            source="fallback",
            reason=f"拼音级发音错误率 {per:.1%} 超过阈值 {per_threshold:.0%},疑似念错/吞字",
            native_windows_s=tuple(native_windows_s),
            per=per,
        )
    if voice_sim is not None and voice_sim < voice_sim_threshold:
        return DialogueSourceDecision(
            segment_id=segment_id,
            source="fallback",
            reason=(
                f"音色相似度 {voice_sim:.3f} 低于阈值 {voice_sim_threshold},"
                "疑似跟该角色已确认的原声不是同一个人"
            ),
            native_windows_s=tuple(native_windows_s),
            per=per,
            voice_sim=voice_sim,
        )
    return DialogueSourceDecision(
        segment_id=segment_id,
        source="native",
        reason="",
        native_windows_s=tuple(native_windows_s),
        per=per,
        voice_sim=voice_sim,
    )


@dataclass
class CharacterVoiceRegistry:
    """每个角色的"参考音色"没有独立录的干净样本,只能从已经判定为 native 的段里现攒——
    第一段天然没有参考(`similarity` 返回 None,`decide_dialogue_source` 据此跳过音色
    闸门),之后每多一个 native 段就多一份参考,取跟已有参考的平均相似度。"""

    _refs: dict[str, list[list[float]]] = field(default_factory=dict)

    def similarity(self, character: str, embedding: list[float]) -> float | None:
        refs = self._refs.get(character)
        if not refs:
            return None
        sims = [cosine_similarity(embedding, r) for r in refs]
        return sum(sims) / len(sims)

    def register(self, character: str, embedding: list[float]) -> None:
        self._refs.setdefault(character, []).append(embedding)


def _span(windows_s: list[tuple[float, float]]) -> tuple[float, float]:
    starts = [s for s, _ in windows_s]
    ends = [e for _, e in windows_s]
    return max(0.0, min(starts) - _WINDOW_PAD_S), max(ends) + _WINDOW_PAD_S


async def extract_native_dialogue_audio(
    clip: Path, windows_s: list[tuple[float, float]], *, output_path: Path
) -> Path:
    """把原声开口窗口的**连续跨度**(第一个窗口起点到最后一个窗口终点,含 padding)从
    `clip` 音轨里切出来——不是掐头去尾拼接各个子窗口,窗口之间的停顿是台词本身的自然
    节奏,应该保留。"""
    start, end = _span(windows_s)
    await ffmpeg_run(
        args=[
            "-i",
            str(clip),
            "-vn",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        expected_output=output_path,
    )
    return output_path


async def strip_dialogue_from_track(
    clip: Path, windows_s: list[tuple[float, float]], *, output_path: Path, floor_db: float = -60.0
) -> Path:
    """反过来:把原声开口窗口(含 padding)从整条音轨里静音掉,剩下的才是真正的环境床——
    喂给 `dialogue_track.py::build_ambient_bed`,不是原始整条 AAC(那条里混着台词,
    `build_ambient_bed` 这个名字本身就是"环境音"的承诺,喂带台词的整条轨是调用方的锅,
    不是它的实现问题)。没有开口窗口(这段本来就没台词)→ 原样拷贝,不需要处理。"""
    if not windows_s:
        await ffmpeg_run(
            args=["-i", str(clip), "-vn", "-acodec", "pcm_s16le", str(output_path)],
            expected_output=output_path,
        )
        return output_path

    filters = []
    for s, e in windows_s:
        lo, hi = max(0.0, s - _WINDOW_PAD_S), e + _WINDOW_PAD_S
        filters.append(f"volume=enable='between(t,{lo:.3f},{hi:.3f})':volume={floor_db}dB")
    await ffmpeg_run(
        args=[
            "-i",
            str(clip),
            "-vn",
            "-filter:a",
            ",".join(filters),
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        expected_output=output_path,
    )
    return output_path


_DEFAULT_DUPLICATE_MATCH_THRESHOLD = 0.3  # 比 native/fallback 判定的 0.15 松——这里只是
# 粗筛"这段转写像不像是在念这句台词",不是判断念得准不准,阈值收紧只会让真正的重复漏检。
_DEFAULT_DUPLICATE_MERGE_GAP_S = 2.0  # ASR 把同一次连续开口切成几段 cue 是常态(中间有
# 停顿),间隔小于这个就并成一段"一次开口"处理,不能把它错判成两次独立渲染。


@dataclass(frozen=True)
class DuplicateDialogueRender:
    speaker: str | None
    text: str
    windows_s: tuple[tuple[float, float], ...]  # 2 个以上互相隔开的命中窗口,即重复渲染


class DuplicateDialogueError(Exception):
    """成片音轨里同一句台词被渲染了不止一次。"""


def _merge_asr_cues(cues: list[Any], *, merge_gap_s: float) -> list[tuple[float, float, str]]:
    """把间隔小于 `merge_gap_s` 的相邻 ASR cue 并成一段"一次连续开口"(start, end, 拼接
    文本)——同一句台词中间的自然停顿不该被当成两次独立渲染。"""
    if not cues:
        return []
    ordered = sorted(cues, key=lambda c: c.start)
    spans = [[ordered[0].start, ordered[0].end, ordered[0].text]]
    for c in ordered[1:]:
        if c.start - spans[-1][1] <= merge_gap_s:
            spans[-1][1] = max(spans[-1][1], c.end)
            spans[-1][2] += c.text
        else:
            spans.append([c.start, c.end, c.text])
    return [(s, e, t) for s, e, t in spans]


def _find_line_occurrences(
    cues: list[Any], text: str, *, match_threshold: float, merge_gap_s: float
) -> list[tuple[float, float]]:
    """一句台词在这堆 ASR cue 里出现了几次(各自命中的时间窗口)。

    **不能直接先按 `merge_gap_s` 全局合并再逐句比对**——2026-07-20 真机验证过这个天真
    做法的真实反例:G-FINAL v1 那个双轨回声 bug(原声 + 独立 TTS)两条音轨的开口时点只
    差 0.9-1.0s,小于任何合理的"同一次开口自然停顿"合并间隔,会被直接合并成一段,
    duplicate 检测反而测不出真实撞见过的这个 bug——等于闸门形同虚设。

    正确顺序:先看每个 cue **单独自己**够不够格算一次完整渲染(是就直接算一次,不管跟
    别的 cue 离多近——两次独立渲染凑巧挨在一起也该被抓出来);只有单独不够格的碎片
    (可能只是同一次开口被 ASR 切碎的一段,比如台词中间的停顿导致的拆分)才允许彼此
    合并后再判一次。"""
    ordered = sorted(cues, key=lambda c: c.start)
    standalone = [c for c in ordered if pinyin_error_rate(text, c.text) < match_threshold]
    standalone_ids = {id(c) for c in standalone}
    leftover = [c for c in ordered if id(c) not in standalone_ids]

    hits = [(c.start, c.end) for c in standalone]
    for s, e, span_text in _merge_asr_cues(leftover, merge_gap_s=merge_gap_s):
        if pinyin_error_rate(text, span_text) < match_threshold:
            hits.append((s, e))
    return sorted(hits)


async def verify_no_duplicate_dialogue_renders(
    final_audio_or_video: Path,
    *,
    expected_lines: list[tuple[str | None, str]],
    tmp_wav: Path,
    transcribe_fn: Any = None,
    match_threshold: float = _DEFAULT_DUPLICATE_MATCH_THRESHOLD,
    merge_gap_s: float = _DEFAULT_DUPLICATE_MERGE_GAP_S,
) -> list[DuplicateDialogueRender]:
    """ASR 转写成片(或其音轨)全长,独立核实 `expected_lines`(装配前就知道的、这部片子
    "应该"出现的每句台词)里每一句在最终混出来的音轨里只被念了一次。纯粹的结果核验——
    不看装配脚本内部走了 native 还是 fallback、算没算对,只看最终产物里实际听得到什么。

    `expected_lines` 里有重复台词文本(比如同一句台词在剧情里被两个不同时刻的人分别真的
    说了两次,不是渲染 bug)——这种情况下这个函数没法区分"剧情本来就要说两次"和"渲染
    重复了",调用方如果知道剧本里有这种合法重复,应该只传一次这句台词去核验对应的那次
    渲染,不要把两次都塞进 `expected_lines`(那样会把两次合法渲染也判成 violation)。
    """
    import asyncio

    if transcribe_fn is None:
        from hevi.assembly.subtitle_align import transcribe_to_cues

        transcribe_fn = transcribe_to_cues

    await ffmpeg_run(
        args=[
            "-i",
            str(final_audio_or_video),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(tmp_wav),
        ],
        expected_output=tmp_wav,
    )
    cues = await asyncio.to_thread(transcribe_fn, tmp_wav, language="zh")

    violations: list[DuplicateDialogueRender] = []
    for speaker, text in expected_lines:
        hits = _find_line_occurrences(
            cues, text, match_threshold=match_threshold, merge_gap_s=merge_gap_s
        )
        if len(hits) >= 2:
            violations.append(
                DuplicateDialogueRender(speaker=speaker, text=text, windows_s=tuple(hits))
            )
    return violations


async def assert_no_duplicate_dialogue_renders(
    final_audio_or_video: Path,
    *,
    expected_lines: list[tuple[str | None, str]],
    tmp_wav: Path,
    transcribe_fn: Any = None,
    match_threshold: float = _DEFAULT_DUPLICATE_MATCH_THRESHOLD,
    merge_gap_s: float = _DEFAULT_DUPLICATE_MERGE_GAP_S,
) -> None:
    """硬闸门版——有 violation 就抛 `DuplicateDialogueError`,不放过。装配流水线在出片
    之后、宣布完成之前调这个,不是调 `verify_no_duplicate_dialogue_renders` 自己看着办。"""
    violations = await verify_no_duplicate_dialogue_renders(
        final_audio_or_video,
        expected_lines=expected_lines,
        tmp_wav=tmp_wav,
        transcribe_fn=transcribe_fn,
        match_threshold=match_threshold,
        merge_gap_s=merge_gap_s,
    )
    if violations:
        detail = "; ".join(
            f"{v.speaker or '?'}「{v.text}」在 {v.windows_s} 被念了 {len(v.windows_s)} 次"
            for v in violations
        )
        raise DuplicateDialogueError(f"成片音轨里检测到台词重复渲染: {detail}")
