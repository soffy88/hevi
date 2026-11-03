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

# Native subtitle stitch (2026-11-01, clean-room, method ideas
# only): image.native_subtitle_stitch -- exact-frame subtitle
# stitching from local video files, native/script modes kept
# apart, rights declaration required. See
# NATIVE_SUBTITLE_STITCH_ATTRIBUTION.md (MIT method source).
from . import native_subtitle_stitch as _native_subtitle_stitch  # noqa: E402,F401
_native_subtitle_stitch.register_native_subtitle_stitch_capabilities_once()
from . import mix_recipe as _mix_recipe  # noqa: E402,F401
_mix_recipe.register_mix_recipe_capabilities_once()
from . import motion_beat_chart as _motion_beat_chart  # noqa: E402,F401
_motion_beat_chart.register_motion_beat_chart_capabilities_once()

# Creator-buddy P1/P2 intake (2026-10-28, clean-room): pipeline.spend_brake
# (storyboard plus machine-readable confirmed=true plus a single
# frame/segment smoke run before any paid batch), script.spoken_script_gate
# (per-sentence speakability issues with rewrites, no score),
# edit.speech_blemish_trim (live recordings only; TTS tracks are refused),
# design.cover_family (pinned colours/font/zones plus a 200px readability
# gate that is an arithmetic projection, never a viewed thumbnail), and
# research.reference_teardown (four questions from quoted evidence only,
# title risk reviews, structured transcripts; teardown only, no reuse).
# Method ideas only; no upstream code or text used. See
# CREATOR_BUDDY_ATTRIBUTION.md (license unverified).
from . import spend_brake as _spend_brake  # noqa: E402,F401
_spend_brake.register_spend_brake_capabilities_once()
from . import spoken_script as _spoken_script  # noqa: E402,F401
_spoken_script.register_spoken_script_capabilities_once()
from . import speech_blemish_trim as _speech_blemish_trim  # noqa: E402,F401
_speech_blemish_trim.register_speech_blemish_trim_capabilities_once()
from . import cover_family as _cover_family  # noqa: E402,F401
_cover_family.register_cover_family_capabilities_once()
from . import reference_teardown as _reference_teardown  # noqa: E402,F401
_reference_teardown.register_reference_teardown_capabilities_once()

# Productization P0 intake (2026-10-28, clean-room, method ideas only):
# pipeline.project_graph (editable node+edge project graph with
# success-recorded templates, on top of pipeline.project_handoff,
# not a second canvas), pipeline.project_snapshot (manual snapshots,
# default newest 20, restore backs up first, stale writes refused,
# conflict drafts; periodic scheduling is an unconnected stub),
# pipeline.spend_ledger (freeze + settle/refund + failed-item
# originals, completing pipeline.spend_brake; prices only from the
# caller), pipeline.smart_reference (prompt picture references
# resolved only against connected assets, skipped when ambiguous or
# unconnected), model.model_directory (listed is not verified;
# config change forces retest; fee prompted from caller figure),
# and pipeline.launch_gate (readiness report only, never a
# deployment). See PRODUCTIZATION_ATTRIBUTION.md (BeefTV method
# borrow, text self-written, not whole-repo MIT).
from . import project_graph as _project_graph  # noqa: E402,F401
_project_graph.register_project_graph_capabilities_once()
from . import project_snapshot as _project_snapshot  # noqa: E402,F401
_project_snapshot.register_project_snapshot_capabilities_once()
from . import spend_ledger as _spend_ledger  # noqa: E402,F401
_spend_ledger.register_spend_ledger_capabilities_once()
from . import smart_reference as _smart_reference  # noqa: E402,F401
_smart_reference.register_smart_reference_capabilities_once()
from . import model_directory as _model_directory  # noqa: E402,F401
_model_directory.register_model_directory_capabilities_once()
from . import launch_gate as _launch_gate  # noqa: E402,F401
_launch_gate.register_launch_gate_capabilities_once()

# Productization P1/P2 follow-up (2026-10-28, clean-room, method ideas only):
# pipeline.skill_version (fixed-version install, one-step rollback,
# private rewrites kept separate from the mainline, full version
# history), pipeline.preview_tasks (verbatim originals, on-demand
# single-threaded H.264 previews, queued/running/completed/failed
# tasks with retry keeping snapshot, reason and history), and
# qa.multimodal_review (supplement to qa.final_qc_gate only: two
# columns, deterministic gate verbatim plus a labelled model
# reference opinion; no model built in, no opinion invented when
# the caller injects none). See PRODUCTIZATION_ATTRIBUTION.md
# (BeefTV method borrow, text self-written, not whole-repo MIT).
from . import skill_version as _skill_version  # noqa: E402,F401
_skill_version.register_skill_version_capabilities_once()
from . import preview_tasks as _preview_tasks  # noqa: E402,F401
_preview_tasks.register_preview_tasks_capabilities_once()
from . import multimodal_review as _multimodal_review  # noqa: E402,F401
_multimodal_review.register_multimodal_review_capabilities_once()

# Talking-head gesture risk gate (2026-10-28, clean-room, method
# ideas only): video.gesture_risk_gate (tiered gestures, max 7
# distinct gestures, chest-to-cheek band, stressed-line anchors,
# person_first/evidence_first opening; high tier warns with a
# downgrade suggestion but does not fail). Written specs only:
# no sample video, no creator likeness, no MuseTalk rig
# connection. See TALKING_HEAD_SKILLS_ATTRIBUTION.md (MIT).
from . import gesture_risk_gate as _gesture_risk_gate  # noqa: E402,F401
_gesture_risk_gate.register_gesture_risk_gate_capabilities_once()

