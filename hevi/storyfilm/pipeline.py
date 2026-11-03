"""story-to-film orchestration: 一句话 → 故事 → 分镜 → 素材 → 配音 → 对齐 → 合成 → 成片。

Stage evidence ledger (lanshu-explainer check_state pattern: state is computed
from artifacts on disk, never just declared). Every stage writes its artifacts
into the job dir and keeps ``job.json`` / ``delivery.json`` current:

  story.json / story.md     故事稿 (title / hook / characters / beats)
  characters.json           人物档案 (图像一致性的锚)
  images/                   定妆图 + 每镜场景图 (image.gpt_generate / gpt_edit)
  narration.wav             旁白母带 (LuxTTS)
  alignment.json            实测词级时间戳 (按 HEVI_TTS_ALIGNMENT_PROVIDER
                            选档: 默认 whisper_local 本地 ASR 免费档;
                            elevenlabs_forced 为付费精度档)
  shots.json                分镜表 — 每镜同时带 first_frame / motion_prompt /
                            duration, 即 PixStag 镜头包的交接字段; 另带结构化
                            分镜字段 (景别/机位/运镜/场次/出场角色/时长估计)
  storyboard.md             结构化分镜表 (人读版: 场次表 + 逐镜计划vs实测)
  assets.json               series 模式下本集用到的资产注册表快照 (角色/场景)
  film.mp4                  render_route="ken_burns" 的代码合成成片
                            ("hyperframes" 是该路由的历史别名, 见下)
  pixstag_package.json      render_route="pixstag_package" 的镜头包,
                            交 video.pixstag_generate 逐镜生成后拼接
  gates.json                film_gate / audio.earshot_gate 结论 (可用时)
  delivery.json             阶段台账: 状态 / 花费 / 产物

  Route semantics (explicit, locked by tests/test_storyfilm_routing.py):
  the in-house film route renders with Ken Burns motion over the shot
  stills (``render_motion_film`` in this module). It does NOT call the
  creator-style-kit styled renderer (``video.hyperframes_styled_render``,
  ``hevi/video/csk_styled_render.py``): that capability is a separate,
  beats-driven 9:16 style render and is not on this pipeline's path.
  The name "hyperframes" survives only as a legacy alias for
  "ken_burns" (``resolve_render_route``); delivery.json records both the
  requested and the resolved route plus the render entry, so the
  routing is inspectable instead of an orphan capability "in the
  catalogue but unused" left ambiguous.

Story-planning note (known, deliberate tradeoff — audited 2026-10-20):
  * The story stage is this module's OWN LLM draft (_STORY_SYSTEM /
    _STORY_USER calls in generate_story); it does NOT reuse the
    storyplan / storygraph planning lines.  Reason: each beat here must
    co-produce ``visual_en`` and ``motion_prompt`` alongside the
    narration — ``visual_en`` feeds GPT-Image scene generation and both
    fields are carried into the PixStag shot package (first_frame /
    motion_prompt / duration handoff); the StoryPlan model does not
    carry those two fields, so routing through it would need a second
    enrichment pass per beat anyway.
  * The planning quality gates (story_check / kids.story_gate) are NOT
    wired into this line at present.  That is a known gap accepted for
    this line, not an oversight: drafts are validated structurally
    (parse_story_draft) and for narration length, but they do not pass
    a story-quality or kids-content gate before images/TTS are spent.

Final-render routes (Soffy 分工定调 2026-10-20; semantics locked
2026-10-31, see RENDER_ROUTES / resolve_render_route below):
  * 代码动画类 → Ken Burns 路由 (历史名 "hyperframes", 别名)
  * 真人故事片 → hevi 出整个流程, 最终成片交外接能力 PixStag; 本模块只产
    镜头包 (每镜 first_frame + motion_prompt + duration), 不等它落地。

Failure policy: a failed stage raises StoryFilmError after recording the
failure in the ledger — the pipeline never fabricates a stage result.
"""

from __future__ import annotations

import contextlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hevi.storyfilm import assets as _asset_registry
from hevi.storyfilm import storyboard as _storyboard

__all__ = [
    "DEFAULT_STYLE",
    # audio mastering
    "TARGET_TRUE_PEAK_DBTP",
    "StoryFilmError",
    "apply_gain_control",
    "build_frame_html",
    "build_pixstag_package",
    "check_measured_duration",
    "choose_mastering",
    "compute_gain_db",
    "estimate_narration_seconds",
    "generate_continuation_beats",
    "generate_story",
    "infer_beat_emotion",
    # motion (Ken Burns)
    "ken_burns_params",
    "map_beats_to_words",
    "motion_for_shot",
    # duration / length enforcement
    "narration_char_count",
    "parse_continuation_beats",
    "parse_story_draft",
    "render_motion_film",
    "run_story_film",
    "trim_draft_to_max_chars",
    # explicit render routing (hyperframes alias -> ken_burns)
    "RENDER_ROUTES",
    "ROUTE_ALIASES",
    "film_render_entry_for",
    "resolve_render_route",
]

DEFAULT_STYLE = (
    "warm storybook watercolor illustration, soft cinematic light, "
    "gentle colors, high detail"
)

_LLM_PROVIDER = "blockrun.ai"
_LLM_ENDPOINT = "/api/v1/chat/completions"
_LLM_MODEL = "gpt-4o-mini"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FILM_GATE = (
    _REPO_ROOT
    / "hevi/layer4_legacy/artmotion/omodul_impl/scripts/film_gate.py"
)

_ASPECT_SIZE = {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}
_ASPECT_RES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (960, 960)}

# Explicit render routing. "hyperframes" is a legacy alias for the
# Ken Burns route only: this pipeline never called the CSK styled
# renderer, and the alias must not be read as "the HyperFrames engine
# renders this film". The CSK renderer stays a separate capability
# (video.hyperframes_styled_render); it is not imported here.
RENDER_ROUTES: dict[str, dict[str, str]] = {
    "ken_burns": {
        "entry": "hevi.storyfilm.pipeline.render_motion_film",
        "produces": "film.mp4",
        "description": "Ken Burns motion over shot stills + narration, in-house.",
    },
    "pixstag_package": {
        "entry": "hevi.storyfilm.pipeline.build_pixstag_package",
        "produces": "pixstag_package.json",
        "description": "Shot package for video.pixstag_generate; no film here.",
    },
}
ROUTE_ALIASES: dict[str, str] = {"hyperframes": "ken_burns"}


def resolve_render_route(route: str) -> str:
    """Resolve a requested route (alias allowed) to its canonical name."""
    requested = str(route or "").strip()
    resolved = ROUTE_ALIASES.get(requested, requested)
    if resolved not in RENDER_ROUTES:
        raise StoryFilmError(
            f"unknown render_route: {route!r}; known: "
            f"{sorted(set(RENDER_ROUTES) | set(ROUTE_ALIASES))}"
        )
    return resolved


def film_render_entry_for(route: str) -> dict[str, str]:
    """Render entry + product for a route (aliases resolved)."""
    resolved = resolve_render_route(route)
    entry = dict(RENDER_ROUTES[resolved])
    entry["canonical_route"] = resolved
    entry["requested_route"] = str(route or "").strip()
    return entry

_PUNCT = set(
    " \t\r\n，。、；：？！·…—–-「」『』（）【】《》〈〉“”‘’\"'.,;:!?()[]<>"
)

# ---------------------------------------------------------------------------
# Duration targets — derived from the pilot_cat baseline (2026-10-20 fix).
#
# Pilot baseline: 138 narration chars (len incl. punctuation, the same
# counting parse_story_draft uses) -> 21.849 s of measured LuxTTS audio,
# i.e. ~6.32 chars/s for the soffy voice.  The film target is 30-60 s.
# Shots add tails (0.35 s/shot + 1.2 s last ~= +2.6 s for 5 shots) on top
# of the narration, so a narration of ~36-49 s lands the film safely in
# the middle of the window even if the voice runs ~15% fast or slow:
#   225 chars / 6.32 ~= 35.6 s narration  (~38 s film)
#   310 chars / 6.32 ~= 49.1 s narration  (~52 s film)
# These are enforced in generate_story (continuation rounds below), NOT
# just requested in the prompt — the pilot prompt already *asked* for
# 150-240 chars and the LLM returned 138 with nothing checking it.
# ---------------------------------------------------------------------------
PILOT_NARRATION_CHARS = 138
PILOT_NARRATION_SECONDS = 21.849
SPEECH_CHARS_PER_SEC = PILOT_NARRATION_CHARS / PILOT_NARRATION_SECONDS  # ~6.32
NARRATION_MIN_CHARS = 225
NARRATION_MAX_CHARS = 310
TARGET_FILM_MIN_S = 30.0
TARGET_FILM_MAX_S = 60.0
MAX_CONTINUATION_ROUNDS = 3
# Continuation may add beats beyond the initial max_shots (image-budget
# guard in the capability layer caps the *initial* draft); the hard cap
# keeps a runaway continuation from blowing the image budget entirely.
HARD_MAX_BEATS = 8

