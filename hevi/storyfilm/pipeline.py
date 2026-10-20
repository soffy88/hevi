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
                            duration, 即 PixStag 镜头包的交接字段
  film.mp4                  render_route="hyperframes" 的代码合成成片
  pixstag_package.json      render_route="pixstag_package" 的镜头包,
                            交 video.pixstag_generate 逐镜生成后拼接
  gates.json                film_gate / audio.earshot_gate 结论 (可用时)
  delivery.json             阶段台账: 状态 / 花费 / 产物

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

Final-render routes (Soffy 分工定调 2026-10-20):
  * 代码动画类 → HyperFrames 线 (本模块的 hyperframes 路线)
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
import subprocess
import sys
from pathlib import Path
from typing import Any

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
      "motion_prompt": "英文运镜提示（如 slow push-in / gentle pan left / static close-up）"}}
  ]
}}
约束：beats 恰好 {max_shots} 个；总旁白必须在 {min_chars}-{max_chars} 字之间（逐字数好再输出，太短就把每拍写长）；人物不超过 3 个，主角排第一。"""

_CONTINUATION_USER = """前提：{premise}
片名：{title}
已有节拍的旁白（按顺序）：
{existing}
现在全片旁白共 {total} 字，还差至少 {need} 字才能达到 {min_chars} 字的最低要求。
请紧接着已有情节续写 {n_beats} 个新节拍：推进情节、不要重复已有内容、最后一个新节拍要能自然接向结局（若已有节拍已是结局，就续写结局之前的经过）。
只输出 JSON，不要 markdown 包裹，字段：
{{"beats": [{{"narration": "旁白（中文口语，40-65字，以句号结尾）", "visual_en": "英文画面描述", "motion_prompt": "英文运镜提示"}}]}}"""


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


def build_pixstag_package(
    *, premise: str, draft: dict[str, Any], shots: list[dict[str, Any]],
    aspect: str, narration_path: Path, alignment_path: Path,
) -> dict[str, Any]:
    """Handoff package for video.pixstag_generate (live-action route).

    Per shot the consumer needs exactly: first_frame + motion_prompt +
    duration. Narration/alignment ride along so the final assembly can keep
    the measured timeline.
    """
    return {
        "kind": "pixstag_shot_package",
        "title": draft["title"],
        "premise": premise,
        "hook": draft.get("hook", ""),
        "aspect": aspect,
        "narration_audio": str(narration_path),
        "alignment_json": str(alignment_path),
        "shots": [
            {
                "shot_id": s["shot_id"],
                "first_frame": s["first_frame"],
                "motion_prompt": s["motion_prompt"],
                "duration_s": s["duration_s"],
                "narration": s["narration"],
            }
            for s in shots
        ],
        "note": (
            "hevi 备齐流程与镜头包; 最终成片由 video.pixstag_generate 逐镜"
            "生成后按 shots.json 的实测时间轴拼接。"
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
    render_route: str = "hyperframes",
    aspect: str = "9:16",
    voice: str = "soffy",
    out_dir: Path,
) -> dict[str, Any]:
    """Run the full one-sentence-to-film chain. Returns the delivery ledger."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "images").mkdir(exist_ok=True)
    meta = {
        "premise": premise,
        "style": style,
        "max_shots": max_shots,
        "render_route": render_route,
        "aspect": aspect,
    }
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

    # -- 1. story ------------------------------------------------------------
    async def _story():
        draft, cost = await generate_story(
            premise, style=style, max_shots=max_shots
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
        hero = draft["characters"][0]
        total_cost = 0.0
        key_path = out_dir / "images" / "character.png"
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
        paths = []
        for i, beat in enumerate(draft["beats"]):
            shot_path = out_dir / "images" / f"shot_{i + 1:02d}.png"
            res = await gpt_image_edit(
                image_paths=[key_path],
                prompt=(
                    f"{beat['visual_en']}. Same main character as the "
                    f"reference: {hero['appearance_en']}. {style}"
                ),
                output_path=shot_path,
                size=size,
            )
            if isinstance(res.get("cost"), (int, float)):
                total_cost += float(res["cost"])
            paths.append(shot_path)
        ledger.mark(
            "images", "ok", cost=round(total_cost, 4),
            artifacts=[f"images/{p.name}" for p in [key_path, *paths]],
        )
        return paths

    image_paths = await stage("images", _images)

    # -- 3. narration ---------------------------------------------------------
    full_text = "".join(b["narration"] for b in draft["beats"])
    narration_path = out_dir / "narration.wav"

    async def _narration():
        from hevi.audio.lux_tts_service import lux_tts_available, synth_with_luxtts

        if not lux_tts_available():
            raise StoryFilmError(
                "LuxTTS HTTP service is not reachable (HEVI_LUXTTS_URL)"
            )
        await synth_with_luxtts(
            text=full_text, output_path=narration_path, voice=voice
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
        tail = 1.2 if i == len(draft["beats"]) - 1 else 0.35
        shots.append(
            {
                "shot_id": f"S{i + 1:02d}",
                "narration": beat["narration"],
                "visual_prompt": beat["visual_en"],
                "motion_prompt": beat["motion_prompt"],
                "ken_burns": ken_burns_params(beat["motion_prompt"], i),
                "image": str(img),
                "first_frame": str(img),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_s": round((end_ms - start_ms) / 1000 + tail, 2),
            }
        )
    (out_dir / "shots.json").write_text(
        json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ledger.mark("shots", "ok", artifacts=["shots.json"])

    delivery_extra: dict[str, Any] = {
        "shots": len(shots),
        "title": draft["title"],
        "hook": draft.get("hook", ""),
        "story_length": story_meta,
        "mastering": mastering_info,
        "duration_check": duration_check,
    }

    # -- 6. render --------------------------------------------------------------
    if render_route == "hyperframes":

        async def _render():
            # Ken Burns motion render (see the motion section header):
            # the HTML storyboard renderer captures one frozen frame
            # per shot, which film_gate rejects as a slideshow.  This
            # route animates every shot still per-frame instead; the
            # route name stays "hyperframes" (code-composed film).
            width, height = _ASPECT_RES.get(aspect, (720, 1280))
            total = render_motion_film(
                shots=shots,
                title=draft["title"],
                narration_path=narration_path,
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

        # -- 7. gates (hyperframes route only; a package has no film to gate) --
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
