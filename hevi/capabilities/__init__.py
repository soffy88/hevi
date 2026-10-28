"""Hevi unified capability registry — public surface.

Importing this package must NOT trigger heavy side effects (no chromium
launch, no ffmpeg).  Capability *registration* is explicit via
:func:`hevi.capabilities.scene3d.register_scene3d_capabilities`, called by the
line's bootstrap so the catalogue is populated lazily and testably.
"""

from __future__ import annotations

from .errors import CapabilityError
from .registry import (
    Capability,
    CapabilityResult,
    Registry,
    contains,
    get,
    list,
    list_capabilities,
    names,
    register,
    resolve,
)
from .result import CapabilityResult

# Auto-register the bundled capability families on import (cheap, side-effect
# free: no chromium / ffmpeg is launched here, only dataclass wiring).  Any
# product line importing ``hevi.capabilities`` can immediately call
# ``hevi.capabilities.get("scene3d.planet_orbit")``.
from . import scene3d as _scene3d  # noqa: E402,F401
_scene3d.register_scene3d_capabilities_once()
from . import svfactory as _svfactory  # noqa: E402,F401

# Handdraw line (merged from feat/handdraw-line): importing registers the four
# handdraw capabilities (handdraw.full / storyboard / narration / illustration)
# on the unified registry.  Heavy pipeline imports stay inside the render fns.
from . import handdraw  # noqa: E402,F401

# Rough-style hand-drawn strokes (clean-room technique, 2026-10-20):
# image.rough_stroke -- also reachable inside handdraw via stroke_style="rough".
from . import rough_stroke as _rough_stroke  # noqa: E402,F401
_rough_stroke.register_rough_stroke_capabilities_once()

# Partsci line (merged from feat/particle-science): importing registers
# particle_text / particle_science_scene / parallax_layers.
from hevi.partsci.capabilities import register_partsci_capabilities_once
register_partsci_capabilities_once()

# GOLIVE3 capabilities (assets.library, assets.extract, image.multi_ref_compose, style.project_snapshot, storyboard.shot_groups)
from . import golive3 as _golive3  # noqa: E402,F401
_golive3.register_golive3_capabilities_once()

from hevi.manga.capabilities import register_manga_capabilities
register_manga_capabilities()

import hevi.capabilities.brandfilm  # noqa: E402,F401
import hevi.capabilities.webrender  # noqa: E402,F401
import hevi.capabilities.motion_taste  # noqa: E402,F401

# Explainer line capabilities (explainer.script, explainer.visual_plan, explainer.render)
from hevi.explainer.script import register_explainer_script_capability
from hevi.explainer.visual_plan import register_explainer_visual_plan_capability
from hevi.explainer.render_engine import register_explainer_render_capability
register_explainer_script_capability()
register_explainer_visual_plan_capability()
register_explainer_render_capability()

# Stickman line (feat/stickman-flow): topic_scout, structure_clone, proposal, render_local, flow_pack, flow_import
from hevi.stickman.capabilities import register_stickman_capabilities_once
register_stickman_capabilities_once()

# Riso B-roll capabilities (feat/riso-broll)
from hevi.riso.capabilities import register_riso_capabilities
register_riso_capabilities()


# Multi-model pipeline (cloud providers via Monid, 2026-10-20):
# audio.forced_align / image.gpt_generate / image.gpt_edit
from . import multimodel as _multimodel  # noqa: E402,F401
_multimodel.register_multimodel_capabilities_once()

# Model catalogue + cost gate (Palmier gap, 2026-10-25): model.model_catalog
# reads model ids/prices from model_catalog_data/models.json. Imported
# BEFORE nano_banana so nano_banana's PER_IMAGE_USD can be built from
# this same catalogue instead of a private copy.
from . import model_catalog as _model_catalog  # noqa: E402,F401
_model_catalog.register_model_catalog_capabilities_once()

# Nano Banana image generation via the official Gemini API (2026-10-25):
# image.nano_banana_generate -- Interactions REST, GEMINI_API_KEY /
# GOOGLE_API_KEY env only, paid-only cost gate (no API free tier).
# Wiring it here (not just self-registering on import) is what makes
# `import hevi.capabilities` the single source the catalogue is
# generated from (G13 leak pattern).
from . import nano_banana as _nano_banana  # noqa: E402,F401
_nano_banana.register_nano_banana_capabilities_once()
from . import storyfilm as _storyfilm  # noqa: E402,F401
_storyfilm.register_storyfilm_capabilities_once()

