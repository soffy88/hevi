"""Story bible ledger — foreshadowing tracking and canon consistency.

Clean-room, file-based companion to the DB-backed ``hevi.storygraph`` layer:
storygraph stores the extracted story graph, this module tracks the two
things a long-running serial needs on top of it, without gating them on a
database migration:

* a **foreshadowing ledger** (one JSON file per work): setups planted in a
  chapter, the chapter window in which they are expected to pay off, and
  their lifecycle state (``planted`` -> ``paid_off`` / ``abandoned``;
  ``overdue`` when the window has passed and the setup is still open);
* a **canon ledger**: confirmed facts (subject / attribute / value, source
  chapter, tags) plus a pre-writing consistency check that compares a new
  chapter's claimed facts against canon and reports contradictions.

Design rules:

* Pure logic + JSON files. No DB, no network, no LLM. The semantic check
  hook (``checker_fn``) is injected by the caller; the built-in rule is
  deterministic: same subject + same attribute + different value is a
  contradiction.
* Writes are atomic: serialize to a temp file in the same directory, then
  ``os.replace`` onto the target, so a crash never leaves a torn ledger.
* Validation lives here (not only in the capability params schema) and
  raises ``ValueError``; the capability layer translates that to
  ``CapabilityError`` so direct users and capability callers both fail
  loudly instead of corrupting a ledger.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "FORESHADOW_STATUSES",
    "CanonFact",
    "CanonLedger",
    "CheckerFn",
    "Contradiction",
    "ForeshadowEntry",
    "ForeshadowLedger",
    "canon_path",
    "check_claims_against_canon",
    "default_storybible_dir",
    "foreshadow_path",
    "slugify_work",
]

FORESHADOW_STATUSES = ("planted", "paid_off", "overdue", "abandoned")
_OPEN_STATUSES = ("planted", "overdue")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value.strip()


def _require_chapter(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer chapter number, got {value!r}")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    return value


def _norm_key_part(value: Any) -> str:
    """Normalize a subject/attribute/value for comparison (case/space-fold)."""
    return " ".join(str(value).strip().lower().split())


# ---------------------------------------------------------------------------
# Storage layout
# ---------------------------------------------------------------------------


def slugify_work(work: str) -> str:
    """Filesystem-safe slug for a work title (unicode letters are kept)."""
    text = _require_text(work, "work")
    slug = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    if not slug:
        raise ValueError(f"work name {work!r} has no usable characters for a file name")
    return slug


def default_storybible_dir() -> Path:
    env = os.environ.get("HEVI_STORYBIBLE_DIR")
    if env:
        return Path(env)
    return Path.cwd() / "data" / "storybible"


def _base_dir(base_dir: Path | str | None) -> Path:
    return Path(base_dir) if base_dir is not None else default_storybible_dir()


def foreshadow_path(work: str, base_dir: Path | str | None = None) -> Path:
    return _base_dir(base_dir) / f"{slugify_work(work)}.foreshadow.json"


def canon_path(work: str, base_dir: Path | str | None = None) -> Path:
    return _base_dir(base_dir) / f"{slugify_work(work)}.canon.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"ledger file is corrupt JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"ledger file must contain a JSON object: {path}")
    return data


# ---------------------------------------------------------------------------
# Foreshadowing ledger
# ---------------------------------------------------------------------------


@dataclass
class ForeshadowEntry:
    """One planted setup and its payoff lifecycle."""

    id: str
    description: str
    planted_chapter: int
    expected_start: int  # first chapter of the expected payoff window
    expected_end: int  # last chapter of the expected payoff window
    status: str = "planted"  # planted | paid_off | overdue | abandoned
    payoff_chapter: int | None = None
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    def is_open(self) -> bool:
        return self.status in _OPEN_STATUSES

    def is_overdue_at(self, current_chapter: int) -> bool:
        return self.is_open() and current_chapter > self.expected_end

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForeshadowEntry:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


class ForeshadowLedger:
    """File-backed foreshadowing ledger for one work."""

    def __init__(self, work: str, base_dir: Path | str | None = None) -> None:
        self.work = _require_text(work, "work")
        self.path = foreshadow_path(self.work, base_dir)
        self._entries: list[ForeshadowEntry] = []
        self._load()

    def _load(self) -> None:
        data = _read_json(self.path)
        if data is None:
            self._entries = []
            return
        raw = data.get("entries", [])
        if not isinstance(raw, list):
            raise ValueError(f"foreshadow ledger {self.path}: 'entries' must be a list")
        self._entries = [ForeshadowEntry.from_dict(item) for item in raw]

    def _save(self) -> None:
        _atomic_write_json(
            self.path,
            {
                "work": self.work,
                "kind": "foreshadow_ledger",
                "version": 1,
                "entries": [e.to_dict() for e in self._entries],
            },
        )

    # -- operations ------------------------------------------------------

    def plant(
        self,
        description: str,
        planted_chapter: int,
        expected_start: int,
        expected_end: int,
        *,
        entry_id: str | None = None,
        note: str = "",
    ) -> ForeshadowEntry:
        """Record a newly planted setup and its expected payoff window."""
        description = _require_text(description, "description")
        planted_chapter = _require_chapter(planted_chapter, "planted_chapter")
        expected_start = _require_chapter(expected_start, "expected_start")
        expected_end = _require_chapter(expected_end, "expected_end")
        if expected_start < planted_chapter:
            raise ValueError(
                f"expected window start {expected_start} precedes "
                f"planted chapter {planted_chapter}"
            )
        if expected_end < expected_start:
            raise ValueError(
                f"expected window end {expected_end} precedes window start {expected_start}"
            )
        entry_id = entry_id or f"fs-{uuid.uuid4().hex[:10]}"
        if self.get(entry_id) is not None:
            raise ValueError(f"duplicate foreshadow id: {entry_id!r}")
        now = _now()
        entry = ForeshadowEntry(
            id=entry_id,
            description=description,
            planted_chapter=planted_chapter,
            expected_start=expected_start,
            expected_end=expected_end,
            status="planted",
            note=note,
            created_at=now,
            updated_at=now,
        )
        self._entries.append(entry)
        self._save()
        return entry

    def get(self, entry_id: str) -> ForeshadowEntry | None:
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def _require_entry(self, entry_id: str) -> ForeshadowEntry:
        entry = self.get(entry_id)
        if entry is None:
            raise ValueError(f"unknown foreshadow id: {entry_id!r}")
        return entry

    def payoff(self, entry_id: str, chapter: int, *, note: str = "") -> ForeshadowEntry:
        """Mark a setup as paid off in ``chapter`` (late payoffs allowed)."""
        entry = self._require_entry(entry_id)
        chapter = _require_chapter(chapter, "chapter")
        if not entry.is_open():
            raise ValueError(
                f"foreshadow {entry_id!r} is {entry.status}; "
                "only planted/overdue entries can pay off"
            )
        if chapter < entry.planted_chapter:
            raise ValueError(
                f"payoff chapter {chapter} precedes planted chapter {entry.planted_chapter}"
            )
        entry.status = "paid_off"
        entry.payoff_chapter = chapter
        if note:
            entry.note = note
        entry.updated_at = _now()
        self._save()
        return entry

    def abandon(self, entry_id: str, *, note: str = "") -> ForeshadowEntry:
        """Retire a setup the author no longer intends to pay off."""
        entry = self._require_entry(entry_id)
        if not entry.is_open():
            raise ValueError(
                f"foreshadow {entry_id!r} is {entry.status}; "
                "only planted/overdue entries can be abandoned"
            )
        entry.status = "abandoned"
        if note:
            entry.note = note
        entry.updated_at = _now()
        self._save()
        return entry

    def list_entries(self, status: str | None = None) -> list[ForeshadowEntry]:
        if status is not None and status not in FORESHADOW_STATUSES:
            raise ValueError(f"unknown foreshadow status filter: {status!r}")
        return [e for e in self._entries if status is None or e.status == status]

    def check_overdue(
        self, current_chapter: int, *, persist: bool = True
    ) -> list[ForeshadowEntry]:
        """Alarm list: open setups whose payoff window passed by ``current_chapter``.

        With ``persist=True`` (default) their stored status flips to
        ``overdue`` so later listings show the alarm state; the returned
        list is the same either way.
        """
        current_chapter = _require_chapter(current_chapter, "current_chapter")
        overdue = [e for e in self._entries if e.is_overdue_at(current_chapter)]
        if persist:
            changed = False
            for entry in overdue:
                if entry.status != "overdue":
                    entry.status = "overdue"
                    entry.updated_at = _now()
                    changed = True
            if changed:
                self._save()
        return overdue


# ---------------------------------------------------------------------------
# Canon ledger + consistency check
# ---------------------------------------------------------------------------


@dataclass
class CanonFact:
    """One confirmed fact of the work's canon."""

    id: str
    fact: str  # human-readable statement of the fact
    subject: str  # who/what the fact is about
    attribute: str  # which property of the subject
    value: str  # the canonical value of that property
    source_chapter: int  # chapter where the fact was established
    tags: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonFact:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Contradiction:
    """A draft claim that clashes with a canon fact."""

    claim_index: int
    subject: str
    attribute: str
    claimed_value: str
    canon_value: str
    canon_fact_id: str
    canon_fact: str
    source_chapter: int  # chapter that established the canon fact
    reason: str = "rule"  # "rule" (deterministic) | "checker" (injected fn)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Injected semantic checker: return True to flag the (claim, canon fact)
