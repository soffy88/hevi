"""hevi.studio —— 制片厂组合层。

把已内化的研究/评分/记忆/素材/发布/试播闸收成可调用工具,用 YAML 配方
排成产线,工单(slate)走统一 intake → 工具 → 履约产品线。
"""

from hevi.studio.assets import AssetRef, bind_asset, get_asset, list_assets, reset_assets
from hevi.studio.brick import ShotBrick, brick_from_payload, import_brick
from hevi.studio.daily import tick as tick_daily
from hevi.studio.fulfill import fulfill_order
from hevi.studio.mix import HistoryMix, plan_history_mix, split_history_script
from hevi.studio.recipes import Recipe, SlotSpec, get_recipe, list_recipes, load_recipes
from hevi.studio.runtime import select_runtime
from hevi.studio.slate import Slate, SlateResult, run_slate
from hevi.studio.tools import ToolResult, ToolSpec, invoke_tool, list_tools
from hevi.studio.veya import produce as produce_for_veya

__all__ = [
    "AssetRef",
    "HistoryMix",
    "Recipe",
    "ShotBrick",
    "Slate",
    "SlateResult",
    "SlotSpec",
    "ToolResult",
    "ToolSpec",
    "bind_asset",
    "brick_from_payload",
    "fulfill_order",
    "get_asset",
    "get_recipe",
    "import_brick",
    "invoke_tool",
    "list_assets",
    "list_recipes",
    "list_tools",
    "load_recipes",
    "plan_history_mix",
    "produce_for_veya",
    "reset_assets",
    "run_slate",
    "select_runtime",
    "split_history_script",
    "tick_daily",
]
