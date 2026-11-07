"""Tests for the AID-learned storyfilm layer: structured storyboard
(hevi.storyfilm.storyboard) + cross-episode asset registry
(hevi.storyfilm.assets) and their pipeline wiring.

Offline: the integration tests monkeypatch every paid/external stage,
following tests/test_story_film.py's _patch_all_stages pattern.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.storyfilm import assets, pipeline, storyboard


# ---------------------------------------------------------------------------
# storyboard: pure enrichment
# ---------------------------------------------------------------------------

LEGACY_DRAFT = {
    "title": "咪咪回家",
    "hook": "雨夜里，咪咪能找回家吗？",
    "characters": [
        {
            "name": "咪咪",
            "role": "主角",
            "appearance_en": "a small orange tabby kitten with a red collar",
        }
    ],
    "beats": [
        {
            "narration": "雨下得很大，咪咪冒雨走在回家的路上，冷得直发抖。",
            "visual_en": "a kitten alone in the rain at night",
            "motion_prompt": "slow push-in",
        },
        {
            "narration": "咪咪鼓起勇气跑过小桥，灯下就是它的家。",
            "visual_en": "a kitten running across a small bridge",
            "motion_prompt": "static warm close-up",
        },
    ],
}


def test_enrich_legacy_draft_derives_structure() -> None:
    enriched = storyboard.enrich_draft(LEGACY_DRAFT)
    assert "scenes" not in LEGACY_DRAFT  # input not mutated
    assert enriched["scenes"], "fallback scene segmentation expected"
    for i, beat in enumerate(enriched["beats"]):
        assert beat["shot_size"] in storyboard.SHOT_SIZES
        assert beat["camera_angle"] in storyboard.CAMERA_ANGLES
        assert beat["camera_movement"] in storyboard.CAMERA_MOVEMENTS
        assert beat["scene_ref"].startswith("SC")
        assert beat["est_duration_s"] > 0
        assert beat["character_refs"] == []
    assert enriched["beats"][0]["transition"] == "fade_in"
    assert enriched["beats"][1]["transition"] == "cut"
    assert enriched["beats"][0]["narrative_function"] == "hook"
    assert enriched["beats"][1]["narrative_function"] == "resolution"
    # motion derivation: push-in stays push-in; "static ... close-up"
    # keeps its explicit static movement and close-up size.
    assert enriched["beats"][0]["camera_movement"] == "push_in"
    assert enriched["beats"][1]["camera_movement"] == "static"
    assert enriched["beats"][1]["shot_size"] == "close_up"


def test_enrich_respects_explicit_fields_and_groups_scenes() -> None:
    draft = {
        "title": "团团",
        "characters": [
            {"name": "团团", "role": "主角", "appearance_en": "a panda cub"},
            {"name": "奶奶", "role": "配角", "appearance_en": "an old panda"},
        ],
        "beats": [
            {
                "narration": "团团在池塘边看荷花。",
                "visual_en": "a panda cub by a pond",
                "motion_prompt": "slow push-in",
                "scene": "池塘边",
                "shot_size": "特写",
                "camera_angle": "俯拍",
                "characters": ["团团"],
            },
            {
                "narration": "奶奶喊团团回家吃饭。",
                "visual_en": "grandma panda calling",
                "motion_prompt": "gentle pan",
                "scene": "池塘边",
                "characters": ["团团", "奶奶", "路人甲"],
            },
            {
                "narration": "团团回到家里。",
                "visual_en": "inside a cozy home",
                "motion_prompt": "static",
                "scene": "家中",
                "characters": [],
            },
        ],
    }
    enriched = storyboard.enrich_draft(draft)
    assert [s["name"] for s in enriched["scenes"]] == ["池塘边", "家中"]
    assert enriched["scenes"][0]["beat_count"] == 2
    b0, b1, b2 = enriched["beats"]
    assert b0["shot_size"] == "close_up"  # Chinese alias normalised
    assert b0["camera_angle"] == "high_angle"
    assert b0["scene_ref"] == b1["scene_ref"] == "SC01"
    assert b2["scene_ref"] == "SC02"
    assert b1["character_refs"] == ["团团", "奶奶"]
    assert b1["character_names_unresolved"] == ["路人甲"]
    assert b2["character_refs"] == []


def test_estimate_beat_seconds_uses_pilot_rate() -> None:
    narration = "旁" * 632  # 632 chars / 6.32 chars/s = 100 s + tail
    assert storyboard.estimate_beat_seconds(narration) == pytest.approx(100.9)


def test_storyboard_markdown_has_scene_and_shot_tables() -> None:
    enriched = storyboard.enrich_draft(LEGACY_DRAFT)
    md = storyboard.storyboard_markdown(enriched)
    assert "分镜表" in md and "场次" in md and "镜号" in md
    shots = [
        {"duration_s": 4.2, "image": "a.png"},
        {"duration_s": 3.8, "image": "b.png"},
    ]
    md2 = storyboard.storyboard_markdown(enriched, shots)
    assert "4.2" in md2  # measured duration shown next to the estimate


def test_parse_story_draft_passes_shot_fields_through() -> None:
    raw = json.loads(json.dumps(LEGACY_DRAFT))
    # parse_story_draft enforces a 60-char narration floor; pad to pass it.
    raw["beats"][0]["narration"] += "它的小爪子冻得通红，它好想念家里温暖的小窝。"
    raw["beats"][0].update(
        {
            "scene": "雨中",
            "shot_size": "wide",
            "camera_angle": "eye_level",
            "characters": ["咪咪"],
        }
    )
    raw["characters"][0]["aliases"] = ["小咪"]
    parsed = pipeline.parse_story_draft(json.dumps(raw), max_shots=5)
    beat = parsed["beats"][0]
    assert beat["scene"] == "雨中"
    assert beat["shot_size"] == "wide"
    assert beat["characters"] == ["咪咪"]
    assert parsed["characters"][0]["aliases"] == ["小咪"]


# ---------------------------------------------------------------------------
# assets: registry semantics
# ---------------------------------------------------------------------------


def test_character_lock_and_variant_recording(tmp_path: Path) -> None:
    library = assets.empty_library()
    rec, created = assets.upsert_character(
        library,
        series="团团历险记",
        name="团团",
        appearance_en="a small round panda cub with a red scarf",
        role="主角",
        voice="soffy",
        episode="第一集",
    )
    assert created and rec["appearance_locked"] is True
    rec2, created2 = assets.upsert_character(
        library,
        series="团团历险记",
        name="团团",
        appearance_en="a totally different panda",
        episode="第二集",
    )
    assert not created2
    assert rec2["appearance_en"] == "a small round panda cub with a red scarf"
    assert rec2["seen_variants"] == [
        {"appearance_en": "a totally different panda"}
    ]
    assert rec2["appearances"] == 2
    assert rec2["episodes"] == ["第一集", "第二集"]
    assert rec2["voice"] == "soffy"

    path = assets.save_library(tmp_path, library)
    loaded = assets.load_library(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["assets"]
    assert assets.find_character(loaded, series="团团历险记", name="团团")


def test_name_normalisation_dedupes() -> None:
    library = assets.empty_library()
    assets.upsert_character(library, series="S", name="TuanTuan", appearance_en="x")
    rec, created = assets.upsert_character(
        library, series="S", name="tuantuan", appearance_en="y"
    )
    assert not created and rec["appearances"] == 2
    assert len(library["assets"]) == 1
    # series scope separates registries
    _, created_other = assets.upsert_character(
        library, series="Other", name="tuantuan", appearance_en="z"
    )
    assert created_other


def test_scene_template_binding_first_wins(tmp_path: Path) -> None:
    library = assets.empty_library()
    rec, _ = assets.upsert_scene(
        library, series="S", name="池塘边", description_en="a quiet pond"
    )
    assert assets.bind_scene_template(library, rec["id"], "pond_night")
    assert not assets.bind_scene_template(library, rec["id"], "river_dusk")
    again, created = assets.upsert_scene(library, series="S", name="池塘边")
    assert not created and again["brush_template"] == "pond_night"

    img = tmp_path / "ref.png"
    img.write_bytes(b"png")
    stored = assets.store_reference_image(tmp_path, rec, img, tag="key")
    assert Path(stored).is_file()
    assert assets.add_reference_image(library, rec["id"], stored)
    assert assets.primary_reference(rec) == stored


def test_register_draft_assets_binds_hero_voice() -> None:
    draft = storyboard.enrich_draft(
        {
            "title": "第一集",
            "characters": [
                {"name": "团团", "role": "主角", "appearance_en": "panda cub"},
                {"name": "奶奶", "role": "配角", "appearance_en": "old panda"},
            ],
            "beats": [
                {
                    "narration": "团团出门了。",
                    "visual_en": "a panda cub by a pond",
                    "motion_prompt": "slow push-in",
                    "scene": "池塘边",
                    "characters": ["团团"],
                }
            ],
        }
    )
    library = assets.empty_library()
    registered = assets.register_draft_assets(
        library, draft, series="团团历险记", episode="第一集", voice="soffy"
    )
    hero = registered["characters"]["团团"]
    assert registered["hero_id"] == hero["id"]
    assert hero["voice"] == "soffy"
    assert registered["characters"]["奶奶"]["voice"] is None
    assert registered["scenes"]["池塘边"]["description_en"]
    cast = assets.resolve_cast(library, series="团团历险记", names=["团团", "路人"])
    assert list(cast) == ["团团"]
    listing = assets.library_listing(library)
    assert listing["counts"] == {"character": 2, "scene": 1, "prop": 0}


# ---------------------------------------------------------------------------
# capability: story.asset_library
# ---------------------------------------------------------------------------


def test_asset_library_capability_roundtrip(tmp_path: Path) -> None:
    cap = caps.get("story.asset_library")
    root = tmp_path / "lib"
    result = cap.render_safe(
        {
            "action": "register_character",
            "library": str(root),
            "series": "团团历险记",
            "name": "团团",
            "description": "a small round panda cub with a red scarf",
            "role": "主角",
            "voice": "soffy",
        },
        tmp_path / "out1",
        duration=0.0,
        aspect="9:16",
        seed=1,
    )
    assert result.qa["counts"]["character"] == 1
    assert result.qa["changed"]["created"] is True
    result2 = cap.render_safe(
        {"action": "list", "library": str(root)},
        tmp_path / "out2",
        duration=0.0,
        aspect="9:16",
        seed=1,
    )
    assert result2.qa["counts"]["character"] == 1
    assert Path(result2.qa["asset_library_json"]).is_file()


# ---------------------------------------------------------------------------
# pipeline integration (offline, brush + gpt flavours)
# ---------------------------------------------------------------------------

EP1 = {
    "title": "团团看荷花",
    "hook": "团团第一次自己去池塘。",
    "characters": [
        {
            "name": "团团",
            "role": "主角",
            "appearance_en": "a small round panda cub with a red scarf",
        },
        {
            "name": "奶奶",
            "role": "配角",
            "appearance_en": "an elderly panda with round glasses",
        },
    ],
    "beats": [
        {
            "narration": "团团背着小书包，一蹦一跳来到池塘边。",
            "visual_en": "a panda cub arriving at a pond with lotus flowers",
            "motion_prompt": "slow push-in",
            "scene": "池塘边",
            "shot_size": "wide",
            "characters": ["团团"],
        },
        {
            "narration": "荷花开了，团团看得眼睛都直了。",
            "visual_en": "pink lotus flowers close up by the pond",
            "motion_prompt": "static close-up",
            "scene": "池塘边",
            "characters": ["团团"],
        },
        {
            "narration": "奶奶笑着走过来，牵起团团的手一起回家。",
            "visual_en": "grandma panda holding the cub's hand by the pond",
            "motion_prompt": "gentle pan right",
            "scene": "池塘边",
            "characters": ["团团", "奶奶"],
        },
    ],
}

EP2 = {
    "title": "团团数荷花",
    "hook": "团团学会数数了。",
    "characters": [
        {
            "name": "团团",
            "role": "主角",
            # Deliberately different: the registry must keep EP1's text.
            "appearance_en": "a completely different description that must not win",
        },
        {
            "name": "奶奶",
            "role": "配角",
            "appearance_en": "an elderly panda with round glasses",
        },
    ],
    "beats": [
        {
            "narration": "第二天，团团又来到池塘边数荷花。",
            "visual_en": "a panda cub counting lotus flowers by the pond",
            "motion_prompt": "slow push-in",
            "scene": "池塘边",
            "characters": ["团团", "奶奶"],
        },
        {
            "narration": "一朵，两朵，团团数得可认真啦。",
            "visual_en": "lotus flowers in a row by the pond",
            "motion_prompt": "gentle pan left",
            "scene": "池塘边",
            "characters": ["团团"],
        },
    ],
}


def _patch_common(monkeypatch: pytest.MonkeyPatch, drafts: list[dict]) -> dict:
    """Patch every external stage; generate_story replays *drafts*."""
    from hevi.audio import lux_tts_service, tts_alignment, whisper_alignment

    state: dict = {"draft_i": 0, "voices": [], "gen_prompts": [], "edit_prompts": []}
    queue = list(drafts)

    async def fake_story(premise, *, style, max_shots):
        return json.loads(json.dumps(queue.pop(0))), 0.0

    monkeypatch.setattr(pipeline, "generate_story", fake_story)
    monkeypatch.setattr(lux_tts_service, "lux_tts_available", lambda: True)

    async def fake_synth(*, text, output_path, voice=None, **_):
        state["voices"].append(voice)
        Path(output_path).write_bytes(b"RIFFfake")
        return Path(output_path)

    monkeypatch.setattr(lux_tts_service, "synth_with_luxtts", fake_synth)

    async def fake_whisper_align(*, audio_path, text, **_):
        chars = list(pipeline.normalize_text(text))
        words = tuple(
            tts_alignment.WordTiming(c, i * 100, i * 100 + 90)
            for i, c in enumerate(chars)
        )
        return words, None

    monkeypatch.setattr(
        whisper_alignment, "whisper_align_words", fake_whisper_align
    )
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda p: 3200)
    monkeypatch.setattr(
        pipeline,
        "apply_gain_control",
        lambda path, **_: {
            "peak_before_dbtp": 0.1,
            "peak_after_dbtp": -1.5,
            "gain_db": -1.6,
            "method": "volume",
        },
    )

    def fake_render(*, shots, title, narration_path, output_path, **_):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"mp4bytes")
        return sum(float(s["duration_s"]) for s in shots)

    monkeypatch.setattr(pipeline, "render_motion_film", fake_render)
    monkeypatch.setattr(
        pipeline,
        "_run_gates",
        lambda film, out, *, aspect: {"film_gate": {"verdict": "green"}},
    )
    return state


def _run_film(out_dir: Path, **kwargs) -> dict:
    return asyncio.run(
        pipeline.run_story_film(
            premise="团团和池塘",
            max_shots=5,
            render_route="hyperframes",
            out_dir=out_dir,
            **kwargs,
        )
    )


def test_series_brush_two_episodes_share_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_common(monkeypatch, [EP1, EP2])
    library_root = tmp_path / "library"
    series = "团团历险记"

    _run_film(
        tmp_path / "ep1",
        image_provider="brush",
        series=series,
        asset_library=str(library_root),
    )
    _run_film(
        tmp_path / "ep2",
        image_provider="brush",
        series=series,
        asset_library=str(library_root),
    )

    library = assets.load_library(library_root)
    hero = assets.find_character(library, series=series, name="团团")
    assert hero is not None
    assert hero["appearances"] == 2
    assert hero["appearance_en"] == EP1["characters"][0]["appearance_en"]
    assert hero["seen_variants"] == [
        {"appearance_en": EP2["characters"][0]["appearance_en"]}
    ]
    assert hero["episodes"] == ["团团看荷花", "团团数荷花"]
    assert hero["voice"] == "soffy"

    pond = assets.find_scene(library, series=series, name="池塘边")
    assert pond is not None and pond["appearances"] == 2
    assert pond["brush_template"]  # bound during episode 1

    for job in ("ep1", "ep2"):
        out = tmp_path / job
        assert (out / "assets.json").is_file()
        assert (out / "storyboard.md").is_file()
        md = (out / "storyboard.md").read_text(encoding="utf-8")
        assert "分镜表" in md and "池塘边" in md
        shots = json.loads((out / "shots.json").read_text(encoding="utf-8"))
        for shot in shots:
            assert shot["shot_size"] in storyboard.SHOT_SIZES
            assert shot["camera_movement"] in storyboard.CAMERA_MOVEMENTS
            assert shot["scene_ref"] == "SC01"
            assert shot["character_refs"]
            assert shot["est_duration_s"] > 0
            assert shot["reference_images"] == []
            assert shot["scene_template"] == pond["brush_template"]
        delivery = json.loads(
            (out / "delivery.json").read_text(encoding="utf-8")
        )
        assert delivery["assets"]["characters"] == 2
        assert delivery["storyboard"]["scenes"] == 1

    ep1_shots = json.loads(
        (tmp_path / "ep1" / "shots.json").read_text(encoding="utf-8")
    )
    assert ep1_shots[0]["shot_size"] == "wide"  # explicit draft value kept
    assert ep1_shots[2]["character_refs"] == ["团团", "奶奶"]
    assert ep1_shots[2]["character_assets"]


def test_series_gpt_key_still_reuse_and_cast_injection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import gpt_image_service

    state = _patch_common(monkeypatch, [EP1, EP2])

    async def fake_generate(*, prompt, output_path, size="1024x1536", **_):
        state["gen_prompts"].append(prompt)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"pngbytes")
        return {"output_path": str(output_path), "cost": 0.0107}

    async def fake_edit(*, image_paths, prompt, output_path, size="1024x1536", **_):
        state["edit_prompts"].append((list(image_paths), prompt))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"pngbytes")
        return {"output_path": str(output_path), "cost": 0.023}

    monkeypatch.setattr(gpt_image_service, "gpt_image_generate", fake_generate)
    monkeypatch.setattr(gpt_image_service, "gpt_image_edit", fake_edit)

    library_root = tmp_path / "library"
    series = "团团历险记"
    _run_film(
        tmp_path / "ep1",
        image_provider="gpt",
        series=series,
        asset_library=str(library_root),
        voice="soffy",
    )
    gen_after_ep1 = len(state["gen_prompts"])
    assert gen_after_ep1 == 1  # only the hero key still was generated
    library = assets.load_library(library_root)
    hero = assets.find_character(library, series=series, name="团团")
    assert hero is not None and hero["reference_images"]
    assert Path(hero["reference_images"][0]).is_file()

    # Second episode asks for a different voice; the binding must win.
    _run_film(
        tmp_path / "ep2",
        image_provider="gpt",
        series=series,
        asset_library=str(library_root),
        voice="someone-else",
    )
    assert len(state["gen_prompts"]) == gen_after_ep1  # key still reused
    assert state["voices"] == ["soffy", "soffy"]

    ep2_assets = json.loads(
        (tmp_path / "ep2" / "assets.json").read_text(encoding="utf-8")
    )
    assert ep2_assets["reused_key_still"] is True

    # The two-character beat's edit prompt carries BOTH locked texts
    # (episode 1 wording), never episode 2's drifting description.
    two_char = [
        prompt
        for _paths, prompt in state["edit_prompts"]
        if "grandma panda" in prompt
    ]
    assert two_char, "expected an edit prompt mentioning the grandma shot"
    prompt = two_char[0]
    assert EP1["characters"][0]["appearance_en"] in prompt
    assert EP1["characters"][1]["appearance_en"] in prompt
    assert "completely different description" not in prompt

    ep1_shots = json.loads(
        (tmp_path / "ep1" / "shots.json").read_text(encoding="utf-8")
    )
    assert ep1_shots[0]["reference_images"]  # key still recorded per shot