# Toonflow 3-5 minute stability intake (2026-10-29, clean-room,
# method ideas only): video.segment_assembly_gate (scenes into
# segments capped at the smaller of 15 seconds and the model
# limit, long lines split at semantic pauses without deleting
# words, one segment per generation node), story.asset_registry_v2
# (script / master asset / episode-reference layers, character
# four views, scene skeleton and light, derivatives with parent
# and changed/unchanged aspects, default extraction boundary,
# at most 5 variants per parent, pending material blocks
# generation), and qa.reference_number_gate (numbered references
# must resolve to the declared order, first-frame and
# multi-parameter modes kept apart, script text is never a
# connection). See TOONFLOW_ATTRIBUTION.md (MIT, repository only).
from . import segment_assembly as _segment_assembly  # noqa: E402,F401
_segment_assembly.register_segment_assembly_capabilities_once()
from . import asset_registry as _asset_registry  # noqa: E402,F401
_asset_registry.register_asset_registry_capabilities_once()
from . import reference_number_gate as _reference_number_gate  # noqa: E402,F401
_reference_number_gate.register_reference_number_gate_capabilities_once()

# Stable-film baseline B1-B7 (2026-10-29, clean-room, method ideas
# only): pipeline.stable_film_assembly (gated assembly: segment
# gate, asset-registry pending check, subtitle re-break with
# frame-measured safe zone, motion-beat gate over motion beats
# only, mix-recipe loudness, final QC; two strict confirmation
# points; finished / partial / review status, never a finished
# name for a failed or pending film). See the deep-dive report
# workspace/hevi-stable-film-deep-dive.md section 4.
from . import stable_film_pipeline as _stable_film_pipeline  # noqa: E402,F401
_stable_film_pipeline.register_stable_film_pipeline_capabilities_once()

# Code-studio workflow (2026-10-30, clean-room, method ideas only):
# pipeline.code_studio_workflow (six gated steps: brief, style note,
# shot table, beat grid, code-rendering checks, contact-sheet review
# and filing; strict confirmation between steps; no generation model
# called, no whole film rendered). Method ideas from Eian's essay on
# making video with code and the Lemo Opuscar skill; no wording or
# prompt text copied, Lemo styles read live via image.lemo_styles.
# Reuses pipeline.project_handoff (manifest), pipeline.spend_brake
# (strict-True confirmation semantics), design.cover_family
# (contrast), and video.code_render (tier table, landscape only).
from . import code_studio_workflow as _code_studio_workflow  # noqa: E402,F401
_code_studio_workflow.register_code_studio_workflow_capabilities_once()

# Pose reference library (2026-10-30, index only, no images bundled):
# image.pose_library (288 pose groups / 1439 records, 4 systems,
# 26 categories, 5 views, from anhao/ai-pose-gallery-zh; MIT covers
# source code only, images/data belong to the original author,
# non-commercial reference use only). See
# POSE_GALLERY_ATTRIBUTION.md. Paths resolve under
# HEVI_POSE_GALLERY_HOME; missing gallery/files fail by name.
from . import pose_library as _pose_library  # noqa: E402,F401
_pose_library.register_pose_library_capabilities_once()

# Colab hardware advisor (2026-10-30, clean-room, method ideas
# only): model.colab_hardware_advisor (classify a job, check it
# against a caller-supplied runtime snapshot, block an expensive
# first download unless explicitly forced, warn on an oversized
# runtime for a small job, suggest resident-model tuning on a
# large-memory runtime; no price table baked in, switches no
# runtime, calls no Colab API). See
# COLAB_HARDWARE_ADVISOR_ATTRIBUTION.md.
from . import colab_hardware_advisor as _colab_hardware_advisor  # noqa: E402,F401
_colab_hardware_advisor.register_colab_hardware_advisor_capabilities_once()

# Beginner science-film workflow (2026-10-31, clean-room, method
# ideas only): pipeline.beginner_science_workflow (seven-column
# script table, pause-marked narration segments, sample-first
# gate, A/B roll discipline, template registry, music on section
# changes; no TTS or video service called). See
# BEGINNER_SCIENCE_SOP_ATTRIBUTION.md.
from . import beginner_science_workflow as _beginner_science_workflow  # noqa: E402,F401
_beginner_science_workflow.register_beginner_science_workflow_capabilities_once()

# video-director P0 grafts (2026-10-31, clean-room, method ideas
# only): qa.timeline_gate (pre-render timeline check), qa.final_qc_gate
# defect scan (extension of the existing gate, default off),
# qa.rendered_text_measure (Otsu measurement), qa.critic_review
# (nine-axis review discipline + revision pixel identity) and
# qa.facts_discipline (three on-screen wording rules). See
# VIDEO_DIRECTOR_ATTRIBUTION.md (MIT, win4r/video-director).
from . import timeline_gate as _timeline_gate  # noqa: E402,F401
_timeline_gate.register_timeline_gate_capabilities_once()
from . import otsu_text as _otsu_text  # noqa: E402,F401
_otsu_text.register_rendered_text_capabilities_once()
from . import critic_review as _critic_review  # noqa: E402,F401
_critic_review.register_critic_review_capabilities_once()
from . import facts_discipline as _facts_discipline  # noqa: E402,F401
_facts_discipline.register_facts_discipline_capabilities_once()