# pair as contradictory, False to explicitly clear it, None to defer to
# the deterministic rule.
CheckerFn = Callable[[dict[str, Any], CanonFact], "bool | None"]


class CanonLedger:
    """File-backed list of confirmed canon facts for one work."""

    def __init__(self, work: str, base_dir: Path | str | None = None) -> None:
        self.work = _require_text(work, "work")
        self.path = canon_path(self.work, base_dir)
        self._facts: list[CanonFact] = []
        self._load()

    def _load(self) -> None:
        data = _read_json(self.path)
        if data is None:
            self._facts = []
            return
        raw = data.get("facts", [])
        if not isinstance(raw, list):
            raise ValueError(f"canon ledger {self.path}: 'facts' must be a list")
        self._facts = [CanonFact.from_dict(item) for item in raw]

    def _save(self) -> None:
        _atomic_write_json(
            self.path,
            {
                "work": self.work,
                "kind": "canon_ledger",
                "version": 1,
                "facts": [f.to_dict() for f in self._facts],
            },
        )

    # -- operations ------------------------------------------------------

    def add_fact(
        self,
        *,
        fact: str,
        subject: str,
        attribute: str,
        value: str,
        source_chapter: int,
        tags: Iterable[str] | None = None,
        fact_id: str | None = None,
    ) -> CanonFact:
        """Confirm a fact into canon.

        Re-adding the same subject/attribute/value is idempotent (the
        existing fact is returned). The same subject/attribute with a
        *different* value is a canon conflict and raises ``ValueError`` —
        canon never silently holds two values for one property.
        """
        fact = _require_text(fact, "fact")
        subject = _require_text(subject, "subject")
        attribute = _require_text(attribute, "attribute")
        value = _require_text(value, "value")
        source_chapter = _require_chapter(source_chapter, "source_chapter")
        clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        for existing in self.find(subject, attribute):
            if _norm_key_part(existing.value) == _norm_key_part(value):
                return existing
            raise ValueError(
                f"canon conflict: {subject}/{attribute} is already "
                f"{existing.value!r} (fact {existing.id}, chapter "
                f"{existing.source_chapter}); cannot also be {value!r}"
            )
        fact_id = fact_id or f"fact-{uuid.uuid4().hex[:10]}"
        if any(f.id == fact_id for f in self._facts):
            raise ValueError(f"duplicate canon fact id: {fact_id!r}")
        entry = CanonFact(
            id=fact_id,
            fact=fact,
            subject=subject,
            attribute=attribute,
            value=value,
            source_chapter=source_chapter,
            tags=clean_tags,
            created_at=_now(),
        )
        self._facts.append(entry)
        self._save()
        return entry

    def find(self, subject: str, attribute: str) -> list[CanonFact]:
        """Canon facts about one subject property (normalized matching)."""
        s = _norm_key_part(subject)
        a = _norm_key_part(attribute)
        return [
            f
            for f in self._facts
            if _norm_key_part(f.subject) == s and _norm_key_part(f.attribute) == a
        ]

    def list_facts(self, tag: str | None = None) -> list[CanonFact]:
        if tag is None:
            return list(self._facts)
        return [f for f in self._facts if tag in f.tags]