# Audio mastering targets: the earshot gate ceiling is -1.0 dBTP; master
# to -1.5 dBTP for a 0.5 dB safety margin.  LUFS tolerance is -14 +/- 2.
TARGET_TRUE_PEAK_DBTP = -1.5
LUFS_TARGET = -14.0
LUFS_TOLERANCE = 2.0


class StoryFilmError(RuntimeError):
    """A story-to-film stage failed; the ledger records where and why."""


# ---------------------------------------------------------------------------
# Story draft (scaled-down chinese-novelist planning: outline + characters +
# hook, sized for a 30-60s short — the skill itself is not installed).
# ---------------------------------------------------------------------------

_STORY_SYSTEM = (
    "你是儿童短片编剧。把一句话前提扩写成 30-60 秒短片的微型故事方案。"
    "规划纪律借鉴长篇小说创作法并缩放：先定人物档案，再排章节大纲，"
    "开头即钩子，每一拍有推进，结尾有回落。只输出 JSON，不要 markdown 包裹。"
)

_STORY_USER = """前提：{premise}
风格：{style}
输出 JSON，字段：
{{
  "title": "片名（中文，8字内）",
  "hook": "钩子（一句话，开场就要抓住人）",
  "characters": [
    {{"name": "名字", "role": "主角", "appearance_en": "英文外貌描述（毛色/体型/标志物），供图像生成"}}
  ],
  "beats": [
    {{"narration": "旁白（中文口语，40-65字，可含两句，以句号结尾）",
      "visual_en": "英文画面描述（这一镜的场景与构图）",
      "motion_prompt": "英文运镜提示（如 slow push-in / gentle pan left / static close-up）",
      "scene": "场景名（中文简短，如 池塘边；同一地点的连续拍必须用同一个名字）",
      "shot_size": "景别：extreme_wide/wide/full/medium/medium_close_up/close_up/extreme_close_up 之一",
      "camera_angle": "机位：eye_level/low_angle/high_angle/overhead 之一",
      "characters": ["本拍出场角色名（须与 characters 中的名字字字一致；没有角色出场就给空数组）"]}}
  ]
}}
约束：beats 恰好 {max_shots} 个；总旁白必须在 {min_chars}-{max_chars} 字之间（逐字数好再输出，太短就把每拍写长）；人物不超过 3 个，主角排第一；每拍都要给出 scene / shot_size / camera_angle / characters 四个分镜字段。"""

_CONTINUATION_USER = """前提：{premise}
片名：{title}
已有节拍的旁白（按顺序）：
{existing}
现在全片旁白共 {total} 字，还差至少 {need} 字才能达到 {min_chars} 字的最低要求。
请紧接着已有情节续写 {n_beats} 个新节拍：推进情节、不要重复已有内容、最后一个新节拍要能自然接向结局（若已有节拍已是结局，就续写结局之前的经过）。
只输出 JSON，不要 markdown 包裹，字段：
{{"beats": [{{"narration": "旁白（中文口语，40-65字，以句号结尾）", "visual_en": "英文画面描述", "motion_prompt": "英文运镜提示", "scene": "场景名（与已有节拍同一地点就用同一个名字）", "characters": ["本拍出场角色名"]}}]}}"""


_SHOT_FIELD_KEYS = (
    "scene",
    "shot_size",
    "camera_angle",
    "camera_movement",
    "narrative_function",
    "transition",
)


def _passthrough_shot_fields(raw: dict[str, Any], beat: dict[str, Any]) -> None:
    """Keep the optional storyboard fields the LLM provided on a beat.

    Advisory only: storyboard.enrich_draft normalises/derives them
    later, so an unrecognised value never fails the draft here.
    """
    for key in _SHOT_FIELD_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            beat[key] = value.strip()
    raw_names = raw.get("characters")
    if isinstance(raw_names, list):
        names = [n.strip() for n in raw_names if isinstance(n, str) and n.strip()]
        if names:
            beat["characters"] = names


def parse_story_draft(text: str, *, max_shots: int) -> dict[str, Any]:
    """Parse + validate an LLM story draft. Raises StoryFilmError if unusable."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        draft = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise StoryFilmError(f"story draft is not valid JSON: {exc}") from exc
    if not isinstance(draft, dict):
        raise StoryFilmError("story draft must be a JSON object")

    title = str(draft.get("title") or "").strip()
    if not title:
        raise StoryFilmError("story draft missing title")
    draft["title"] = title
    draft["hook"] = str(draft.get("hook") or "").strip()

    characters = draft.get("characters")
    if not isinstance(characters, list) or not characters:
        raise StoryFilmError("story draft needs at least one character")
    for ch in characters:
        if not isinstance(ch, dict) or not str(ch.get("name") or "").strip():
            raise StoryFilmError("each character needs a name")
        if not str(ch.get("appearance_en") or "").strip():
            raise StoryFilmError(
                f"character {ch.get('name')!r} needs appearance_en for image gen"
            )
        raw_aliases = ch.get("aliases")
        if isinstance(raw_aliases, list):
            aliases = [
                a.strip() for a in raw_aliases if isinstance(a, str) and a.strip()
            ]
            if aliases:
                ch["aliases"] = aliases

    beats = draft.get("beats")
    if not isinstance(beats, list) or not beats:
        raise StoryFilmError("story draft needs at least one beat")
    if len(beats) > max_shots:
        raise StoryFilmError(
            f"story draft has {len(beats)} beats > max_shots={max_shots}"
        )
    total_chars = 0
    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            raise StoryFilmError(f"beat {i + 1} must be an object")
        narration = str(beat.get("narration") or "").strip()
        if not narration:
            raise StoryFilmError(f"beat {i + 1} missing narration")
        if narration[-1] not in "。！？":
            narration += "。"
        beat["narration"] = narration
        total_chars += len(narration)
        if not str(beat.get("visual_en") or "").strip():
            raise StoryFilmError(f"beat {i + 1} missing visual_en")
        if not str(beat.get("motion_prompt") or "").strip():
            beat["motion_prompt"] = "slow push-in"
        _passthrough_shot_fields(beat, beat)
    if total_chars < 60:
        raise StoryFilmError(
            f"narration too short for a film ({total_chars} chars < 60)"
        )
    return draft


def narration_char_count(draft_or_beats: Any) -> int:
    """Total narration chars (len incl. punctuation — pilot counting)."""
    beats = (
        draft_or_beats.get("beats", [])
        if isinstance(draft_or_beats, dict)
        else draft_or_beats
    )
    return sum(len(str(b.get("narration") or "")) for b in beats)


def estimate_narration_seconds(chars: int) -> float:
    """Estimated spoken seconds at the pilot-measured speech rate."""
    return chars / SPEECH_CHARS_PER_SEC


def _validate_beat(beat: Any, index: int) -> dict[str, Any]:
    if not isinstance(beat, dict):
        raise StoryFilmError(f"beat {index + 1} must be an object")
    narration = str(beat.get("narration") or "").strip()
    if not narration:
        raise StoryFilmError(f"beat {index + 1} missing narration")
    if narration[-1] not in "。！？":
        narration += "。"
    beat = dict(beat)
    beat["narration"] = narration
    if not str(beat.get("visual_en") or "").strip():
        raise StoryFilmError(f"beat {index + 1} missing visual_en")
    if not str(beat.get("motion_prompt") or "").strip():
        beat["motion_prompt"] = "slow push-in"
    _passthrough_shot_fields(beat, beat)
    return beat


def trim_draft_to_max_chars(
    draft: dict[str, Any], *, max_chars: int = NARRATION_MAX_CHARS
) -> dict[str, Any]:
    """Drop penultimate beats while over ``max_chars`` (keeps first+last).

    The opening (hook) and the closing beat carry the story arc, so the
    trimmable fat is in the middle; the penultimate beat is the least
    structural of those.  Never drops below 3 beats.
    """
    draft = dict(draft)
    beats = list(draft.get("beats") or [])
    while len(beats) > 3 and narration_char_count(beats) > max_chars:
        beats.pop(-2)
    draft["beats"] = beats
    return draft


def parse_continuation_beats(text: str) -> list[dict[str, Any]]:
    """Parse a continuation LLM reply (``{"beats": [...]}`` or a bare list)."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise StoryFilmError(f"continuation is not valid JSON: {exc}") from exc
    raw = payload.get("beats") if isinstance(payload, dict) else payload
    if not isinstance(raw, list) or not raw:
        raise StoryFilmError("continuation returned no beats")
    return [_validate_beat(b, i) for i, b in enumerate(raw)]