# H3 character-sheet P0 grafts (2026-10-31, clean-room, method ideas
# only): qa.character_sheet_gate (fixed thirteen-view catalogue with
# a pending-not-fabricated missing-view rule, body-part scope table,
# reference-role policy; judges JSON plans only, no image generated,
# no ComfyUI). See H3_CHARACTER_SHEET_ATTRIBUTION.md (MIT method
# source, ukr8b3g-cmyk/H3-Character-Sheet-Designer; artwork, screenshots
# and weights expressly outside that licence).
from . import character_sheet as _character_sheet  # noqa: E402,F401
_character_sheet.register_character_sheet_capabilities_once()

# H3 character-sheet P1 grafts (2026-10-31, clean-room, method ideas
# only): qa.character_sheet_contract (versioned, strictly key-checked,
# byte-deterministic state contract with explicit migration,
# layout-guide ON/OFF discipline with self-drawn guides only, and a
# style-only-painting rule; judges JSON plans only, no image
# generated, no ComfyUI). See H3_CHARACTER_SHEET_ATTRIBUTION.md.
from . import character_sheet_contract as _character_sheet_contract  # noqa: E402,F401
_character_sheet_contract.register_character_sheet_contract_capabilities_once()

# SceneRef P0 grafts (2026-10-31, clean-room, method ideas only):
# pipeline.scene_reference (the single six-section reference-prompt
# format shared with the character sheet gate, a scene-first
# reference assembly record with slot budgets, and an
# intent/final separation gate; judges JSON plans only, no image
# generated, no ComfyUI). See SCENEREF_ATTRIBUTION.md (Apache-2.0
# method source, AliC-2001/ComfyUI-SceneRef-Nodes; artwork and
# weights expressly outside that licence).
from . import scene_reference as _scene_reference  # noqa: E402,F401
_scene_reference.register_scene_reference_capabilities_once()

# Prompt-quality fix (2026-10-31): qa.prompt_eval_harness (frozen
# prompt samples, offline measurements only; generation consistency
# is declared planned_not_measured, never scored without artifacts).
from . import prompt_eval_harness as _prompt_eval_harness  # noqa: E402,F401
_prompt_eval_harness.register_prompt_eval_harness_capabilities_once()

# 3D cartoon tutorial P0 grafts (2026-10-31, clean-room, method ideas
# only): qa.feedback_discipline (timestamp + part + expected, at most
# two changes per round, unmentioned parts frozen), pipeline.project_style_sheet
# (versioned project-local sheet with numeric fields, fresh sample
# required), and qa.voice_first_gate (shots cut to timed voice
# segments with word-level timing, planned_not_measured). See
# CARTOON_TUTORIAL_ATTRIBUTION.md (method only; no tutorial text
# or reference images copied).
from . import feedback_discipline as _feedback_discipline  # noqa: E402,F401
_feedback_discipline.register_feedback_discipline_capabilities_once()
from . import project_style_sheet as _project_style_sheet  # noqa: E402,F401
_project_style_sheet.register_project_style_sheet_capabilities_once()
from . import voice_first_gate as _voice_first_gate  # noqa: E402,F401
_voice_first_gate.register_voice_first_gate_capabilities_once()

# open-source-canvas P0 grafts (2026-10-31, clean-room, method ideas
# only): qa.comfy_gateway_contract (six-endpoint allowlist, body cap,
# visitor isolation, redacted health checks), qa.model_install_gate
# (pre-submit loader-visibility check against a caller-supplied
# snapshot), and pipeline.canvas_execution_schedule (ready batches,
# upstream-failure skip, interrupt cancel, one task per seed, single
# retry ceiling from canvas_workflow). Contract/plan only: no ComfyUI
# execution, no credentials, no collaboration room, no API wrappers.
# See OPEN_SOURCE_CANVAS_ATTRIBUTION.md (MIT method source,
# raph651/open-source-canvas).
from . import comfy_gateway_contract as _comfy_gateway_contract  # noqa: E402,F401
_comfy_gateway_contract.register_comfy_gateway_capabilities_once()
from . import model_install_gate as _model_install_gate  # noqa: E402,F401
_model_install_gate.register_model_install_capabilities_once()
from . import canvas_execution_schedule as _canvas_execution_schedule  # noqa: E402,F401
_canvas_execution_schedule.register_canvas_execution_capabilities_once()

# Qwen Image 2.1 licence gate (2026-10-31, clean-room, plan/licence
# only): model.qwen_image_license_gate (research/evaluation only
# under the Qwen Research License; commercial use needs a separate
# written licence; Turbo licence unverified; 24 GB int8 route only;
# speed unmeasured). No weights bundled, no generation performed.
# See QWEN_IMAGE_LICENSE_ATTRIBUTION.md.
from . import qwen_image_license_gate as _qwen_image_license_gate  # noqa: E402,F401
_qwen_image_license_gate.register_qwen_image_license_gate_capabilities_once()

# HyperFrames engine discipline (2026-10-31, clean-room; Apache-2.0
# method discipline, see HYPERFRAMES_ATTRIBUTION.md): converged __hf
# seek protocol + settle confirmation, deterministic render gate,
# render lint, frozen-picture/blur-settle gate, beats schema gate.
# CSK styles below are style templates, not the HeyGen engine.
from . import frame_adapter_contract as _frame_adapter_contract  # noqa: E402,F401
_frame_adapter_contract.register_frame_adapter_contract_capabilities_once()
from . import deterministic_render_gate as _deterministic_render_gate  # noqa: E402,F401
_deterministic_render_gate.register_deterministic_render_gate_capabilities_once()
from . import render_lint as _render_lint  # noqa: E402,F401
_render_lint.register_render_lint_capabilities_once()
from . import frozen_picture_gate as _frozen_picture_gate  # noqa: E402,F401
_frozen_picture_gate.register_frozen_picture_gate_capabilities_once()
from . import beats_schema_gate as _beats_schema_gate  # noqa: E402,F401
_beats_schema_gate.register_beats_schema_gate_capabilities_once()

