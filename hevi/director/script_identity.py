"""G0.2-A Script Stable Identity spike — minimal adapter.

不重构 screenplay 生成/解析,只提供:
- `ScriptUnit`:稳定文本单元(身份与顺序分离,身份不可变)
- `assign_unit_ids`:老数据补 ID(确定性)
- `inherit_unit_ids`:revision 时继承 ID(Rule 1-3)
- `resolve_unit`:引用解析,缺失即 orphan(供 Anchor 侧报 ANCHOR_ORPHANED)

匹配策略是 spike 级(同 scene 内 difflib 相似度贪心,阈值 0.5),生产级
语义匹配是后续工作,见 docs/p10/spikes/script_identity_report.md。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptUnit:
    unit_id: str  # 不可变;删除后永不复用
    scene_id: str = ""
    order: int = 0  # 顺序可变,身份不变
    text: str = ""
    source_ref: str = ""
    revision: int = 1  # 文本改写 bump revision,不换 ID


_MATCH_THRESHOLD = 0.5
_LINE_NO_RE = re.compile(r"\.line(\d+)$")


def _next_line_no(scene_id: str, taken: set[str]) -> int:
    taken_no = 0
    for uid in taken:
        if uid.startswith(scene_id + ".line"):
            m = _LINE_NO_RE.search(uid)
            if m:
                taken_no = max(taken_no, int(m.group(1)))
    return taken_no + 1


def _fresh_id(scene_id: str, taken: set[str]) -> str:
    return f"{scene_id}.line{_next_line_no(scene_id, taken):03d}"


def assign_unit_ids(units: list[ScriptUnit]) -> list[ScriptUnit]:
    """补齐空 unit_id。确定性:同 scene 按 order/出现序递增,不复用已有 ID。"""
    taken = {u.unit_id for u in units if u.unit_id}
    out: list[ScriptUnit] = []
    for u in units:
        if u.unit_id:
            out.append(u)
            continue
        uid = _fresh_id(u.scene_id or "scene", taken)
        taken.add(uid)
        out.append(ScriptUnit(uid, u.scene_id, u.order, u.text, u.source_ref, u.revision))
    return out


def inherit_unit_ids(
    old: list[ScriptUnit],
    new_texts: list[tuple[str, str, str]],
) -> list[ScriptUnit]:
    """Rule 1-3:改写继承(同 scene 相似度贪心)、插入新增、删除 ID 永不复用。

    new_texts: [(scene_id, text, source_ref)] 按新顺序。
    返回 units 的 order 为新顺序。
    """
    old_by_scene: dict[str, list[ScriptUnit]] = {}
    for u in old:
        old_by_scene.setdefault(u.scene_id, []).append(u)
    retired = {u.unit_id for u in old}
    taken = set(retired)
    used_old: set[str] = set()
    out: list[ScriptUnit] = []

    # pass 1:同 scene 同文本精确继承
    pending: list[tuple[int, str, str, str]] = []
    for i, (scene_id, text, source_ref) in enumerate(new_texts):
        hit = next(
            (u for u in old_by_scene.get(scene_id, []) if u.unit_id not in used_old and u.text == text),
            None,
        )
        if hit is not None:
            used_old.add(hit.unit_id)
            out.append(
                ScriptUnit(hit.unit_id, scene_id, i, text, source_ref or hit.source_ref, hit.revision)
            )
        else:
            pending.append((i, scene_id, text, source_ref))

    # pass 2:同 scene 相似度继承(Rule 1 改写场景)
    still_pending: list[tuple[int, str, str, str]] = []
    for i, scene_id, text, source_ref in pending:
        best: ScriptUnit | None = None
        best_ratio = 0.0
        for u in old_by_scene.get(scene_id, []):
            if u.unit_id in used_old:
                continue
            ratio = difflib.SequenceMatcher(None, u.text, text).ratio()
            if ratio > best_ratio:
                best_ratio, best = ratio, u
        if best is not None and best_ratio >= _MATCH_THRESHOLD:
            used_old.add(best.unit_id)
            out.append(
                ScriptUnit(best.unit_id, scene_id, i, text, source_ref or best.source_ref, best.revision + 1)
            )
        else:
            still_pending.append((i, scene_id, text, source_ref))

    # pass 3:剩余为新单元(Rule 2),序号从历史最大值后递增(Rule 3 不复用)
    for i, scene_id, text, source_ref in still_pending:
        uid = _fresh_id(scene_id, taken)
        taken.add(uid)
        out.append(ScriptUnit(uid, scene_id, i, text, source_ref, 1))

    out.sort(key=lambda u: u.order)
    return out


def resolve_unit(units: list[ScriptUnit], unit_id: str) -> ScriptUnit | None:
    """引用解析。返回 None = orphan,调用方必须 fail-loud(ANCHOR_ORPHANED)。"""
    return next((u for u in units if u.unit_id == unit_id), None)


# ── Q5:多语言单元对应 ──


def namespaced_unit_id(unit_id: str, language: str) -> str:
    """翻译单元 ID 加语言命名空间,避免多语言共用一套 ID 时互相覆盖。

    `scene1.line004` + `zh` → `zh:scene1.line004`;已是命名空间则替换(不叠加)。
    """
    base = unit_id.split(":", 1)[1] if ":" in unit_id else unit_id
    return f"{language}:{base}" if language else base


@dataclass(frozen=True)
class TranslationLink:
    language: str
    source_unit_id: str
    target_unit_id: str


@dataclass(frozen=True)
class TranslationIndex:
    """同一 Direction 下,源语言单元 → 各语言单元的对应表。"""

    links: tuple[TranslationLink, ...] = ()

    def targets(self, source_unit_id: str) -> tuple[str, ...]:
        return tuple(link.target_unit_id for link in self.links
                     if link.source_unit_id == source_unit_id)

    def missing_sources(self, source_unit_ids: tuple[str, ...]) -> tuple[str, ...]:
        """源单元没有对应译单元 = orphan(删除/合并后翻译侧会缺锚点)。"""
        linked = {link.source_unit_id for link in self.links}
        return tuple(uid for uid in source_unit_ids if uid not in linked)


def build_translation_index(*, language: str,
                            pairs: list[tuple[str, str]]) -> TranslationIndex:
    """由**显式**对应关系建索引(pairs: [(source_unit_id, target_unit_id)])。

    刻意不做按文本的自动配对:翻译后源文与译文文本必然不同,按文本推断等于
    错连锚点。对应关系由翻译层给出;给不出就是不连边(宁可缺,不可错连)。
    """
    return TranslationIndex(tuple(
        TranslationLink(language, source_id, namespaced_unit_id(target_id, language))
        for source_id, target_id in pairs
    ))
