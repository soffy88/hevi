"""Bridge hevi's async asset store to oskill's synchronous asset_loader contract.

oskill.asset_reference_inject(*, shot_spec, asset_refs, asset_loader) calls
asset_loader(asset_type, asset_id) -> dict | None **synchronously**, but hevi's
assets live in async Postgres. So we pre-fetch all referenced assets (async),
then hand asset_reference_inject a sync dict-backed loader.

Typical usage at the injection boundary:

    asset_map = await load_asset_map(repo, asset_refs)
    loader = make_asset_loader(asset_map)
    enriched = asset_reference_inject(
        shot_spec=spec, asset_refs=asset_refs, asset_loader=loader
    )
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hevi.assets.repository import AssetRepository


async def load_asset_map(
    repo: AssetRepository, asset_refs: dict[str, str]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Pre-fetch every referenced asset, keyed by (ref_key, asset_id).

    asset_refs maps {character_id, scene_id, ...} -> asset-id. We key the map by
    the *ref key* (e.g. "character_id") because oskill.asset_reference_inject
    invokes asset_loader(key, asset_id) with that exact key. The asset's stored
    asset_type is verified against the key (trailing '_id' stripped) so a wrong
    type id won't resolve. Missing / deleted / type-mismatched refs are omitted.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, asset_id in asset_refs.items():
        if not asset_id:
            continue
        asset_type = key[:-3] if key.endswith("_id") else key
        asset = await repo.get(asset_id)
        if asset is not None and asset.get("asset_type") == asset_type:
            out[(key, asset_id)] = asset
    return out


def make_asset_loader(
    asset_map: dict[tuple[str, str], dict[str, Any]],
) -> Callable[[str, str], dict[str, Any] | None]:
    """Return a sync loader over a pre-fetched asset map (E4 contract).

    The first arg is the ref key that asset_reference_inject passes through
    (e.g. "character_id"), matching how load_asset_map keys the map.
    """

    def _loader(ref_key: str, asset_id: str) -> dict[str, Any] | None:
        return asset_map.get((ref_key, asset_id))

    return _loader