# Floyo H3 registration (2026-10-31, registration only, no account /
# payment / promo code / network / generation): model.floyo_h3_registration
# records the Floyo-hosted Minimax_H3_Image_to_Video_OpenWeight workflow
# and the separate local H3 route in a model directory, both unverified;
# unstated claims stay "unverified". See floyo_h3_registration.py.
from . import floyo_h3_registration as _floyo_h3_registration  # noqa: E402,F401
_floyo_h3_registration.register_floyo_h3_registration_capabilities_once()

# Modal compute pricing (2026-11-01, registration only, no account /
# payment / API key / network / generation): model.modal_pricing_registration
# records the Starter / Team / Enterprise tiers from the modal.com/pricing
# page text read 2026-11-01, with per-second billing, billed 60-second
# keep-alive, 3x sandbox and non-preemptible multipliers and 1.15x-1.75x
# region multipliers. Per-unit GPU/CPU prices stay 'unverified'.
# See modal_pricing_registration.py.
from . import modal_pricing_registration as _modal_pricing_registration  # noqa: E402,F401
_modal_pricing_registration.register_modal_pricing_registration_capabilities_once()

# video-director residuals (2026-10-31, clean-room, method ideas
# only): qa.page_contract (DUR/FPS/seek/READY/TEXTS record judge;
# reverse-render diff is planned_not_measured without a reverse
# render), qa.director_dials (clock/continuity/register/
# text-policy + coupling rules; sound-clock contract carried as
# a declaration), qa.decision_log (append-only DECISION records
# with overturn-by-annotation), qa.ai_tells_ban (ban list +
# failure-to-repair table + plain-language symptom report).
# Main-path wiring for the earlier grafts (timeline gate, critic
# review, defect scan, Otsu measurement) lives in
# pipeline.stable_film_assembly / video.segment_assembly_gate /
# qa.final_qc_gate. See VIDEO_DIRECTOR_ATTRIBUTION.md (MIT,
# win4r/video-director).
from . import page_contract as _page_contract  # noqa: E402,F401
_page_contract.register_page_contract_capabilities_once()
from . import director_dials as _director_dials  # noqa: E402,F401
_director_dials.register_director_dials_capabilities_once()
from . import decision_log as _decision_log  # noqa: E402,F401
_decision_log.register_decision_log_capabilities_once()
from . import ai_tells_ban as _ai_tells_ban  # noqa: E402,F401
_ai_tells_ban.register_ai_tells_ban_capabilities_once()

# open-source-canvas P1-4 graft (2026-10-31, clean-room, method ideas
# only): pipeline.canvas_comfy_executor translates canvas_workflow
# video nodes into ComfyUI API graphs (template plus runtime
# injection, sizes snapped to the 32 grid) and submits them after
# the gateway contract and model-install gate, polling /history
# at 800 ms with a 10-minute timeout and cancelling via /interrupt.
# Tested only against a local fake ComfyUI server; no real ComfyUI
# generation has been run through it (GPU stopped). No
# collaboration room, no API wrappers, no H3 workflow, no 3D chain.
# See OPEN_SOURCE_CANVAS_ATTRIBUTION.md (MIT method source).
from . import canvas_comfy_executor as _canvas_comfy_executor  # noqa: E402,F401
_canvas_comfy_executor.register_canvas_comfy_executor_capabilities_once()

# Editorial project model (2026-10-31, clean-room, method ideas
# only): edit.editorial_project -- Asset-first references, clips
# pinned to concrete Assets, Takes with Original restore, lineage
# stored separately from canvas edges, and a revision-checked,
# idempotent incremental write path. Model only; no MCP layer,
# no browser canvas/timeline UI, no export, no provider adapter.
# See BEATDESIGN_ATTRIBUTION.md (Apache-2.0 method source).
from . import editorial_project as _editorial_project  # noqa: E402,F401
_editorial_project.register_editorial_project_capabilities_once()

# ASR line fix P0-P3 (2026-11-01): audio.asr_transcribe -- local
# faster-whisper transcription (default small, large-v3-turbo only as
# the coverage-triggered fallback), observed-side t2s normalisation
# plus the versioned audited glossary, all recorded in evidence.
# final_qc vo_asr calls it via audio_path; see asr_transcribe.py.
from . import asr_transcribe as _asr_transcribe  # noqa: E402,F401
_asr_transcribe.register_asr_transcribe_capabilities_once()

# Code-stage MV graft A1 + A2 + B1 (2026-11-01, clean-room, method
# ideas only, reconstructed from an article description): A1
# qa.greenscreen_generation_gate -- five greenscreen generation
# constraints judged on plan text only, reusing the strict
# prompt-compiler anchor / tier discipline; A2 extends
# pipeline.project_style_sheet with a stage block (lighting rig /
# camera path / particles / materials) under the existing
# version + stale discipline, stage plans missing lighting or
# camera fields stay pending; B1 qa.chroma_key_gate -- six
# chroma-key gates over offline frame measurements, FFmpeg
# chromakey route as contract only (see the sample recorded in
# /data/soffy/code-stage-sample/, not in this repo). No external
# account, no external video or article material, no SVG skeleton dance.
# See CODE_STAGE_MV_ATTRIBUTION.md.
from . import greenscreen_generation_gate as _greenscreen_generation_gate  # noqa: E402,F401
_greenscreen_generation_gate.register_greenscreen_generation_gate_capabilities_once()
from . import chroma_key_gate as _chroma_key_gate  # noqa: E402,F401
_chroma_key_gate.register_chroma_key_gate_capabilities_once()

