"""stickdir FX source —— 把 5 种火柴人风格注册进 fx registry。

**TODO(stickdir): register styles in fx registry after feat/fx-registry merges.**

本分支(``feat/stickman-director``)上没有 ``hevi/fx`` 包 —— 它只在
``feat/fx-registry`` 分支上。试合并该分支会改动受保护文件
(``hevi/prompt/style_presets.py`` / ``hevi/studio/*``), 故按 STICKDIR_TASK.md §(c)
的约定未合并, 改为在这里提供符合 fx-registry 约定的 source 模块:

* 该分支的约定(见 ``feat/fx-registry:hevi/fx/sources/sfx.py``):每个 source 暴露一个
  ``load_<source>()``, 返回 ``FXTemplate`` 列表, 字段 ``id``/``name_zh``/``category``/
  ``source``/``source_ref``/``tags``/``duration_hint``。id 用 ``<source>:<slug>``。
* 合并 ``feat/fx-registry`` 后, 只需在 ``hevi/fx/sources/__init__.py`` 加一行
  ``from hevi.fx_sources.stickdir import load_stickdir``, 并在 ``loader.load_all``
  的 source 循环里加 ``("stickdir", load_stickdir)``, 即可让 5 个风格进入统一目录。

为了让本分支也能独立验证, 本模块的 :func:`templates_as_dicts` 返回与 ``FXTemplate``
同构的 dict(不 import 未合并的 ``hevi.fx``), 测试据此校验注册约定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hevi.layer4_legacy.stickdir import styles

#: fx-registry 的 4 个类别(见 feat/fx-registry:hevi/fx/registry.py Category)
CATEGORY = "style"

#: 风格 → (slug, 中文名, tags, 代表时长提示)
_META: dict[str, tuple[str, str, list[str], float | None]] = {
    "1A": ("classic-light", "经典极简·亮", ["stickman", "minimalist", "light", "white"], None),
    "1B": ("classic-dark", "经典极简·暗", ["stickman", "minimalist", "dark", "black"], None),
    "2A": ("studio-tech", "现代毛线帽·工作室科技", ["stickman", "beanie", "studio", "tech"], None),
    "2B": ("cinematic-story", "现代毛线帽·电影故事", ["stickman", "beanie", "cinematic"], None),
    "3": ("prehistoric", "史前手绘·黑色幽默", ["stickman", "prehistoric", "cartoon"], None),
}


@dataclass(slots=True)
class StickdirTemplate:
    """与 fx-registry ``FXTemplate`` 同构的最小条目。"""

    id: str
    name_zh: str
    category: str
    source: str
    source_ref: str | None = None
    tags: list[str] = field(default_factory=list)
    duration_hint: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name_zh": self.name_zh,
            "category": self.category,
            "source": self.source,
            "source_ref": self.source_ref,
            "tags": list(self.tags),
            "duration_hint": self.duration_hint,
        }


def templates_as_dicts() -> list[dict[str, Any]]:
    """返回 5 个火柴人风格的注册条目(与 FXTemplate 同构的 dict)。"""
    out: list[dict[str, Any]] = []
    for key in styles.ALL:
        slug, name_zh, tags, dur = _META[key]
        out.append(
            {
                "id": f"stickdir:{slug}",
                "name_zh": f"火柴人·{name_zh}",
                "category": CATEGORY,
                "source": "stickdir",
                "source_ref": key,
                "tags": ["stickman", key.lower(), *tags],
                "duration_hint": dur,
            }
        )
    return out


def load_stickdir() -> list[Any]:
    """fx-registry 约定的加载器。

    当 ``hevi.fx`` 存在(即 ``feat/fx-registry`` 合并后)时, 返回真正的
    ``FXTemplate`` 列表;否则返回同构 dict, 保证本分支不依赖未合并模块。
    """
    rows = templates_as_dicts()
    try:
        from hevi.fx.registry import Category, FXTemplate, Source  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - 未合并分支: 返回同构 dict
        return rows
    return [
        FXTemplate(
            id=r["id"],
            name_zh=r["name_zh"],
            category=Category(r["category"]),
            source=Source.CUSTOM,
            source_ref=r["source_ref"],
            tags=list(r["tags"]),
            duration_hint=r["duration_hint"],
        )
        for r in rows
    ]


__all__ = ["CATEGORY", "StickdirTemplate", "load_stickdir", "templates_as_dicts"]
