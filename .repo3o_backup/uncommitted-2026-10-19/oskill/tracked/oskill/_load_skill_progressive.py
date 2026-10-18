"""Auto-split from hicode whl."""

from __future__ import annotations
from oprim import file_read

import os
import sys
from pathlib import Path
from typing import Any



def load_skill_progressive(
    skill_dir: str,
    *,
    matched: bool = True,
) -> dict[str, Any]:
    """渐进加载 skill：命中时读 body，未命中只返回 meta（纯内存 + 文件读）。

    组合：read_skill_frontmatter（B批已有）+ file_read。

    Args:
        skill_dir: skill 目录路径。
        matched: True 时读取 body，False 时只返回 meta。

    Returns:
        {
            "name": str,
            "description": str,
            "tools": list,
            "body": str,    # matched=True 时填充
            "meta": dict,
        }

    Example:
        >>> ctx = load_skill_progressive("/skills/refactor", matched=True)
        >>> "body" in ctx
        True
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "oprim"))
    try:
        from oprim.hooks_image_skill import read_skill_frontmatter

        meta = read_skill_frontmatter(skill_dir)
        meta_dict = {
            "name": meta.name,
            "description": meta.description,
            "version": meta.version,
            "tools": meta.tools,
            "tags": meta.tags,
            "hooks": meta.hooks,
            "raw": meta.raw,
        }
    except Exception as e:
        return {"name": "", "description": "", "tools": [], "body": "", "meta": {}, "error": str(e)}

    body = ""
    if matched:
        skill_md = Path(skill_dir) / "SKILL.md"
        try:
            full = file_read(str(skill_md))
            # 去掉 frontmatter，取 body 部分
            fm_end = full.find("\n---\n", full.find("---\n") + 4)
            body = full[fm_end + 5 :] if fm_end != -1 else full
        except Exception:  # pragma: no cover
            body = ""  # pragma: no cover

    return {
        "name": meta_dict["name"],
        "description": meta_dict["description"],
        "tools": meta_dict["tools"],
        "body": body,
        "meta": meta_dict,
    }
