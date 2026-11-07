"""Hevi Huobao package — short-drama agent layer absorbed from huobao-drama.

Implements:
1. Asset registry & cross-episode dedup (Character, Scene, Prop).
2. Keyframe generation for assets & shots (CPU guofeng_anime preset).
3. Storyboard @ref syntax resolution (@角色/@场景/@道具).
4. Tone-aware novel-to-screenplay rewriter with verbatim dialogue preservation.
5. Batch estimation, failed-shot retry, and merge validation.

Status (2026-10-20, verified against the code — read this before assuming
what this package can do):

- Positioning: this is the adaptation + shot-preparation layer of the
  short-drama line (novel -> screenplay rewrite, asset registry/dedup,
  keyframes, batch estimate/retry/merge pre-check). Whole-season planning
  is NOT here: it lives in ``hevi/shortdrama`` (``plan_longform_drama``),
  ``hevi/storygraph`` and ``hevi/season_planner``.
- The rewriter (``rewrite.py``) calls no LLM at all: it is deterministic
  regex/template segmentation with verbatim-dialogue enforcement, so it
  costs nothing. The planning layer in ``hevi/shortdrama`` /
  ``storygraph`` / ``season_planner`` is the part that uses an LLM, via
  ``hevi.shortdrama.llm_channel.resolve_planning_llm`` ->
  ``hevi.providers.free_llm.resolve_free_llm`` (free/local channels only,
  ``settings.dramaplan_llm_channel`` default ``auto``; never the paid
  DashScope ``qwen_cloud``). Do not attribute that LLM channel to huobao.
- Rendering: huobao DOES render single shots itself — capability
  ``huobao.shot`` (SD-Turbo keyframe + Piper TTS + Ken Burns via ffmpeg)
  plus ``huobao.character_ref`` / ``huobao.scene_ref`` stills, all
  CPU-only and free. It does NOT assemble a finished episode/film: there
  is no merge/render-out implementation here, only
  ``validate_merge_prerequisites`` (a pre-merge file check). Finished
  pieces are assembled downstream by the consuming product line / studio
  pipeline from the per-shot clips huobao produces.
- Capability catalogue: the three capabilities above exist and are
  tested, but registration is lazy — ``register_huobao_capabilities()``
  runs only as an import side effect of the API routers
  (``hevi/api/routers/huobao.py``, ``hevi/api/routers/capabilities.py``)
  or when a caller imports ``hevi.huobao.capabilities`` directly. Unlike
  the bundled families, huobao is NOT auto-registered in
  ``hevi/capabilities/__init__.py``, and the three names are absent from
  the generated catalogue (``docs/generated/capability_catalogue.json``).
  To be listed there, huobao needs: (1) auto-registration wiring in
  ``hevi/capabilities/__init__.py`` following the other families, and
  (2) a catalogue regeneration that includes them.
"""

from __future__ import annotations

from hevi.huobao.assets import (
    AssetRegistry,
    CharacterAsset,
    PropAsset,
    SceneAsset,
    normalize_name,
)
from hevi.huobao.batch import (
    BatchEstimate,
    MissingClipPrerequisiteError,
    ShotTask,
    estimate_batch,
    retry_failed_shots,
    validate_merge_prerequisites,
)
from hevi.huobao.refs import (
    ResolvedPrompt,
    UnknownAssetReferenceError,
    parse_references,
    resolve_references,
)
from hevi.huobao.rewrite import (
    TONES,
    rewrite_novel_to_screenplay,
    verify_dialogue_retention,
)
from hevi.huobao.capabilities import (
    register_huobao_capabilities,
)

__all__ = [
    "TONES",
    "AssetRegistry",
    "BatchEstimate",
    "CharacterAsset",
    "MissingClipPrerequisiteError",
    "PropAsset",
    "ResolvedPrompt",
    "SceneAsset",
    "ShotTask",
    "UnknownAssetReferenceError",
    "estimate_batch",
    "normalize_name",
    "parse_references",
    "register_huobao_capabilities",
    "resolve_references",
    "retry_failed_shots",
    "rewrite_novel_to_screenplay",
    "validate_merge_prerequisites",
    "verify_dialogue_retention",
]