# Code-stage MV graft B2 + B3 + B4 (2026-11-01, clean-room, method
# ideas only, reconstructed from an article description): B2
# qa.dance_action_events -- footstep / turn / raise_arm / hold
# events from an offline keypoint contract only (no pose
# estimator installed; synthetic-video runs are labelled
# synthetic_video, never human measurements); B3
# qa.event_trigger_wiring -- versioned event-to-music/stage
# mapping table, plan only, no music generated, tolerance
# calibrated from measured dual-template runs; B4
# video.minimal_stage_render -- minimal code-built Three.js
# stage, zero external assets, __hf + settle + atomic capture
# under the determinism gates, rendered twice with identical
# per-frame hashes. No external account, no external video or
# article material, no SVG skeleton dance. See
# CODE_STAGE_MV_ATTRIBUTION.md.
from . import dance_action_events as _dance_action_events  # noqa: E402,F401
_dance_action_events.register_dance_action_events_capabilities_once()
from . import event_trigger_wiring as _event_trigger_wiring  # noqa: E402,F401
_event_trigger_wiring.register_event_trigger_wiring_capabilities_once()
from . import minimal_stage_render as _minimal_stage_render  # noqa: E402,F401
_minimal_stage_render.register_minimal_stage_render_capabilities_once()

# Athenaion graft (2026-11-01, clean-room, method only; see
# ATHENAION_ATTRIBUTION.md): A1 world.athenaion_discipline +
# A2 qa.look_shot_separation, A3 qa.reference_restoration_gate,
# A4 pipeline.athenaion_session, B1 video.athenaion_world_engine,
# B2 world.athenaion_sdf_statue, B3
# world.athenaion_classical_orders, B4 video.athenaion_waterfall,
# B5 world.athenaion_vegetation_scatter. Appended at the tail only;
# earlier registrations (including native_subtitle_stitch) untouched.
from . import athenaion_contract as _athenaion_contract  # noqa: E402,F401
_athenaion_contract.register_athenaion_contract_capabilities_once()
from . import athenaion_restoration as _athenaion_restoration  # noqa: E402,F401
_athenaion_restoration.register_athenaion_restoration_capabilities_once()
from . import athenaion_session as _athenaion_session  # noqa: E402,F401
_athenaion_session.register_athenaion_session_capabilities_once()
from . import athenaion_world as _athenaion_world  # noqa: E402,F401
_athenaion_world.register_athenaion_world_capabilities_once()
from . import athenaion_statue as _athenaion_statue  # noqa: E402,F401
_athenaion_statue.register_athenaion_statue_capabilities_once()
from . import athenaion_orders as _athenaion_orders  # noqa: E402,F401
_athenaion_orders.register_athenaion_orders_capabilities_once()
from . import athenaion_waterfall as _athenaion_waterfall  # noqa: E402,F401
_athenaion_waterfall.register_athenaion_waterfall_capabilities_once()
from . import athenaion_vegetation as _athenaion_vegetation  # noqa: E402,F401
_athenaion_vegetation.register_athenaion_vegetation_capabilities_once()

# Seven-step video workflow graft (2026-11-01, clean-room, method
# only, reconstructed from an article description; see
# VIDEO_WORKFLOW_7STEPS_ATTRIBUTION.md): A1 qa.generation_spec_gate
# (four-item spec sheet, tier reuse, no invented numbers), A2
# qa.ban_revision_log (rule_id + supersede chain, retired text
# kept), A3 qa.verdict_vocabulary (single pass/fail/not_checked
# vocabulary for final_qc skipped and harness
# planned_not_measured), A4 qa.post_production_checklist (seven
# post items, generation side refused post work), B1
# qa.reference_role_gate (four roles, max four images, definition
# review; H3 route left not_checked under its own budget), B2
# qa.hardest_shot_pilot (hardest shot first + caller-supplied
# reserve fraction), B3 qa.three_layer_clip (three layers, one
# action + one camera move per segment; coexists with the
# six-section H3 structure, never redefines it), B4 qa.fix_ticket
# (timecode + segment + check item + verdict, evidence frame on
# fail). Appended at the tail only; earlier registrations
# (including native_subtitle_stitch) untouched.
#
# H3 exemplar gapfill (hevi-vs-h3-exemplar-prompts.md section 4,
# gaps 1/2/4): qa.reference_numbering_gate (declared numbering
# convention + camera_composition role + registered audio; the H3
# assembly route is judged here, never not_checked) and
# qa.segment_match_gate (cross-segment outgoing/incoming match).
# Appended at the tail only; earlier registrations untouched.
from . import generation_spec_gate as _generation_spec_gate  # noqa: E402,F401
_generation_spec_gate.register_generation_spec_gate_capabilities_once()
from . import ban_revision_log as _ban_revision_log  # noqa: E402,F401
_ban_revision_log.register_ban_revision_log_capabilities_once()
from . import verdict_vocabulary as _verdict_vocabulary  # noqa: E402,F401
_verdict_vocabulary.register_verdict_vocabulary_capabilities_once()
from . import post_production_checklist as _post_production_checklist  # noqa: E402,F401
_post_production_checklist.register_post_production_checklist_capabilities_once()
from . import reference_role_gate as _reference_role_gate  # noqa: E402,F401
_reference_role_gate.register_reference_role_gate_capabilities_once()
from . import hardest_shot_pilot as _hardest_shot_pilot  # noqa: E402,F401
_hardest_shot_pilot.register_hardest_shot_pilot_capabilities_once()
from . import three_layer_clip as _three_layer_clip  # noqa: E402,F401
_three_layer_clip.register_three_layer_clip_capabilities_once()
from . import fix_ticket as _fix_ticket  # noqa: E402,F401
_fix_ticket.register_fix_ticket_capabilities_once()
from . import reference_numbering_gate as _reference_numbering_gate  # noqa: E402,F401
_reference_numbering_gate.register_reference_numbering_gate_capabilities_once()
from . import segment_match_gate as _segment_match_gate  # noqa: E402,F401
_segment_match_gate.register_segment_match_gate_capabilities_once()

