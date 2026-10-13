"""ShotSpec —— 单镜规格(模板/入场转场/特效/风格/音效/运镜/字幕样式/时长)。

GAP_PLAN §2 W1:此前每个镜头的"怎么接、加什么效果、配什么音效"散落在各处调用参数
里,没有统一可持久化、可校验的单镜规格。本模块定义 ``ShotSpec`` 模型,并把所有取值
收敛到既有注册表做校验:

  - ``template``       → T1 FX 注册表 ``hevi/fx/registry.py`` 的模板 id
  - ``transition_in``  → T2 xfade 注册表 ``hevi/assembly/xfade_transitions.py`` 的 id
                         (``cut`` = 硬切;第 1 镜忽略)
  - ``effect``         → 内置 5 种(warm/cool/mono/vignette/sharpen)+ 注册表里
                         style 类条目(能映射成 ffmpeg 滤镜的尽力而为)
  - ``style``          → 若 ``hevi/layer4_legacy/dirstyle`` 已合并则校验其风格 id;
                         否则自由字符串
  - ``sfx``            → ``assets/audio/sfx/library/manifest.json`` 里的音效 id
  - ``camera`` / ``subtitle_style`` / ``duration`` → 自由/数值字段

未知取值一律让 pydantic 抛 ``ValidationError``(FastAPI 转 422),绝不静默放行。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ── 内置特效名 ────────────────────────────────────────────────────────
# 这些名字直接映射到 shot_spec_render 里的 ffmpeg 滤镜链。
BUILTIN_EFFECTS: frozenset[str] = frozenset({"warm", "cool", "mono", "vignette", "sharpen"})

#: ``transition_in`` 的特殊值:硬切(不重叠,由 build_xfade_chain 的 concat 分支处理)。
CUT = "cut"


def _repo_root() -> Path:
    """仓库根(hevi/production/shot_spec.py 往上三层)。"""
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _registry():
    """惰性单例 FX 注册表(不扫预览,只取 id 集合做校验)。"""
    from hevi.fx.loader import load_all

    return load_all(sync_previews=False)


@lru_cache(maxsize=1)
def _manifest_ids() -> frozenset[str]:
    """sfx manifest 里的全部音效 id(70 条,含 library/ 子目录资产)。"""
    manifest = _repo_root() / "assets" / "audio" / "sfx" / "library" / "manifest.json"
    if not manifest.exists():
        return frozenset()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return frozenset(a["id"] for a in data.get("assets", []) if a.get("id"))


def valid_sfx_ids() -> frozenset[str]:
    """合法音效 id 集合 = 注册表 sfx 源 + manifest 资产 id(二者取并)。"""
    from hevi.fx.registry import Source

    reg_ids = {t.source_ref for t in _registry().list_all() if t.source == Source.SFX}
    return frozenset(reg_ids | set(_manifest_ids()))


def sfx_asset_path(sfx_id: str) -> Path:
    """按 id 解析音效文件路径(manifest 的 ``file`` 字段,仓库相对)。"""
    manifest = _repo_root() / "assets" / "audio" / "sfx" / "library" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for a in data.get("assets", []):
        if a.get("id") == sfx_id:
            return _repo_root() / a["file"]
    # 退化:顶层 sfx/<id>.wav(注册表 sfx 源对应)
    return _repo_root() / "assets" / "audio" / "sfx" / f"{sfx_id}.wav"


def valid_template_ids() -> frozenset[str]:
    """FX 注册表里的全部模板 id。"""
    return frozenset(t.id for t in _registry().list_all())


def valid_style_effect_ids() -> frozenset[str]:
    """注册表里 category==style 的模板 id(effect 字段可接受这些)。"""
    from hevi.fx.registry import Category

    return frozenset(t.id for t in _registry().list_all() if t.category == Category.STYLE)


def valid_transition_ids() -> frozenset[str]:
    """xfade 注册表里的全部转场 id(不含 ``cut``)。"""
    from hevi.assembly.xfade_transitions import ALL_TRANSITIONS

    return frozenset(t.id for t in ALL_TRANSITIONS)


def _dirstyle_module():
    """dirstyle 模块(未合并时为 None)。"""
    try:
        from hevi.layer4_legacy import dirstyle  # type: ignore[attr-defined]

        return dirstyle
    except Exception:  # 模块未合并/导入失败都视作不可用
        return None


class SFXCue(BaseModel):
    """一条音效提示:音效 id + 相对本镜起点的偏移秒数。"""

    id: str
    offset: float = 0.0

    @field_validator("offset")
    @classmethod
    def _offset_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"sfx offset must be >= 0, got {v}")
        return v


class ShotSpec(BaseModel):
    """单镜规格。所有字段可选;未知取值由校验器拒绝(→ 422)。"""

    template: str | None = None
    transition_in: str | None = None
    effect: str | None = None
    # TODO(dirstyle): validate once feat/director-styles merges —— 目前 dirstyle 未合并,
    # 该字段是自由字符串;合并后改为校验 dirstyle 风格 id。
    style: str | None = None
    sfx: list[SFXCue] = Field(default_factory=list)
    camera: str | None = None
    subtitle_style: str | None = None
    duration: float | None = None

    @field_validator("duration")
    @classmethod
    def _duration_positive(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError(f"duration must be > 0, got {v}")
        return v

    @field_validator("template")
    @classmethod
    def _template_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in valid_template_ids():
            raise ValueError(f"unknown template id '{v}' (not in FX registry)")
        return v

    @field_validator("transition_in")
    @classmethod
    def _transition_known(cls, v: str | None) -> str | None:
        if v is None or v == CUT:
            return v
        if v not in valid_transition_ids():
            raise ValueError(f"unknown transition id '{v}' (not in xfade registry)")
        return v

    @field_validator("effect")
    @classmethod
    def _effect_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v in BUILTIN_EFFECTS:
            return v
        # 注册表 style 类条目:尽力而为映射成 ffmpeg 滤镜(见 shot_spec_render)。
        if v in valid_style_effect_ids():
            return v
        raise ValueError(
            f"unknown effect '{v}' (must be one of {sorted(BUILTIN_EFFECTS)} "
            "or a registry style id)"
        )

    @field_validator("style")
    @classmethod
    def _style_known(cls, v: str | None) -> str | None:
        if v is None:
            return v
        mod = _dirstyle_module()
        if mod is None:
            return v  # dirstyle 未合并 → 自由字符串
        ids = getattr(mod, "valid_style_ids", None)
        if callable(ids) and v not in ids():
            raise ValueError(f"unknown dirstyle id '{v}'")
        return v

    @model_validator(mode="after")
    def _sfx_valid(self) -> ShotSpec:
        known = valid_sfx_ids()
        for cue in self.sfx:
            if cue.id not in known:
                raise ValueError(f"unknown sfx id '{cue.id}' (not in sfx manifest/registry)")
            if self.duration is not None and cue.offset >= self.duration:
                raise ValueError(f"sfx offset {cue.offset} must be < duration {self.duration}")
        return self

    def to_dict(self) -> dict[str, Any]:
        """JSON 安全 dict(落库/响应共用)。"""
        return self.model_dump(exclude_none=False)


def validate_specs(specs: list[dict[str, Any]]) -> list[ShotSpec]:
    """批量校验:任一非法整体抛 ``ValidationError``(调用方转 422)。"""
    return [ShotSpec.model_validate(s) for s in specs]


# ── 持久化(挂在 shot_states.selection_json["shot_spec"],零迁移)──────────
# 与 hevi.season_planner.preparation 同构:跟随任务现有 shot 存储,不新建库表。

SPEC_KEY = "shot_spec"


def upsert_spec(shot_row: dict[str, Any], spec: ShotSpec) -> dict[str, Any]:
    """把规格写回 shot_states 行(selection_json.shot_spec)。"""
    sel = dict(shot_row.get("selection_json") or {})
    sel[SPEC_KEY] = spec.to_dict()
    shot_row["selection_json"] = sel
    return shot_row


def read_spec(shot_row: dict[str, Any]) -> ShotSpec | None:
    """从 shot_states 行读取规格(无则 None)。"""
    raw = (shot_row.get("selection_json") or {}).get(SPEC_KEY)
    if not raw:
        return None
    return ShotSpec.model_validate(raw)


def merge_patch(base: ShotSpec, patch: dict[str, Any]) -> ShotSpec:
    """部分更新:只覆盖 ``patch`` 里显式给出的键,未给字段保留 ``base`` 的值。

    ``patch`` 应为 ``model_dump(exclude_unset=True)`` 的结果——区分"显式传 null"
    (清空该字段)与"没传"(保留)。
    """
    merged = base.model_dump()
    merged.update(patch)
    return ShotSpec.model_validate(merged)
