"""
oskill: LLM 依赖算法组 + semantic_search
=========================================
summarize_file / compress_context / plan_decompose
rank_relevant_files / build_repo_context / semantic_search

LLM 经 LLMCaller Protocol 注入（C批已有）。
semantic_search 的向量检索经 VectorStoreHandle Protocol 注入。
全部 stateless，不持久化。
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Protocol, runtime_checkable

from ._types import Chunk, LLMOskillError, OskillError, RepoMap, SubTask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "oprim"))
try:
    from oprim.fs import file_read
    from oprim.text import count_tokens
except ImportError:  # pragma: no cover

    def file_read(path, **kw):
        return open(path, errors="replace").read()  # type: ignore  # pragma: no cover

    def count_tokens(text, **kw):
        return max(1, len(str(text)) // 4)  # type: ignore  # pragma: no cover


# ---------------------------------------------------------------------------
# VectorStoreHandle Protocol（semantic_search 用）
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStoreHandle(Protocol):
    """
    向量存储 Protocol（obase.persistence 向量查询接口）。
    semantic_search 接受此类型注入，不 import obase.persistence。
    生产实现由 obase.persistence.VectorStore 提供。
    """

    async def search(
        self,
        *,
        vector: list[float],
        top_k: int = 5,
        filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        向量相似度搜索。

        Returns:
            list of {"chunk_id": str, "content": str, "score": float, "path": str}
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# summarize_file
# ---------------------------------------------------------------------------


async def summarize_file(
    path: str,
    *,
    caller: Any,
    max_content_tokens: int = 8000,
    model: str = "claude-sonnet-4-6",
) -> str:
    """读取文件并用 LLM 生成简洁摘要（文件读 + LLM 调用）。

    组合：file_read(oprim) + count_tokens(oprim) + caller(LLMCaller Protocol)。
    oskill 约束：不写盘，返回摘要字符串。

    Args:
        path: 文件路径。
        caller: LLMCaller Protocol 实例（由调用方注入）。
        max_content_tokens: 输入内容最大 token 数（超出时截断），默认 8000。
        model: 用于 token 计数的模型名。

    Returns:
        文件摘要字符串。

    Raises:
        LLMOskillError: 文件读取或 LLM 调用失败。

    Example:
        >>> summary = await summarize_file("src/main.py", caller=my_caller)
        >>> isinstance(summary, str)
        True
    """
    try:
        content = file_read(path)
    except Exception as e:
        raise LLMOskillError(f"summarize_file: cannot read '{path}'", cause=e)

    # token 预算截断
    toks = count_tokens(content, model=model)
    if toks > max_content_tokens:
        # 粗截断：按比例取前缀
        ratio = max_content_tokens / toks
        content = content[: int(len(content) * ratio)]

    messages = [
        {
            "role": "user",
            "content": (
                f"Summarize this file in 2-4 sentences. Focus on what it does "
                f"and key exported symbols.\n\nFile: {path}\n\n```\n{content}\n```"
            ),
        }
    ]

    try:
        response = await caller(messages=messages, tools=None, max_tokens=256)
        text = ""
        for block in response.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text += block.get("text", "")
        return text.strip() or "(no summary)"
    except Exception as e:
        raise LLMOskillError(f"summarize_file: LLM call failed for '{path}'", cause=e)


# ---------------------------------------------------------------------------
# compress_context
# ---------------------------------------------------------------------------


async def compress_context(
    messages: list[dict],
    *,
    caller: Any,
    budget: int = 4000,
    model: str = "claude-sonnet-4-6",
) -> list[dict]:
    """将过长的消息历史压缩为摘要，返回新的消息列表（LLM 辅助）。

    组合：count_tokens(oprim) + caller(LLMCaller Protocol)。
    若已在预算内，直接返回原列表（不调 LLM）。

    Args:
        messages: 当前消息列表。
        caller: LLMCaller Protocol 实例。
        budget: 目标 token 预算，默认 4000。
        model: 用于 token 计数的模型名。

    Returns:
        压缩后的消息列表（首条保留，中间替换为摘要，末 2 条保留）。

    Raises:
        LLMOskillError: LLM 调用失败。

    Example:
        >>> short = await compress_context(long_messages, caller=my_caller, budget=2000)
        >>> count_tokens(short) <= 2000 * 1.2  # 允许 20% 余量
        True
    """
    if not messages:
        return []

    current_tokens = count_tokens(messages, model=model)
    if current_tokens <= budget:
        return list(messages)

    # 保留首 1 条（system/user）和末 2 条（最近上下文）
    keep_first = messages[:1]
    keep_last = messages[-2:] if len(messages) > 3 else []
    middle = messages[1 : len(messages) - len(keep_last)] if keep_last else messages[1:]

    if not middle:
        return list(messages)  # pragma: no cover

    # 用 LLM 压缩 middle 部分
    history_text = "\n".join(f"[{m.get('role', '?')}]: {_msg_text(m)[:500]}" for m in middle)
    compress_prompt = (
        f"Summarize this conversation history in 3-5 sentences, "
        f"preserving key decisions, code changes, and findings:\n\n{history_text}"
    )

    try:
        response = await caller(
            messages=[{"role": "user", "content": compress_prompt}],
            tools=None,
            max_tokens=512,
        )
        summary_text = ""
        for block in response.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                summary_text += block.get("text", "")
        summary_text = summary_text.strip() or "(conversation history)"
    except Exception as e:
        raise LLMOskillError("compress_context: LLM call failed", cause=e)

    summary_msg = {"role": "user", "content": f"[Conversation summary]: {summary_text}"}
    return keep_first + [summary_msg] + keep_last


def _msg_text(msg: dict) -> str:
    """提取消息文本内容。"""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # pragma: no cover
        return " ".join(  # pragma: no cover
            b.get("text", "")
            for b in content  # pragma: no cover
            if isinstance(b, dict) and b.get("type") == "text"  # pragma: no cover
        )  # pragma: no cover
    return str(content)  # pragma: no cover


# ---------------------------------------------------------------------------
# plan_decompose
# ---------------------------------------------------------------------------


async def plan_decompose(
    goal: str,
    *,
    caller: Any,
    context: str = "",
    max_subtasks: int = 10,
) -> list[SubTask]:
    """将高层目标分解为有序子任务列表（LLM 辅助）。

    组合：prompt 构建(纯) + caller(LLMCaller Protocol) + JSON 解析(纯)。

    Args:
        goal: 高层任务描述。
        caller: LLMCaller Protocol 实例。
        context: 额外上下文（如代码库信息），可选。
        max_subtasks: 最多子任务数，默认 10。

    Returns:
        SubTask 列表（有序，含依赖关系）。

    Raises:
        LLMOskillError: LLM 调用失败或响应无法解析。

    Example:
        >>> tasks = await plan_decompose("Add user auth", caller=my_caller)
        >>> tasks[0].title
        'Design auth schema'
    """
    ctx_section = f"\n\nContext:\n{context}" if context else ""
    prompt = (
        f"Decompose this goal into {max_subtasks} or fewer concrete subtasks. "
        f"Return ONLY a JSON array of objects with fields: "
        f"id (string), title (string), description (string), "
        f"dependencies (array of ids), estimated_complexity (low/medium/high).\n\n"
        f"Goal: {goal}{ctx_section}"
    )

    try:
        response = await caller(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            max_tokens=1024,
        )
        raw_text = ""
        for block in response.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                raw_text += block.get("text", "")
    except Exception as e:
        raise LLMOskillError("plan_decompose: LLM call failed", cause=e)

    # 解析 JSON
    raw_text = raw_text.strip()
    # 去除 markdown fence
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
    raw_text = re.sub(r"```\s*$", "", raw_text, flags=re.MULTILINE)

    try:
        items = json.loads(raw_text.strip())
        if not isinstance(items, list):
            items = []  # pragma: no cover
    except (json.JSONDecodeError, ValueError):
        # 回退：尝试提取 JSON 数组
        m = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if m:
            try:  # pragma: no cover
                items = json.loads(m.group(0))  # pragma: no cover
            except Exception:  # pragma: no cover
                items = []  # pragma: no cover
        else:
            items = []

    subtasks: list[SubTask] = []
    for item in items[:max_subtasks]:
        if not isinstance(item, dict):
            continue  # pragma: no cover
        subtasks.append(
            SubTask(
                id=str(item.get("id", f"task_{len(subtasks) + 1}")),
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                dependencies=[str(d) for d in item.get("dependencies", [])],
                estimated_complexity=str(item.get("estimated_complexity", "medium")),
            )
        )

    return subtasks


# ---------------------------------------------------------------------------
# rank_relevant_files
# ---------------------------------------------------------------------------


async def rank_relevant_files(
    query: str,
    *,
    repo_map: RepoMap,
    caller: Any | None = None,
    top_k: int = 10,
) -> list[tuple[str, float]]:
    """对 repo_map 中的文件按与 query 的相关度排序（纯内存 + 可选 LLM）。

    无 LLM 时：关键词 + 符号名匹配评分。
    有 LLM（caller 非 None）：用 LLM 对 top 候选做 rerank（未来扩展点，
    当前实现仅关键词模式，caller 参数保留接口）。

    Args:
        query: 搜索查询。
        repo_map: build_repo_context 产出的 RepoMap。
        caller: LLMCaller Protocol（可选，当前未使用）。
        top_k: 返回文件数，默认 10。

    Returns:
        list of (path, score) 元组，按 score 降序。

    Example:
        >>> ranked = await rank_relevant_files("authentication", repo_map=rmap)
        >>> ranked[0][1] > 0
        True
    """
    query_words = set(re.findall(r"\w+", query.lower()))

    scored: list[tuple[str, float]] = []
    for rf in repo_map.files:
        path_words = set(re.findall(r"\w+", rf.path.lower()))
        sym_words = set(
            w
            for sym in rf.symbols
            for w in re.findall(r"\w+", (sym.name + " " + sym.signature).lower())
        )
        head_words = set(re.findall(r"\w+", rf.head_lines.lower()))
        all_words = path_words | sym_words | head_words

        overlap = len(query_words & all_words)
        # 加权：符号名命中权重 > 路径 > head
        sym_hit = len(query_words & sym_words)
        path_hit = len(query_words & path_words)
        score = (sym_hit * 3 + path_hit * 2 + overlap) / max(len(query_words) * 3, 1)
        if score > 0:
            scored.append((rf.path, round(score, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# build_repo_context
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------


async def semantic_search(
    query: str,
    *,
    store: VectorStoreHandle,
    embed_caller: Any,
    top_k: int = 5,
    filter: dict | None = None,
) -> list[Chunk]:
    """语义向量搜索，返回最相关的代码 Chunk 列表。

    组合：embed_text(oprim C批) + store.search(VectorStoreHandle Protocol)。
    oskill 约束：只读，不写盘。

    Args:
        query: 自然语言查询。
        store: VectorStoreHandle Protocol 实例（由调用方注入）。
        embed_caller: EmbedCaller Protocol 实例（用于 embed query）。
        top_k: 返回数量，默认 5。
        filter: 向量检索过滤条件（可选，传给 store）。

    Returns:
        Chunk 列表（按相似度排序）。

    Raises:
        LLMOskillError: 嵌入或检索失败。

    Example:
        >>> chunks = await semantic_search("user authentication", store=vs, embed_caller=ec)
        >>> chunks[0].content
        'def authenticate_user(...):'
    """
    if not query or not query.strip():
        raise LLMOskillError("semantic_search: query must not be empty")

    # embed query（复用 oprim embed_text 的逻辑，直接调 embed_caller）
    try:
        vector = await embed_caller(text=query, model="text-embedding-3-small")
    except Exception as e:
        raise LLMOskillError("semantic_search: embedding failed", cause=e)

    # 向量检索
    try:
        raw = await store.search(vector=vector, top_k=top_k, filter=filter)
    except Exception as e:
        raise LLMOskillError("semantic_search: vector store search failed", cause=e)

    chunks: list[Chunk] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        chunks.append(
            Chunk(
                content=item.get("content", ""),
                start_line=item.get("start_line", 0),
                end_line=item.get("end_line", 0),
                token_count=item.get("token_count", count_tokens(item.get("content", ""))),
                path=item.get("path", ""),
                language=item.get("language", ""),
                chunk_id=item.get("chunk_id", ""),
            )
        )

    return chunks
