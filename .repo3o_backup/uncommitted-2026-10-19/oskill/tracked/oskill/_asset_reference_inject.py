"""K-asset_reference_inject: inject asset references into shot_spec (injection pattern).

Layer4 (hevi) owns the asset DB. oskill only does the mechanical injection:
  - resolve each ref ID via asset_loader (if provided)
  - merge resolved asset data into shot_spec under standardized keys
  - asset_loader=None → skip loading, inject raw ref IDs as-is (staging/dry-run)
"""

from __future__ import annotations

_ASSET_KEYS = ("character_id", "scene_id", "voice_id", "prop_id", "fx_id")


def asset_reference_inject(
    *,
    shot_spec: dict,
    asset_refs: dict,
    asset_loader,
) -> dict:
    """Inject asset references into shot_spec.

    asset_refs: {character_id: "char_001", scene_id: "scene_002", voice_id: "voice_v1", ...}
    asset_loader: callable(asset_type: str, asset_id: str) -> dict  (Layer4-injected)
                  None → inject raw ref IDs without loading.

    Returns a new dict (shot_spec not mutated) with _assets key containing
    all resolved or raw references.
    """
    result = dict(shot_spec)
    resolved: dict[str, dict | str] = {}

    for key, asset_id in asset_refs.items():
        if not asset_id:
            continue
        if asset_loader is not None:
            try:
                data = asset_loader(key, asset_id)
                resolved[key] = data if data is not None else asset_id
            except Exception:
                resolved[key] = asset_id
        else:
            resolved[key] = asset_id

    result["_assets"] = resolved
    return result
