"""KidsConsistencyManifest —— 最小只读加载层（K2 草案实现）。

依据：RENOISE_EVAL.md §3.3 草案 schema。K1（feat/kids-manifest）在并行开发正式
``KidsConsistencyManifest``；本分支**不等待**它，先按 §3.3 草案实现一个最小只读
加载/校验层。所有消费 manifest 的代码只通过 ``hevi/kids/manifest_adapter`` 的
``load_manifest()`` 单一适配点访问，日后可无缝换成 K1 的正式实现。

本模块**只读**分析 K1 worktree 的已 commit 代码（方法学），不修改它，也不复制其原文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = "1.0-draft"

# §3.3 要求的 style_bible 四段
STYLE_BIBLE_KEYS = ("art_style", "camera_language", "color_grade", "negative")

# 续作闸门在 §3.6 里要求的平均镜头时长下限
MIN_SHOT_DURATION = 2.5
AVG_SHOT_DURATION = 3.5


class ManifestValidationError(Exception):
    """manifest 不合法（缺字段 / 取值越界 / 未知引用）。"""


@dataclass
class ShotEntry:
    """单镜条目（§3.3 shots[] 的轻量投影）。"""

    shot_index: int
    duration: float
    line: str = ""
    camera: str | None = None
    framing: str | None = None
    keyframe: str | None = None
    shot_spec: dict[str, Any] | None = None

    def spec(self) -> dict[str, Any]:
        return self.shot_spec or {}


@dataclass
class KidsConsistencyManifestDraft:
    """§3.3 草案 manifest 的只读投影 + 基础校验。"""

    data: dict[str, Any]
    source_path: Path | None = None

    # ── 构造 / 加载 ────────────────────────────────────────────────
    @classmethod
    def load(cls, path: str | Path) -> "KidsConsistencyManifestDraft":
        p = Path(path)
        if not p.exists():
            raise ManifestValidationError(f"manifest not found: {p}")
        import json

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ManifestValidationError(f"manifest is not valid JSON: {e}") from e
        return cls(data=data, source_path=p)

    # ── 字段访问 ──────────────────────────────────────────────────
    def shots(self) -> list[ShotEntry]:
        out: list[ShotEntry] = []
        for raw in self.data.get("shots", []):
            spec = raw.get("shot_spec")
            kf = raw.get("keyframe")
            if kf is None:
                # 顶层 keyframes 映射（可选扩展，便于本地渲染回灌真实关键帧）
                kf = (self.data.get("keyframes") or {}).get(str(raw.get("shot_index")))
            out.append(
                ShotEntry(
                    shot_index=int(raw.get("shot_index", len(out))),
                    duration=float(raw.get("duration", 0.0)),
                    line=str(raw.get("line", "")),
                    camera=raw.get("camera"),
                    framing=raw.get("framing"),
                    keyframe=kf,
                    shot_spec=spec,
                )
            )
        out.sort(key=lambda s: s.shot_index)
        return out

    def shot(self, idx: int) -> ShotEntry | None:
        for s in self.shots():
            if s.shot_index == idx:
                return s
        return None

    def style_bible(self) -> dict[str, Any]:
        return self.data.get("style_bible", {}) or {}

    def transition_table(self) -> list[dict[str, Any]]:
        return self.data.get("transition_table", []) or []

    def characters(self) -> list[dict[str, Any]]:
        return self.data.get("characters", []) or []

    def props(self) -> list[dict[str, Any]]:
        return self.data.get("props", []) or []

    def scenes(self) -> list[dict[str, Any]]:
        return self.data.get("scenes", []) or []

    def spoken_language(self) -> list[dict[str, Any]]:
        return self.data.get("spoken_language", []) or []

    def theme(self) -> dict[str, Any]:
        return self.data.get("theme", {}) or {}

    def episode(self) -> int:
        return int(self.data.get("episode", 1))

    def title(self) -> str:
        return str(self.data.get("title", "未命名"))

    def total_duration(self) -> float:
        return sum(s.duration for s in self.shots())

    def language_for_shot(self, idx: int) -> str | None:
        for entry in self.spoken_language():
            if int(entry.get("shot_index", -1)) == idx:
                return entry.get("language")
        return None

    # ── 校验（委派给 ShotSpec 校验器做 shot_spec 字段合法性）────────
    def validate(self) -> list[str]:
        """返回错误列表（空 = 合法）。非法 shot_spec 直接抛 ManifestValidationError。"""
        errors: list[str] = []
        shots = self.shots()
        if not shots:
            errors.append("manifest 没有 shots")
            return errors

        # 1) duration 约束
        for s in shots:
            if s.duration < MIN_SHOT_DURATION:
                errors.append(
                    f"S{s.shot_index} duration {s.duration}s < {MIN_SHOT_DURATION}s"
                )
        avg = sum(s.duration for s in shots) / len(shots)
        if avg < AVG_SHOT_DURATION:
            errors.append(f"平均镜头时长 {avg:.2f}s < {AVG_SHOT_DURATION}s")

        # 2) style_bible 四段齐全
        sb = self.style_bible()
        for k in STYLE_BIBLE_KEYS:
            if not sb.get(k):
                errors.append(f"style_bible 缺字段 {k}")

        # 3) transition_table 覆盖除 S1 外每个切点
        covered = {t.get("cut") for t in self.transition_table()}
        n = len(shots)
        for i in range(1, n):
            cut = f"S{i}->S{i+1}"
            if cut not in covered:
                errors.append(f"transition_table 缺切点 {cut}")

        # 4) spoken_language 覆盖每个说话镜（有 line 的镜）
        spoken = {int(e.get("shot_index", -1)) for e in self.spoken_language()}
        for s in shots:
            if s.line and s.shot_index not in spoken:
                errors.append(f"S{s.shot_index} 有台词但缺 spoken_language")

        # 5) @引用 解析（manifest 内 characters/props/scenes 的 id）
        errors.extend(self._check_references())

        # 6) 委派 ShotSpec 校验器（未知 template/transition/sfx/style → 抛错）
        from hevi.production.shot_spec import ShotSpec

        for s in shots:
            spec = s.shot_spec
            if not spec:
                continue
            try:
                ShotSpec.model_validate(spec)
            except Exception as e:  # pydantic ValidationError 或 ValueError
                errors.append(f"S{s.shot_index} shot_spec 非法: {e}")

        return errors

    def _check_references(self) -> list[str]:
        """@char_fox / @prop_star / @scene_forest 必须在 manifest 内可解析。"""
        ids: set[str] = set()
        for c in self.characters():
            ids.add(f"@{c.get('id')}")
        for p in self.props():
            ids.add(f"@{p.get('id')}")
        for sc in self.scenes():
            ids.add(f"@{sc.get('id')}")

        import re

        ref_re = re.compile(r"@([A-Za-z0-9_]+)")
        errors: list[str] = []
        for s in self.shots():
            for token in ref_re.findall(s.line or ""):
                ref = f"@{token}"
                if ref not in ids:
                    errors.append(f"S{s.shot_index} 未知引用 {ref}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return self.data


@dataclass
class ManifestValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    shot_count: int = 0
    total_duration: float = 0.0
    style_bible_complete: bool = False
    transition_table_complete: bool = False