def check_claims_against_canon(
    claims: Iterable[dict[str, Any]],
    ledger: CanonLedger,
    *,
    checker_fn: CheckerFn | None = None,
) -> dict[str, Any]:
    """Pre-writing consistency check: draft claims vs the canon ledger.

    Each claim is a mapping with ``subject`` / ``attribute`` / ``value``
    (an optional free-text ``fact`` is passed through to ``checker_fn``).
    Deterministic rule: a claim contradicts canon when a canon fact shares
    its subject and attribute but carries a different value. When
    ``checker_fn`` is given it is consulted for every same-subject /
    same-attribute pair: True forces a contradiction, False clears the
    pair, None defers to the rule.

    Returns ``{"ok": bool, "checked": int, "contradictions": [...]}``.
    """
    claims = list(claims)
    contradictions: list[Contradiction] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(
                f"claim #{index} must be an object, got {type(claim).__name__}"
            )
        subject = _require_text(claim.get("subject"), f"claim #{index} subject")
        attribute = _require_text(claim.get("attribute"), f"claim #{index} attribute")
        value = _require_text(claim.get("value"), f"claim #{index} value")
        for fact in ledger.find(subject, attribute):
            rule_hit = _norm_key_part(fact.value) != _norm_key_part(value)
            verdict = checker_fn(claim, fact) if checker_fn is not None else None
            hit = rule_hit if verdict is None else bool(verdict)
            if hit:
                contradictions.append(
                    Contradiction(
                        claim_index=index,
                        subject=subject,
                        attribute=attribute,
                        claimed_value=value,
                        canon_value=fact.value,
                        canon_fact_id=fact.id,
                        canon_fact=fact.fact,
                        source_chapter=fact.source_chapter,
                        reason="checker" if verdict is not None else "rule",
                    )
                )
    return {
        "ok": not contradictions,
        "checked": len(claims),
        "contradictions": [c.to_dict() for c in contradictions],
    }
