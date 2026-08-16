"""失败模式注册表 + 负向子句生成(3O 内化 Phase A,来源 dramaclaw failure_registry)。

dramaclaw 的 failure_registry 思路:失败模式**定义**是共享单源(verification.db),
按层(layer)注入生成 prompt 的**负向子句**;每项目记录**命中统计**反哺优先级。
这正是 HEVI-ARCH §5.3.4"provider 默认行为对照表自我校正闭环"的已实现形态:
verdict 观测到某类失败 → 命中计数 → 负向子句更精准 → 下次生成偏置减小。

本实现为 hevi 暂驻(待上游 `obase.failure_mode_registry` + `oskill.failure_negative_clause`):
- 定义库为纯内存 + JSON 持久化(定义单源,项目命中另存)。
- 负向子句按 layer 生成,可注入逐镜头 prompt 富化。
- 全部确定性、无模型调用,可平移零改动。

3O 归属(待上游): `obase.failure_mode_registry`(定义库)/
`oskill.failure_negative_clause`(子句生成)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: 生成层:身份 / 场景 / 动作 / 语音 / 口型 / 装配(与 L1 分层流水线对齐)。
LAYER_IDS = ("identity", "scene", "action", "voice", "lipsync", "assembly")


@dataclass(frozen=True)
class FailureMode:
    """一条失败模式定义。"""

    code: str  # 稳定标识,一经发布不重排
    layer: str
    description: str
    negative_clause: str  # 注入 prompt 的负向子句(中文,与现有 prompt 风格一致)
    keywords: tuple[str, ...] = ()  # 命中关键词(verdict 诊断分类映射用)


@dataclass
class FailureRegistry:
    """失败模式定义库:共享单源 + 可选 JSON 持久化。"""

    modes: dict[str, FailureMode] = field(default_factory=dict)

    def add(self, mode: FailureMode) -> None:
        if mode.layer not in LAYER_IDS:
            raise ValueError(f"unknown layer {mode.layer!r}; expected one of {LAYER_IDS}")
        self.modes[mode.code] = mode

    def get(self, code: str) -> FailureMode | None:
        return self.modes.get(code)

    def by_layer(self, layer: str) -> list[FailureMode]:
        return [m for m in self.modes.values() if m.layer == layer]

    def build_negative_clause(self, layer: str) -> str:
        """按层生成负向子句块(供逐镜头 prompt 富化注入)。

        - 该层无定义 → 空串(不污染 prompt)。
        - 多条按 code 稳定排序,确定性输出。
        """
        modes = sorted(self.by_layer(layer), key=lambda m: m.code)
        if not modes:
            return ""
        lines = [m.negative_clause for m in modes]
        return "负面约束: " + "。".join(lines) + "。"

    def save(self, path: str | Path) -> None:
        """定义库持久化(JSON)。"""
        data = [
            {
                "code": m.code,
                "layer": m.layer,
                "description": m.description,
                "negative_clause": m.negative_clause,
                "keywords": list(m.keywords),
            }
            for m in self.modes.values()
        ]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> FailureRegistry:
        """从 JSON 载入定义库。"""
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        registry = cls()
        for item in raw:
            registry.add(
                FailureMode(
                    code=item["code"],
                    layer=item["layer"],
                    description=item["description"],
                    negative_clause=item["negative_clause"],
                    keywords=tuple(item.get("keywords", [])),
                )
            )
        return registry


#: 种子定义库 —— 从短剧/通鉴实战诊断沉淀起步(可追加,编号只增不重排)。
SEED_FAILURE_MODES: tuple[FailureMode, ...] = (
    FailureMode(
        code="dialogue_text_overlay",
        layer="assembly",
        description="对白文字叠加层错位/遮挡画面主体",
        negative_clause="无画面内文字叠加,字幕仅由后期独立轨道提供",
        keywords=("字幕", "文字叠加"),
    ),
    FailureMode(
        code="bad_hands",
        layer="action",
        description="手部畸形/多余手指(AI 生成高发)",
        negative_clause="手部结构正常,五根手指,无畸形无多指",
        keywords=("手", "手指"),
    ),
    FailureMode(
        code="face_morph",
        layer="identity",
        description="面部特征漂移/变形,偏离身份锚点",
        negative_clause="面部特征与参考图一致,无变形无漂移",
        keywords=("脸", "五官"),
    ),
    FailureMode(
        code="gibberish_text",
        layer="scene",
        description="场景内出现乱码/无意义文字",
        negative_clause="无乱码文字,场景内文字清晰可读且有意义",
        keywords=("文字", "乱码"),
    ),
    FailureMode(
        code="watermark_logo",
        layer="scene",
        description="画面出现水印/logo 残留",
        negative_clause="无水印,无 logo 残留,无平台角标",
        keywords=("水印", "logo"),
    ),
    FailureMode(
        code="over_smooth",
        layer="action",
        description="动作过平滑/塑料感,缺乏物理",
        negative_clause="动作自然有物理感,衣物布料随动合理,非塑料质感",
        keywords=("塑料", "平滑"),
    ),
)


def default_registry() -> FailureRegistry:
    """内置种子注册表(每次进程内重建;持久化由调用方 save/load 决定)。"""
    registry = FailureRegistry()
    for mode in SEED_FAILURE_MODES:
        registry.add(mode)
    return registry


@dataclass
class FailureHits:
    """每项目命中统计:code → 命中次数(反哺负向子句优先级)。"""

    hits: dict[str, int] = field(default_factory=dict)

    def bump(self, code: str) -> None:
        self.hits[code] = self.hits.get(code, 0) + 1

    def top(self, registry: FailureRegistry, *, limit: int = 5) -> list[tuple[FailureMode, int]]:
        """按命中数降序取 top N 失败模式(诊断/告警用)。"""
        ranked = sorted(
            ((registry.get(code), count) for code, count in self.hits.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        return [(mode, count) for mode, count in ranked if mode is not None][:limit]
