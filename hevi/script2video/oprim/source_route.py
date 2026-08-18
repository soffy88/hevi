"""把用户输入路由到 idea / script / novel / cameo。

3O 归属(待上游): `oprim.source_route`。确认门仍由 hevi 工作流来问。
"""

from __future__ import annotations

from hevi.script2video.adapter_schemas import SourceKind

_SCRIPT_MARKERS = ("EXT.", "INT.", "FADE IN", "CUT TO", "角色：", "场次")


def classify_source(
    text: str,
    *,
    has_photos: bool = False,
    explicit: SourceKind | None = None,
) -> SourceKind:
    if explicit is not None:
        return explicit
    if has_photos:
        return "cameo"
    blob = text or ""
    if any(marker in blob for marker in _SCRIPT_MARKERS):
        return "script"
    if len(blob) >= 2000 and blob.count("\n") >= 8:
        return "novel"
    return "idea"
