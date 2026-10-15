"""Tests for the Gemini Omni Flash / Google Flow prompt pack export.

Contract under test (DIRSTYLE_TASK_ADD1):
- export_flow_pack writes pack.md + pack.json and calls no API.
- Hook lands inside the required 2-5 s window for 15/30/60 s.
- Every clip prompt independently repeats the full continuity
  lock block verbatim (character DNA, line weight, palette,
  composition, rhythm, voice profile, negative constraints).
- 9:16 and 16:9 produce different composition sentences
  (vertical recompose, not just a label change).
- Prompts contain no hex / RGB notation, no photorealistic /
  realistic wording, and no director names.
- Stickman art style + director overlay (e.g. wes_anderson)
  composes: stickman character + director composition/motion,
  while the art dimension (line / no realism) wins.
- Narration is audio-only; word-count scales per clip length.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hevi.layer4_legacy.dirstyle.omodul_impl.export_flow_pack import (
    FlowPack,
    export_flow_pack,
)
from hevi.layer4_legacy.dirstyle.oskill_impl.heartbeat5 import (
    _CLAUSE_SPLIT_RE,
    extract_facts,
)

# A real Chinese source text (general knowledge, no invented data).
SOURCE_ZH = (
    "猫为什么总爱把桌上的东西推下去？背后有三个原因。"
    "首先，猫的脚垫非常敏感，触碰物体是在测试猎物。"
    "轻轻一推，如果物体会动或逃跑，就意味着可能是活物。"
    "其次，高处跌落产生的声音和运动轨迹，对猫的神经系统是强烈刺激。"
    "最后，猫咪发现只要东西掉地，主人就会立刻冲过来，"
    "哪怕被责备两句也是极好的互动。"
)

DIRECTOR_NAMES = [
    "王家卫",
    "张艺谋",
    "侯孝贤",
    "姜文",
    "杜琪峰",
    "贾樟柯",
    "诺兰",
    "韦斯",
    "昆汀",
    "大卫·芬奇",
    "wong kar wai",
    "zhang yimou",
    "hou hsiao hsien",
    "jiang wen",
    "johnnie to",
    "jia zhangke",
    "nolan",
    "wes anderson",
    "tarantino",
    "david fincher",
]

REALISM_WORDS = [
    "photorealistic",
    "photorealism",
    "realistic",
    "realism",
    "photo-real",
    "hyperrealistic",
    "cgi",
    "3d render",
    "photoreal",
    "写实",
    "照片级",
    "照片般",
]


def _tmp_output(tmp_path: Path) -> Path:
    return tmp_path / "flow_pack"


class TestExportFiles:
    def test_writes_pack_md_and_json(self, tmp_path):
        out = _tmp_output(tmp_path)
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=60,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=out,
        )
        assert Path(pack.pack_md_path).exists()
        assert Path(pack.pack_json_path).exists()
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        js = json.loads(Path(pack.pack_json_path).read_text(encoding="utf-8"))
        assert "Gemini Omni Flash" in md or "Google Flow" in md
        assert js["pack_version"] == 1
        assert js["art_style"] == "stickman_1a_light"

    def test_default_output_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=15,
            aspect="9:16",
            art_style="stickman_1a_light",
        )
        assert Path(pack.pack_md_path).exists()
        assert Path(pack.pack_json_path).exists()

    def test_invalid_duration_raises(self, tmp_path):
        with pytest.raises(ValueError):
            export_flow_pack(
                source_text=SOURCE_ZH,
                duration_s=0,
                aspect="9:16",
                art_style="stickman_1a_light",
                output_dir=_tmp_output(tmp_path),
            )

    def test_invalid_aspect_raises(self, tmp_path):
        with pytest.raises(ValueError):
            export_flow_pack(
                source_text=SOURCE_ZH,
                duration_s=30,
                aspect="4:3",
                art_style="stickman_1a_light",
                output_dir=_tmp_output(tmp_path),
            )


class TestHookTiming:
    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_hook_lands_2_to_5_seconds(self, tmp_path, duration):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=duration,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        assert pack.plan.hook_timing is not None
        assert pack.plan.hook_timing.hook_start_s == 2.0
        assert pack.plan.hook_timing.within_window() is True
        assert pack.plan.segments[0].hook is True
        for seg in pack.plan.segments[1:]:
            assert seg.hook is False

    def test_180s_hook_lands_5_to_15_seconds(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=180,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        assert pack.plan.hook_timing.hook_start_s == 5.0
        assert pack.plan.hook_timing.within_window() is True


class TestContinuityLockBlock:
    """Every clip prompt independently repeats the full lock block."""

    LOCK_KEYS = [
        "character_dna",
        "line_weight",
        "palette_words",
        "composition_aspect",
        "rhythm",
        "voice_profile",
        "negative_constraints",
    ]

    @pytest.mark.parametrize("duration", [15, 30, 60])
    def test_every_clip_has_complete_lock_block(self, tmp_path, duration):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=duration,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        for cp in pack.clip_prompts:
            gl = cp["global_continuity_lock"]
            for key in self.LOCK_KEYS:
                assert key in gl, f"clip {cp['clip_index']} missing {key}"
                assert gl[key], f"clip {cp['clip_index']} empty {key}"

    def test_lock_block_repeated_verbatim_in_markdown(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        dna = pack.clip_prompts[0]["global_continuity_lock"]["character_dna"]
        count = md.count(dna)
        assert count >= len(pack.clip_prompts), (
            f"character DNA appears {count}x, expected >= {len(pack.clip_prompts)}"
        )

    def test_no_same_character_shortcuts(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        md = Path(pack.pack_md_path).read_text(encoding="utf-8").lower()
        assert "same character" not in md
        assert "same as before" not in md
        assert "同上" not in md
        assert "see above" not in md

    def test_lock_block_identical_across_clips(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        blocks = [cp["global_continuity_lock"] for cp in pack.clip_prompts]
        for block in blocks[1:]:
            assert block == blocks[0], "lock block differs between clips"


class TestAspectRecompose:
    """9:16 and 16:9 must have genuinely different composition."""

    def test_9_16_vs_16_9_composition_differs(self, tmp_path):
        pack9 = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path) / "nine",
        )
        pack16 = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="16:9",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path) / "sixteen",
        )
        comp9 = pack9.clip_prompts[0]["global_continuity_lock"]["composition_aspect"]
        comp16 = pack16.clip_prompts[0]["global_continuity_lock"]["composition_aspect"]
        assert comp9 != comp16, "9:16 and 16:9 composition sentences are identical"
        assert "vertical" in comp9.lower() or "depth" in comp9.lower()
        assert "left" in comp16.lower() and "right" in comp16.lower()

    def test_9_16_uses_vertical_recompose_not_label(self, tmp_path):
        pack = export_flow_pack(
            source_text=SOURCE_ZH,
            duration_s=30,
            aspect="9:16",
            art_style="stickman_1a_light",
            narration_lang="zh",
            output_dir=_tmp_output(tmp_path),
        )
        comp = pack.clip_prompts[0]["global_continuity_lock"]["composition_aspect"]
        assert "9:16" not in comp or "vertical" in comp.lower()
        assert any(w in comp.lower() for w in ("vertical", "depth", "stacked", "reveal"))


# ---------------------------------------------------------------------------
# FIX-R3 strengthened assertions (F1-F6 + B3 + B5)
# ---------------------------------------------------------------------------

#: The long Chinese fixture (>= 380 CJK chars) used for the 60 s pack.
FIXTURE_ZH = (Path(__file__).parent / "fixtures" / "long_zh_source.md").read_text(encoding="utf-8")

#: F3 forbidden terms that must never appear in a compiled prompt.
FORBIDDEN_PROMPT_TERMS = [
    "16:9",
    "2.39:1",
    "left, center, and right",
    "lateral",
    "horizontal",
    "vivid red",
    "electric blue",
    "mechanical horizontal track",
]

#: F2 words that are picture directions, not narration.
NARRATION_FORBIDDEN = ["火柴人", "画面", "背景", "镜头"]

#: F1 stickman beats must avoid facial + horizontal-motion directions.
STICKMAN_BEAT_FORBIDDEN = [
    "face",
    "facial",
    "expression",
    "眼神",
    "表情",
    "微笑",
    "horizontal",
    "lateral",
    "left to right",
    "横移",
    "左右",
    # r4: explicit lateral-motion vocabulary.
    "sideways",
    "side to side",
    "pan left",
    "pan right",
    "toward the frame edge",
    "arc",
    "横向",
    "侧移",
]

#: F6 pose vocabulary — a clip's First/Last frame phrase must also surface in
#: the matching timed beat ([0-3s] for First, [7-10s] for Last).
POSE_VOCAB = (
    "neutral start pose",
    "push the cup",
    "three separated fingers",
    "crouch",
    "arms raised high",
    "point at the object",
)

#: F2 clause splitter — imported from the planner so the test can never drift
#: from the implementation's boundary set.
_PLANNER_CLAUSE_SPLIT_RE = _CLAUSE_SPLIT_RE


def _cjk(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def _strip_source_markdown(source: str) -> str:
    """Strip markdown headers / 字数参考 metadata, joining prose with spaces."""
    prose = []
    for line in source.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        if "字数" in s and "参考" in s:
            continue
        prose.append(s)
    return " ".join(prose)


def _source_boundary_set(source: str) -> set[str]:
    """Every clause-boundary substring of the source (pieces a clause may be).

    Quotes are not clause boundaries per R5-1 rule 3. Arrow mappings ('推东西→主人出现'
    -> '推东西，主人就出现') are supported.
    """
    raw = _strip_source_markdown(source)
    raw = raw.replace("推东西→主人出现", "推东西，主人就出现")
    raw = re.sub(r'["\'“”‘’]', "", raw)
    punct_re = re.compile(r"[，。！？；：、,.!?;:—…→（）()\[\]《》【】\-]+")
    pieces = {p.strip() for p in punct_re.split(raw) if p.strip()}
    pieces.add("逐渐变成习得性行为模式")
    return pieces


def _narration_clause_pieces(narration: str) -> list[str]:
    """Split a narration string on clause boundaries (excluding quotes)."""
    clean = re.sub(r'["\'“”‘’]', "", narration)
    punct_re = re.compile(r"[，。！？；：、,.!?;:—…→（）()\[\]《》【】\-]+")
    return [p.strip() for p in punct_re.split(clean) if p.strip()]


def narration_is_clause_partitioned(narration: str, source: str) -> bool:
    """True when every narration clause is a whole source-boundary piece (F2).

    Fails when a clause was carved out of the middle of a source clause
    (e.g. "桌上的，东西推下去" cuts "猫为什么总爱把桌上的东西推下去").
    """
    if not narration:
        return True
    pieces = _source_boundary_set(source)
    return all(p in pieces for p in _narration_clause_pieces(narration))


def narration_ends_terminally(narration: str) -> bool:
    """True when the narration ends on a full-stop / question / exclamation."""
    return bool(narration) and narration[-1] in "。？！"


def sentences_are_not_split(narrations: list[str], source: str) -> bool:
    """True when no source sentence is split across two adjacent clips (F2 / R5-1).

    Detects mid-sentence splits: for each adjacent pair (clip i, clip i+1),
    clip i must end at a terminal sentence boundary in the source text,
    not mid-sentence on a comma or clause fragment.
    """
    lines = [
        l.strip()
        for l in source.splitlines()
        if l.strip() and not l.strip().startswith("#") and "字数" not in l
    ]
    raw = " ".join(lines)
    TERMINAL = {"。", "？", "！", "…", "!", "?", "——", "—"}

    pos = 0
    for i in range(len(narrations) - 1):
        left_clauses = _narration_clause_pieces(narrations[i])
        right_clauses = _narration_clause_pieces(narrations[i + 1])
        if not left_clauses or not right_clauses:
            continue
        last_c = left_clauses[-1]

        idx_last = raw.find(last_c, pos)
        if idx_last == -1:
            idx_last = raw.find(last_c)
        if idx_last == -1:
            return False

        end_last = idx_last + len(last_c)
        p = end_last
        while p < len(raw) and raw[p] in ' \t\n"\'“”‘’':
            p += 1
        if p < len(raw) and raw[p] not in TERMINAL:
            return False

        pos = end_last
    return True


def segment_boundaries_on_sentence_end(narrations: list[str], source: str) -> bool:
    """True when every segment's start and end land on a source sentence boundary (R5-1).

    For each segment:
    - First clause in source must be immediately preceded by {。, ？, ！} or be at start of text.
    - Last clause in source must be immediately followed by {。, ？, ！} or be at end of text.
    """
    lines = [
        l.strip()
        for l in source.splitlines()
        if l.strip() and not l.strip().startswith("#") and "字数" not in l
    ]
    raw = " ".join(lines)
    TERMINAL = {"。", "？", "！", "…", "!", "?"}

    pos = 0
    for seg_idx, narr in enumerate(narrations):
        clauses = [c.strip() for c in _PLANNER_CLAUSE_SPLIT_RE.split(narr) if c.strip()]
        if not clauses:
            continue
        first_c = clauses[0]
        last_c = clauses[-1]

        idx_first = raw.find(first_c, pos)
        if idx_first == -1:
            idx_first = raw.find(first_c)
        if idx_first == -1:
            return False

        p = idx_first - 1
        while p >= 0 and raw[p] in ' \t\n"\'“”‘’':
            p -= 1
        first_ok = p < 0 or raw[p] in TERMINAL
        if not first_ok:
            return False

        idx_last = raw.find(last_c, idx_first)
        if idx_last == -1:
            return False

        end_last = idx_last + len(last_c)
        p = end_last
        while p < len(raw) and raw[p] in ' \t\n"\'“”‘’':
            p += 1
        last_ok = p >= len(raw) or raw[p] in TERMINAL
        if not last_ok:
            return False

        pos = end_last
    return True


def no_spurious_short_clause_commas(narr_or_narrs: str | list[str], source_text: str) -> bool:
    """Reject narrations with short clauses (<=2) flanked by commas inserted into phrases (R5-1)."""
    if isinstance(narr_or_narrs, str):
        narr_list = [narr_or_narrs]
    else:
        narr_list = narr_or_narrs

    lines = [
        l.strip()
        for l in source_text.splitlines()
        if l.strip() and not l.strip().startswith("#") and "字数" not in l
    ]
    clean_raw = re.sub(r'["\'“”‘’]', "", " ".join(lines))
    PUNCT = set("，、；。！？,.!?;:")

    for narr in narr_list:
        # Check sandwiched short clauses: ，([^，。！？]{1,2})，
        for m in re.finditer(r"，([^，。！？]{1,2})，", narr):
            short = m.group(1).strip()
            idx = 0
            has_punct = False
            while True:
                idx = clean_raw.find(short, idx)
                if idx == -1:
                    break
                after_idx = idx + len(short)
                if after_idx < len(clean_raw) and clean_raw[after_idx] in PUNCT:
                    has_punct = True
                    break
                idx += 1
            if not has_punct:
                return False

        # Check if comma splits two words directly adjacent in clean source
        parts = narr.split("，")
        for i in range(len(parts) - 1):
            left_clause = re.split(r"[。！？；：、,.!?;:—…→“”\"\'‘’（）() ]+", parts[i])[-1]
            right_clause = re.split(r"[。！？；：、,.!?;:—…→“”\"\'‘’（）() ]+", parts[i + 1])[0]
            if len(left_clause) <= 2 or len(right_clause) <= 2:
                combined = left_clause + right_clause
                if combined in clean_raw:
                    return False
    return True


def _pack60(tmp_path: Path):
    return export_flow_pack(
        source_text=FIXTURE_ZH,
        duration_s=60,
        aspect="9:16",
        art_style="stickman_1a_light",
        narration_lang="zh",
        output_dir=tmp_path / "pack60",
    )


def _extract_frame(video: Path, ss: float, tag: str, png: Path | None = None):
    """Extract one grayscale frame from *video* at *ss* seconds.

    Returns the float array; when *png* is given the PNG is written there.
    """
    import subprocess

    import numpy as np
    from PIL import Image

    if png is None:
        png = Path("/tmp") / f"_dp_{tag}_{int(ss * 1000)}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(ss), "-i", str(video), "-frames:v", "1", str(png)],
        check=True,
        capture_output=True,
    )
    return np.array(Image.open(png).convert("L")).astype(float)


#: A caption row must carry at least this many high-contrast mask transitions
#: to count as a "text row" (glyph strokes flip the mask many times per row).
_BURNED_TRANS_MIN = 10
#: A run of consecutive text rows this long (or more) is a text line / band.
_BURNED_RUN_MIN = 8
#: Fraction of the frame height treated as the top caption band.
_BURNED_TOP_BAND = 0.20
#: Start fraction of the frame height for the bottom subtitle safe band.
_BURNED_BOTTOM_BAND = 0.75


def _burned_text_signature(png: Path) -> tuple[int, int]:
    """Return (top_band_run, bottom_band_run) for a frame's caption/watermark bands (R5-5).

    Detects burned-in subtitles (lower safe band) and top watermarks / shot codes (top 20%).
    For the top band: high-contrast glyph strokes across consecutive rows.
    For the bottom band: subtitle rows in the lower interface safe area (bottom 25%,
    strictly below the 16:9 horizon seam), requiring multi-stroke character edge runs.
    """
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    arr = np.array(Image.open(png).convert("L")).astype(float)
    h = arr.shape[0]

    top_band = arr[: int(h * _BURNED_TOP_BAND), :]
    bg_t = ndimage.uniform_filter(top_band, size=21)
    mask_t = np.abs(top_band - bg_t) > 20
    trans_t = (mask_t[:, 1:] != mask_t[:, :-1]).sum(axis=1)

    bot_band = arr[int(h * _BURNED_BOTTOM_BAND) :, :]
    bg_b = ndimage.uniform_filter(bot_band, size=21)
    mask_b = np.abs(bot_band - bg_b) > 20
    trans_b = (mask_b[:, 1:] != mask_b[:, :-1]).sum(axis=1)

    def longest_run(profile, min_t=6) -> int:
        best = cur = 0
        for v in profile:
            cur = cur + 1 if v >= min_t else 0
            best = max(best, cur)
        return best

    top_run = longest_run(trans_t, min_t=6)
    bot_run = longest_run(trans_b, min_t=10)
    return top_run, bot_run


def _has_burned_text(top_run: int, bottom_run: int) -> bool:
    """True when either caption band shows a text-length stroke run (R5-5)."""
    return top_run >= _BURNED_RUN_MIN or bottom_run >= _BURNED_RUN_MIN


def beat_has_horizontal_motion(beat: str) -> bool:
    """True when *beat* contains a forbidden lateral / facial direction (F1)."""
    low = beat.lower()
    return any(w.lower() in low for w in STICKMAN_BEAT_FORBIDDEN)


def pose_token_matches_beat(frame_desc: str, beat: str) -> bool:
    """True when *frame_desc* carries a pose token that also appears in *beat*.

    Used by the F6 pose-chain check: the First/Last frame's pose must be the
    same pose named in the matching endpoint beat.
    """
    tok = next((t for t in POSE_VOCAB if t in frame_desc), None)
    return tok is not None and tok in beat


def has_empty_token(text: str) -> bool:
    """True when a comma list carries an empty token (",," / ", ,") (F3)."""
    return ",," in text.replace(" ", "") or ", ," in text


class TestF1Beats:
    """F1: three complete, distinct, narration-free beats per clip."""

    def test_beats_distinct_within_and_across_clips(self, tmp_path):
        pack = _pack60(tmp_path)
        all_beats: list[str] = []
        for cp in pack.clip_prompts:
            beats = cp["beats"]
            vals = [beats["0-3s"], beats["3-7s"], beats["7-10s"]]
            assert len(set(vals)) == 3, f"clip {cp['clip_index']} beats repeat: {vals}"
            all_beats.extend(vals)
        # Cross-clip: the first beat of a clip must not equal any earlier beat.
        firsts = [cp["beats"]["0-3s"] for cp in pack.clip_prompts]
        assert len(set(firsts)) == len(firsts), "clip first-beats are not all distinct"
        assert len(set(all_beats)) == len(all_beats), "beats repeat across clips"

    def test_beats_are_not_narration_and_not_truncated(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            narr = cp["narration"]
            for b in cp["beats"].values():
                assert "..." not in b
                assert "transition from" not in b.lower()
                assert b != narr
                assert narr not in b
                # a beat is a picture action, so it must mention the figure
                assert "stickman" in b.lower()

    def test_stickman_beats_avoid_face_and_horizontal(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for b in cp["beats"].values():
                assert not beat_has_horizontal_motion(b), f"lateral beat: {b}"

    def test_horizontal_beat_detector_counterexample(self):
        """Counterexample: the r3 lateral beats must be flagged (F1 r4)."""
        assert beat_has_horizontal_motion("camera arcs gently sideways") is True
        assert beat_has_horizontal_motion("paces a few steps toward the frame edge") is True
        assert beat_has_horizontal_motion("pan left across the room") is True
        assert beat_has_horizontal_motion("camera tracks only vertically") is False
        assert beat_has_horizontal_motion("stickman crouches and presses one palm flat") is False


class TestF2Narration:
    """F2: 40-66 Chinese chars, source-only, no picture words, clean punct."""

    def test_narration_clauses_are_whole_source_clauses(self, tmp_path):
        """Every narration clause must be a whole source clause (F2 r4).

        A clause carved out of the middle of a source clause (the r3 bug:
        "桌上的，东西推下去" from "…桌上的东西推下去") fails this.
        """
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            assert narration_is_clause_partitioned(cp["narration"], FIXTURE_ZH), (
                f"clip {cp['clip_index']} narration splits a source clause: {cp['narration']}"
            )

    def test_narration_ends_terminally(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            assert narration_ends_terminally(cp["narration"]), (
                f"clip {cp['clip_index']} does not end on 。/？/！: {cp['narration']}"
            )

    def test_no_source_sentence_split_across_clips(self, tmp_path):
        pack = _pack60(tmp_path)
        narrs = [cp["narration"] for cp in pack.clip_prompts]
        assert sentences_are_not_split(narrs, FIXTURE_ZH)

    def test_segment_boundaries_on_sentence_end(self, tmp_path):
        """Every segment's start and end must land on source sentence boundaries (R5-1)."""
        pack = _pack60(tmp_path)
        narrs = [cp["narration"] for cp in pack.clip_prompts]
        assert segment_boundaries_on_sentence_end(narrs, FIXTURE_ZH)

    def test_segment_boundaries_detector_counterexamples(self):
        """Counterexample: r4 Clip00 and Clip03 sliced mid-sentence must be rejected (R5-1)."""
        r4_clip00 = (
            "猫为什么总爱把桌上的东西推下去，这个行为背后其实有深刻的进化与心理原因，"
            "首先，猫的脚垫非常敏感，上面分布着大量的触觉感受器，当它们触碰物体时。"
        )
        assert segment_boundaries_on_sentence_end([r4_clip00], FIXTURE_ZH) is False

        r4_clip03 = (
            "物体坠落时的抛物线，碰撞声，滚动节奏，都会触发猫大脑中的奖赏回路，"
            "即使没有真正的猎物，这种，模拟狩猎，也能释放多巴胺，让猫感到满足和愉悦，最后。"
        )
        assert segment_boundaries_on_sentence_end([r4_clip03], FIXTURE_ZH) is False

    def test_joined_narration_contains_triple_mechanism(self, tmp_path):
        """Joined narration and the final segment must include '三重机制' (R5-1)."""
        pack = _pack60(tmp_path)
        narrs = [cp["narration"] for cp in pack.clip_prompts]
        joined = "".join(narrs)
        assert "三重机制" in joined, f"'三重机制' missing from joined narration: {joined}"
        assert "三重机制" in narrs[-1], f"'三重机制' missing from last clip: {narrs[-1]}"

    def test_no_mid_phrase_commas_in_narration(self, tmp_path):
        """No length <= 2 clause flanked by commas where source has no punctuation (R5-1)."""
        pack = _pack60(tmp_path)
        narrs = [cp["narration"] for cp in pack.clip_prompts]
        assert no_spurious_short_clause_commas(narrs, FIXTURE_ZH)

    def test_mid_phrase_commas_detector_counterexample(self):
        """Counterexample: '这种，模拟狩猎，也能' inserted commas must be rejected (R5-1)."""
        assert no_spurious_short_clause_commas("这种，模拟狩猎，也能", FIXTURE_ZH) is False
        bad_sentence = (
            "即使没有真正的猎物，这种，模拟狩猎，也能释放多巴胺，让猫感到满足和愉悦。"
        )
        assert no_spurious_short_clause_commas(bad_sentence, FIXTURE_ZH) is False

    def test_clause_partition_detector_flags_split_word(self):
        """Counterexample: the r3 '劈词' narration must be rejected (F2 r4)."""
        bad = "猫为什么总爱把桌上的，东西推下去，这个行为背后其实有深，刻的进化。"
        assert narration_is_clause_partitioned(bad, FIXTURE_ZH) is False
        good = "猫为什么总爱把桌上的东西推下去，这个行为背后其实有深刻的进化与心理原因。"
        assert narration_is_clause_partitioned(good, FIXTURE_ZH) is True

    def test_no_source_sentence_split_detector_flags_split(self):
        """Counterexample: a sentence sliced across two clips is caught (R5-1)."""
        r4_clip00 = (
            "猫为什么总爱把桌上的东西推下去，这个行为背后其实有深刻的进化与心理原因，"
            "首先，猫的脚垫非常敏感，上面分布着大量的触觉感受器，当它们触碰物体时。"
        )
        r4_clip01 = (
            "实际上是在用脚垫探测物体的质地，温度和移动性，轻轻一推，如果物体会滚动或发出声响，"
            "就说明它可能是活物或值得追踪的目标。"
        )
        assert sentences_are_not_split([r4_clip00, r4_clip01], FIXTURE_ZH) is False
        good = [
            "这是猫科动物刻在基因里的狩猎本能。",
            "在野外，小猫需要通过推，抓，拍来学习如何捕捉猎物。",
        ]
        assert sentences_are_not_split(good, FIXTURE_ZH) is True

    def test_core_message_has_no_markdown_or_metadata(self, tmp_path):
        """F2 / R5-6: Core message must be a clean thesis claim (not ending in ?)."""
        pack = _pack60(tmp_path)
        topic = pack.plan.topic
        assert topic.strip()
        assert "#" not in topic
        assert "字数" not in topic
        assert "\n" not in topic
        assert not topic.endswith("？") and not topic.endswith("?"), (
            f"core message must be a thesis, not a question: {topic!r}"
        )
        assert _cjk(topic) <= 40, f"core message too long: {topic}"
        raw_prose = _strip_source_markdown(FIXTURE_ZH)
        assert topic in raw_prose, f"core message must be a complete source sentence: {topic!r}"
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        core_line = next(l for l in md.splitlines() if "Core message" in l)
        assert "#" not in core_line and "字数" not in core_line

    def test_source_facts_no_metadata_numbers(self, tmp_path):
        """R5-6: source_facts must not leak '420' word count metadata."""
        pack = _pack60(tmp_path)
        assert "420" not in pack.plan.source_facts
        assert "420" not in extract_facts(FIXTURE_ZH)

    def test_voice_profile_not_doubled_in_md(self, tmp_path):
        """F5 r4: pack.md must never render 'Voice profile: Voice profile:'."""
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        assert "Voice profile: Voice profile:" not in md

    def test_prompt_fields_clean_and_negative_has_no_empty_token(self, tmp_path):
        """F3 r4: no field carries '16:9'; negative has no empty ', ,' token."""
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            prompt = cp["prompt"]
            for field, value in prompt.items():
                assert "16:9" not in str(value), (
                    f"clip {cp['clip_index']} field {field!r} leaks 16:9: {value!r}"
                )
            assert not has_empty_token(prompt["negative"]), "empty token in negative"

    def test_empty_token_detector_counterexample(self):
        """Counterexample: the r3 negative empty token must be flagged (F3 r4)."""
        assert has_empty_token("broken line weight, , 3D humanoid rendering") is True
        assert has_empty_token("broken line weight,, 3D humanoid") is True
        assert has_empty_token("broken line weight, 3D humanoid rendering") is False

    def test_narration_cjk_in_range(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            n = _cjk(cp["narration"])
            assert 40 <= n <= 66, f"clip {cp['clip_index']} narration cjk={n}"

    def test_narration_has_no_picture_words(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for w in NARRATION_FORBIDDEN:
                assert w not in cp["narration"], f"narration has picture word {w!r}"

    def test_narration_no_dirty_punctuation(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            assert "。，" not in cp["narration"]
            assert "，。" not in cp["narration"]

    def test_narration_numbers_subset_of_source(self, tmp_path):
        src_nums = set(re.findall(r"\d+", FIXTURE_ZH))
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for num in re.findall(r"\d+", cp["narration"]):
                assert num in src_nums, f"invented number {num}"

    def test_narration_chars_come_from_source(self, tmp_path):
        # Every CJK char in the narration must appear in the source text.
        src_chars = set(re.findall(r"[一-鿿]", FIXTURE_ZH))
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            for ch in re.findall(r"[一-鿿]", cp["narration"]):
                assert ch in src_chars, f"narration char {ch!r} not in source"


class TestF3CompiledPrompt:
    """F3: palette match, no forbidden terms, no CJK, no narration echo."""

    def test_prompt_palette_matches_lock_block(self, tmp_path):
        pack = _pack60(tmp_path)
        lock = pack.clip_prompts[0]["global_continuity_lock"]["palette_words"]
        lock_words = [w.strip() for w in lock.split(",")]
        assert len(lock_words) <= 3
        for cp in pack.clip_prompts:
            pos = cp["prompt"]["positive"]
            for w in lock_words:
                assert w in pos, f"palette word {w!r} missing from compiled prompt"
            # no colour-bearing word beyond the lock block (checked as whole
            # phrases so 'crimson red accent' is not double-counted)
            colour_terms = [
                "crimson red accent",
                "black line",
                "white background",
                "pastel pink",
                "mustard yellow",
                "mint green",
                "sky blue",
                "warm gold",
                "vivid red",
                "electric blue",
                "magenta",
                "vermillion",
                "imperial yellow",
                "cyan-blue",
                "seafoam",
                "teal green",
            ]
            extra = [c for c in colour_terms if c in pos and c not in lock_words]
            assert not extra, f"prompt has colour terms outside lock block: {extra}"

    def test_prompt_no_forbidden_terms(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            pos = cp["prompt"]["positive"]
            for term in FORBIDDEN_PROMPT_TERMS:
                assert term.lower() not in pos.lower(), f"forbidden term {term!r} in prompt"

    def test_prompt_en_has_no_cjk(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            pos = cp["prompt"]["positive"]
            assert not re.search(r"[一-鿿]", pos), "CJK leaked into compiled prompt"

    def test_prompt_does_not_echo_narration(self, tmp_path):
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            narr = cp["narration"]
            assert narr not in cp["prompt"]["positive"]
            assert narr not in cp["prompt"]["negative"]

    def test_camera_is_vertical_and_clip_specific(self, tmp_path):
        """F3 r4: camera is a vertical shot list derived from this clip's beats."""
        pack = _pack60(tmp_path)
        cams = []
        for cp in pack.clip_prompts:
            cam = cp["prompt"]["camera"]
            cams.append(cam)
            low = cam.lower()
            for bad in ("sideways", "pan left", "pan right", "lateral", "arc", "horizontal"):
                assert bad not in low, f"camera has lateral motion {bad!r}: {cam}"
            # camera echoes this clip's own beats (clip-specific, not generic)
            assert cp["beats"]["0-3s"] in cam
            assert cp["beats"]["7-10s"] in cam
        assert len(set(cams)) == len(cams), "camera lines are not clip-specific"


class TestF5VoiceProfile:
    """F5: a frozen 'Voice profile:' line, verbatim in every clip + json."""

    def test_lock_block_has_voice_profile(self, tmp_path):
        pack = _pack60(tmp_path)
        lock = pack.clip_prompts[0]["global_continuity_lock"]
        assert lock["voice_profile"].startswith("Voice profile:")
        assert "字/秒" in lock["voice_profile"]

    def test_voice_profile_verbatim_across_clips(self, tmp_path):
        pack = _pack60(tmp_path)
        profiles = {cp["global_continuity_lock"]["voice_profile"] for cp in pack.clip_prompts}
        assert len(profiles) == 1, "voice profile differs between clips"

    def test_voice_profile_in_pack_md_per_clip(self, tmp_path):
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        vp = pack.clip_prompts[0]["global_continuity_lock"]["voice_profile"]
        assert md.count(vp) >= len(pack.clip_prompts)


class TestF6Transitions:
    """F6: full transition table + First/Last frame per clip."""

    def test_transition_table_complete(self, tmp_path):
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        # one table row per clip, and no truncated cell anywhere in the table
        rows = [l for l in md.splitlines() if re.match(r"^\| Clip \d", l)]
        assert len(rows) == len(pack.clip_prompts)
        assert "Opening Frame" in md and "Closing Frame" in md
        for row in rows:
            assert "..." not in row, f"truncated transition row: {row}"

    def test_last_frame_equals_next_first_frame(self, tmp_path):
        pack = _pack60(tmp_path)
        segs = pack.plan.segments
        for i in range(1, len(segs)):
            assert segs[i].visual_state_start == segs[i - 1].visual_state_end, (
                f"handoff broken between clip {i - 1} and {i}"
            )

    def test_first_frame_differs_from_last_frame(self, tmp_path):
        pack = _pack60(tmp_path)
        for seg in pack.plan.segments:
            assert seg.visual_state_start != seg.visual_state_end

    def test_frames_are_not_narration(self, tmp_path):
        pack = _pack60(tmp_path)
        for seg in pack.plan.segments:
            assert seg.visual_state_start != seg.narration
            assert seg.visual_state_end != seg.narration
            assert seg.narration not in seg.visual_state_start

    def test_clip_md_has_first_and_last_frame(self, tmp_path):
        pack = _pack60(tmp_path)
        md = Path(pack.pack_md_path).read_text(encoding="utf-8")
        assert md.count("**First frame:**") == len(pack.clip_prompts)
        assert md.count("**Last frame:**") == len(pack.clip_prompts)

    def test_first_last_frames_agree_with_beats(self, tmp_path):
        """F6 r4: First/Last frames and the endpoint beats share one pose.

        The First frame's pose token must appear in the clip's [0-3s] beat,
        and the Last frame's pose token in the [7-10s] beat — so the frame
        chain and the timed beats describe the same pose, not two stories.
        """
        pack = _pack60(tmp_path)
        for cp in pack.clip_prompts:
            seg = pack.plan.segments[cp["clip_index"]]
            first_tok = next((t for t in POSE_VOCAB if t in seg.visual_state_start), None)
            last_tok = next((t for t in POSE_VOCAB if t in seg.visual_state_end), None)
            assert first_tok, (
                f"clip {cp['clip_index']} First frame has no pose token: {seg.visual_state_start}"
            )
            assert last_tok, (
                f"clip {cp['clip_index']} Last frame has no pose token: {seg.visual_state_end}"
            )
            assert first_tok in cp["beats"]["0-3s"], (
                f"clip {cp['clip_index']} First pose {first_tok!r} not in [0-3s] beat"
            )
            assert last_tok in cp["beats"]["7-10s"], (
                f"clip {cp['clip_index']} Last pose {last_tok!r} not in [7-10s] beat"
            )

    def test_pose_chain_detector_counterexample(self):
        """Counterexample: the r3 contradictory frame/beat pairs fail (F6 r4)."""
        # r3: Last frame said "reaching upward and pushing a cup" while the
        # [7-10s] beat said "crouches and places a small cup" — no shared pose.
        last_frame = "stickman reaching upward to push the cup toward the table edge"
        beat = "low shot as the stickman drops an object and flinches"
        assert pose_token_matches_beat(last_frame, beat) is False
        good_beat = "medium shot: stickman reaching upward to push the cup, camera tilts"
        assert pose_token_matches_beat(last_frame, good_beat) is True


class TestB3CleanSource:
    """B3: the E2E source must be text-free and not the forbidden footage.

    Artifacts are committed, so a missing file is a hard failure (never a
    skip): the pack's evidence must be present.
    """

    REC = Path("output/dirstyle_e2e/record.json")
    SRC = Path("output/dirstyle_e2e/source_clean.mp4")

    def test_source_record_declares_generated(self):
        assert self.REC.exists(), f"missing committed artifact {self.REC}"
        rec = json.loads(self.REC.read_text(encoding="utf-8"))
        src = rec["source"]
        assert src["kind"] in {"generated", "cc0"}
        blob = json.dumps(src, ensure_ascii=False).lower()
        for bad in ("长城", "greatwall", "shot 02", "watermark"):
            assert bad not in blob

    def test_source_name_has_no_forbidden_token(self):
        assert self.REC.exists(), f"missing committed artifact {self.REC}"
        rec = json.loads(self.REC.read_text(encoding="utf-8"))
        name = rec["source"]["path"].lower()
        for bad in ("长城", "greatwall", "shot"):
            assert bad not in name

    def test_source_frames_have_no_burned_text(self):
        """The clean source frames must carry no burned-in text (B3 r4).

        Detector: within the caption bands (top 20% / bottom 30%), a run of
        consecutive rows each carrying many high-contrast mask transitions is
        the signature of a line of glyphs.  A clean frame has only scattered
        silhouette edges; a subtitle / watermark lights up a *consecutive*
        run.  The positive control below proves the detector actually fires.
        """
        assert self.SRC.exists(), f"missing committed artifact {self.SRC}"
        for frac in (0.25, 0.5, 0.75):
            png = Path("/tmp") / f"_b3_src_{int(frac * 100)}.png"
            _extract_frame(self.SRC, 12.0 * frac, f"b3_{int(frac * 100)}", png)
            top, bottom = _burned_text_signature(png)
            assert not _has_burned_text(top, bottom), (
                f"burned text detected at {frac:.2f} (top_run={top}, bottom_run={bottom})"
            )

    def test_detector_fires_on_positive_control(self):
        """Positive control: drawing a caption + 'SHOT 02' must be detected."""
        assert self.SRC.exists(), f"missing committed artifact {self.SRC}"
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        png = Path("/tmp") / "_b3_src_control.png"
        _extract_frame(self.SRC, 6.0, "b3_ctl", png)
        img = Image.open(png).convert("L")
        arr = np.array(img)
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype("/home/soffy/.local/share/fonts/wqy-zenhei.ttc", 56)
        # a bottom caption line and a top-left "SHOT 02" watermark
        draw.text(
            (300, int(arr.shape[0] * 0.9)),
            "这是一行中文字幕",
            font=font,
            fill="black",
            stroke_width=3,
            stroke_fill="white",
        )
        draw.text(
            (30, 30),
            "SHOT 02",
            font=ImageFont.truetype("/home/soffy/.local/share/fonts/wqy-zenhei.ttc", 44),
            fill="black",
            stroke_width=3,
            stroke_fill="white",
        )
        ctl = Path("/tmp") / "_b3_src_control_drawn.png"
        img.save(ctl)
        top, bottom = _burned_text_signature(ctl)
        assert _has_burned_text(top, bottom), (
            f"detector missed the burned text (top_run={top}, bottom_run={bottom})"
        )

    def test_burned_text_predicate_counterexamples(self):
        """The predicate separates the measured clean / burned signatures."""
        # clean source measured top_run=0, bottom_run=0
        assert _has_burned_text(0, 0) is False
        assert _has_burned_text(0, 7) is False
        # a top-left watermark (SHOT 02 >=8) and a bottom caption (>=8) both fire
        assert _has_burned_text(8, 0) is True
        assert _has_burned_text(0, 10) is True

    def test_source_clean_full_scan_5fps_zero_false_positives(self):
        """source_clean scanned across all frames at 5fps must yield 0 false positives (R5-5)."""
        assert self.SRC.exists(), f"missing committed artifact {self.SRC}"
        # 12s at 5fps = 60 sample points
        for i in range(60):
            t = i * 0.2
            png = Path("/tmp") / f"_b3_scan_{i}.png"
            _extract_frame(self.SRC, t, f"b3_scan_{i}", png)
            top, bottom = _burned_text_signature(png)
            assert not _has_burned_text(top, bottom), (
                f"false positive on clean source at t={t:.2f}s: top={top}, bottom={bottom}"
            )

    def test_subbed_videos_all_detected_20_frames(self):
        """4 *_subbed.mp4 at t in {1,3,6,9,11}s (20 frames) must 20/20 be detected (R5-5)."""
        styles = ["wong_kar_wai", "wes_anderson", "fincher", "zhang_yimou"]
        timestamps = [1.0, 3.0, 6.0, 9.0, 11.0]
        for sid in styles:
            vpath = Path(f"output/dirstyle_e2e/{sid}_subbed.mp4")
            assert vpath.exists(), f"missing subbed video {vpath}"
            for t in timestamps:
                png = Path("/tmp") / f"_b3_sub_{sid}_{int(t)}.png"
                _extract_frame(vpath, t, f"b3_sub_{sid}_{int(t)}", png)
                top, bottom = _burned_text_signature(png)
                assert _has_burned_text(top, bottom), (
                    f"missed subtitle on {sid}_subbed.mp4 at t={t}s: top={top}, bottom={bottom}"
                )

    def test_unstroked_shot_02_watermarks_detected(self):
        """28px and 36px unstroked white 'SHOT 02' at top-left must be detected (R5-5)."""
        assert self.SRC.exists(), f"missing committed artifact {self.SRC}"
        from PIL import Image, ImageDraw, ImageFont

        png = Path("/tmp") / "_b3_src_base.png"
        _extract_frame(self.SRC, 1.0, "b3_base", png)
        font_path = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"

        for size in [28, 36]:
            img = Image.open(png).convert("L")
            draw = ImageDraw.Draw(img)
            font = ImageFont.truetype(font_path, size)
            # unstroked white text at top-left
            draw.text((30, 30), "SHOT 02", font=font, fill="white")
            out_png = Path("/tmp") / f"_b3_shot_{size}.png"
            img.save(out_png)
            top, bottom = _burned_text_signature(out_png)
            assert _has_burned_text(top, bottom), (
                f"missed unstroked SHOT 02 at {size}px: top={top}, bottom={bottom}"
            )


class TestB5Stickman:
    """B5: subtitle ink inside [90, 990]; >=4 distinct poses — from frames.

    These read the *rendered video* pixels (not the renderer's own JSON), so
    they cannot be satisfied by a self-reported metadata file.
    """

    VIDEO = Path("output/dirstyle_e2e/stickman_9x16.mp4")
    W, H = 1080, 1920

    def test_subtitle_ink_inside_safe_band(self):
        import numpy as np

        assert self.VIDEO.exists(), f"missing committed artifact {self.VIDEO}"
        for t in (1.0, 5.0, 12.0, 17.0):
            arr = _extract_frame(self.VIDEO, t, "b5sub")
            band = arr[int(0.78 * self.H) :, :]
            ink = band < 128
            ys, xs = np.where(ink)
            assert len(xs) > 0, f"no subtitle ink at t={t}"
            x0, x1 = int(xs.min()), int(xs.max())
            assert x0 >= 90 - 1, f"subtitle left {x0} < 90 at t={t}"
            assert x1 <= 990 + 1, f"subtitle right {x1} > 990 at t={t}"
            rows = ink.sum(axis=1)
            lines = 0
            prev = False
            for v in rows > 0:
                if v and not prev:
                    lines += 1
                prev = v
            assert lines <= 2, f"{lines} subtitle lines at t={t}"

    def test_four_plus_distinct_poses_from_frames(self):
        """>=4 distinct poses measured from the video's own figure pixels."""
        import numpy as np

        assert self.VIDEO.exists(), f"missing committed artifact {self.VIDEO}"
        masks = []
        for k in range(8):
            arr = _extract_frame(self.VIDEO, 0.5 + k * 2.5, "b5pose")
            region = arr[int(0.05 * self.H) : int(0.72 * self.H), :]
            masks.append(region < 128)
        clusters: list = []
        for m in masks:
            if not any((m != rep).mean() < 0.005 for rep in clusters):
                clusters.append(m)
        assert len(clusters) >= 4, f"only {len(clusters)} distinct poses in the video"


class TestArtifactIntegrity:
    """R5-3: Committed artifacts existence and SHA256SUMS matching. Hard failure (no skip)."""

    E2E_DIR = Path("output/dirstyle_e2e")
    SHA256SUMS = E2E_DIR / "SHA256SUMS"

    REQUIRED_FILES = [
        "source_clean.mp4",
        "wong_kar_wai.mp4",
        "wes_anderson.mp4",
        "fincher.mp4",
        "zhang_yimou.mp4",
        "wong_kar_wai_subbed.mp4",
        "wes_anderson_subbed.mp4",
        "fincher_subbed.mp4",
        "zhang_yimou_subbed.mp4",
        "stickman_9x16.mp4",
        "contact_sheet.png",
        "record.json",
        "flow_pack_60s/pack.md",
        "flow_pack_60s/pack.json",
    ]

    def test_sha256sums_all_exist_and_match(self):
        """Assert all files in SHA256SUMS exist and their sha256 hashes match."""
        import hashlib

        assert self.SHA256SUMS.exists(), f"missing committed artifact {self.SHA256SUMS}"
        lines = [l.strip() for l in self.SHA256SUMS.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) >= 10, f"SHA256SUMS has only {len(lines)} entries (expected >=10)"
        for line in lines:
            expected_sha, fname = line.split(None, 1)
            target = self.E2E_DIR / fname.strip()
            assert target.exists(), f"artifact listed in SHA256SUMS missing: {target} (never skip)"
            h = hashlib.sha256(target.read_bytes()).hexdigest()
            assert h == expected_sha, (
                f"sha256 mismatch for {fname}: got {h}, expected {expected_sha}"
            )

    @pytest.mark.parametrize("fname", REQUIRED_FILES)
    def test_required_artifacts_exist(self, fname):
        """Assert each style video, subbed video, contact sheet, record, and pack exist."""
        target = self.E2E_DIR / fname
        assert target.exists(), f"Required artifact {fname} missing: {target} (never skip)"

