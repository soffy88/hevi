"""Adversarial tests for local 3O implementation classification."""

from __future__ import annotations

import ast

from _3o_common import has_real_implementation


def classify(source: str) -> bool:
    return has_real_implementation(ast.parse(source))


def test_pure_reexport_is_not_real() -> None:
    assert not classify("from oprim import foo\n__all__ = ['foo']")


def test_pure_delegate_is_not_real() -> None:
    assert not classify(
        "from canonical import foo\ndef old(*args, **kwargs):\n    return foo(*args, **kwargs)"
    )


def test_transform_delegate_is_real() -> None:
    assert classify("def old(x):\n    x = transform(x)\n    return foo(x)")


def test_io_delegate_is_real() -> None:
    assert classify("def old(x):\n    result = foo(x)\n    write_file(result)\n    return result")


def test_copied_body_is_real() -> None:
    assert classify("def old(x):\n    return x.strip().lower()")


def test_project_namespace_is_real() -> None:
    assert classify("def old(project_id):\n    return project_id")
