"""Manim 源码沙箱 —— AST 白名单,禁止任意 Python。

只允许 manim / manimlib / math / numpy 与 Scene.construct 里常见动画调用。
LLM 或确稿台送来的 ``code`` 必须先过这里,再交给子进程渲染。
"""

from __future__ import annotations

import ast

_ALLOWED_IMPORT_ROOTS = frozenset(
    {"manim", "manimlib", "math", "numpy", "collections", "typing", "dataclasses"}
)
_FORBIDDEN_NAMES = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "open",
        "input",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "exit",
        "quit",
        "help",
        "memoryview",
        "copyright",
        "credits",
        "license",
    }
)
_ALLOWED_DUNDER = frozenset({"__init__", "__name__", "__class__"})


class ManimSandboxError(ValueError):
    """源码未通过白名单。"""


class _Visitor(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            _assert_allowed_module(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module:
            raise ManimSandboxError("禁止 relative import")
        _assert_allowed_module(node.module)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr not in _ALLOWED_DUNDER:
            raise ManimSandboxError(f"禁止访问 {node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_NAMES:
            raise ManimSandboxError(f"禁止使用 {node.id}")
        if node.id.startswith("__") and node.id not in _ALLOWED_DUNDER:
            raise ManimSandboxError(f"禁止使用 {node.id}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
            raise ManimSandboxError(f"禁止调用 {func.id}")
        self.generic_visit(node)


def _assert_allowed_module(name: str) -> None:
    root = name.split(".", 1)[0]
    if root not in _ALLOWED_IMPORT_ROOTS:
        raise ManimSandboxError(f"禁止 import {name}")


def validate_manim_source(source: str) -> ast.Module:
    """解析并校验源码。返回 AST,失败抛 ManimSandboxError。"""
    text = (source or "").strip()
    if not text:
        raise ManimSandboxError("Manim 源码为空")
    if len(text) > 80_000:
        raise ManimSandboxError("Manim 源码过长")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ManimSandboxError(f"Manim 源码语法错误: {exc.msg}") from exc
    _Visitor().visit(tree)
    return tree


def scene_class_name(source: str, preferred: str = "HeviScene") -> str:
    """取第一个 Scene 子类名;没有则回落 preferred。"""
    tree = validate_manim_source(source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            label = _base_name(base)
            if label.endswith("Scene"):
                return node.name
    return preferred


def _base_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
