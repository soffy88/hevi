"""HEVI P6.1 — Narrative grammar registry.

One authority for narrative grammar definitions: ``NARRATIVE_GRAMMAR_REGISTRY``.

Why this is not a duplicate of the P6.0 ``GRAMMAR_REGISTRY``
-----------------------------------------------------------
They answer different questions and neither can answer the other's:

* ``hevi.production.p6.registry.GRAMMAR_REGISTRY`` maps a ``GrammarKind`` to the
  *Python contract class* that carries it — a dispatch table for the ten grammar
  kinds. It holds no content.
* ``NARRATIVE_GRAMMAR_REGISTRY`` holds *actual narrative definitions* — named,
  versioned, content-hashed shapes that a product profile references by id.

Collapsing them would mean either a dispatch table holding content, or a content
store that also dispatches. Keeping them separate is what lets a product say
``narrative_grammar_id="documentary.v1"`` and get a definition, rather than a
class.

Fail-closed
-----------
Duplicate ``id@version`` raises. A grammar that fails its own invariants cannot
be constructed in the first place (see :mod:`hevi.production.p6.narrative.model`),
so registration cannot smuggle in a malformed shape.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p6.narrative.model import NarrativeGrammar


class NarrativeGrammarRegistry:
    """Single authority for narrative grammar definitions."""

    def __init__(self) -> None:
        self._grammars: dict[str, NarrativeGrammar] = {}
        self._versions: dict[str, list[str]] = {}

    @staticmethod
    def _key(grammar_id: str, version: str) -> str:
        """Storage key. Matches :attr:`NarrativeGrammar.qualified_id` exactly."""
        return f"{grammar_id}@v{version}"

    def register(self, grammar: NarrativeGrammar) -> NarrativeGrammar:
        if not isinstance(grammar, NarrativeGrammar):
            raise ValueError(f"NOT_A_NARRATIVE_GRAMMAR:{type(grammar).__name__}")
        key = grammar.qualified_id
        if key in self._grammars:
            raise ValueError(f"NARRATIVE_GRAMMAR_IMMUTABLE:{key} already registered")
        self._grammars[key] = grammar
        self._versions.setdefault(grammar.id, []).append(grammar.version)
        return grammar

    def get(self, ref: str, version: str | None = None) -> NarrativeGrammar | None:
        """Look up by bare id or by a qualified ``id@version`` reference.

        Accepts both ``documentary@1.0.0`` and ``documentary@v1.0.0`` — with or
        without the ``v`` — because both spellings appear in profile fields and
        a lookup that only accepted one of them would fail closed on a
        perfectly reasonable reference.

        An explicit ``version`` argument wins over one embedded in ``ref``.
        """
        grammar_id, embedded = _split_qualified(ref)
        target = version or embedded
        if target:
            direct = self._grammars.get(self._key(grammar_id, target))
            if direct is not None:
                return direct
            # Tolerate the "v"-prefixed spelling of an already-@v reference.
            stripped = target[1:] if target.startswith("v") else None
            if stripped:
                return self._grammars.get(self._key(grammar_id, stripped))
            return None
        versions = self._versions.get(grammar_id, [])
        if not versions:
            return None
        latest = sorted(versions, key=_version_sort_key)[-1]
        return self._grammars.get(self._key(grammar_id, latest))

    def resolve(self, ref: str, version: str | None = None) -> NarrativeGrammar:
        """Resolve a grammar by reference, raising when absent.

        ``ref`` may be a bare id (``"documentary"``, meaning latest) or an
        already-qualified ``id@version`` (``"documentary@1.0.0"``). An explicit
        ``version`` argument wins over a version embedded in ``ref``.

        Compilation uses this. A missing grammar is a defect in the profile, not
        an empty result to be handled downstream.
        """
        grammar_id, embedded = _split_qualified(ref)
        grammar = self.get(grammar_id, version or embedded)
        if grammar is None:
            raise KeyError(f"NARRATIVE_GRAMMAR_NOT_FOUND:{ref}")
        return grammar

    def list_all(self) -> list[NarrativeGrammar]:
        """Every registered grammar, across all ids and versions.

        Named ``list_all`` rather than ``list`` because inside the class body
        ``list`` shadows the builtin, which makes the ``-> list[...]``
        annotations on neighbouring methods unresolvable.
        """
        return list(self._grammars.values())

    def list_ids(self) -> list[str]:
        return sorted(self._versions)

    def list_versions(self, grammar_id: str) -> list[str]:
        return list(self._versions.get(grammar_id, []))

    def has(self, grammar_id: str, version: str | None = None) -> bool:
        return self.get(grammar_id, version) is not None

    def validate(self, ref: str, version: str | None = None) -> tuple[bool, list[str]]:
        """Re-verify a stored grammar rather than trusting registration.

        Registration already rejects malformed input, so this exists to prove
        the stored object is still internally consistent and to give the
        qualification suite something executable to assert against.
        """
        grammar_id, _ = _split_qualified(ref)
        grammar = self.get(grammar_id, version)
        if grammar is None:
            return False, [f"NARRATIVE_GRAMMAR_NOT_FOUND:{ref}"]
        errors: list[str] = []
        node_ids = [n.id for n in grammar.nodes]
        if len(set(node_ids)) != len(node_ids):
            errors.append("DUPLICATE_NARRATIVE_NODE_ID")
        orders = [n.order for n in grammar.nodes]
        if len(set(orders)) != len(orders):
            errors.append("AMBIGUOUS_NODE_ORDER")
        if grammar.ordered_nodes()[0].id != node_ids[0] and len(orders) != len(set(orders)):
            errors.append("ORDER_NOT_STABLE")
        if not grammar.required_node_ids():
            errors.append("NARRATIVE_GRAMMAR_WITHOUT_REQUIRED_NODE")
        expected = grammar.sequence()
        if grammar.sequence() != tuple(
            n.type.value for n in sorted(grammar.nodes, key=lambda x: x.order)
        ):
            errors.append("SEQUENCE_MISMATCH")
        if not expected:
            errors.append("EMPTY_NARRATIVE_SEQUENCE")
        return (not errors), errors

    def validate_all(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for grammar_id in self.list_ids():
            ok, grammar_errors = self.validate(grammar_id)
            if not ok:
                errors.extend(f"{grammar_id}:{e}" for e in grammar_errors)
        return (not errors), errors

    def stats(self) -> dict[str, Any]:
        return {
            "total_grammars": len(self._grammars),
            "distinct_ids": len(self._versions),
            "ids": self.list_ids(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {key: g.to_dict() for key, g in sorted(self._grammars.items())}


def _split_qualified(ref: str) -> tuple[str, str | None]:
    """Split ``id@version`` into parts. A bare id means latest.

    Handles both ``id@1.0.0`` and ``id@v1.0.0``; a leading ``v`` on the version
    is stripped so the two spellings resolve to the same grammar.
    """
    if "@" not in ref:
        return ref, None
    base, _, version = ref.partition("@")
    if not base or not version:
        return ref, None
    if version.startswith("v") and len(version) > 1:
        version = version[1:]
    return base, version


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Numeric version ordering. Non-numeric segments sort last, never raise."""
    parts: list[int] = []
    for segment in version.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            return (0, *parts, 0)
    return tuple(parts)


#: The single narrative grammar authority.
NARRATIVE_GRAMMAR_REGISTRY = NarrativeGrammarRegistry()


__all__ = ["NARRATIVE_GRAMMAR_REGISTRY", "NarrativeGrammarRegistry"]