# Earshot audio gate + SFX bank (feat/earshot): model-free, local
from . import earshot_gate as _earshot_gate  # noqa: E402,F401
_earshot_gate.register_earshot_capabilities_once()

# Unified export QA gate (qa.export_gate): pre-delivery checklist
from . import export_qa as _export_qa  # noqa: E402,F401
_export_qa.register_export_qa_capabilities_once()

# BGM beat alignment (assembly line): assembly.beat_align
from . import beat_align as _beat_align  # noqa: E402,F401
_beat_align.register_beat_align_capabilities_once()

# Music analysis pipeline (audio.music_analyze): librosa structured
# report (duration/BPM/beats/downbeats/onsets/sections/loudness),
# optional whisper_local lyrics timings; Demucs stems downgraded out.
from . import music_analyze as _music_analyze  # noqa: E402,F401
_music_analyze.register_music_analyze_capabilities_once()

# PixStag external render (live-action story films, 2026-10-20):
# video.pixstag_generate - hevi ships shot packages, PixStag renders them
from . import pixstag as _pixstag  # noqa: E402,F401
_pixstag.register_pixstag_capabilities_once()

# creator-style-kit (HyperFrames line, 2026-10-20):
# video.hyperframes_styles / video.hyperframes_styled_render - 18 styles
from . import csk_styles as _csk_styles  # noqa: E402,F401
_csk_styles.register_csk_capabilities_once()

# Story/writing internalization (InkOS gap analysis, 2026-10-20; clean-room):
# storybranch / textcraft / storybible / novelpipeline / shortstory /
# longtranslate / playworld / jobguard
from . import storybranch as _storybranch  # noqa: E402,F401
_storybranch.register_storybranch_capabilities_once()
from . import textcraft as _textcraft  # noqa: E402,F401
_textcraft.register_textcraft_capabilities_once()
from . import storybible as _storybible  # noqa: E402,F401
_storybible.register_storybible_capabilities_once()
from . import novelpipeline as _novelpipeline  # noqa: E402,F401
_novelpipeline.register_novelpipeline_capabilities_once()
from . import shortstory as _shortstory  # noqa: E402,F401
_shortstory.register_shortstory_capabilities_once()
from . import longtranslate as _longtranslate  # noqa: E402,F401
_longtranslate.register_longtranslate_capabilities_once()
from . import playworld as _playworld  # noqa: E402,F401
_playworld.register_playworld_capabilities_once()
from . import jobguard as _jobguard  # noqa: E402,F401
_jobguard.register_jobguard_capabilities_once()

# Huobao line (character_ref / scene_ref / shot): previously registered only
# as an import side effect of the API routers, so the catalogue missed it.
# register_huobao_capabilities() is idempotent; wiring it here makes the
# registry the single source the catalogue is generated from.
from hevi.huobao.capabilities import register_huobao_capabilities as _register_huobao  # noqa: E402
_register_huobao()


# Kids / anime safety gates (``qa.kids_gate``, ``kids.story_gate``,
# ``kids.consistency_manifest``) are registered by importing the registry.
# ``registry.register`` is import-triggered for these three so every line can
# resolve them by name without extra wiring.

__all__ = [
    "Capability",
    "CapabilityError",
    "CapabilityResult",
    "register",
    "get",
    "resolve",
    "list",
    "list_capabilities",
    "names",
    "contains",
    "Registry",
]


# Procedural watercolour (image.watercolor_render): pure-Python local $0
from . import watercolor as _watercolor  # noqa: E402,F401
_watercolor.register_watercolor_capabilities_once()

# Map-route line (video.map_route): narration-timestamp-driven real-map
# route animation over the free OSM stack (Photon/OSRM/CARTO), AMap optional.
from . import maproute as _maproute  # noqa: E402,F401
_maproute.register_maproute_capabilities_once()

# Blender clay line (video.blender_clay_render): headless bpy, Cycles CPU
from . import blender_clay as _blender_clay  # noqa: E402,F401
_blender_clay.register_blender_clay_capabilities_once()
# Handraw-style numbered prompt library (yang0/handraw-style, MIT with
# attribution): image.handraw_styles catalogue + image.styled_generate
# (numbered style -> assembled prompt -> Monid GPT-Image backend).
from . import handraw_styles as _handraw_styles  # noqa: E402,F401
_handraw_styles.register_handraw_style_capabilities_once()

