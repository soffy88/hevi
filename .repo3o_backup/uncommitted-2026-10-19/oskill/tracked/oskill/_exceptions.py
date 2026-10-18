"""oskill 异常 shim — canonical 定义在 oskill._types (含子类层次).

此模块仅做单源 re-export,避免出现第二个 OskillError 类导致
isinstance/except 失效 (曾导致 except OskillError 漏捕 _types.OskillError)。
"""

from __future__ import annotations

from oskill._types import OskillError

__all__ = ["OskillError"]