# open-3d-skills graft (2026-11-01, clean-room, method only;
# see OPEN_3D_SKILLS_ATTRIBUTION.md): A1 qa.virtual_clock_contract
# (virtual-clock recording contract), A2 qa.browser_check_matrix
# (Chromium + WebKit x 1440/768/390 matrix), A3
# qa.seam_loop_vocabulary (seam/loop scoring vocabulary, thresholds
# caller-supplied, no defaults), A4 qa.spend_preflight_checklist
# (spend preflight; budget rule reused from pipeline.spend_brake),
# A5 qa.transparent_delivery_contract (stacked-alpha / VP9 / WebP
# delivery; asset must separately pass qa.chroma_key_gate), B1
# video.virtual_clock_recorder (minimal virtual-clock recorder,
# __hf settle, two-run hash identity, not BeginFrame), B5
# world.threejs_imaging_upgrade (lighting presets, post stack,
# caller-supplied budget, quality tiers, vantages/flights; GTAO
# declared but not applied -- no vendored GTAO pass). Appended at
# the tail only; earlier registrations untouched.
from . import virtual_clock_contract as _virtual_clock_contract  # noqa: E402,F401
_virtual_clock_contract.register_virtual_clock_contract_capabilities_once()
from . import browser_check_matrix as _browser_check_matrix  # noqa: E402,F401
_browser_check_matrix.register_browser_check_matrix_capabilities_once()
from . import seam_loop_vocabulary as _seam_loop_vocabulary  # noqa: E402,F401
_seam_loop_vocabulary.register_seam_loop_vocabulary_capabilities_once()
from . import spend_preflight_checklist as _spend_preflight_checklist  # noqa: E402,F401
_spend_preflight_checklist.register_spend_preflight_checklist_capabilities_once()
from . import transparent_delivery_contract as _transparent_delivery_contract  # noqa: E402,F401
_transparent_delivery_contract.register_transparent_delivery_contract_capabilities_once()
from . import virtual_clock_recorder as _virtual_clock_recorder  # noqa: E402,F401
_virtual_clock_recorder.register_virtual_clock_recorder_capabilities_once()
from . import threejs_imaging_upgrade as _threejs_imaging_upgrade  # noqa: E402,F401
_threejs_imaging_upgrade.register_threejs_imaging_upgrade_capabilities_once()

# H3 exemplar gapfill 6+7 (2026-11-02, clean-room, method only;
# see H3_GAPFILL_6_7_ATTRIBUTION.md): qa.beat_floor_policy (default
# 1.0s floor identical to prompt_compiler gate 1, reviewed lower
# floors need a recorded reason, short-beat merging with an audit
# trail; no C-chain invented). Appended at the tail only; earlier
# registrations untouched.
from . import beat_floor_policy as _beat_floor_policy  # noqa: E402,F401
_beat_floor_policy.register_beat_floor_policy_capabilities_once()

# open-3d-skills B3/B4 (2026-11-02, clean-room, method only;
# see OPEN_3D_SKILLS_ATTRIBUTION.md): video.scroll_film_engine
# (keys-driven scroll film, 4-frame GOP, seam/loop judged by the
# seam vocabulary gate) and video.alpha_cutout_keyer (per-frame
# plate keying with edge despill; output must separately pass
# qa.chroma_key_gate). Appended at the tail only; earlier
# registrations untouched.
from . import scroll_film_engine as _scroll_film_engine  # noqa: E402,F401
_scroll_film_engine.register_scroll_film_engine_capabilities_once()
from . import alpha_cutout_keyer as _alpha_cutout_keyer  # noqa: E402,F401
_alpha_cutout_keyer.register_alpha_cutout_keyer_capabilities_once()

# <雨停之前> graft (2026-11-02, clean-room, method only;
# see RAIN_BEFORE_STOPS_ATTRIBUTION.md): A1 qa.story_intake_gate
# (five-item story intake + adjective stripping), A2
# qa.text_image_consistency_gate (written assertions vs picture
# inventory, window case), A3 qa.review_signoff_gate (author
# confirmation before the fix list, same-list recheck, old cut
# kept), A4 qa.issue_kind_labels (continuity / aesthetic /
# unconfirmed; unconfirmed never counts as pass), A5
# qa.version_cost_view (read-only per-version cost view, methods
# marked incomparable, no per-episode quote), B1
# video.draft_task_ledger (fake backend: 7-day draft task ids,
# 1080p-only conversion, local files never substitute for an id),
# B2 model.seedance_pricing_registration (Ark list prices with
# source and date, derived figures flagged unverified, no key).
# Appended at the tail only; earlier registrations untouched.
from . import story_intake_gate as _story_intake_gate  # noqa: E402,F401
_story_intake_gate.register_story_intake_gate_capabilities_once()
from . import text_image_consistency_gate as _text_image_consistency_gate  # noqa: E402,F401
_text_image_consistency_gate.register_text_image_consistency_gate_capabilities_once()
from . import review_signoff_gate as _review_signoff_gate  # noqa: E402,F401
_review_signoff_gate.register_review_signoff_gate_capabilities_once()
from . import issue_kind_labels as _issue_kind_labels  # noqa: E402,F401
_issue_kind_labels.register_issue_kind_labels_capabilities_once()
from . import version_cost_view as _version_cost_view  # noqa: E402,F401
_version_cost_view.register_version_cost_view_capabilities_once()
from . import draft_task_ledger as _draft_task_ledger  # noqa: E402,F401
_draft_task_ledger.register_draft_task_ledger_capabilities_once()
from . import seedance_pricing_registration as _seedance_pricing_registration  # noqa: E402,F401
_seedance_pricing_registration.register_seedance_pricing_capabilities_once()