# Structured review sheet (qa.review_sheet): cross-line review comments
# with statuses + frame grabs assembled into a review sheet.
from . import review_sheet as _review_sheet  # noqa: E402,F401
_review_sheet.register_review_sheet_capabilities_once()


# Launch-film rhythm sheet (motion.rhythm_sheet): validate a RhythmSheet
# against docs/rules/launch_rhythm.md, and measure a finished film
# per-stretch (audio energy / picture motion) against the plan.
from . import rhythm_sheet as _rhythm_sheet  # noqa: E402,F401
_rhythm_sheet.register_rhythm_sheet_capabilities()


# Score-driven music composition (audio.score_render): ABC notation
# scores fitted to picture marks, rendered locally with numpy synths;
# plus a category/scene direction fallback that drafts the score.
from . import score_render as _score_render  # noqa: E402,F401
_score_render.register_score_render_capabilities_once()


# Hand-drawn character expression rig (image.expression_rig /
# image.expression_contact_sheet): views x emotions x combinable parts
# over an original demo character; see docs/rules/expression_rig.md.
from . import expression_rig as _expression_rig  # noqa: E402,F401
_expression_rig.register_expression_rig_capabilities_once()

# Generic data-driven three.js scenes (scene3d.generic): JSON scene + CatmullRom camera path; presets are templates.
from . import scene3d_generic as _scene3d_generic  # noqa: E402,F401


# Pre-generation gate suite (preflight.*): prompt audit, first-frame check,
# dialogue fit, budget gate, prompt compiler, pass-rate ledger.
from hevi.preflight.capabilities import register_preflight_capabilities_once as _register_preflight  # noqa: E402,F401
_register_preflight()

# Shadow capabilities wired into the unified entry (G13, 2026-10-24):
# these six modules self-register on import but were never imported here,
# so `import hevi.capabilities` missed them (audit universe 112 -> 118).
from . import brushpaint as _brushpaint  # noqa: E402,F401
_brushpaint.register_brushpaint_capabilities_once()
from . import generative_art as _generative_art  # noqa: E402,F401
_generative_art.register_generative_art_capabilities_once()
from . import portrait_vocab as _portrait_vocab  # noqa: E402,F401
_portrait_vocab.register_portrait_vocab_capabilities_once()
from . import manim_render as _manim_render  # noqa: E402,F401
_manim_render.register_manim_capabilities_once()
from . import world_contract as _world_contract  # noqa: E402,F401
_world_contract.register_world_contract_capabilities_once()
from . import shotcraft as _shotcraft  # noqa: E402,F401
_shotcraft.register_shotcraft_capabilities_once()

# Talking-head presenter line (G14, 2026-10-24): portrait + script ->
# lip-synced MP4, local zero-fee pipeline (LuxTTS / wav2lip / musetalk).
from . import talking_head as _talking_head  # noqa: E402,F401
_talking_head.register_talking_head_capabilities_once()

