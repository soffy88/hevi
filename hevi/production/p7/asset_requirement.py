"""HEVI P7.0 — Asset requirements: what a compiled production plan needs.

An :class:`AssetRequirement` is a *declaration of need*, not an asset and not an
asset type. It names two orthogonal things — the media representation wanted and
the narrative role it serves — plus how many, how good, and under what sourcing
terms:

    {"media_type": "IMAGE", "semantic_role": "CHARACTER",
     "quality_floor": 8, "source_policy": "PREFERRED_LICENSED",
     "constraints": {"period": "1930s", "face_required": "true"}}

``quality_floor`` reuses ``hevi.provider_policy.ProviderPolicy.quality_floor``'s
scale — an integer 0-10 — rather than inventing a second one. Two quality scales
would be the vocabulary mistake P6.5.2 made, in a different place.

``source_policy`` states the licensing terms a candidate must satisfy. It is a
declaration, not a decision: which provider ends up serving it is
``hevi.provider_policy``'s call, reached through
:mod:`hevi.production.p7.asset_policy`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType

#: Constraint keys the sourcing authority already understands. Declared as a closed
#: set so a requirement can be validated, while still permitting extras — an
#: unconstrained string vocabulary here would drift from the validator's.
KNOWN_CONSTRAINTS: frozenset[str] = frozenset(
    {
        "period",
        "face_required",
        "resolution",
        "duration",
        "license",
        "locale",
        "aspect",
        "query",
        # B0:负向硬约束。「不要拿通用星空 / 纯标题卡 / 大段说明文字代替真实画面」
        # 是 HEVI 早已声明、却从未执行的产品约束。值是逗号分隔的 substitute_kind,
        # 判定在 p7/constraint_check.py::check_forbidden_substitutes。
        "forbidden_substitutes",
    }
)

#: B0:`forbidden_substitutes` 的取值分隔符与 token 形状。
FORBIDDEN_SUBSTITUTES_SEPARATOR = ","
_SUBSTITUTE_KIND_PATTERN = re.compile(r"^[a-z0-9_]+$")

#: 0-10, matching ProviderPolicy.quality_floor.
QUALITY_FLOOR_MIN = 0
QUALITY_FLOOR_MAX = 10


class SourcePolicy(StrEnum):
    """Licensing terms an accepted candidate must satisfy.

    Stated as a requirement, enforced against ``hevi.provider_policy``'s decision —
    never by branching on a provider name.
    """

    LICENSED_ONLY = "LICENSED_ONLY"
    PREFERRED_LICENSED = "PREFERRED_LICENSED"
    LOCAL_ONLY = "LOCAL_ONLY"
    ANY_AVAILABLE = "ANY_AVAILABLE"


@dataclass(frozen=True)
class AssetRequirement:
    """One declared need: representation, role, quantity, floor and terms."""

    media_type: MediaType
    semantic_role: AssetSemanticRole
    requirement_id: str = ""
    quantity: int = 1
    quality_floor: int = 7
    source_policy: SourcePolicy = SourcePolicy.PREFERRED_LICENSED
    constraints: tuple[tuple[str, str], ...] = ()
    evidence_required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.media_type, MediaType):
            raise ValueError(f"UNKNOWN_MEDIA_TYPE:{self.media_type!r}")
        if not isinstance(self.semantic_role, AssetSemanticRole):
            raise ValueError(f"UNKNOWN_ASSET_SEMANTIC_ROLE:{self.semantic_role!r}")
        if self.quantity < 1:
            raise ValueError(f"INVALID_ASSET_QUANTITY:{self.quantity}; must be >= 1")
        if not QUALITY_FLOOR_MIN <= self.quality_floor <= QUALITY_FLOOR_MAX:
            raise ValueError(
                f"INVALID_QUALITY_FLOOR:{self.quality_floor}; expected "
                f"{QUALITY_FLOOR_MIN}-{QUALITY_FLOOR_MAX}, the same scale as "
                "hevi.provider_policy.ProviderPolicy.quality_floor"
            )
        if not isinstance(self.source_policy, SourcePolicy):
            raise ValueError(f"UNKNOWN_SOURCE_POLICY:{self.source_policy!r}")
        if not self.requirement_id:
            # Derived, never random: the same need always yields the same id, so a
            # decision can be traced to its requirement across runs.
            object.__setattr__(
                self, "requirement_id", f"{self.media_type.value}/{self.semantic_role.value}"
            )
        for key, value in self.constraints:
            if not key:
                raise ValueError("EMPTY_ASSET_CONSTRAINT_KEY")
            if key == "forbidden_substitutes":
                # B0:畸形值必须**构造期**失败。若解析器静默丢弃畸形 token,
                # 打错字符的「禁止」会变成 no-op —— 那是 fail-OPEN。
                self._validate_forbidden_substitutes(value)

    @staticmethod
    def _validate_forbidden_substitutes(value: str) -> None:
        if not value:
            raise ValueError("EMPTY_FORBIDDEN_SUBSTITUTES")
        tokens = value.split(FORBIDDEN_SUBSTITUTES_SEPARATOR)
        for token in tokens:
            if not token or not _SUBSTITUTE_KIND_PATTERN.match(token):
                raise ValueError(
                    f"MALFORMED_FORBIDDEN_SUBSTITUTE:{token!r} in {value!r}; expected "
                    f"comma-separated lowercase [a-z0-9_]+ substitute kinds")

    def constraint_map(self) -> dict[str, str]:
        return dict(self.constraints)

    def forbidden_substitutes(self) -> tuple[str, ...]:
        """被禁止的替代物种类,按声明顺序。

        与 ``query()`` 同形:从 ``constraints`` 读,不新增字段。
        构造期已保证取值合法(见 `_validate_forbidden_substitutes`),所以这里
        不会静默返回空集合。
        """
        raw = self.constraint_map().get("forbidden_substitutes", "")
        if not raw:
            return ()
        return tuple(raw.split(FORBIDDEN_SUBSTITUTES_SEPARATOR))

    def unknown_constraints(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, _ in self.constraints if k not in KNOWN_CONSTRAINTS))

    def query(self) -> str:
        """The declared search query, if any.

        Read from ``constraints["query"]``. A requirement may declare one; P7 never
        invents a query from a product identity.
        """
        return self.constraint_map().get("query", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "media_type": self.media_type.value,
            "semantic_role": self.semantic_role.value,
            "quantity": self.quantity,
            "quality_floor": self.quality_floor,
            "source_policy": self.source_policy.value,
            "constraints": dict(self.constraints),
            "evidence_required": self.evidence_required,
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "FORBIDDEN_SUBSTITUTES_SEPARATOR",
    "KNOWN_CONSTRAINTS",
    "QUALITY_FLOOR_MAX",
    "QUALITY_FLOOR_MIN",
    "AssetRequirement",
    "SourcePolicy",
]
