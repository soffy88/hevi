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

# Handdraw line (merged from feat/handdraw-line): importing registers the four
# handdraw capabilities (handdraw.full / storyboard / narration / illustration)
# on the unified registry.  Heavy pipeline imports stay inside the render fns.
from . import handdraw  # noqa: E402,F401

# Partsci line (merged from feat/particle-science): importing registers
# particle_text / particle_science_scene / parallax_layers.
from hevi.partsci.capabilities import register_partsci_capabilities_once
register_partsci_capabilities_once()

# GOLIVE3 capabilities (assets.library, assets.extract, image.multi_ref_compose, style.project_snapshot, storyboard.shot_groups)
from . import golive3 as _golive3  # noqa: E402,F401
_golive3.register_golive3_capabilities_once()

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


# Kids / anime safety gates (``qa.kids_gate``, ``kids.story_gate``,
# ``kids.consistency_manifest``) are registered by importing the registry.
# ``registry.register`` is import-triggered for these three so every line can
# --- grafted from main closure branch 2026-10-21 (score_render sampled /
# music_analyze / expression_rig transplant; module files copied verbatim) ---

# Score render (audio.score_render): ABC score -> wav, synth + sampled
# real-instrument timbres (hevi.audio.sampled, vendored VCSL samples).
from . import score_render as _score_render  # noqa: E402,F401
_score_render.register_score_render_capabilities_once()

# Music analysis pipeline (audio.music_analyze): librosa structured
# report (duration/BPM/beats/downbeats/onsets/sections/loudness),
# optional whisper_local lyrics timings; Demucs stems downgraded out.
from . import music_analyze as _music_analyze  # noqa: E402,F401
_music_analyze.register_music_analyze_capabilities_once()

# Hand-drawn character expression rig (image.expression_rig /
# image.expression_contact_sheet): views x emotions x combinable parts
# over an original demo character; see docs/rules/expression_rig.md.
from . import expression_rig as _expression_rig  # noqa: E402,F401
_expression_rig.register_expression_rig_capabilities_once()

# Story film lines (story.film_from_prompt / story.oneclick_film):
# one-sentence premise -> story -> images -> LuxTTS narration ->
# alignment -> sampled score -> motion render -> film_gate/earshot
# gates; oneclick adds presets, rig faces and the gate-retry policy.
from . import storyfilm as _storyfilm  # noqa: E402,F401
_storyfilm.register_storyfilm_capabilities_once()

# Earshot audio gate + SFX bank (audio.earshot_gate / audio.sfx_render):
# model-free, local earshot CLI under ~/.venvs/earshot.
from . import earshot_gate as _earshot_gate  # noqa: E402,F401
_earshot_gate.register_earshot_capabilities_once()

# Structured review sheet (qa.review_sheet): cross-line review comments.
from . import review_sheet as _review_sheet  # noqa: E402,F401
_review_sheet.register_review_sheet_capabilities_once()

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

# G5 port (2026-10-24): capabilities ported from main closure branch.
# 57 audit-gap items + 6 shadow items + talking_head.render (G14).
# scene3d.generic deliberately NOT wired here: its module file is
# other-line untracked work in main (see launch report); preflight.*
# is the other line's scope and is not ported in this wave.
from . import svfactory as _svfactory  # noqa: E402,F401
from . import rough_stroke as _rough_stroke  # noqa: E402,F401
_rough_stroke.register_rough_stroke_capabilities_once()
from hevi.manga.capabilities import register_manga_capabilities  # noqa: E402
register_manga_capabilities()
import hevi.capabilities.brandfilm  # noqa: E402,F401
import hevi.capabilities.webrender  # noqa: E402,F401
import hevi.capabilities.motion_taste  # noqa: E402,F401
from hevi.riso.capabilities import register_riso_capabilities  # noqa: E402
register_riso_capabilities()
from . import multimodel as _multimodel  # noqa: E402,F401
_multimodel.register_multimodel_capabilities_once()
from . import export_qa as _export_qa  # noqa: E402,F401
_export_qa.register_export_qa_capabilities_once()
from . import beat_align as _beat_align  # noqa: E402,F401
_beat_align.register_beat_align_capabilities_once()
from . import pixstag as _pixstag  # noqa: E402,F401
_pixstag.register_pixstag_capabilities_once()
from . import csk_styles as _csk_styles  # noqa: E402,F401
_csk_styles.register_csk_capabilities_once()
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
from hevi.huobao.capabilities import register_huobao_capabilities as _register_huobao  # noqa: E402
_register_huobao()
from . import watercolor as _watercolor  # noqa: E402,F401
_watercolor.register_watercolor_capabilities_once()
from . import maproute as _maproute  # noqa: E402,F401
_maproute.register_maproute_capabilities_once()
from . import blender_clay as _blender_clay  # noqa: E402,F401
_blender_clay.register_blender_clay_capabilities_once()
from . import handraw_styles as _handraw_styles  # noqa: E402,F401
_handraw_styles.register_handraw_style_capabilities_once()
from . import rhythm_sheet as _rhythm_sheet  # noqa: E402,F401
_rhythm_sheet.register_rhythm_sheet_capabilities()
# Shadow capabilities (G13, same wiring as main).
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
# Talking-head presenter line (G14).
from . import talking_head as _talking_head  # noqa: E402,F401
_talking_head.register_talking_head_capabilities_once()

# scene3d.generic -- UNCOMMITTED by design (G13 evasion): the module file
# + engine are other-line untracked work in main; this wiring + the files
# stay uncommitted in pubfix until that line commits them in main.
from . import scene3d_generic as _scene3d_generic  # noqa: E402,F401