# Paradigm normalization (2026-10-25): the five grafted story helpers
# (story.shot_chain / story.reference_bundle / story.canvas_workflow /
# story.novel_import / story.narration_srt) plus the drama-50 report
# family and video.blender_mcp.  All self-register on import; wiring
# them here is what makes `import hevi.capabilities` the single source
# the catalogue is generated from (the G13 leak pattern: self-register
# without this import leaves a capability invisible to GET
# /api/capabilities and to ShotSpec).  Naming: story.* throughout;
# story.novel_import maps a finished book to episode inputs, while
# novel.* (novelpipeline) creates the book itself.
from . import shot_chain as _shot_chain  # noqa: E402,F401
_shot_chain.register_shot_chain_capabilities_once()
from . import reference_bundle as _reference_bundle  # noqa: E402,F401
_reference_bundle.register_reference_bundle_capabilities_once()
from . import canvas_workflow as _canvas_workflow  # noqa: E402,F401
_canvas_workflow.register_canvas_workflow_capabilities_once()
from . import novel_import as _novel_import  # noqa: E402,F401
_novel_import.register_novel_import_capabilities_once()
from . import narration_srt as _narration_srt  # noqa: E402,F401
_narration_srt.register_narration_srt_capabilities_once()
from . import season_bible as _season_bible  # noqa: E402,F401
_season_bible.register_season_bible_capabilities_once()
from . import season_arc as _season_arc  # noqa: E402,F401
_season_arc.register_season_arc_capabilities_once()
from . import episode_prompts as _episode_prompts  # noqa: E402,F401
_episode_prompts.register_episode_prompts_capabilities_once()
from . import drama_gates as _drama_gates  # noqa: E402,F401
_drama_gates.register_drama_gates_capabilities_once()
# Long-form consistency (2026-10-25, clean-room method intake):
# story.context_store / story.foreshadow_ledger / story.chapter_workspace.
from . import longform_context as _longform_context  # noqa: E402,F401
_longform_context.register_longform_context_capabilities_once()
from . import reference_decompose as _reference_decompose  # noqa: E402,F401
_reference_decompose.register_reference_decompose_capabilities_once()
from . import edit_assemble as _edit_assemble  # noqa: E402,F401
_edit_assemble.register_edit_assemble_capabilities_once()
from . import model_test as _model_test  # noqa: E402,F401
_model_test.register_model_test_capabilities_once()
from . import script_polish as _script_polish  # noqa: E402,F401
_script_polish.register_script_polish_capabilities_once()
# video.blender_mcp is listed in the catalogue but its preview endpoint
# is gated (preview_restricted): its `code` param executes arbitrary
# bpy code in a live Blender session, so generic callers must never
# reach it through preview — only trusted direct render_safe callers.
# Local FastH3 Reference-to-Video (2026-10-26): video.fasth3_local,
# ComfyUI on localhost:8188, INT8, 8 steps. Same self-register +
# __init__ import pattern as video.blender_mcp (G13 guard).
from . import fasth3_local as _fasth3_local  # noqa: E402,F401
_fasth3_local.register_fasth3_local_capabilities_once()

from . import blender_mcp as _blender_mcp  # noqa: E402,F401
_blender_mcp.register_blender_mcp_capabilities_once()

# Cinematic technique libraries (movie-atmosphere 10-site intake, 2026-10-25):
# shot.camera_movements (40 movements) + shot.cinematic_techniques
# (melies index, 30 vvsvs core techniques, index-only pointers).
from . import cinematic_techniques as _cinematic_techniques  # noqa: E402,F401
_cinematic_techniques.register_cinematic_techniques_capabilities_once()

# Palmier gaps (2026-10-25, clean-room): generate-into-timeline
# (edit.timeline_register), reusable edit recipes (edit.edit_recipe),
# and the tool-boundary readback layer (tool_contract: no Capability
# of its own, imported here so the tool layer is reachable from the
# package; its five tools are built by tool_contract.builtin_tools()).
from . import timeline_register as _timeline_register  # noqa: E402,F401
_timeline_register.register_timeline_capabilities_once()
from . import edit_recipes as _edit_recipes  # noqa: E402,F401
_edit_recipes.register_edit_recipe_capabilities_once()
# video-use method (2026-10-25): transcript-first editing, cut-point
# self-check and the 12 hard rules, folded into the edit_assemble line
# (edit.video_use). Free routes only; Scribe is an interface, never run.
from . import edit_video_use as _edit_video_use  # noqa: E402,F401
_edit_video_use.register_video_use_capabilities_once()
from . import tool_contract as _tool_contract  # noqa: E402,F401

# Pixelle-Video gap fill (2026-10-25, clean-room): supplier directory
# (model.provider_catalog, layered on model_catalog prices), user-asset
# script draft (story.asset_script, injected VLM only, no default VLM),
# and named edit templates (edit.edit_template, orientation + shot-kind
# validated, preview is a readable plan). Mounting follows the same
# registry + __init__ import pattern as talking_head.render (which has
# no plugin registry of its own); the G13 completeness guard fails if
# this import is missing.
from . import provider_catalog as _provider_catalog  # noqa: E402,F401
_provider_catalog.register_provider_catalog_capabilities_once()
from . import asset_script as _asset_script  # noqa: E402,F401
_asset_script.register_asset_script_capabilities_once()
from . import edit_templates as _edit_templates  # noqa: E402,F401
_edit_templates.register_edit_template_capabilities_once()

# Beat-schema prompt compiler (2026-10-26, clean-room): story.prompt_compiler
# -- per-shot beat schema, five fatal compile gates, verbatim lines,
# closed movement vocabulary from cinematic_techniques.
from . import prompt_compiler as _prompt_compiler  # noqa: E402,F401
_prompt_compiler.register_prompt_compiler_capabilities_once()

