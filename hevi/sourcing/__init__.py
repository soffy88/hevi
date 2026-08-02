"""Layer 4 素材供给域 (sourcing) — 3O §3 Task 3.1 收拢。

合并原 hevi/stock/(Pexels 素材检索 + 出处持久化)与 hevi/assets/(E4 资产库)
为单一 sourcing 域:

    stock_search.py   # Pexels 及云端素材检索 (oprim 边界)
    match_score.py    # 素材与剧本对位校验算法 (oskill 边界,纯算法)
    loader_bridge.py  # 资产库加载桥接 (obase 适配,oskill asset_reference_inject 契约)

对外符号与原 hevi.stock / hevi.assets 完全兼容(零回归迁移)。
"""

from hevi.sourcing.loader_bridge import (
    ASSET_TYPES,
    AssetRepository,
    load_asset_map,
    make_asset_loader,
)
from hevi.sourcing.match_score import calculate_stock_match_score
from hevi.sourcing.stock_search import (
    StockAssetRepository,
    StockProviderError,
    StockProviderUnavailable,
    StockSearchService,
)

__all__ = [
    "ASSET_TYPES",
    "AssetRepository",
    "StockAssetRepository",
    "StockProviderError",
    "StockProviderUnavailable",
    "StockSearchService",
    "calculate_stock_match_score",
    "load_asset_map",
    "make_asset_loader",
]
