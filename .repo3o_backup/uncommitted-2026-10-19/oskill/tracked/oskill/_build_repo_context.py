"""Auto-split from hicode whl."""

from __future__ import annotations
from oskill import repo_map_build, rank_relevant_files
from oprim import count_tokens, file_read

from typing import Any, Protocol, runtime_checkable



from ._types import OskillError


@runtime_checkable
class VectorStoreHandle(Protocol):
    """
    向量存储 Protocol（obase.persistence 向量查询接口）。
    semantic_search 接受此类型注入，不 import obase.persistence。
    生产实现由 obase.persistence.VectorStore 提供。
    """

    async def search(
        self, *, vector: list[float], top_k: int = 5, filter: dict | None = None
    ) -> list[dict[str, Any]]:
        """
        向量相似度搜索。

        Returns:
            list of {"chunk_id": str, "content": str, "score": float, "path": str}
        """
        ...


async def build_repo_context(
    task: str,
    *,
    root: str,
    budget: int = 8000,
    model: str = "claude-sonnet-4-6",
    caller: Any | None = None,
) -> str:
    """构建任务相关的代码库上下文字符串（文件遍历 + LLM 可选）。

    组合：repo_map_build(oskill) + rank_relevant_files(oskill) + file_read(oprim)。
    oskill 约束：只读，不写盘，返回字符串。

    Args:
        task: 任务描述（用于相关度排序）。
        root: 仓库根目录。
        budget: 输出 token 预算，默认 8000。
        model: 用于 token 计数的模型名。
        caller: LLMCaller Protocol（可选，传给 rank_relevant_files）。

    Returns:
        格式化的上下文字符串（含相关文件路径 + 内容片段）。

    Example:
        >>> ctx = await build_repo_context("fix auth bug", root="/project")
        >>> len(ctx) > 0
        True
    """
    from .analysis import repo_map_build

    try:
        rmap = repo_map_build(root=root, max_files=200)
    except Exception as e:  # pragma: no cover
        raise OskillError("build_repo_context: repo_map_build failed", cause=e)  # pragma: no cover

    if not rmap.files:
        return f"# Repository: {root}\n(no source files found)"

    ranked = await rank_relevant_files(task, repo_map=rmap, caller=caller)

    parts = [f"# Repository Context for: {task}\n"]
    used_tokens = count_tokens(parts[0], model=model)

    for path, score in ranked:
        if used_tokens >= budget:
            break  # pragma: no cover
        try:
            content = file_read(path)
        except Exception:  # pragma: no cover
            continue  # pragma: no cover
        lines = content.splitlines()
        # 取头部 + 符号摘要
        head = "\n".join(lines[:30])
        entry = f"\n## {path} (relevance={score:.2f})\n```\n{head}\n```\n"
        entry_toks = count_tokens(entry, model=model)
        if used_tokens + entry_toks > budget:
            break  # pragma: no cover
        parts.append(entry)
        used_tokens += entry_toks

    return "\n".join(parts)