# Hand-painted animation planning (2026-10-27, clean-room method intake):
# animation.guide_check / time_camera / timeline / brush_wipe /
# render_check / tuantuan_demo (self-registers on import as well).
from . import handpaint_anim as _handpaint_anim  # noqa: E402,F401
_handpaint_anim.register_handpaint_anim_capabilities_once()

# Multi-shot reference-lock planning (2026-10-27, clean-room):
# video.multishot_lock (self-registers on import as well).
from . import multishot_lock as _multishot_lock  # noqa: E402,F401
_multishot_lock.register_multishot_lock_capabilities_once()

# Physics / vector gaps (2026-10-27, clean-room): animation.physics2d,
# scene3d.collision_check, image.vector_path (self-register on import).
from . import physics2d as _physics2d  # noqa: E402,F401
_physics2d.register_physics2d_capabilities_once()
from . import collision3d as _collision3d  # noqa: E402,F401
_collision3d.register_collision3d_capabilities_once()
from . import vector_path as _vector_path  # noqa: E402,F401
_vector_path.register_vector_path_capabilities_once()

# Openshorts method intake (2026-10-27, clean-room): edit.clip_moments,
# edit.vertical_reframe, edit.word_subtitle_contract, edit.publish_plan,
# edit.webhook_final (self-register on import as well).
from . import clip_moments as _clip_moments  # noqa: E402,F401
_clip_moments.register_clip_moments_capabilities_once()
from . import vertical_reframe as _vertical_reframe  # noqa: E402,F401
_vertical_reframe.register_vertical_reframe_capabilities_once()
from . import word_subtitle_contract as _word_subtitle_contract  # noqa: E402,F401
_word_subtitle_contract.register_word_subtitle_contract_capabilities_once()
from . import publish_plan as _publish_plan  # noqa: E402,F401
_publish_plan.register_publish_plan_capabilities_once()
from . import webhook_final as _webhook_final  # noqa: E402,F401
_webhook_final.register_webhook_final_capabilities_once()

# 369-list method intake (2026-10-27, clean-room): handpaint narration
# alignment, karaoke vertical, frame-return review, GSAP timeline
# plan, portrait consent gate, shot continuity gate, editable
# project, word appear plan (self-register on import as well).
from . import handpaint_narration as _handpaint_narration  # noqa: E402,F401
_handpaint_narration.register_handpaint_narration_capabilities_once()
from . import karaoke_vertical as _karaoke_vertical  # noqa: E402,F401
_karaoke_vertical.register_karaoke_vertical_capabilities_once()
from . import frame_review as _frame_review  # noqa: E402,F401
_frame_review.register_frame_review_capabilities_once()
from . import gsap_timeline as _gsap_timeline  # noqa: E402,F401
_gsap_timeline.register_gsap_timeline_capabilities_once()
from . import portrait_consent as _portrait_consent  # noqa: E402,F401
_portrait_consent.register_portrait_consent_capabilities_once()
from . import shot_continuity as _shot_continuity  # noqa: E402,F401
_shot_continuity.register_shot_continuity_capabilities_once()
from . import editable_project as _editable_project  # noqa: E402,F401
_editable_project.register_editable_project_capabilities_once()
from . import word_appear as _word_appear  # noqa: E402,F401
_word_appear.register_word_appear_capabilities_once()

# Motion-method gates (2026-10-27, clean-room): edit.semantic_shot_list,
# edit.reuse_baseline_gate, audio.transcript_once, qa.sample_first_gate,
# edit.caption_plan_gate (self-registers on import as well).
from . import motion_gates as _motion_gates  # noqa: E402,F401
_motion_gates.register_motion_gates_capabilities_once()

# Commentary-short line (2026-10-27, clean-room): story.five_segment_short
# (Lu Shihao five-segment template compressed to 90-150s, segment 3
# honestly labelled commentary, not live-action performance),
# story.audio_first_board (SRT-timed storyboard, about 8s per shot,
# first shot at 0, research pending never invented), and
# edit.jianying_draft_plan (pyJianYingDraft-shaped draft PLAN only;
# no .draft file is written and nothing is installed).
from . import five_segment_short as _five_segment_short  # noqa: E402,F401
_five_segment_short.register_five_segment_short_capabilities_once()
from . import audio_first_board as _audio_first_board  # noqa: E402,F401
_audio_first_board.register_audio_first_board_capabilities_once()
from . import jianying_draft_plan as _jianying_draft_plan  # noqa: E402,F401
_jianying_draft_plan.register_jianying_draft_plan_capabilities_once()