# <oyasumi-gamedev> graft (2026-11-02, clean-room, method only;
# see OYASUMI_GAMEDEV_ATTRIBUTION.md): A1 qa.panel_contrast_gate
# (importance tiers, contrast basis, break cues, gutter pauses as
# not_checked), A2 qa.camera_baseline_drop_gate (baseline, one-axis
# drop, bridge), A3 qa.emotion_orientation_vocabulary (action
# direction plus five-part orientations, declared compound intent),
# A4 qa.effect_restraint_gate (one lead effect, layer-off check,
# caller thresholds), A5 qa.stage_freeze_gate (stage order, frozen
# inputs, declared re-review), B1 video.single_image_sway
# (caller-zoned still-picture sway, deterministic), B2
# qa.parametric_pose_template (caller ranges, counter-swing /
# counter-twist, hevi pose JSON plus stick silhouette; no VRMA).
# Appended at the tail only; earlier registrations untouched.
from . import panel_contrast_gate as _panel_contrast_gate  # noqa: E402,F401
_panel_contrast_gate.register_panel_contrast_gate_capabilities_once()
from . import camera_baseline_drop_gate as _camera_baseline_drop_gate  # noqa: E402,F401
_camera_baseline_drop_gate.register_camera_baseline_drop_gate_capabilities_once()
from . import emotion_orientation_vocabulary as _emotion_orientation_vocabulary  # noqa: E402,F401
_emotion_orientation_vocabulary.register_emotion_orientation_capabilities_once()
from . import effect_restraint_gate as _effect_restraint_gate  # noqa: E402,F401
_effect_restraint_gate.register_effect_restraint_gate_capabilities_once()
from . import stage_freeze_gate as _stage_freeze_gate  # noqa: E402,F401
_stage_freeze_gate.register_stage_freeze_gate_capabilities_once()
from . import single_image_sway as _single_image_sway  # noqa: E402,F401
_single_image_sway.register_single_image_sway_capabilities_once()
from . import parametric_pose_template as _parametric_pose_template  # noqa: E402,F401
_parametric_pose_template.register_parametric_pose_template_capabilities_once()

# <prefixstream> graft (clean-room, method only; see
# PREFIXSTREAM_ATTRIBUTION.md): A1 qa.continuation_grid_gate (5+17k
# grid, compile-time snap, fasth3/h3 calibres separate), A2
# qa.continuation_source_gate (real product id + sha256, no tags
# field, no auto-promoted references), A3 qa.clip_lineage_schema
# (parent lineage, human-only rating, DAG selection branches), A4
# qa.disk_stream_gate (segmented disk writes + manifest, geometry
# rejection, seam handling declared separately), A5
# qa.degradation_ledger (consecutive order, named sources, filled
# observations; unfilled is not_checked, unverified remedies never
# defaults). Appended at the tail only; earlier registrations
# untouched.
from . import continuation_grid_gate as _continuation_grid_gate  # noqa: E402,F401
_continuation_grid_gate.register_continuation_grid_gate_capabilities_once()
from . import continuation_source_gate as _continuation_source_gate  # noqa: E402,F401
_continuation_source_gate.register_continuation_source_gate_capabilities_once()
from . import clip_lineage_schema as _clip_lineage_schema  # noqa: E402,F401
_clip_lineage_schema.register_clip_lineage_schema_capabilities_once()
from . import disk_stream_gate as _disk_stream_gate  # noqa: E402,F401
_disk_stream_gate.register_disk_stream_gate_capabilities_once()
from . import degradation_ledger as _degradation_ledger  # noqa: E402,F401
_degradation_ledger.register_degradation_ledger_capabilities_once()

# <digital-human-koubo recheck> graft (2026-11-02, clean-room,
# method only; see DIGITAL_HUMAN_KOUBO_ATTRIBUTION.md): A1
# qa.first_segment_confirmation_gate (first segment confirmed,
# dual sign-off reused, retake needs a fresh quote), A2
# qa.segment_listenback_gate (per-segment ASR listen-back record
# before assembly), A3 qa.misread_judgement_gate (word-by-word
# comparison, prompted transcripts are not pronunciation
# evidence, three judgement classes), A4
# qa.av_duration_consistency_gate (caller tolerance, drift repair
# chain, missing tolerance is not_checked), A5
# qa.reference_account_binding_gate (account binding declared,
# demo/author ids refused), B1 video.segment_cost_ledger (fake
# local ledger, sourced prices only, over-budget blocked,
# registered rates flagged unverified), B4
# qa.packaging_component_vocabulary (method index in hevi's own
# words, purpose + constraint per use, no template text).
# B2/B3 blocked (need real audio evidence, a voice-clone key,
# and the speaker's own recording). Appended at the tail only;
# earlier registrations untouched.
from . import first_segment_confirmation_gate as _first_segment_confirmation_gate  # noqa: E402,F401
_first_segment_confirmation_gate.register_first_segment_confirmation_gate_capabilities_once()
from . import segment_listenback_gate as _segment_listenback_gate  # noqa: E402,F401
_segment_listenback_gate.register_segment_listenback_gate_capabilities_once()
from . import misread_judgement_gate as _misread_judgement_gate  # noqa: E402,F401
_misread_judgement_gate.register_misread_judgement_gate_capabilities_once()
from . import av_duration_consistency_gate as _av_duration_consistency_gate  # noqa: E402,F401
_av_duration_consistency_gate.register_av_duration_consistency_gate_capabilities_once()
from . import reference_account_binding_gate as _reference_account_binding_gate  # noqa: E402,F401
_reference_account_binding_gate.register_reference_account_binding_gate_capabilities_once()
from . import segment_cost_ledger as _segment_cost_ledger  # noqa: E402,F401
_segment_cost_ledger.register_segment_cost_ledger_capabilities_once()
from . import packaging_component_vocabulary as _packaging_component_vocabulary  # noqa: E402,F401
_packaging_component_vocabulary.register_packaging_component_vocabulary_capabilities_once()

