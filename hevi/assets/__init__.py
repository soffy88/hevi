"""Layer4 asset store — backing for E4 oskill.asset_reference_inject.

Assets carry per-shot reference constraints (character/scene/voice/prop/fx).
AssetRepository is the async DB layer; loader bridges to oskill's *synchronous*
asset_loader contract by pre-fetching referenced assets into a dict first.
"""
from hevi.assets.loader import load_asset_map, make_asset_loader
from hevi.assets.repository import ASSET_TYPES, AssetRepository

__all__ = ["AssetRepository", "ASSET_TYPES", "load_asset_map", "make_asset_loader"]