# Commentary-LONG line (2026-10-27, clean-room): story.five_segment_long
# (Lu Shihao five-segment template for a YouTube long video, target
# 1800s / 8500-9000 narration chars, segment 3 honestly labelled
# commentary, not live-action performance), story.youtube_long_board
# (16:9 board, about 8s per image, YouTube chapters, research pending
# never invented), and edit.jianying_draft_long_plan (16:9 draft PLAN
# only; no .draft file is written and nothing is installed).
from . import five_segment_long as _five_segment_long  # noqa: E402,F401
_five_segment_long.register_five_segment_long_capabilities_once()
from . import youtube_long_board as _youtube_long_board  # noqa: E402,F401
_youtube_long_board.register_youtube_long_capabilities_once()

# Shuohao-method intake (2026-10-28, clean-room): story.opening_blocking
# (one fixed opening arrangement per scene, with the exact sentence the
# storyboard must copy into each scene's first segment),
# qa.storyboard_opening_gate (verbatim-copy check), qa.production_gates
# (deterministic outline/art/script/storyboard gates covering only the
# gaps hevi's other gates do not cover), and qa.character_anchor_gate
# (one confirmed anchor root, views derive from it alone, anchor
# changes mark views stale without deleting them; no image is
# generated here). Method ideas only; no upstream code or text used.
from . import stage_opening as _stage_opening  # noqa: E402,F401
_stage_opening.register_stage_opening_capabilities_once()
from . import production_gates as _production_gates  # noqa: E402,F401
_production_gates.register_production_gates_capabilities_once()
from . import character_anchor as _character_anchor  # noqa: E402,F401
_character_anchor.register_character_anchor_capabilities_once()

# Opus 5.5 collection intake (2026-10-28, clean-room): story.opus_prompt_library
# (yihui 703 full prompts searchable by category/tech; zhuyansen 2220
# metadata only, no prompt text bundled), image.lemo_styles (59 lemo
# styles live-read from the checkout, 3 csk slugs flagged not duplicated),
# video.code_render (deterministic frame(t) tiers up to 4K60, manifest,
# retry, ffmpeg assembly) and edit.karaoke_render (executable karaoke
# chain below the plan-only karaoke_vertical). No upstream code copied;
# see OPUS5_COLLECTION_ATTRIBUTION.md.
from . import opus_prompt_library as _opus_prompt_library  # noqa: E402,F401
_opus_prompt_library.register_opus_prompt_library_capabilities_once()
from . import lemo_styles as _lemo_styles  # noqa: E402,F401
_lemo_styles.register_lemo_styles_capabilities_once()
from . import code_render as _code_render  # noqa: E402,F401
_code_render.register_code_render_capabilities_once()
from . import karaoke_render as _karaoke_render  # noqa: E402,F401
_karaoke_render.register_karaoke_render_capabilities_once()

# Creator-buddy intake (2026-10-28, clean-room): pipeline.project_handoff
# (fixed project directories plus a per-step manifest with a gate
# that names missing stages/files), qa.final_qc_gate (probed shape,
# first/middle/last keyframes, picture-change rate, caption
# pictograph ban, vertical safe zone), edit.subtitle_discipline
# (breath breaks, glossary, post-edit retranscription freshness,
# vertical safe zone), audio.mix_recipe (fixed mix numbers plus a
# loudnorm gate; a missing meter reports unmeasured, never pass),
# and video.motion_beat_chart (per-beat time/action/mover/change/
# camera/text/asset plus a motion thesis, 80% real-change gate,
# plain downstream plan for code_render/Manim/Blender; renders
# nothing itself). Method ideas only; no upstream code or text
# used. See CREATOR_BUDDY_ATTRIBUTION.md (license unverified).
from . import project_handoff as _project_handoff  # noqa: E402,F401
_project_handoff.register_project_handoff_capabilities_once()
from . import final_qc as _final_qc  # noqa: E402,F401
_final_qc.register_final_qc_capabilities_once()
from . import subtitle_discipline as _subtitle_discipline  # noqa: E402,F401
_subtitle_discipline.register_subtitle_discipline_capabilities_once()
from . import mix_recipe as _mix_recipe  # noqa: E402,F401
_mix_recipe.register_mix_recipe_capabilities_once()
from . import motion_beat_chart as _motion_beat_chart  # noqa: E402,F401
_motion_beat_chart.register_motion_beat_chart_capabilities_once()
