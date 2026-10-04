"""P5-A External Video Runtime Contract —— 定义 surface,不安装 runtime。

HEVI **不** vendor、不安装、不猜测 runtime 内部。HEVI 只持有五件事:

    runtime_ref · endpoint/process contract · version ·
    checkpoint identity · capability evidence · health state

两个可用形态(kind):
    ENDPOINT —— 独立 inference 服务(HTTP/自选协议),HEVI 只做客户端
    PROCESS  —— 外部可执行程序(子进程 argv 模板),HEVI 只做调用方

设计立场(与 P4 一致):环境不满足时必须 **ENV_BLOCKED** 早退,
不能在 10GB 卡上启动一个需要 48GB 的 runtime 再等它 OOM。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from hevi.generation.errors import GenerationError

OUTPUT_PROFILES = ("720p", "30fps")


class RuntimeKind(StrEnum):
    ENDPOINT = "ENDPOINT"
    PROCESS = "PROCESS"


class HealthState(StrEnum):
    UNKNOWN = "UNKNOWN"
    REACHABLE = "REACHABLE"
    UNREACHABLE = "UNREACHABLE"
    UNSUPPORTED_ENV = "UNSUPPORTED_ENV"  # 环境不满足,不是 runtime 坏了


class RuntimeUnavailable(GenerationError):
    code = "RUNTIME_UNAVAILABLE"


class EnvironmentBlocked(GenerationError):
    code = "ENV_BLOCKED"


@dataclass(frozen=True)
class EnvironmentRequirements:
    """runtime 声明的硬前置。缺任何一项 → 不得尝试启动。"""
    vram_gb: float = 0.0
    disk_gb: float = 0.0
    cuda_required: bool = False

    def unmet(self, *, vram_gb: float, disk_gb: float, cuda: bool) -> tuple[str, ...]:
        gaps: list[str] = []
        if self.vram_gb and vram_gb < self.vram_gb:
            gaps.append(f"vram {vram_gb}G < {self.vram_gb}G")
        if self.disk_gb and disk_gb < self.disk_gb:
            gaps.append(f"disk {disk_gb}G < {self.disk_gb}G")
        if self.cuda_required and not cuda:
            gaps.append("cuda unavailable")
        return tuple(gaps)


@dataclass(frozen=True)
class EndpointSpec:
    base_url: str
    protocol: str = "http"
    auth_ref: str = ""  # 只存引用(secret manager / env 名),不存凭据


@dataclass(frozen=True)
class ProcessSpec:
    argv_template: tuple[str, ...]
    workdir: str = ""
    env_ref: str = ""
    timeout_s: int = 1800


@dataclass(frozen=True)
class ExternalRuntimeRef:
    """HEVI 对外部 runtime 的**全部**认知。不含任何模型内部参数。"""
    runtime_id: str
    kind: RuntimeKind
    version: str = ""
    checkpoint_identity: str = ""   # 模型 revision id 或权重内容哈希
    endpoint: EndpointSpec | None = None
    process: ProcessSpec | None = None
    requirements: EnvironmentRequirements = field(default_factory=EnvironmentRequirements)
    provenance: str = ""            # 这个 ref 从哪来(谁声明的)

    def validate(self) -> None:
        if not self.runtime_id:
            raise GenerationError("runtime_ref requires runtime_id", code="RUNTIME_REF_INVALID")
        if self.kind is RuntimeKind.ENDPOINT and self.endpoint is None:
            raise GenerationError("ENDPOINT runtime requires endpoint spec",
                                  code="RUNTIME_REF_INVALID")
        if self.kind is RuntimeKind.PROCESS and self.process is None:
            raise GenerationError("PROCESS runtime requires process spec",
                                  code="RUNTIME_REF_INVALID")
        if not self.checkpoint_identity:
            raise GenerationError("runtime_ref requires checkpoint identity",
                                  code="RUNTIME_REF_UNPINNED")

    def fingerprint(self) -> str:
        """稳定身份:换 checkpoint / 换版本 = 换 runtime,证据不可继承。"""
        return hashlib.sha256(json.dumps(
            {"runtime_id": self.runtime_id, "kind": str(self.kind), "version": self.version,
             "checkpoint_identity": self.checkpoint_identity},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {"runtime_id": self.runtime_id, "kind": str(self.kind),
                "version": self.version, "checkpoint_identity": self.checkpoint_identity,
                "requirements": {"vram_gb": self.requirements.vram_gb,
                                 "disk_gb": self.requirements.disk_gb,
                                 "cuda_required": self.requirements.cuda_required},
                "provenance": self.provenance, "fingerprint": self.fingerprint()}


@dataclass(frozen=True)
class RuntimeHealth:
    state: HealthState
    detail: str = ""
    checked_at: str = ""
    latency_ms: int = 0

    @property
    def usable(self) -> bool:
        return self.state is HealthState.REACHABLE


@dataclass(frozen=True)
class RuntimeCapabilities:
    """runtime **实测**能力。缺键 = False(与 P4 同纪律)。"""
    generation: dict[str, bool] = field(default_factory=dict)
    output_profiles: dict[str, bool] = field(default_factory=dict)

    def supports(self, key: str) -> bool:
        return bool(self.generation.get(key, False))

    def profile(self, key: str) -> bool:
        return bool(self.output_profiles.get(key, False))


@dataclass(frozen=True)
class RuntimeSample:
    """一次探针的产物:媒体证据 + 观测。"""
    ok: bool
    artifact_path: str = ""
    detail: str = ""
    observed: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class VideoRuntimeSurface(Protocol):
    """外部 runtime surface 契约。实现体在 HEVI 之外。"""

    ref: ExternalRuntimeRef

    def health(self) -> RuntimeHealth: ...

    def capabilities(self) -> RuntimeCapabilities: ...

    def generate(self, request: object, mode: str) -> RuntimeSample: ...

    def validate_media(self, sample: RuntimeSample) -> RuntimeSample: ...


def check_environment(ref: ExternalRuntimeRef, *, vram_gb: float, disk_gb: float,
                      cuda: bool) -> RuntimeHealth:
    """先查环境再谈 runtime:不满足就 ENV_BLOCKED,不去启动注定失败的进程。"""
    gaps = ref.requirements.unmet(vram_gb=vram_gb, disk_gb=disk_gb, cuda=cuda)
    if gaps:
        return RuntimeHealth(HealthState.UNSUPPORTED_ENV, "; ".join(gaps))
    return RuntimeHealth(HealthState.UNKNOWN, "environment satisfied; runtime not probed")


__all__ = [
    "OUTPUT_PROFILES",
    "EndpointSpec",
    "EnvironmentBlocked",
    "EnvironmentRequirements",
    "ExternalRuntimeRef",
    "HealthState",
    "ProcessSpec",
    "RuntimeCapabilities",
    "RuntimeHealth",
    "RuntimeKind",
    "RuntimeSample",
    "RuntimeUnavailable",
    "VideoRuntimeSurface",
    "check_environment",
]
