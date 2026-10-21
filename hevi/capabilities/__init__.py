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