async def _chat_completion(
    messages: list[dict[str, str]], *, max_tokens: int = 1400
) -> tuple[str, float | None]:
    """One Monid blockrun chat call → (message content, cost)."""
    from hevi.audio import monid_client

    body = {
        "model": _LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    output, cost = await monid_client.run_endpoint(
        _LLM_PROVIDER, _LLM_ENDPOINT, body=body
    )
    try:
        content = output["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise StoryFilmError(
            f"LLM response has no message content: {str(output)[:200]}"
        ) from exc
    return str(content), cost


async def generate_continuation_beats(
    draft: dict[str, Any],
    *,
    premise: str,
    need_chars: int,
) -> tuple[list[dict[str, Any]], float | None]:
    """Ask the LLM for additional beats continuing ``draft`` (~55 chars each)."""
    n_beats = max(1, min(3, -(-need_chars // 55)))
    existing = "\n".join(
        f"{i + 1}. {b['narration']}" for i, b in enumerate(draft["beats"])
    )
    content, cost = await _chat_completion(
        [
            {"role": "system", "content": _STORY_SYSTEM},
            {
                "role": "user",
                "content": _CONTINUATION_USER.format(
                    premise=premise,
                    title=draft.get("title", ""),
                    existing=existing,
                    total=narration_char_count(draft),
                    need=need_chars,
                    min_chars=NARRATION_MIN_CHARS,
                    n_beats=n_beats,
                ),
            },
        ]
    )
    return parse_continuation_beats(content), cost


async def generate_story(
    premise: str, *, style: str, max_shots: int
) -> tuple[dict[str, Any], float | None]:
    """LLM story draft with narration-length enforcement.

    The initial draft is *checked* against NARRATION_MIN/MAX_CHARS:
    too long → trim middle beats; too short → continuation rounds
    (``generate_continuation_beats``, at most MAX_CONTINUATION_ROUNDS,
    beats capped at HARD_MAX_BEATS) until the minimum is met.  If the
    minimum still is not met after all rounds, the draft is returned
    with ``_length_warning`` set — recorded in the delivery ledger by
    the caller, never silently pretended to be on target.
    """
    content, cost = await _chat_completion(
        [
            {"role": "system", "content": _STORY_SYSTEM},
            {
                "role": "user",
                "content": _STORY_USER.format(
                    premise=premise,
                    style=style,
                    max_shots=max_shots,
                    min_chars=NARRATION_MIN_CHARS,
                    max_chars=NARRATION_MAX_CHARS,
                ),
            },
        ]
    )
    draft = parse_story_draft(str(content), max_shots=max_shots)
    total_cost = cost or 0.0

    if narration_char_count(draft) > NARRATION_MAX_CHARS:
        draft = trim_draft_to_max_chars(draft)

    rounds = 0
    while (
        narration_char_count(draft) < NARRATION_MIN_CHARS
        and rounds < MAX_CONTINUATION_ROUNDS
        and len(draft["beats"]) < HARD_MAX_BEATS
    ):
        rounds += 1
        need = NARRATION_MIN_CHARS - narration_char_count(draft)
        try:
            new_beats, c = await generate_continuation_beats(
                draft, premise=premise, need_chars=need
            )
        except StoryFilmError:
            break
        if c:
            total_cost += c
        room = HARD_MAX_BEATS - len(draft["beats"])
        # Insert before the final beat so the ending stays the ending.
        insert_at = max(1, len(draft["beats"]) - 1)
        for beat in new_beats[:room]:
            draft["beats"].insert(insert_at, beat)
            insert_at += 1
        if narration_char_count(draft) > NARRATION_MAX_CHARS:
            draft = trim_draft_to_max_chars(draft)

    draft["_continuation_rounds"] = rounds
    total = narration_char_count(draft)
    if total < NARRATION_MIN_CHARS:
        draft["_length_warning"] = (
            f"narration {total} chars < target minimum "
            f"{NARRATION_MIN_CHARS} after {rounds} continuation round(s); "
            f"estimated {estimate_narration_seconds(total):.1f}s spoken"
        )
    return draft, (round(total_cost, 4) if total_cost else cost)


def check_measured_duration(
    duration_ms: int | float,
    *,
    min_s: float = TARGET_FILM_MIN_S,
    max_s: float = TARGET_FILM_MAX_S,
) -> dict[str, Any]:
    """Post-TTS verification against the film-duration target.

    Returns an explicit verdict dict; a below-target result carries the
    reason so the delivery ledger can record it honestly.
    """
    seconds = float(duration_ms) / 1000.0
    ok = min_s <= seconds <= max_s
    return {
        "measured_narration_s": round(seconds, 2),
        "target_min_s": min_s,
        "target_max_s": max_s,
        "target_met": ok,
        "reason": (
            ""
            if ok
            else f"measured narration {seconds:.1f}s outside "
            f"{min_s:.0f}-{max_s:.0f}s target after story-stage "
            "continuation; film may miss the duration window"
        ),
    }


def story_markdown(premise: str, draft: dict[str, Any]) -> str:
    lines = [
        f"# {draft['title']}",
        "",
        f"前提：{premise}",
        f"钩子：{draft.get('hook', '')}",
        "",
        "## 人物",
    ]
    lines.extend(
        f"- {ch['name']}（{ch.get('role', '')}）：{ch.get('appearance_en', '')}"
        for ch in draft["characters"]
    )
    lines.append("")
    lines.append("## 分镜大纲")
    for i, beat in enumerate(draft["beats"], 1):
        lines.append(f"{i}. {beat['narration']}")
        lines.append(f"   画面：{beat['visual_en']}｜运镜：{beat['motion_prompt']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Alignment → shot timing
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def map_beats_to_words(
    beat_texts: list[str], words: list[Any]
) -> list[tuple[int, int]]:
    """Map each beat's narration onto the measured word stream by char count.

    ``words`` are WordTiming-like objects (text/start_ms/end_ms). Returns one
    (start_ms, end_ms) span per beat. Raises StoryFilmError when the word
    stream is exhausted early — timing must come from measurement, never
    from a silent fallback.
    """
    spans: list[tuple[int, int]] = []
    wi = 0
    for beat_text in beat_texts:
        target = len(normalize_text(beat_text))
        if target == 0:
            raise StoryFilmError("beat narration has no speakable characters")
        start: int | None = None
        end: int | None = None
        acc = 0
        while wi < len(words):
            word = words[wi]
            wi += 1
            if start is None:
                start = int(word.start_ms)
            acc += len(normalize_text(str(word.text)))
            end = int(word.end_ms)
            if acc >= target:
                break
        else:
            raise StoryFilmError(
                "alignment word stream exhausted before narration ended"
            )
        spans.append((int(start or 0), int(end or 0)))
    return spans


# ---------------------------------------------------------------------------
# Composition (HyperFrames route) + PixStag handoff package
# ---------------------------------------------------------------------------


def build_frame_html(
    image_path: Path, narration: str, *, title: str | None = None
) -> str:
    """One storyboard frame: full-bleed still + subtitle band (+title card)."""
    title_div = (
        f'<div class="title">{html.escape(title)}</div>' if title else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;width:100%;height:100%;background:#101418;overflow:hidden}}
img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.title{{position:absolute;top:5%;left:0;right:0;text-align:center;color:#fff;
font:700 46px sans-serif;text-shadow:0 2px 14px rgba(0,0,0,.7);padding:0 40px}}
.sub{{position:absolute;left:0;right:0;bottom:0;padding:30px 36px 34px;
background:linear-gradient(transparent,rgba(0,0,0,.75));color:#fff;
font:500 31px/1.55 sans-serif;text-align:center}}
</style></head><body>
<img src="{Path(image_path).as_uri()}">
{title_div}
<div class="sub">{html.escape(narration)}</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Ken Burns motion (film_gate fix)
#
# Why not CSS animation in build_frame_html?  The storyboard renderer
# (html_video_pipeline._capture_frame / hyperframes_service._capture_frames)
# captures each frame with a *fixed* --virtual-time-budget (200 ms / 100 ms):
# every capture starts the page at the same virtual instant, so a CSS
# animation is frozen at the same phase in every frame — and
# render_storyboard only captures ONE frame per shot and duplicates it.
# CSS motion therefore cannot move under the current capturers.
#
# The renderer-compatible route is to animate the still itself per
# output frame (PIL crop/resize, the same Ken Burns idea as
# hevi/tongjian/assemble.py's zoompan, but keeping the subtitle band
# static) and pipe the frames to ffmpeg.  Magnitudes are calibrated to
# film_gate's metric (12 fps, 320-wide gray, mean abs diff >= 9 = fast):
# the pilot's static frames scored ~0; these moves gave mean_diff ~18 /
# fast_ratio 1.0 on the pilot images in prototyping (2026-10-20).
#   zoom_in : crop width 0.92 -> 0.50 of the cover width (~1.8x push)
#   zoom_out: the reverse
#   pan_*   : crop width 0.62, centre travels 12% -> 88% of the slack
# ---------------------------------------------------------------------------

_KB_FALLBACK_CYCLE = ("zoom_in", "pan_right", "zoom_out", "pan_left")


def ken_burns_params(motion_prompt: str | None, index: int) -> dict[str, Any]:
    """Map a beat's motion_prompt (+ shot index) to Ken Burns parameters.

    Pure function.  ``crop_w_start``/``crop_w_end`` are fractions of the
    cover-crop width; ``cx_start``/``cx_end`` are fractions of the pan
    slack (0 = hard left, 1 = hard right).  Prompts asking for a static
    shot still get a slow zoom_out — a truly static shot is exactly
    what film_gate rejects, and the beat's *content* stays framed.
    """
    p = (motion_prompt or "").lower()
    if "pan" in p and "left" in p:
        kind = "pan_left"
    elif "pan" in p or "tracking" in p or "follow" in p:
        kind = "pan_right" if index % 2 == 0 else "pan_left"
    elif "pull" in p or "static" in p or "wide" in p:
        kind = "zoom_out"
    elif "push" in p or "close" in p or "zoom" in p:
        kind = "zoom_in"
    else:
        kind = _KB_FALLBACK_CYCLE[index % len(_KB_FALLBACK_CYCLE)]
    if kind == "zoom_in":
        return {"kind": kind, "crop_w_start": 0.92, "crop_w_end": 0.50,
                "cx_start": 0.5, "cx_end": 0.5}
    if kind == "zoom_out":
        return {"kind": kind, "crop_w_start": 0.50, "crop_w_end": 0.92,
                "cx_start": 0.5, "cx_end": 0.5}
    if kind == "pan_right":
        return {"kind": kind, "crop_w_start": 0.62, "crop_w_end": 0.62,
                "cx_start": 0.12, "cx_end": 0.88}
    return {"kind": "pan_left", "crop_w_start": 0.62, "crop_w_end": 0.62,
            "cx_start": 0.88, "cx_end": 0.12}


def motion_for_shot(motion_prompt: str | None, index: int) -> str:
    return str(ken_burns_params(motion_prompt, index)["kind"])


_FONT_CANDIDATES = (
    Path.home() / ".fonts" / "simhei.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)


def _find_cjk_font() -> Path | None:
    for cand in _FONT_CANDIDATES:
        if cand.is_file():
            return cand
    return None


def _wrap_subtitle(text: str, per_line: int = 16) -> str:
    return "\n".join(text[i:i + per_line] for i in range(0, len(text), per_line))


def render_motion_film(
    *,
    shots: list[dict[str, Any]],
    title: str,
    narration_path: Path,
    output_path: Path,
    width: int = 720,
    height: int = 1280,
    fps: int = 24,
) -> float:
    """Render shots to film.mp4 with per-shot Ken Burns motion.

    Per output frame: crop the shot still per ken_burns_params, resize
    to the output frame, draw a static subtitle band (+ title on shot
    1), and pipe raw RGB to ffmpeg; the (mastered) narration is padded
    to the full storyboard duration so tails are not cut by -shortest.
    Returns the total duration in seconds.
    """
    from PIL import Image, ImageDraw, ImageFont

    font_path = _find_cjk_font()
    if font_path is None:
        raise StoryFilmError("no CJK font found for subtitle rendering")
    font_sub = ImageFont.truetype(str(font_path), 34)
    font_title = ImageFont.truetype(str(font_path), 48)
    total = sum(float(s["duration_s"]) for s in shots)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-i", str(narration_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac",
        "-af", f"apad=pad_dur={total:.3f}",
        "-t", f"{total:.3f}",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    try:
        for si, shot in enumerate(shots):
            params = shot.get("ken_burns") or ken_burns_params(
                shot.get("motion_prompt"), si
            )
            img = Image.open(shot["image"]).convert("RGB")
            sw, sh = img.size
            aspect = width / height
            max_crop_w = sh * aspect
            n_frames = max(1, round(float(shot["duration_s"]) * fps))
            for f in range(n_frames):
                t = f / max(1, n_frames - 1)
                crop_w = max_crop_w * (
                    params["crop_w_start"]
                    + (params["crop_w_end"] - params["crop_w_start"]) * t
                )
                crop_h = crop_w / aspect
                slack = max(0.0, sw - crop_w)
                cx = crop_w / 2 + slack * (
                    params["cx_start"]
                    + (params["cx_end"] - params["cx_start"]) * t
                )
                cx = min(max(cx, crop_w / 2), sw - crop_w / 2)
                cy = min(max(sh / 2, crop_h / 2), sh - crop_h / 2)
                box = (
                    int(cx - crop_w / 2), int(cy - crop_h / 2),
                    int(cx + crop_w / 2), int(cy + crop_h / 2),
                )
                frame = img.crop(box).resize(
                    (width, height), Image.LANCZOS
                )
                draw = ImageDraw.Draw(frame, "RGBA")
                draw.rectangle(
                    [0, height - 190, width, height], fill=(0, 0, 0, 140)
                )
                draw.multiline_text(
                    (width / 2, height - 165),
                    _wrap_subtitle(str(shot["narration"])),
                    font=font_sub, fill=(255, 255, 255, 255),
                    anchor="ma", align="center", spacing=8,
                )
                if si == 0 and title:
                    draw.text(
                        (width / 2, 70), title, font=font_title,
                        fill=(255, 255, 255, 255), anchor="ma",
                        stroke_width=2, stroke_fill=(0, 0, 0, 180),
                    )
                proc.stdin.write(frame.tobytes())
    except BrokenPipeError as exc:
        err = (proc.stderr.read().decode(errors="replace")[-500:]
               if proc.stderr else "")
        raise StoryFilmError(f"ffmpeg motion render broke: {err}") from exc
    finally:
        with contextlib.suppress(BrokenPipeError):
            proc.stdin.close()
    err_text = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.wait() != 0 or not output_path.is_file():
        raise StoryFilmError(
            f"ffmpeg motion render failed: {err_text[-500:]}"
        )
    return total


# ---------------------------------------------------------------------------
# Audio mastering (earshot gate fix)
# ---------------------------------------------------------------------------


def compute_gain_db(
    true_peak_dbtp: float, *, target_dbtp: float = TARGET_TRUE_PEAK_DBTP
) -> float:
    """Gain to bring a true peak to target: attenuation only, never boost."""
    return round(min(0.0, target_dbtp - float(true_peak_dbtp)), 2)


def choose_mastering(
    true_peak_dbtp: float, lufs: float | None
) -> dict[str, Any]:
    """Decide volume vs loudnorm from measured peak/LUFS (pure).

    Simple attenuation is preferred; it shifts LUFS by the same amount.
    If that predicted LUFS would leave the -14 +/- 2 tolerance, fall
    back to loudnorm (which targets LUFS and the peak ceiling at once).
    """
    gain = compute_gain_db(true_peak_dbtp)
    if gain == 0.0:
        return {"method": "none", "gain_db": 0.0}
    if lufs is not None and (lufs + gain) < (LUFS_TARGET - LUFS_TOLERANCE):
        return {"method": "loudnorm", "gain_db": gain}
    return {"method": "volume", "gain_db": gain}


def _measure_audio(path: Path) -> dict[str, Any]:
    from hevi.audio import earshot_client

    return earshot_client.measure(Path(path))


def apply_gain_control(
    wav_path: Path, *, target_dbtp: float = TARGET_TRUE_PEAK_DBTP
) -> dict[str, Any]:
    """Master ``wav_path`` in place so its true peak <= gate ceiling.

    Measures with earshot (the gate's own tool), applies volume or
    loudnorm via ffmpeg, then re-measures and returns the evidence.
    If earshot is unavailable the stage fails loudly — an unmeasured
    master is not a master.
    """
    wav_path = Path(wav_path)
    before = _measure_audio(wav_path)
    peak_before = before.get("true_peak_dbtp")
    if peak_before is None:
        raise StoryFilmError("earshot measure returned no true peak")
    plan = choose_mastering(float(peak_before), before.get("lufs"))
    info: dict[str, Any] = {
        "peak_before_dbtp": peak_before,
        "lufs_before": before.get("lufs"),
        "target_dbtp": target_dbtp,
        "method": plan["method"],
        "gain_db": plan["gain_db"],
    }
    if plan["method"] == "none":
        info["peak_after_dbtp"] = peak_before
        info["lufs_after"] = before.get("lufs")
        return info
    if plan["method"] == "loudnorm":
        af = f"loudnorm=I={LUFS_TARGET}:TP={target_dbtp}:LRA=11"
    else:
        af = f"volume={plan['gain_db']:.2f}dB"
    tmp = wav_path.with_suffix(".mastered.wav")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(wav_path),
         "-af", af, str(tmp)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not tmp.is_file():
        raise StoryFilmError(
            f"gain-control ffmpeg failed: {(proc.stderr or '')[-300:]}"
        )
    tmp.replace(wav_path)
    after = _measure_audio(wav_path)
    info["peak_after_dbtp"] = after.get("true_peak_dbtp")
    info["lufs_after"] = after.get("lufs")
    return info


# ---------------------------------------------------------------------------
# PixStag handles + beat-dependent tails (W4)
#
# Handles: a generated clip should be *longer* than the used (adopted)
# duration -- generation is requested for use + head + tail, and the
# returned clip is trimmed at source_in_s (= effective head) for
# use_duration_s during assembly. PixStag bills integer seconds exactly,
# so the requested duration is ceil(use+head+tail) clamped to 4..30.
# ---------------------------------------------------------------------------
PIXSTAG_HANDLE_HEAD_S = 0.5
PIXSTAG_HANDLE_TAIL_S = 0.5
PIXSTAG_DURATION_MIN_S = 4
PIXSTAG_DURATION_MAX_S = 30


def compute_pixstag_timing(
    use_duration_s: float,
    *,
    handle_head_s: float | None = None,
    handle_tail_s: float | None = None,
) -> dict[str, Any]:
    """Timing for one PixStag shot: used duration vs requested duration.

    ``duration`` (the PixStag request, integer seconds) is
    ``ceil(use + head + tail)`` clamped to 4..30. When the sum exceeds
    30 s the *used* duration is preserved first: handles are compressed
    (head first, then tail from what remains) and ``handles_clipped``
    is set. Below the 4 s floor the handles are kept as-is -- the extra
    generated padding is harmless because assembly trims by in-point.
    """
    from math import ceil

    use = float(use_duration_s)
    head = PIXSTAG_HANDLE_HEAD_S if handle_head_s is None else float(handle_head_s)
    tail = PIXSTAG_HANDLE_TAIL_S if handle_tail_s is None else float(handle_tail_s)
    if use <= 0:
        raise StoryFilmError(f"pixstag use_duration_s must be > 0, got {use}")
    if head < 0 or tail < 0:
        raise StoryFilmError(
            f"pixstag handles must be >= 0, got head={head} tail={tail}"
        )
    clipped = False
    eff_head, eff_tail = head, tail
    if use + head + tail > PIXSTAG_DURATION_MAX_S:
        clipped = True
        budget = max(0.0, PIXSTAG_DURATION_MAX_S - use)
        eff_head = min(head, budget)
        eff_tail = min(tail, max(0.0, budget - eff_head))
    duration = min(
        PIXSTAG_DURATION_MAX_S,
        max(PIXSTAG_DURATION_MIN_S, ceil(use + eff_head + eff_tail)),
    )
    return {
        "use_duration_s": round(use, 4),
        "handle_head_s": round(eff_head, 4),
        "handle_tail_s": round(eff_tail, 4),
        "source_in_s": round(eff_head, 4),
        "duration": duration,
        "handles_clipped": clipped,
    }


# Beat-dependent shot tails. Beats in this pipeline carry no explicit
# beat-type field (the story draft only guarantees narration / visual_en /
# motion_prompt), so the kind is inferred, in order:
#   1. an explicit beat["beat_type"|"beat_kind"|"type"|"kind"|"shot_type"]
#      when a future draft supplies one;
#   2. keyword inference over motion_prompt + visual_en + narration --
#      close-up / reaction / emotion wording -> "reaction";
#      finally / reveal / finds / returns-home wording -> "result";
#   3. otherwise "default".
_BEAT_TAIL_S = {"reaction": 0.8, "emotion": 0.8, "result": 0.5, "default": 0.35}
_LAST_SHOT_TAIL_MIN_S = 1.2
_REACTION_WORDS = (
    "close-up", "closeup", "reaction", "tear", "crying", "smile",
    "surprised", "expression", "face", "hug",
    "哭", "眼泪", "笑", "惊讶", "愣", "表情", "拥抱", "害怕", "担心",
)
_RESULT_WORDS = (
    "finally", "reveal", "discover", "finds", "arrives", "opens the door",
    "终于", "发现", "原来", "回到家", "打开门", "结果",
)


# Expression-rig emotion inference (oneclick rig mode).  Keywords are
# checked in the order below over narration / visual_en / motion_prompt;
# every target is a legal key of expression_rig.EMOTIONS (verified
# 2026-10-23: neutral/happy/joy/playful/proud/shy/surprised/excited/
# thinking/confused/sad/angry/scared/disgusted/sleepy/dizzy).
_EMOTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("难过", "哭", "眼泪", "孤单", "伤心", "sad", "crying", "tear", "lonely"), "sad"),
    (("害怕", "担心", "危险", "恐惧", "scared", "afraid", "danger", "worried"), "scared"),
    (("惊讶", "惊奇", "忽然", "突然", "surprised", "surprise", "suddenly"), "surprised"),
    (("开心", "快乐", "高兴", "笑", "happy", "smile", "laugh"), "happy"),
    (("终于", "回家", "成功", "胜利", "团聚", "finally", "success", "victory", "reunited"), "joy"),
    (("思考", "为什么", "想", "thinking", "wonder", "why"), "thinking"),
)


def infer_beat_emotion(beat: dict[str, Any]) -> str:
    """Infer an expression-rig emotion name for a beat (pure).

    Keyword inference over narration / visual_en / motion_prompt, in the
    rule order of ``_EMOTION_RULES``; defaults to ``"neutral"``.  The
    result is always a legal ``expression_rig.EMOTIONS`` key when that
    module is importable; on any doubt it falls back to ``"neutral"``.
    """
    text = " ".join(
        str(beat.get(k) or "")
        for k in ("narration", "visual_en", "motion_prompt")
    ).lower()
    emotion = "neutral"
    for words, name in _EMOTION_RULES:
        if any(w in text for w in words):
            emotion = name
            break
    try:
        from hevi.layer4_legacy.handdraw.expression_rig import EMOTIONS

        if emotion not in EMOTIONS:
            return "neutral"
    except Exception:
        pass
    return emotion


def infer_beat_kind(beat: dict[str, Any]) -> str:
    """Infer the beat kind used for tail sizing (see table above)."""
    explicit = ""
    for key in ("beat_type", "beat_kind", "type", "kind", "shot_type"):
        if beat.get(key):
            explicit = str(beat[key]).strip().lower()
            break
    if explicit:
        if any(w in explicit for w in ("react", "emot", "close")):
            return "reaction"
        if any(w in explicit for w in ("result", "reveal", "payoff", "outcome")):
            return "result"
        return "default"
    text = " ".join(
        str(beat.get(k) or "")
        for k in ("motion_prompt", "visual_en", "narration")
    ).lower()
    if any(w in text for w in _REACTION_WORDS):
        return "reaction"
    if any(w in text for w in _RESULT_WORDS):
        return "result"
    return "default"


def tail_for_beat(beat: dict[str, Any], *, is_last: bool = False) -> float:
    """Tail seconds after a beat's narration: reaction/emotion 0.8,
    result 0.5, default 0.35; the last shot keeps a 1.2 s floor."""
    tail = _BEAT_TAIL_S.get(infer_beat_kind(beat), _BEAT_TAIL_S["default"])
    if is_last:
        tail = max(tail, _LAST_SHOT_TAIL_MIN_S)
    return tail


def build_pixstag_package(
    *, premise: str, draft: dict[str, Any], shots: list[dict[str, Any]],
    aspect: str, narration_path: Path, alignment_path: Path,
) -> dict[str, Any]:
    """Handoff package for video.pixstag_generate (live-action route).

    Per shot the consumer needs: first_frame + motion_prompt + the
    PixStag request ``duration`` (integer seconds). The request duration
    is NOT the used duration: it is ``ceil(use + head + tail)`` clamped
    to 4..30 (see compute_pixstag_timing), the returned clip is trimmed
    at ``source_in_s`` (= effective handle head) for ``use_duration_s``
    during assembly, and ``duration_s`` keeps the used duration for
    backwards compatibility. A shot may carry its own
    ``handle_head_s`` / ``handle_tail_s``; defaults are 0.5 s / 0.5 s.
    Narration/alignment ride along so the final assembly can keep
    the measured timeline.
    """

    def _pkg_shot(s: dict[str, Any]) -> dict[str, Any]:
        timing = compute_pixstag_timing(
            s["duration_s"],
            handle_head_s=s.get("handle_head_s"),
            handle_tail_s=s.get("handle_tail_s"),
        )
        return {
            "shot_id": s["shot_id"],
            "first_frame": s["first_frame"],
            "motion_prompt": s["motion_prompt"],
            "duration_s": s["duration_s"],
            "duration": timing["duration"],
            "use_duration_s": timing["use_duration_s"],
            "handle_head_s": timing["handle_head_s"],
            "handle_tail_s": timing["handle_tail_s"],
            "source_in_s": timing["source_in_s"],
            "handles_clipped": timing["handles_clipped"],
            "narration": s["narration"],
        }

    return {
        "kind": "pixstag_shot_package",
        "title": draft["title"],
        "premise": premise,
        "hook": draft.get("hook", ""),
        "aspect": aspect,
        "narration_audio": str(narration_path),
        "alignment_json": str(alignment_path),
        "shots": [_pkg_shot(s) for s in shots],
        "note": (
            "hevi 备齐流程与镜头包; 最终成片由 video.pixstag_generate 逐镜"
            "按 duration(生成时长,含首尾 handles)生成, 回片按 source_in_s "
            "裁切 use_duration_s 后按 shots.json 的实测时间轴拼接。"
        ),
    }


# ---------------------------------------------------------------------------
# Gates (best evidence available; absence is recorded, never faked)
# ---------------------------------------------------------------------------


def _run_gates(film_path: Path, out_dir: Path, *, aspect: str) -> dict[str, Any]:
    gates: dict[str, Any] = {}

    if _FILM_GATE.is_file():
        try:
            proc = subprocess.run(
                [
                    sys.executable, str(_FILM_GATE), str(film_path),
                    "--json", "--no-template",
                ],
                capture_output=True, text=True, timeout=900,
            )
            parsed = json.loads(proc.stdout)
            gates["film_gate"] = {
                "verdict": parsed.get("verdict"),
                "gate_light": parsed.get("gate_light"),
            }
        except Exception as exc:
            gates["film_gate"] = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        gates["film_gate"] = {"skipped": "film_gate script not found"}

    try:
        import hevi.capabilities as caps

        cap = caps.get("audio.earshot_gate")
        result = cap.render_safe(
            {"media_path": str(film_path)},
            out_dir / "earshot_gate",
            duration=0.0,
            aspect=aspect,
            seed=0,
        )
        gates["earshot_gate"] = {
            "pass": result.qa.get("pass"),
            "report": result.qa.get("report"),
        }
    except Exception as exc:
        gates["earshot_gate"] = {"skipped": f"{type(exc).__name__}: {exc}"}

    return gates


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class _Ledger:
    def __init__(self, out_dir: Path, meta: dict[str, Any]) -> None:
        self.out_dir = out_dir
        self.meta = meta
        self.stages: dict[str, dict[str, Any]] = {}

    def mark(
        self, stage: str, status: str, *, cost: float | None = None,
        artifacts: list[str] | None = None, error: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {"status": status}
        if cost is not None:
            entry["cost"] = cost
        if artifacts:
            entry["artifacts"] = artifacts
        if error:
            entry["error"] = error
        self.stages[stage] = entry
        self.flush()

    def flush(self) -> None:
        job = {
            **self.meta,
            "stages": {k: v["status"] for k, v in self.stages.items()},
        }
        (self.out_dir / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        delivery = {
            **self.meta,
            "stages": self.stages,
            "total_cost_usd": round(
                sum(
                    v["cost"]
                    for v in self.stages.values()
                    if isinstance(v.get("cost"), (int, float))
                ),
                4,
            ),
        }
        (self.out_dir / "delivery.json").write_text(
            json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def run_story_film(
    *,
    premise: str,
    style: str = DEFAULT_STYLE,
    max_shots: int = 5,
    render_route: str = "ken_burns",
    aspect: str = "9:16",
    voice: str = "soffy",
    out_dir: Path,
    music: bool = False,
    music_product: str = "cute",
    music_style: str | None = None,
    rig_character: str | None = None,
    image_provider: str = "gpt",
    series: str | None = None,
    asset_library: str | None = None,
) -> dict[str, Any]:
    """Run the full one-sentence-to-film chain. Returns the delivery ledger.

    ``series`` opts the run into the cross-episode asset registry
    (hevi.storyfilm.assets, AID-learned): the draft's characters and
    scenes are upserted into the library at ``asset_library`` (default
    ``$HEVI_ASSET_LIBRARY`` or ``~/.hevi/storyfilm_assets``), locked
    appearance text is injected for every character a shot references,
    and a registered hero key still is reused instead of re-bought.
    Without ``series`` the run behaves exactly as before.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "images").mkdir(exist_ok=True)
    requested_route = str(render_route or "").strip()
    render_route = resolve_render_route(requested_route)
    render_entry = film_render_entry_for(requested_route)
    meta = {
        "premise": premise,
        "style": style,
        "max_shots": max_shots,
        "render_route": requested_route,
        "render_route_resolved": render_route,
        "render_entry": render_entry["entry"],
        "aspect": aspect,
    }
    if series:
        meta["series"] = series
    ledger = _Ledger(out_dir, meta)

    async def stage(name, coro_factory):  # type: ignore[no-untyped-def]
        try:
            result = await coro_factory()
        except StoryFilmError as exc:
            ledger.mark(name, "failed", error=str(exc))
            raise
        except Exception as exc:
            ledger.mark(name, "failed", error=f"{type(exc).__name__}: {exc}")
            raise StoryFilmError(f"stage {name} failed: {exc}") from exc
        return result

    story_meta: dict[str, Any] = {}
    mastering_info: dict[str, Any] = {}
    rig_emotions: dict[int, str] = {}
    # Asset-registry context (filled by the story stage when a series
    # is set) and per-shot media facts the images stage records for
    # the shots table (reference images actually fed to the generator,
    # brush templates actually used, the voice actually applied).
    asset_ctx: dict[str, Any] = {}
    media_ctx: dict[str, Any] = {}

    # -- 1. story ------------------------------------------------------------
    async def _story():
        draft, cost = await generate_story(
            premise, style=style, max_shots=max_shots
        )
        # Structured storyboard layer (AID-learned): scenes, shot
        # parameters, cast references and per-shot duration estimates.
        # Pure enrichment — fields the LLM omitted are derived.
        draft = _storyboard.enrich_draft(draft)
        if series:
            root = (
                Path(asset_library).expanduser()
                if asset_library
                else _asset_registry.default_library_root()
            )
            library = _asset_registry.load_library(root)
            registered = _asset_registry.register_draft_assets(
                library,
                draft,
                series=series,
                episode=str(draft.get("title") or premise),
                voice=voice,
            )
            _asset_registry.save_library(root, library)
            asset_ctx.update(
                {"root": root, "library": library, "registered": registered}
            )
        story_meta.update(
            {
                "narration_chars": narration_char_count(draft),
                "estimated_narration_s": round(
                    estimate_narration_seconds(narration_char_count(draft)), 1
                ),
                "continuation_rounds": draft.get("_continuation_rounds", 0),
                "length_warning": draft.get("_length_warning"),
            }
        )
        (out_dir / "story.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "story.md").write_text(
            story_markdown(premise, draft), encoding="utf-8"
        )
        (out_dir / "characters.json").write_text(
            json.dumps(draft["characters"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ledger.mark(
            "story", "ok", cost=cost,
            artifacts=["story.json", "story.md", "characters.json"],
        )
        return draft

    draft = await stage("story", _story)

    # -- 2. images ------------------------------------------------------------
    async def _images():
        from hevi.image.gpt_image_service import (
            gpt_image_edit,
            gpt_image_generate,
        )

        size = _ASPECT_SIZE.get(aspect, "1024x1536")
        if image_provider == "brush":
            # Brush provider (zero-cost): paint each beat with the
            # procedural brush engine (hevi.image.brushpaint) instead of
            # a GPT image call.  Beat text is keyword-routed to a scene
            # template; per-beat seeds derive from the premise, so a
            # run is reproducible.  Takes precedence over rig mode.
            import zlib

            from hevi.image.brushpaint import (
                get_template,
                parse_scene,
                pick_template_for_text,
                render_still,
            )

            w_px, h_px = (int(v) for v in size.split("x"))
            base_seed = zlib.crc32(premise.encode("utf-8"))
            brush_paths = []
            brush_templates: dict[int, str] = {}
            for i, beat in enumerate(draft["beats"]):
                shot_path = out_dir / "images" / f"shot_{i + 1:02d}.png"
                # A registered scene asset's bound template wins over
                # keyword routing, so a place looks the same across
                # episodes; the first routing decision is bound back
                # into the registry.
                scene_record = None
                if asset_ctx:
                    scene_record = asset_ctx["registered"]["scenes"].get(
                        str(beat.get("scene_name") or "")
                    )
                if scene_record and scene_record.get("brush_template"):
                    template = str(scene_record["brush_template"])
                else:
                    template = pick_template_for_text(
                        f"{beat.get('visual_en', '')} {beat.get('narration', '')}"
                    )
                    if scene_record:
                        _asset_registry.bind_scene_template(
                            asset_ctx["library"],
                            str(scene_record["id"]),
                            template,
                        )
                brush_templates[i] = template
                spec = get_template(template)
                spec["seed"] = base_seed + i
                render_still(parse_scene(spec), w_px, h_px).save(shot_path)
                brush_paths.append(shot_path)
            media_ctx["scene_templates"] = brush_templates
            media_ctx["reference_images"] = [[] for _ in brush_paths]
            ledger.mark(
                "images", "ok", cost=0.0,
                artifacts=[f"images/{p.name}" for p in brush_paths],
            )
            return brush_paths
        if image_provider != "gpt":
            raise StoryFilmError(
                f"unknown image_provider {image_provider!r} (want gpt|brush)"
            )
        if rig_character:
            # Rig mode (opt-in): skip the GPT character sheet entirely.
            # Each shot is a GPT background still (no characters in the
            # prompt) with the expression-rig face for the beat's
            # inferred emotion alpha-composited on top, so the character
            # is byte-identical across shots.
            from PIL import Image

            from hevi.layer4_legacy.handdraw.expression_rig import (
                render_face,
            )

            rig_cost = 0.0
            rig_paths = []
            for i, beat in enumerate(draft["beats"]):
                shot_path = out_dir / "images" / f"shot_{i + 1:02d}.png"
                res = await gpt_image_generate(
                    prompt=(
                        f"{beat['visual_en']}, background environment only, "
                        f"empty scene, no characters, no people, no animals. "
                        f"{style}"
                    ),
                    output_path=shot_path,
                    size=size,
                )
                if isinstance(res.get("cost"), (int, float)):
                    rig_cost += float(res["cost"])
                emotion = infer_beat_emotion(beat)
                rig_emotions[i] = emotion
                bg = Image.open(shot_path).convert("RGBA")
                face_size = max(96, min(1024, int(bg.width * 0.62)))
                face = render_face(
                    character=rig_character, emotion=emotion, size=face_size
                )
                face_x = (bg.width - face.width) // 2
                face_y = int(bg.height * 0.58 - face.height / 2)
                bg.alpha_composite(face, (face_x, face_y))
                bg.convert("RGB").save(shot_path)
                rig_paths.append(shot_path)
            media_ctx["reference_images"] = [[] for _ in rig_paths]
            ledger.mark(
                "images", "ok", cost=round(rig_cost, 4),
                artifacts=[f"images/{p.name}" for p in rig_paths],
            )
            return rig_paths
        hero = draft["characters"][0]
        total_cost = 0.0
        key_path = out_dir / "images" / "character.png"
        registered_chars: dict[str, Any] = {}
        hero_record: dict[str, Any] | None = None
        if asset_ctx:
            registered_chars = asset_ctx["registered"]["characters"]
            hero_record = registered_chars.get(str(hero["name"]))
        # Cross-episode reuse: a registered hero key still is copied in
        # instead of re-bought; a fresh one is stored into the library
        # so the next episode of the series can reuse it.
        reused_key = False
        if hero_record:
            for ref in hero_record.get("reference_images") or []:
                if Path(ref).is_file():
                    shutil.copyfile(ref, key_path)
                    reused_key = True
                    break
        media_ctx["reused_key_still"] = reused_key
        if not reused_key:
            res = await gpt_image_generate(
                prompt=(
                    f"{hero['appearance_en']}, full-body character sheet, front "
                    f"view, standing, {style}"
                ),
                output_path=key_path,
                size=size,
            )
            if isinstance(res.get("cost"), (int, float)):
                total_cost += float(res["cost"])
            if hero_record:
                stored = _asset_registry.store_reference_image(
                    asset_ctx["root"], hero_record, key_path, tag="key"
                )
                _asset_registry.add_reference_image(
                    asset_ctx["library"], str(hero_record["id"]), stored
                )
        paths = []
        shot_refs: list[list[str]] = []
        for i, beat in enumerate(draft["beats"]):
            shot_path = out_dir / "images" / f"shot_{i + 1:02d}.png"
            cast_records: list[dict[str, Any]] = []
            if asset_ctx:
                for ref_name in beat.get("character_refs") or []:
                    record = registered_chars.get(ref_name)
                    if record is not None:
                        cast_records.append(record)
            if cast_records:
                # AID-style cast injection: every character the shot
                # references contributes its LOCKED appearance text,
                # and each one's primary reference image (the hero's
                # is this run's key still) feeds the edit.
                cast_text = "; ".join(
                    f"{rec['name']}: {rec.get('appearance_en') or ''}"
                    for rec in cast_records
                )
                ref_paths: list[Path] = []
                for rec in cast_records:
                    if rec is hero_record:
                        ref_paths.append(key_path)
                    else:
                        primary = _asset_registry.primary_reference(rec)
                        if primary and Path(primary).is_file():
                            ref_paths.append(Path(primary))
                prompt = (
                    f"{beat['visual_en']}. Characters in this shot — keep "
                    f"their appearance exactly: {cast_text}. {style}"
                )
                if ref_paths:
                    res = await gpt_image_edit(
                        image_paths=ref_paths,
                        prompt=prompt,
                        output_path=shot_path,
                        size=size,
                    )
                else:
                    res = await gpt_image_generate(
                        prompt=prompt,
                        output_path=shot_path,
                        size=size,
                    )
                shot_refs.append([str(p) for p in ref_paths])
            else:
                res = await gpt_image_edit(
                    image_paths=[key_path],
                    prompt=(
                        f"{beat['visual_en']}. Same main character as the "
                        f"reference: {hero['appearance_en']}. {style}"
                    ),
                    output_path=shot_path,
                    size=size,
                )
                shot_refs.append([str(key_path)])
            if isinstance(res.get("cost"), (int, float)):
                total_cost += float(res["cost"])
            paths.append(shot_path)
        media_ctx["reference_images"] = shot_refs
        ledger.mark(
            "images", "ok", cost=round(total_cost, 4),
            artifacts=[f"images/{p.name}" for p in [key_path, *paths]],
        )
        return paths

    image_paths = await stage("images", _images)

    if asset_ctx:
        # Persist what the images stage bound (scene brush templates,
        # the hero's stored key still) and snapshot the assets this
        # episode used into the job folder.
        _asset_registry.save_library(asset_ctx["root"], asset_ctx["library"])
        registered = asset_ctx["registered"]
        snapshot = {
            "series": series,
            "library_root": str(asset_ctx["root"]),
            "episode": draft["title"],
            "characters": list(registered["characters"].values()),
            "scenes": list(registered["scenes"].values()),
            "created_ids": registered["created_ids"],
            "updated_ids": registered["updated_ids"],
            "reused_key_still": bool(media_ctx.get("reused_key_still")),
        }
        (out_dir / "assets.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ledger.mark("assets", "ok", artifacts=["assets.json"])

    # -- 3. narration ---------------------------------------------------------
    full_text = "".join(b["narration"] for b in draft["beats"])
    narration_path = out_dir / "narration.wav"

    async def _narration():
        from hevi.audio.lux_tts_service import lux_tts_available, synth_with_luxtts

        if not lux_tts_available():
            raise StoryFilmError(
                "LuxTTS HTTP service is not reachable (HEVI_LUXTTS_URL)"
            )
        # Series voice binding: the hero's registered voice (bound at
        # first registration) wins over the run parameter, so a series
        # keeps one narrator voice across episodes.
        narration_voice = voice
        if asset_ctx:
            hero_rec = _asset_registry.get_asset(
                asset_ctx["library"],
                str(asset_ctx["registered"].get("hero_id") or ""),
            )
            if hero_rec and hero_rec.get("voice"):
                narration_voice = str(hero_rec["voice"])
        media_ctx["voice_applied"] = narration_voice
        await synth_with_luxtts(
            text=full_text, output_path=narration_path, voice=narration_voice
        )
        if not narration_path.is_file():
            raise StoryFilmError("LuxTTS returned no narration file")
        # Master the narration bus: LuxTTS can peak at 0 dBTP (pilot:
        # +0.1 dBTP, 534 clipped samples), which the earshot gate
        # rejects.  Attenuate to <= -1.5 dBTP before it is baked in.
        mastering_info.update(apply_gain_control(narration_path))
        ledger.mark("narration", "ok", artifacts=["narration.wav"])

    await stage("narration", _narration)

    # -- 4. alignment ---------------------------------------------------------
    async def _alignment():
        from hevi.audio.tts_alignment import probe_duration_ms

        # Alignment provider tiers, selected by HEVI_TTS_ALIGNMENT_PROVIDER
        # (same env switch as hevi.audio.tts_alignment).  storyfilm defaults
        # to whisper_local: local faster-whisper ASR measurement, free, no
        # key - validated against the ElevenLabs ground truth of the pilot
        # narration (median word-start deviation 60 ms, P90 ~100 ms; the
        # timestamps only cut shots at second scale).  Setting
        # elevenlabs_forced keeps the paid precision tier (Monid) available.
        provider = (
            os.getenv("HEVI_TTS_ALIGNMENT_PROVIDER", "whisper_local")
            .strip()
            .lower()
        )
        if provider in {"elevenlabs", "elevenlabs_forced", "forced"}:
            from hevi.audio.forced_alignment import forced_align_words

            words, cost = await forced_align_words(
                audio_path=narration_path, text=full_text
            )
            source = "elevenlabs_forced_alignment"
            tier = "elevenlabs_forced"
        elif provider in {"whisper", "whisper_local", "whisper_asr"}:
            from hevi.audio.whisper_alignment import whisper_align_words

            words, _no_cost = await whisper_align_words(
                audio_path=narration_path, text=full_text
            )
            source = "whisper_asr_local"
            tier = "whisper_local"
            cost = 0.0  # local CPU inference: honestly zero, recorded as such
        else:
            raise StoryFilmError(
                f"unsupported HEVI_TTS_ALIGNMENT_PROVIDER={provider!r} for "
                "storyfilm alignment; choose whisper_local (free, default) "
                "or elevenlabs_forced"
            )
        payload = {
            "alignment_source": source,
            "alignment_provider": tier,
            "is_estimated": False,
            "duration_ms": probe_duration_ms(narration_path),
            "words": [
                {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms}
                for w in words
            ],
        }
        (out_dir / "alignment.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ledger.mark("alignment", "ok", cost=cost, artifacts=["alignment.json"])
        return words, payload["duration_ms"]

    words, duration_ms = await stage("alignment", _alignment)

    # -- 5. shots ---------------------------------------------------------------
    try:
        spans = map_beats_to_words(
            [b["narration"] for b in draft["beats"]], list(words)
        )
    except StoryFilmError as exc:
        ledger.mark("shots", "failed", error=str(exc))
        raise
    # Post-TTS duration verification: the story stage already enforced
    # the char target, but the *measured* audio is the truth.  A miss is
    # recorded in the delivery ledger — never hidden.
    duration_check = check_measured_duration(duration_ms)

    shots: list[dict[str, Any]] = []
    for i, (beat, img, (start_ms, end_ms)) in enumerate(
        zip(draft["beats"], image_paths, spans, strict=True)
    ):
        # Tail by beat kind (reaction/emotion hold longer, result beats
        # a beat less, default 0.35 s; last shot floor 1.2 s) -- the kind
        # is inferred by tail_for_beat/infer_beat_kind, see their comment.
        tail = tail_for_beat(beat, is_last=i == len(draft["beats"]) - 1)
        shot: dict[str, Any] = {
            "shot_id": f"S{i + 1:02d}",
            "narration": beat["narration"],
            "visual_prompt": beat["visual_en"],
            "motion_prompt": beat["motion_prompt"],
            "beat_kind": infer_beat_kind(beat),
            "tail_s": tail,
            "ken_burns": ken_burns_params(beat["motion_prompt"], i),
            "image": str(img),
            "first_frame": str(img),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_s": round((end_ms - start_ms) / 1000 + tail, 2),
            **({"emotion": rig_emotions[i]} if i in rig_emotions else {}),
        }
        # Structured storyboard fields (plan values from the enriched
        # draft) + the reference images this shot actually consumed.
        ref_images = media_ctx.get("reference_images") or []
        shot.update(
            {
                "shot_size": beat.get("shot_size"),
                "camera_angle": beat.get("camera_angle"),
                "camera_movement": beat.get("camera_movement"),
                "scene_ref": beat.get("scene_ref"),
                "scene_name": beat.get("scene_name"),
                "character_refs": list(beat.get("character_refs") or []),
                "narrative_function": beat.get("narrative_function"),
                "transition": beat.get("transition"),
                "est_duration_s": beat.get("est_duration_s"),
                "reference_images": (
                    list(ref_images[i]) if i < len(ref_images) else []
                ),
            }
        )
        templates = media_ctx.get("scene_templates") or {}
        if i in templates:
            shot["scene_template"] = templates[i]
        if asset_ctx:
            reg_chars = asset_ctx["registered"]["characters"]
            shot["character_assets"] = [
                str(reg_chars[name]["id"])
                for name in shot["character_refs"]
                if name in reg_chars
            ]
            scene_rec = asset_ctx["registered"]["scenes"].get(
                str(beat.get("scene_name") or "")
            )
            if scene_rec:
                shot["scene_asset"] = str(scene_rec["id"])
        shots.append(shot)
    (out_dir / "shots.json").write_text(
        json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "storyboard.md").write_text(
        _storyboard.storyboard_markdown(draft, shots), encoding="utf-8"
    )
    ledger.mark("shots", "ok", artifacts=["shots.json", "storyboard.md"])

    delivery_extra: dict[str, Any] = {
        "shots": len(shots),
        "title": draft["title"],
        "hook": draft.get("hook", ""),
        "story_length": story_meta,
        "mastering": mastering_info,
        "duration_check": duration_check,
        "render_route_requested": requested_route,
        "render_route_resolved": render_route,
        "render_entry": render_entry["entry"],
        "storyboard": {
            "scenes": len(draft.get("scenes") or []),
            "table": "storyboard.md",
        },
    }
    if asset_ctx:
        delivery_extra["assets"] = {
            "series": series,
            "library_root": str(asset_ctx["root"]),
            "snapshot": "assets.json",
            "characters": len(asset_ctx["registered"]["characters"]),
            "scenes": len(asset_ctx["registered"]["scenes"]),
            "created": len(asset_ctx["registered"]["created_ids"]),
            "updated": len(asset_ctx["registered"]["updated_ids"]),
            "reused_key_still": bool(media_ctx.get("reused_key_still")),
            "voice_applied": media_ctx.get("voice_applied"),
        }

    # -- 5b. music (opt-in; any failure degrades to narration-only) --------
    film_audio_path = narration_path
    if music and render_route == "ken_burns":
        try:
            import numpy as np

            from hevi.audio.score_render import (
                generate_score,
                parse_abc,
                render_score,
            )

            scenes: list[dict[str, Any]] = []
            cursor = 0.0
            for s in shots:
                dur = float(s["duration_s"])
                scenes.append(
                    {
                        "id": s["shot_id"],
                        "start_s": round(cursor, 3),
                        "end_s": round(cursor + dur, 3),
                    }
                )
                cursor += dur
            abc_text, align = generate_score(
                music_product, scenes, music_style, seed=0
            )
            score = parse_abc(abc_text)
            mix, sidecar = render_score(score, align, seed=0, timbre="sampled")
            bgm_path = out_dir / "bgm.wav"
            sample_rate = int(sidecar.get("sample_rate") or 48000)
            pcm16 = (np.clip(mix, -1.0, 1.0) * 32767.0).astype("<i2")
            import wave as _wave

            with _wave.open(str(bgm_path), "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16.tobytes())
            (out_dir / "bgm.abc").write_text(abc_text, encoding="utf-8")
            (out_dir / "bgm_sidecar.json").write_text(
                json.dumps(sidecar, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            total_dur = float(scenes[-1]["end_s"]) if scenes else 0.0
            soundtrack_path = out_dir / "soundtrack.wav"
            fade_out_start = max(0.0, total_dur - 2.0)
            af = (
                "[1:a]volume=0.22,afade=t=in:st=0:d=1,"
                f"afade=t=out:st={fade_out_start:.3f}:d=2[bgm];"
                "[0:a][bgm]amix=inputs=2:duration=first:normalize=0[out]"
            )
            proc = subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-i", str(narration_path), "-i", str(bgm_path),
                    "-filter_complex", af, "-map", "[out]",
                    str(soundtrack_path),
                ],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode != 0 or not soundtrack_path.is_file():
                raise StoryFilmError(
                    f"music mix ffmpeg failed: {(proc.stderr or '')[-300:]}"
                )
            apply_gain_control(soundtrack_path)
            film_audio_path = soundtrack_path
            delivery_extra["music"] = {
                "engine": sidecar.get("engine"),
                "timbre": sidecar.get("timbre"),
                "duration_s": sidecar.get("duration_s"),
                "note_count": sidecar.get("note_count"),
            }
            ledger.mark(
                "music", "ok", cost=0.0,
                artifacts=["bgm.wav", "bgm_sidecar.json", "soundtrack.wav"],
            )
        except Exception as exc:  # degraded, never fatal to the film
            ledger.mark(
                "music", "degraded",
                error=f"{type(exc).__name__}: {exc}",
            )
            delivery_extra["music"] = {
                "degraded": f"{type(exc).__name__}: {exc}"
            }
            film_audio_path = narration_path
    elif music:
        ledger.mark("music", "skipped")
    delivery_extra["film_audio"] = str(film_audio_path)

    # -- 6. render --------------------------------------------------------------
    if render_route == "ken_burns":

        async def _render():
            # Ken Burns motion render (see the motion section header):
            # the HTML storyboard renderer captures one frozen frame
            # per shot, which film_gate rejects as a slideshow. This
            # route animates every shot still per-frame instead.
            # It is NOT the CSK styled renderer (video.hyperframes_
            # styled_render); "hyperframes" only survives as the legacy
            # alias resolved to this route above.
            width, height = _ASPECT_RES.get(aspect, (720, 1280))
            total = render_motion_film(
                shots=shots,
                title=draft["title"],
                narration_path=film_audio_path,
                output_path=out_dir / "film.mp4",
                width=width,
                height=height,
                fps=24,
            )
            ledger.mark("render", "ok", artifacts=["film.mp4"])
            return total

        total_s = await stage("render", _render)
        delivery_extra["film"] = {
            "path": str(out_dir / "film.mp4"),
            "duration_s": round(total_s, 2),
        }

        # -- 7. gates (ken_burns route only; a package has no film to gate) --
        gates = _run_gates(out_dir / "film.mp4", out_dir, aspect=aspect)
        (out_dir / "gates.json").write_text(
            json.dumps(gates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ledger.mark("gates", "ok", artifacts=["gates.json"])
        delivery_extra["gates"] = gates
    elif render_route == "pixstag_package":
        package = build_pixstag_package(
            premise=premise, draft=draft, shots=shots, aspect=aspect,
            narration_path=narration_path,
            alignment_path=out_dir / "alignment.json",
        )
        (out_dir / "pixstag_package.json").write_text(
            json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ledger.mark("render", "ok", artifacts=["pixstag_package.json"])
        delivery_extra["pixstag_package"] = str(out_dir / "pixstag_package.json")
        ledger.mark("gates", "skipped")
    else:  # capability layer validates first; this is a backstop
        raise StoryFilmError(f"unknown render_route: {render_route!r}")

    ledger.flush()
    delivery = json.loads((out_dir / "delivery.json").read_text(encoding="utf-8"))
    delivery.update(delivery_extra)
    delivery["_narration_duration_ms"] = duration_ms
    (out_dir / "delivery.json").write_text(
        json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return delivery
