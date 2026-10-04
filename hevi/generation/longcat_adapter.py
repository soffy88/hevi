"""LongCatVideoAdapterSkeleton —— 默认态 NOT_EVALUABLE,不声称任何能力。

它实现 canonical `VideoGenerationBackend` 形状,因此一旦 runtime 接入即可替换,
但在 Evidence Gate 通过之前:
  - capabilities() 全 False;
  - generate() 抛 PROVIDER_NOT_INSTALLED,不产出任何媒体;
  - 不注册进 ProviderRegistry。
"""

from __future__ import annotations

from hevi.generation.errors import GenerationError
from hevi.generation.longcat_probe import (
    ProbeReport,
    admitted_capabilities_from,
    evidence_snapshot,
    probe,
)
from hevi.generation.models import (
    CAPABILITY_KEYS,
    GeneratedClip,
    VideoGenerationCapabilities,
    VideoGenerationRequest,
)

NAME = "longcat-video"
VERSION = "skeleton-0.1"


class ProviderNotInstalled(GenerationError):
    code = "PROVIDER_NOT_INSTALLED"


class LongCatVideoAdapterSkeleton:
    """形状齐备、能力为空。存在它是为了让接线点可见,而不是为了假装可用。"""

    name = NAME
    version = VERSION

    def __init__(self, *, source_root: str | None = None,
                 checkpoint_path: str | None = None) -> None:
        self._source_root = source_root
        self._checkpoint_path = checkpoint_path

    def probe(self) -> ProbeReport:
        return probe(source_root=self._source_root, checkpoint_path=self._checkpoint_path)

    def capabilities(self) -> VideoGenerationCapabilities:
        """只反映 probe 结果。未全通过 → 全 False。"""
        return VideoGenerationCapabilities(admitted_capabilities_from(self.probe()))

    def generate(self, request: VideoGenerationRequest) -> GeneratedClip:
        # 无条件拒绝:骨架不产出媒体。接线后此处才由真实 runtime 承接。
        raise ProviderNotInstalled(
            f"{NAME} is an integration boundary; admission gate not satisfied "
            f"({evidence_snapshot()['admission']})")

    def supports_anything(self) -> bool:
        return any(self.capabilities().declared.values())


def longcat_is_admitted() -> bool:
    return LongCatVideoAdapterSkeleton().supports_anything()


__all__ = [
    "CAPABILITY_KEYS",
    "LongCatVideoAdapterSkeleton",
    "ProviderNotInstalled",
    "evidence_snapshot",
    "longcat_is_admitted",
]
