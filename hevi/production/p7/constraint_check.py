"""p7 requirement 兼容性判定 —— 填补 canonical 层的既有缺口。

事实(S0 审计):`AssetRequirement.constraints` 的 8 个 key 里**只有 `query` 被读过**
(`asset_requirement.py:116`);其余 7 个(period / face_required / resolution / duration /
license / locale / aspect)在 `asset_binding.py` 只被**写成字面量**,全仓没有任何
「这份素材是否满足这条需求」的判定原语。

本模块提供该原语,遵循既有约定:
- 素材事实来自 **canonical probe**(`hevi/artifact/probes.py` 的 OBSERVABLE_FIELDS),
  不自己重新探测;
- 判定用既有 `CheckOperator` 语义,不发明新比较语义;
- **类型必须显式换算**:constraint 值是字符串("1080" / "3"),probe 产出的是
  tuple(w,h) / float。直接 `EQ` 永不匹配 —— 那正是原实现的静默失败模式。
- 只判**硬约束**。软分(scoring)不属本模块,归 canonical scorer。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hevi.production.p7.asset_requirement import AssetRequirement

# 素材事实字段名 → constraint key 的映射(只覆盖可机械判定的)
OBSERVED_TO_CONSTRAINT = {
    "duration": "duration",
    "resolution": "resolution",
    "license": "license",
    "locale": "locale",
    "aspect": "aspect",
    "face_required": "face_required",
    "period": "period",
}

# 需要换算的 constraint(direct EQ 会静默失败)
_TYPED_CONSTRAINTS = {"duration", "resolution", "aspect"}


@dataclass(frozen=True)
class ConstraintOutcome:
    key: str
    expected: str
    satisfied: bool | None  # None = 该约束**未被观察**,不可判定(不是通过)
    observed: object = None
    detail: str = ""

    @property
    def blocking(self) -> bool:
        """只有「观察到了且不满足」才算阻塞。未观察到 → 由调用方 fail-closed。"""
        return self.satisfied is False

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "expected": self.expected, "satisfied": self.satisfied,
                "observed": self.observed, "detail": self.detail}


@dataclass(frozen=True)
class CompatibilityReport:
    requirement_id: str
    outcomes: tuple[ConstraintOutcome, ...] = ()

    @property
    def blocked_keys(self) -> tuple[str, ...]:
        return tuple(o.key for o in self.outcomes if o.blocking)

    @property
    def undecidable_keys(self) -> tuple[str, ...]:
        """约束存在但素材事实里观察不到 —— 无法判定,必须显式处理。"""
        return tuple(o.key for o in self.outcomes if o.satisfied is None)

    @property
    def compatible(self) -> bool:
        return not self.blocked_keys and not self.undecidable_keys

    def to_dict(self) -> dict[str, object]:
        return {"requirement_id": self.requirement_id,
                "compatible": self.compatible,
                "blocked": list(self.blocked_keys),
                "undecidable": list(self.undecidable_keys),
                "outcomes": [o.to_dict() for o in self.outcomes]}


def _parse_aspect(value: str) -> tuple[int, int] | None:
    try:
        w, _, h = value.partition(":")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None


def check_duration(expected: str, observed: object) -> bool | None:
    """`duration` 是**下限**(素材应至少覆盖镜头时长)。observed 是 float 秒。"""
    try:
        return float(str(observed)) >= float(expected)
    except (TypeError, ValueError):
        return None


def check_resolution(expected: str, observed: object) -> bool | None:
    """`resolution` 语义为最小高度约束("1080" → height >= 1080)。

    probe 产出 `resolution=(w,h)`;若只有 width/height 也接受。
    """
    try:
        min_height = int(expected)
    except (TypeError, ValueError):
        return None
    height = observed[1] if isinstance(observed, tuple | list) and len(observed) == 2 else observed
    try:
        return int(str(height)) >= min_height
    except (TypeError, ValueError):
        return None


def _reduce_aspect(pair: tuple[int, int] | list[int]) -> tuple[int, int] | None:
    """把像素比约分到最小整数比:1080x1920 → 9:16。"""
    try:
        w, h = int(pair[0]), int(pair[1])
    except (TypeError, ValueError, IndexError):
        return None
    if w <= 0 or h <= 0:
        return None
    divisor = math.gcd(w, h)
    return w // divisor, h // divisor


def check_aspect(expected: str, observed: object) -> bool | None:
    want = _parse_aspect(expected)
    if want is None or not isinstance(observed, tuple | list) or len(observed) != 2:
        return None
    got = _reduce_aspect(observed)
    if got is None:
        return None
    # 像素比必须先约分:1080x1920 与 9:16 是同一比例
    return got == _reduce_aspect(want)


def check_equality(expected: str, observed: object) -> bool | None:
    if observed is None:
        return None
    return str(observed) == str(expected)


def check_bool(expected: str, observed: object) -> bool | None:
    if observed is None:
        return None
    return bool(observed) is (str(expected).lower() in {"1", "true", "yes"})


_CHECKS = {
    "duration": check_duration,
    "resolution": check_resolution,
    "aspect": check_aspect,
    "license": check_equality,
    "locale": check_equality,
    "face_required": check_bool,
    "period": check_equality,
}


def _derive_aspect(observed: dict[str, object]) -> tuple[int, int] | None:
    """probe 不直接给 `aspect`,只给 `resolution=(w,h)` —— 从中派生(归一化的一环)。"""
    raw = observed.get("aspect")
    if isinstance(raw, tuple | list) and len(raw) == 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return None
    resolution = observed.get("resolution")
    if isinstance(resolution, tuple | list) and len(resolution) == 2:
        try:
            return int(resolution[0]), int(resolution[1])
        except (TypeError, ValueError):
            return None
    return None


def check_compatibility(requirement: AssetRequirement,
                        observed: dict[str, object]) -> CompatibilityReport:
    """需求硬约束 × 素材观测事实 → CompatibilityReport。

    `observed` 用 `hevi/artifact/probes.py::OBSERVABLE_FIELDS` 的键。
    未在 observed 里的约束 → `satisfied=None`(不可判定),**不是**通过。
    """
    if "aspect" in requirement.constraint_map() and observed.get("aspect") is None:
        derived = _derive_aspect(observed)
        if derived is not None:
            observed = {**observed, "aspect": derived}
    outcomes: list[ConstraintOutcome] = []
    for key, expected in requirement.constraint_map().items():
        if key == "query":
            # query 是检索意图,不是可判定约束(由候选来源负责)
            continue
        observed_key = OBSERVED_TO_CONSTRAINT.get(key, key)
        checker = _CHECKS.get(key)
        raw = observed.get(observed_key)
        if checker is None:
            outcomes.append(ConstraintOutcome(key, expected, None, raw, "no checker"))
            continue
        satisfied = checker(expected, raw)
        detail = ""
        if satisfied is None:
            detail = "not observed" if raw is None else "unparseable"
        outcomes.append(ConstraintOutcome(key, expected, satisfied, raw, detail))
    return CompatibilityReport(requirement.requirement_id, tuple(outcomes))


__all__ = [
    "OBSERVED_TO_CONSTRAINT",
    "CompatibilityReport",
    "ConstraintOutcome",
    "check_aspect",
    "check_bool",
    "check_compatibility",
    "check_duration",
    "check_equality",
    "check_resolution",
]