"""Deterministic serialization codec shared by the S1 director contracts.

Canonical form: `json.dumps(..., sort_keys=True, separators=(",", ":"),
ensure_ascii=False, allow_nan=False)`. Non-JSON types and NaN/Infinity raise
instead of being stringified — a silent fallback would make a hash lie about
what it attests to.
"""

from __future__ import annotations

import hashlib
import json

from hevi.creative.director_brief.errors import DirectorBriefError


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def canonical_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def reject_unknown(payload: dict[str, object], allowed: tuple[str, ...], where: str) -> None:
    extra = sorted(set(payload) - set(allowed))
    if extra:
        raise DirectorBriefError(f"{where}: unknown fields {extra}", code="PAYLOAD_UNKNOWN_FIELD")


def require_keys(payload: dict[str, object], required: tuple[str, ...], where: str) -> None:
    missing = [key for key in required if key not in payload]
    if missing:
        raise DirectorBriefError(f"{where}: missing fields {missing}", code="PAYLOAD_INCOMPLETE")


def as_str(payload: dict[str, object], key: str, default: str = "") -> str:
    return str(payload[key]) if key in payload else default


def as_int(payload: dict[str, object], key: str, default: int) -> int:
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise DirectorBriefError(f"{key}: expected int, got {value!r}", code="PAYLOAD_BAD_TYPE")
    return value


def as_str_tuple(payload: dict[str, object], key: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, list):
        raise DirectorBriefError(f"{key}: expected list, got {value!r}", code="PAYLOAD_BAD_TYPE")
    return tuple(str(item) for item in value)


def as_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise DirectorBriefError(f"{key}: expected object, got {value!r}", code="PAYLOAD_BAD_TYPE")
    return value


def as_dict_list(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DirectorBriefError(f"{key}: expected list of objects, got {value!r}",
                                 code="PAYLOAD_BAD_TYPE")
    return [dict(item) for item in value]