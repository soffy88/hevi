"""A13:Authority pin 解析(只读)。范本 = VisualStyleGrammar 的 id@version。

pin 三元组 {authority, id, version_or_hash}。未 pin → 拒绝;解析不到 → STALE。
本模块只读,不写任何 Authority,也不缓存权威事实。
"""

from __future__ import annotations

from dataclasses import dataclass

from hevi.creative.direction_verify.errors import VerifyError

AUTHORITIES = ("narrative", "visual_style", "asset", "provider", "timeline", "voice", "audio")


@dataclass(frozen=True)
class AuthorityPin:
    authority: str
    id: str
    version_or_hash: str

    def key(self) -> str:
        return f"{self.authority}@{self.id}@{self.version_or_hash}"


@dataclass(frozen=True)
class ResolvedPin:
    pin: AuthorityPin
    content_hash: str


def parse_pin(authority: str, ref: str) -> AuthorityPin:
    """`id@version` → pin。缺 version → 未 pin,拒绝(不猜)。"""
    if authority not in AUTHORITIES:
        raise VerifyError(f"unknown authority: {authority}", code="AUTHORITY_UNKNOWN")
    if "@" not in ref:
        raise VerifyError(f"unpinned authority ref: {ref!r}", code="AUTHORITY_REF_UNPINNED")
    ident, _, version = ref.rpartition("@")
    if not ident or not version:
        raise VerifyError(f"unpinned authority ref: {ref!r}", code="AUTHORITY_REF_UNPINNED")
    return AuthorityPin(authority, ident, version)


def resolve_pin(pin: AuthorityPin, registry: dict[str, dict[str, str]]) -> ResolvedPin:
    """registry: {authority: {id@version: content_hash}}。缺失 → STALE(fail-loud)。"""
    versions = registry.get(pin.authority, {})
    content_hash = versions.get(f"{pin.id}@{pin.version_or_hash}")
    if not content_hash:
        raise VerifyError(f"pin not resolvable: {pin.key()}", code="AUTHORITY_REF_STALE")
    return ResolvedPin(pin, content_hash)


def pin_manifest(pins: list[AuthorityPin], registry: dict[str, dict[str, str]]) -> tuple[str, ...]:
    """解析全部 pin,返回 manifest 用的稳定 pin 列表(顺序确定)。"""
    return tuple(resolve_pin(pin, registry).pin.key() for pin in sorted(
        pins, key=lambda p: p.key()))