# Toonflow recheck graft (see TOONFLOW_RECHECK_ATTRIBUTION.md):
# A1 qa.reference_map_contract, A2 qa.sandbox_material_reference_gate,
# A3 qa.task_recovery_gate, B1 video.reference_map_adapter,
# B2 qa.task_recovery_contract (fake execution adapters; no provider
# calls, no keys, no sponsor pricing as thresholds).
from . import reference_map_contract as _reference_map_contract  # noqa: E402,F401
_reference_map_contract.register_reference_map_contract_capabilities_once()
from . import sandbox_material_reference_gate as _sandbox_material_reference_gate  # noqa: E402,F401
_sandbox_material_reference_gate.register_sandbox_material_reference_gate_capabilities_once()
from . import task_recovery_gate as _task_recovery_gate  # noqa: E402,F401
_task_recovery_gate.register_task_recovery_gate_capabilities_once()
from . import reference_map_adapter as _reference_map_adapter  # noqa: E402,F401
_reference_map_adapter.register_reference_map_adapter_capabilities_once()
from . import task_recovery_contract as _task_recovery_contract  # noqa: E402,F401
_task_recovery_contract.register_task_recovery_contract_capabilities_once()

# ai-manju graft (see AI_MANJU_ATTRIBUTION.md):
# A1 qa.season_pack_gate, A2 qa.reference_use_gate,
# A3 qa.status_card_monotonic_gate, A4 qa.dialogue_timeline_gate,
# A5 qa.genre_scale_table_gate, B1 story.genre_rhythm_pack,
# B2 story.director_handbook_compiler (clean-room, method only;
# no template text, no Mixed N, no model routing or pricing).
from . import season_pack_gate as _season_pack_gate  # noqa: E402,F401
_season_pack_gate.register_season_pack_gate_capabilities_once()
from . import reference_use_gate as _reference_use_gate  # noqa: E402,F401
_reference_use_gate.register_reference_use_gate_capabilities_once()
from . import status_card_monotonic_gate as _status_card_monotonic_gate  # noqa: E402,F401
_status_card_monotonic_gate.register_status_card_monotonic_gate_capabilities_once()
from . import dialogue_timeline_gate as _dialogue_timeline_gate  # noqa: E402,F401
_dialogue_timeline_gate.register_dialogue_timeline_gate_capabilities_once()
from . import genre_scale_table_gate as _genre_scale_table_gate  # noqa: E402,F401
_genre_scale_table_gate.register_genre_scale_table_gate_capabilities_once()
from . import genre_rhythm_pack as _genre_rhythm_pack  # noqa: E402,F401
_genre_rhythm_pack.register_genre_rhythm_pack_capabilities_once()
from . import director_handbook_compiler as _director_handbook_compiler  # noqa: E402,F401
_director_handbook_compiler.register_director_handbook_compiler_capabilities_once()

# VidoGrid pricing registration (see VIDOGRID_ATTRIBUTION.md):
# model.vidogrid_pricing_registration (free plan + free/paid model
# tables + credit rate from the public pages read 2026-11-02;
# registration only, no key, no API, no generation).
from . import vidogrid_pricing_registration as _vidogrid_pricing_registration  # noqa: E402,F401
_vidogrid_pricing_registration.register_vidogrid_pricing_capabilities_once()

# pixelaigc single-segment H3 workflow (see PIXELAIGC_H3_WORKFLOW_ATTRIBUTION.md):
# qa.h3_config_registration + qa.h3_frame_align_gate + qa.h3_stale_defaults_gate
# + video.h3_single_segment_adapter (fake) + qa.h3_config_equivalence_protocol.
# Clean-room restatement only; no workflow JSON, no weights, no licence asserted.
from . import h3_config_registration as _h3_config_registration  # noqa: E402,F401
_h3_config_registration.register_h3_config_registration_capabilities_once()
from . import h3_frame_align_gate as _h3_frame_align_gate  # noqa: E402,F401
_h3_frame_align_gate.register_h3_frame_align_gate_capabilities_once()
from . import h3_stale_defaults_gate as _h3_stale_defaults_gate  # noqa: E402,F401
_h3_stale_defaults_gate.register_h3_stale_defaults_gate_capabilities_once()
from . import h3_single_segment_adapter as _h3_single_segment_adapter  # noqa: E402,F401
_h3_single_segment_adapter.register_h3_single_segment_adapter_capabilities_once()
from . import h3_config_equivalence_protocol as _h3_config_equivalence_protocol  # noqa: E402,F401
_h3_config_equivalence_protocol.register_h3_config_equivalence_protocol_capabilities_once()
