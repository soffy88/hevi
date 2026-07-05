"""manifest.json 契约 —— 见 HEVI-SPEC-03 §2.2。pydantic 模型即结构校验器,不另写
jsonschema 校验(项目既有惯例,同 hevi/tongjian/schemas.py 的决策)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

PACK_TYPES: frozenset[str] = frozenset({"identity", "style", "scene", "voice"})
LIFECYCLE_STATES: frozenset[str] = frozenset(
    {"draft", "validated", "published", "superseded", "deprecated"}
)


class ManifestFile(BaseModel):
    sha256: str
    role: str = ""  # canonical_portrait/kinetic_ref/...


class Provenance(BaseModel):
    built_by_run: str | None = None
    source_chapter: str | None = None
    gen_models: list[str] = Field(default_factory=list)


class StabilityCheck(BaseModel):
    """稳定性预检(§4.1):同参考同 prompt 生成 3 次,≥2 次过身份门才允许 validated。"""

    passed: bool = False
    score: str = ""  # 如 "3/3"
    checked_at: str | None = None


class Manifest(BaseModel):
    pack_id: str  # 如 "identity/C001"
    pack_type: str
    version: str  # semver,不可变
    name: str
    immutable_traits: str = ""
    era_lock: str = ""
    files: dict[str, ManifestFile] = Field(default_factory=dict)  # 相对路径 → 文件信息
    embeddings: dict[str, dict] = Field(default_factory=dict)  # kind → {model, dim}
    voice: dict = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)
    stability_check: StabilityCheck = Field(default_factory=StabilityCheck)
    lifecycle: str = "draft"
    reuse_stats: dict = Field(default_factory=dict)

    @field_validator("pack_type")
    @classmethod
    def _check_pack_type(cls, v: str) -> str:
        if v not in PACK_TYPES:
            raise ValueError(f"pack_type must be one of {sorted(PACK_TYPES)}, got {v!r}")
        return v

    @field_validator("lifecycle")
    @classmethod
    def _check_lifecycle(cls, v: str) -> str:
        if v not in LIFECYCLE_STATES:
            raise ValueError(f"lifecycle must be one of {sorted(LIFECYCLE_STATES)}, got {v!r}")
        return v
