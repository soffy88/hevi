"""
oskill: 代码分析组
==================
syntax_check / validate_edit / chunk_code / extract_symbols
repo_map_build / resolve_mentions / load_skill_progressive
resolve_memory_hierarchy / select_skill

归属约束：stateless 纯算法，不持久化。
IO 操作（file_read / glob_match）通过已有 oprim 函数调用（不是 oprim 间裸调）。
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ._types import (
    Chunk,
    EditBlock,
    RepoFile,
    RepoMap,
    Symbol,
)
from .edit import apply_edit_block

# oprim 函数（批次A已完成）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "oprim"))
try:
    from oprim.fs import dir_list, file_read, glob_match
    from oprim.text import count_tokens, detect_language
except ImportError:  # pragma: no cover
    # fallback stubs for isolated testing  # pragma: no cover
    def file_read(path, **kw):
        return Path(path).read_text(errors="replace")  # type: ignore  # pragma: no cover

    def glob_match(pat, *, root, **kw):
        return sorted(Path(root).glob(pat))  # type: ignore  # pragma: no cover

    def dir_list(path, **kw):
        return sorted(Path(path).iterdir())  # type: ignore  # pragma: no cover

    def detect_language(path, **kw):
        return Path(path).suffix.lstrip(".") or "unknown"  # type: ignore  # pragma: no cover

    def count_tokens(text, **kw):
        return max(1, len(str(text)) // 4)  # type: ignore  # pragma: no cover


# ---------------------------------------------------------------------------
# syntax_check
# ---------------------------------------------------------------------------


def syntax_check(
    content: str,
    *,
    path: str = "",
    language: str | None = None,
) -> list[dict[str, Any]]:
    """对代码内容做语法检查，返回错误列表（纯内存）。

    组合：detect_language + 对应解析器（Python=ast，JSON=json.loads）。
    其他语言暂返回空列表（tree-sitter 接入点）。

    Args:
        content: 代码内容字符串。
        path: 文件路径（用于语言检测，可选）。
        language: 显式指定语言，覆盖 path 检测。

    Returns:
        错误 dict 列表，每项含 {line, message, severity}。
        空列表表示无错误。

    Example:
        >>> syntax_check("def f(\\n", path="x.py")
        [{"line": 1, "message": "unexpected EOF ...", "severity": 1}]
    """
    lang = language or (detect_language(path) if path else "unknown")
    errors: list[dict] = []

    if lang == "python":
        try:
            ast.parse(content)
        except SyntaxError as e:
            errors.append(
                {
                    "line": e.lineno or 1,
                    "message": str(e.msg),
                    "severity": 1,
                    "language": "python",
                }
            )
        except Exception as e:  # pragma: no cover
            errors.append(
                {"line": 1, "message": str(e), "severity": 1, "language": "python"}
            )  # pragma: no cover

    elif lang == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(
                {
                    "line": e.lineno,
                    "message": e.msg,
                    "severity": 1,
                    "language": "json",
                }
            )

    # 其他语言：暂无错误（tree-sitter 扩展点）
    return errors


# ---------------------------------------------------------------------------
# validate_edit
# ---------------------------------------------------------------------------


def validate_edit(
    original: str,
    edit: dict[str, Any],
    *,
    language: str | None = None,
) -> dict[str, Any]:
    """应用编辑后做语法校验（纯内存）。

    组合：apply_edit_block（本文件同批）+ syntax_check。

    Args:
        original: 原始文件内容。
        edit: edit dict，含 full_content / blocks / unified_diff 之一。
        language: 语言标识，空时从 edit.get("path") 检测。

    Returns:
        {
            "ok": bool,
            "content": str,      # 应用后的内容
            "errors": list[dict], # 语法错误列表
            "conflicts": list,   # edit 冲突
        }

    Example:
        >>> result = validate_edit("x = 1\\n",
        ...     {"path": "f.py", "blocks": [{"search": "x = 1", "replace": "x = "}]})
        >>> result["ok"]
        False  # 语法错误
    """
    path = edit.get("path", "")
    lang = language or (detect_language(path) if path else None)
    conflicts: list[str] = []
    new_content = original

    if "full_content" in edit:
        new_content = edit["full_content"]
    elif "blocks" in edit:
        blocks = [
            EditBlock(b["search"], b["replace"]) if isinstance(b, dict) else b
            for b in edit["blocks"]
        ]
        result = apply_edit_block(original, blocks=blocks)
        new_content = result.content
        conflicts = result.conflicts
    # unified_diff 分支由 apply_unified_diff 处理，validate_edit 不重复

    errors = syntax_check(new_content, path=path, language=lang)
    return {
        "ok": len(errors) == 0 and len(conflicts) == 0,
        "content": new_content,
        "errors": errors,
        "conflicts": conflicts,
    }


# ---------------------------------------------------------------------------
# chunk_code
# ---------------------------------------------------------------------------


def chunk_code(
    content: str,
    *,
    path: str = "",
    language: str | None = None,
    max_tokens: int = 500,
    model: str = "claude-sonnet-4-6",
) -> list[Chunk]:
    """将代码内容按语义边界分块（纯内存）。

    组合：detect_language + 语义切分（Python=函数/类级，其他=行数）。

    Args:
        content: 代码内容。
        path: 文件路径（用于语言检测）。
        language: 显式语言。
        max_tokens: 每块最大 token 数（粗估）。
        model: 用于 count_tokens 的模型名。

    Returns:
        Chunk 列表（按代码结构切分）。

    Example:
        >>> chunks = chunk_code("def f():\\n    pass\\ndef g():\\n    pass\\n", path="x.py")
        >>> len(chunks) >= 1
        True
    """
    lang = language or (detect_language(path) if path else "unknown")
    lines = content.splitlines(keepends=True)
    chunks: list[Chunk] = []

    if lang == "python":
        # 按顶级函数/类边界切分
        boundaries = [0]
        for i, line in enumerate(lines):
            if re.match(r"^(def |class |async def )", line):
                if i > 0:
                    boundaries.append(i)
        boundaries.append(len(lines))

        for i in range(len(boundaries) - 1):
            start, end = boundaries[i], boundaries[i + 1]
            chunk_lines = lines[start:end]
            chunk_text = "".join(chunk_lines)
            # 若块太大，进一步按行数切
            if count_tokens(chunk_text, model=model) > max_tokens:
                step = max(1, max_tokens * 4 // 80)  # ~80 chars/line
                for j in range(0, len(chunk_lines), step):
                    sub = "".join(chunk_lines[j : j + step])
                    if sub.strip():
                        chunks.append(
                            Chunk(
                                content=sub,
                                start_line=start + j,
                                end_line=min(start + j + step, end),
                                token_count=count_tokens(sub, model=model),
                                path=path,
                                language=lang,
                                chunk_id=f"{path}:{start + j}",
                            )
                        )
            else:
                if chunk_text.strip():
                    chunks.append(
                        Chunk(
                            content=chunk_text,
                            start_line=start,
                            end_line=end,
                            token_count=count_tokens(chunk_text, model=model),
                            path=path,
                            language=lang,
                            chunk_id=f"{path}:{start}",
                        )
                    )
    else:
        # 通用：按 max_tokens 行数切
        step = max(1, max_tokens * 4 // 80)
        for i in range(0, len(lines), step):
            sub = "".join(lines[i : i + step])
            if sub.strip():
                chunks.append(
                    Chunk(
                        content=sub,
                        start_line=i,
                        end_line=min(i + step, len(lines)),
                        token_count=count_tokens(sub, model=model),
                        path=path,
                        language=lang,
                        chunk_id=f"{path}:{i}",
                    )
                )

    return chunks


# ---------------------------------------------------------------------------
# extract_symbols
# ---------------------------------------------------------------------------


def extract_symbols(
    path: str,
    *,
    server: Any = None,  # LspServerHandle（可选）
    content: str | None = None,
) -> list[Symbol]:
    """从文件中提取代码符号列表（纯内存 + 可选 LSP）。

    无 LSP 时使用 AST（Python）或正则（其他语言）回退。

    Args:
        path: 文件路径。
        server: LspServerHandle（可选，有时用 LSP 获取精确符号）。
        content: 文件内容（可选，不提供则从 path 读）。

    Returns:
        Symbol 列表，按行号排序。

    Example:
        >>> syms = extract_symbols("x.py", content="def foo():\\n    pass\\n")
        >>> syms[0].name
        'foo'
    """
    if content is None:
        try:  # pragma: no cover
            content = file_read(path)  # pragma: no cover
        except Exception:  # pragma: no cover
            return []  # pragma: no cover

    lang = detect_language(path)
    symbols: list[Symbol] = []

    if lang == "python":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "function"
                    sig = f"def {node.name}({_args_str(node.args)})"
                    doc = ast.get_docstring(node) or ""
                    symbols.append(
                        Symbol(
                            name=node.name,
                            kind=kind,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            path=path,
                            signature=sig,
                            docstring=doc[:120],
                        )
                    )
                elif isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node) or ""
                    symbols.append(
                        Symbol(
                            name=node.name,
                            kind="class",
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            path=path,
                            signature=f"class {node.name}",
                            docstring=doc[:120],
                        )
                    )
        except SyntaxError:
            pass
    else:
        # 正则回退：匹配常见函数/类定义
        for pat, kind in [
            (r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
            (r"^(?:export\s+)?class\s+(\w+)", "class"),
            (r"^def\s+(\w+)", "function"),
            (r"^class\s+(\w+)", "class"),
            (r"^(?:pub\s+)?fn\s+(\w+)", "function"),  # Rust
            (r"^func\s+(\w+)", "function"),  # Go
        ]:
            for i, line in enumerate(content.splitlines(), 1):
                m = re.match(pat, line.strip())
                if m:
                    symbols.append(
                        Symbol(
                            name=m.group(1),
                            kind=kind,
                            start_line=i,
                            end_line=i,
                            path=path,
                            signature=line.strip()[:80],
                        )
                    )

    return sorted(symbols, key=lambda s: s.start_line)


def _args_str(args: ast.arguments) -> str:
    parts = [a.arg for a in args.args]
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")  # pragma: no cover
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")  # pragma: no cover
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# repo_map_build
# ---------------------------------------------------------------------------


def repo_map_build(
    *,
    root: str,
    ignore: list[str] | None = None,
    max_files: int = 500,
    head_lines: int = 5,
) -> RepoMap:
    """构建代码库结构地图（文件遍历 + 符号提取）。

    组合：glob_match + file_read（头部）+ extract_symbols。
    oskill 约束：只读，不写盘。

    Args:
        root: 仓库根目录。
        ignore: 额外 glob 忽略模式列表。
        max_files: 最多处理文件数，默认 500。
        head_lines: 每个文件读取头部行数，默认 5。

    Returns:
        RepoMap（含文件列表、语言统计）。

    Example:
        >>> rmap = repo_map_build(root="/project")
        >>> rmap.total_files > 0
        True
    """
    _IGNORE = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
    }
    _EXTS = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".cs",
        ".rb",
    }

    extra_ignore = set(ignore or [])
    files: list[RepoFile] = []
    languages: dict[str, int] = {}

    try:
        all_paths = glob_match("**/*", root=root, respect_gitignore=True)
    except Exception:
        return RepoMap(root=root, files=[], total_files=0, languages={})

    for p in all_paths[: max_files * 2]:  # 多取再过滤
        if len(files) >= max_files:
            break

        # 过滤目录和忽略项
        if not p.is_file():
            continue  # pragma: no cover
        rel = str(p.relative_to(root) if hasattr(p, "relative_to") else p)
        parts = Path(rel).parts
        if any(part in _IGNORE or part in extra_ignore for part in parts):
            continue  # pragma: no cover
        if p.suffix not in _EXTS:
            continue  # pragma: no cover

        lang = detect_language(str(p))
        languages[lang] = languages.get(lang, 0) + 1

        try:
            size = p.stat().st_size
            raw = file_read(str(p))
            head = "\n".join(raw.splitlines()[:head_lines])
            syms = extract_symbols(str(p), content=raw)
        except Exception:  # pragma: no cover
            head = ""  # pragma: no cover
            syms = []  # pragma: no cover
            size = 0  # pragma: no cover

        files.append(
            RepoFile(
                path=str(p),
                language=lang,
                size_bytes=size,
                symbols=syms,
                head_lines=head,
            )
        )

    return RepoMap(root=root, files=files, total_files=len(files), languages=languages)


# ---------------------------------------------------------------------------
# resolve_mentions
# ---------------------------------------------------------------------------


def resolve_mentions(
    text: str,
    *,
    root: str,
) -> dict[str, Any]:
    """解析文本中的 @file/@symbol 引用，展开为文件路径 + 内容（只读）。

    组合：正则解析 + glob_match + file_read。

    Args:
        text: 含 @mention 的用户输入文本。
        root: 工作区根目录。

    Returns:
        {
            "expanded": str,      # 展开后的文本
            "files": list[str],   # 被引用的文件路径列表
            "symbols": list[str], # 被引用的符号名列表
        }

    Example:
        >>> r = resolve_mentions("Look at @src/main.py please", root="/proj")
        >>> "src/main.py" in r["files"]
        True
    """
    file_refs = re.findall(r"@([\w./\-]+\.\w+)", text)
    symbol_refs = re.findall(r"@(\w+)(?!\.\w)", text)

    resolved_files: list[str] = []
    expanded = text

    for ref in file_refs:
        candidate = Path(root) / ref
        if candidate.exists():
            try:
                content = file_read(str(candidate))
                snippet = "\n".join(content.splitlines()[:50])
                placeholder = f"\n```\n# {ref}\n{snippet}\n```\n"
                expanded = expanded.replace(f"@{ref}", placeholder, 1)
                resolved_files.append(str(candidate))
            except Exception:  # pragma: no cover
                pass  # pragma: no cover
        else:
            # glob 查找
            try:
                matches = glob_match(f"**/{ref}", root=root)
                if matches:
                    p = str(matches[0])  # pragma: no cover
                    content = file_read(p)  # pragma: no cover
                    snippet = "\n".join(content.splitlines()[:50])  # pragma: no cover
                    placeholder = f"\n```\n# {ref}\n{snippet}\n```\n"  # pragma: no cover
                    expanded = expanded.replace(f"@{ref}", placeholder, 1)  # pragma: no cover
                    resolved_files.append(p)  # pragma: no cover
            except Exception:  # pragma: no cover
                pass  # pragma: no cover

    return {
        "expanded": expanded,
        "files": resolved_files,
        "symbols": [s for s in symbol_refs if s not in {r.replace(".", "") for r in file_refs}],
    }


# ---------------------------------------------------------------------------
# select_skill
# ---------------------------------------------------------------------------


def select_skill(
    task: str,
    *,
    skill_index: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """根据任务描述从 skill 索引中选择最相关的 skill（纯内存）。

    渐进披露第一步：只用 SkillMeta（name+description+tags），不读 body。

    Args:
        task: 任务描述字符串。
        skill_index: SkillMeta dict 列表（含 name/description/tags）。
        top_k: 最多返回数量，默认 3。

    Returns:
        最相关的 SkillMeta dict 列表（按相关度排序）。

    Example:
        >>> skills = select_skill("refactor python code",
        ...     skill_index=[{"name": "refactor_python", "description": "..."}])
        >>> skills[0]["name"]
        'refactor_python'
    """
    task_words = set(re.findall(r"\w+", task.lower()))
    scored: list[tuple[float, dict]] = []

    for meta in skill_index:
        name_words = set(re.findall(r"\w+", meta.get("name", "").lower()))
        desc_words = set(re.findall(r"\w+", meta.get("description", "").lower()))
        tag_words = set(re.findall(r"\w+", " ".join(meta.get("tags", [])).lower()))
        all_words = name_words | desc_words | tag_words
        score = len(task_words & all_words) / max(len(task_words), 1)
        # 名称直接匹配加权
        if task_words & name_words:
            score += 0.5
        scored.append((score, meta))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for score, m in scored[:top_k] if score >= 0]


# ---------------------------------------------------------------------------
# load_skill_progressive
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# resolve_memory_hierarchy
# ---------------------------------------------------------------------------


def resolve_memory_hierarchy(
    *,
    enterprise: str | None = None,
    project: str | None = None,
    user: str | None = None,
    local: str | None = None,
    max_imports: int = 10,
) -> dict[str, Any]:
    """解析四层 CLAUDE.md 记忆层级，支持 @import 递归（只读）。

    组合：file_read + @import 解析（递归，最多 max_imports 次）。
    优先级：local > user > project > enterprise。

    Args:
        enterprise: enterprise 级 CLAUDE.md 路径（可选）。
        project: project 级 CLAUDE.md 路径（可选）。
        user: user 级 CLAUDE.md 路径（可选）。
        local: local 级 CLAUDE.md 路径（可选）。
        max_imports: @import 最大递归次数，默认 10。

    Returns:
        {
            "content": str,       # 合并后的记忆内容
            "sources": list[str], # 实际读取的文件路径
            "import_count": int,
        }

    Example:
        >>> mem = resolve_memory_hierarchy(project="/project/CLAUDE.md")
        >>> isinstance(mem["content"], str)
        True
    """
    layers = [enterprise, project, user, local]
    parts: list[str] = []
    sources: list[str] = []
    import_count = 0

    def read_with_imports(path: str, depth: int = 0) -> str:
        nonlocal import_count
        if depth > max_imports or import_count >= max_imports:
            return ""  # pragma: no cover
        try:
            content = file_read(path)
            sources.append(path)
        except Exception:
            return ""
        # 解析 @import 指令
        result_lines = []
        for line in content.splitlines():
            m = re.match(r"^@import\s+(.+)", line.strip())
            if m and import_count < max_imports:
                import_path = m.group(1).strip()
                if not Path(import_path).is_absolute():
                    import_path = str(Path(path).parent / import_path)  # pragma: no cover
                import_count += 1
                result_lines.append(read_with_imports(import_path, depth + 1))
            else:
                result_lines.append(line)
        return "\n".join(result_lines)

    for layer_path in layers:
        if layer_path:
            text = read_with_imports(layer_path)
            if text.strip():
                parts.append(text)

    return {
        "content": "\n\n".join(parts),
        "sources": sources,
        "import_count": import_count,
    }
