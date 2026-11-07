"""长篇一致性三件套 -- ``story.context_store`` / ``story.foreshadow_ledger`` /
``story.chapter_workspace``。

干净重写，只凭方法论原则描述实现，不引用任何外部作品或仓库的原文与代码。
本模块补的是 season_bible / season_arc / drama_gates 查漏后仍缺的三处：

* season_bible 只校验一本静态圣经，不存上下文、不管变更；
  season_arc 只校验一季弧线表，不管逐章落盘。
  下面三项把“校验”补成“带状态的工作流”，但仍是确定性离线门禁：
  零 LLM、零成本、零网络。

1. 上下文分层 (story.context_store)
   上下文文档分两层分开存放，绝不混写：
   - protected（受保护设定）：人物 / 世界 / 主线。改动受保护设定必须
     显式确认（confirm_protected_change=true），未确认的改动判 blocker，
     且落盘的 context.json 仍是改动前原样——改动不生效、不丢旧设定。
   - summaries（可压缩上下文）：已写章节摘要。压缩时只删不含关键设定
     的句子：含受保护人物名 / 世界关键词的句子一律保留，首句一律保留；
     压缩后仍含原文出现过的全部关键设定词，丢了即判不过（本实现按
     构造保证，压缩函数本身可单测）。
   顶层除 protected / summaries 外再出现 characters / world 之类设定键，
   记 major（混层警告）：设定只能住在 protected 里。

2. 伏笔状态结算 (story.foreshadow_ledger)
   伏笔三态台账：registered（登记）-> planted（埋设）-> paid（回收）。
   - planted 必须有 planted_chapter（埋设章节），缺了判 blocker；
   - paid 必须有 paid_chapter（回收出处章节），且 planted_chapter 须早于
     paid_chapter；无出处回收、未埋先兑，都判 blocker；
   - 已到 due_chapter（计划揭示章）仍未 paid，判 blocker（悬而未决）；
   - paid_chapter 超出当前章（current_chapter），判 blocker（未来兑现）。
   任一 blocker 即 passed=false。

3. 安全章节工作区 (story.chapter_workspace)
   新章节先校验后落盘，顺序不可颠倒：
   - 章号必须连续（上一章 + 1，无上一章时须为第 1 章）；
   - 出场人物必须全部在 protected 人物表内（按 id 或 name 匹配）；
   - 本章埋设的伏笔必须已在台账登记，本章回收的伏笔必须已埋设且未回收；
   - 章节正文不能为空。
   校验不过：只写门禁报告（workspace_report.json），不写章节文件，
   不写更新后的台账——任何状态都不推进。校验通过：章节文件与更新后
   台账经临时文件 + os.replace 一次原子落盘（临时文件不残留）。

Harness 思想对照（任务第 4 项，见最终报告亦有同款说明）：
本模块与 drama_gates / script_polish 共享同一完成判定——口头完成不算数，
只有落盘报告文件存在且其中 passed 字段为真才算通过：
- drama_gates：passed = blocker 数为 0，报告 drama_gates_report.json +
  账本 ledger 追加行；
- script_polish：passed = blocker 数为 0，报告 polish_report.json；
- 本模块三项：同款规则，报告分别为 context_report.json /
  foreshadow_ledger_report.json / workspace_report.json。
调用方验完成时应读报告文件本身，而不是只看返回值。

Skill 粒度对照（任务第 5 项，只作说明不动结构）：
hevi 的能力注册本就是一能力一职责（一个 Capability = 一道门或一次编译，
params_schema 显式、additionalProperties 关闭），与“小粒度、可组合的
skill”同一粒度；本模块三项各注册一个能力，不合并成一个大而全的
“长篇助手”，现有注册结构因此不动。
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_LEDGER_STATUSES = ("registered", "planted", "paid")


# ---------------------------------------------------------------------------
# 通用 helpers
# ---------------------------------------------------------------------------


def _finding(
    check: str, severity: str, issue: str, suggestion: str
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "issue": issue,
        "suggestion": suggestion,
    }


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"blocker": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


def _atomic_write(path: Path, text: str) -> Path:
    """经临时文件 + os.replace 一次落盘；临时文件不残留。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    return _atomic_write(
        path, json.dumps(payload, ensure_ascii=False, indent=2)
    )


# ---------------------------------------------------------------------------
# 1. 上下文分层
# ---------------------------------------------------------------------------


def _protected_key_terms(protected: dict[str, Any]) -> list[str]:
    """从受保护设定中抽关键设定词：人物 id/name、世界地名类字符串。

    只抽长度 >= 2 的字符串，排序去重，保证压缩校验确定性。
    """
    terms: set[str] = set()
    for char in protected.get("characters", []) or []:
        if isinstance(char, dict):
            for key in ("id", "name"):
                val = char.get(key)
                if isinstance(val, str) and len(val.strip()) >= 2:
                    terms.add(val.strip())
        elif isinstance(char, str) and len(char.strip()) >= 2:
            terms.add(char.strip())
    world = protected.get("world")
    if isinstance(world, dict):
        for val in world.values():
            if isinstance(val, str) and 2 <= len(val.strip()) <= 20:
                terms.add(val.strip())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and 2 <= len(item.strip()) <= 20:
                        terms.add(item.strip())
    elif isinstance(world, str) and len(world.strip()) >= 2:
        terms.add(world.strip())
    return sorted(terms)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；！？\n])")


def compress_summary(text: str, key_terms: list[str]) -> str:
    """压缩一段章节摘要：首句必留，含关键设定词的句子必留，其余删去。

    压缩后仍含原文出现过的全部关键设定词（按构造保证：含词的句子
    一个不少）。无句读分隔的单句摘要原样返回。
    """
    if not isinstance(text, str) or not text.strip():
        return text
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        return text
    kept: list[str] = []
    for idx, sent in enumerate(sentences):
        if idx == 0 or any(term in sent for term in key_terms):
            kept.append(sent)
    return "".join(kept)


def validate_context(
    context: Any,
    proposed_protected: dict[str, Any] | None = None,
    confirm_protected_change: bool = False,
    compress_summaries: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """校验上下文文档，返回 (findings, 生效后的上下文)。

    未确认的受保护改动判 blocker，且生效上下文仍是原样（改动不生效）。
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(context, dict):
        raise CapabilityError("story.context_store: 'context' must be an object")
    protected = context.get("protected")
    summaries = context.get("summaries")
    if not isinstance(protected, dict) or not protected:
        raise CapabilityError(
            "story.context_store: 'context.protected' must be a non-empty object"
        )
    if not isinstance(summaries, dict):
        raise CapabilityError(
            "story.context_store: 'context.summaries' must be an object"
        )
    for key in context:
        if key not in ("protected", "summaries"):
            findings.append(
                _finding(
                    "context_layering",
                    "major",
                    f"上下文顶层混入设定键 {key!r}：设定只能住在 protected 里，"
                    "顶层只留 protected / summaries 两层。",
                    f"把 {key!r} 移入 protected（受保护设定）或 summaries（摘要）其一。",
                )
            )
    effective = copy.deepcopy(context)
    if proposed_protected is not None:
        if not isinstance(proposed_protected, dict):
            raise CapabilityError(
                "story.context_store: 'proposed_protected' must be an object"
            )
        changed = {
            k
            for k in set(protected) | set(proposed_protected)
            if protected.get(k) != proposed_protected.get(k)
        }
        if changed:
            if not confirm_protected_change:
                findings.append(
                    _finding(
                        "protected_change",
                        "blocker",
                        "受保护设定改动未确认："
                        f"改动键 {sorted(changed)}，须显式确认才生效。",
                        "确认无误后以 confirm_protected_change=true 重新提交；"
                        "未确认前旧设定保持不变。",
                    )
                )
            else:
                effective["protected"] = copy.deepcopy(proposed_protected)
    if compress_summaries:
        terms = _protected_key_terms(effective["protected"])
        new_summaries: dict[str, Any] = {}
        for chap, summary in effective["summaries"].items():
            if isinstance(summary, str):
                compressed = compress_summary(summary, terms)
                dropped_terms = [
                    t
                    for t in terms
                    if t in summary and t not in compressed
                ]
                if dropped_terms:
                    findings.append(
                        _finding(
                            "summary_compression",
                            "blocker",
                            f"摘要压缩丢关键设定：第 {chap} 章摘要压缩后丢失 "
                            f"{dropped_terms}。",
                            "压缩不得删除含关键设定词的句子，恢复被删句子后重试。",
                        )
                    )
                new_summaries[chap] = compressed
            else:
                new_summaries[chap] = summary
        if not any(f["severity"] == "blocker" for f in findings):
            effective["summaries"] = new_summaries
    if any(f["severity"] == "blocker" for f in findings):
        # blocker 在场：生效上下文回滚为提交前原样（改动一律不生效）。
        effective = copy.deepcopy(context)
    return findings, effective


# ---------------------------------------------------------------------------
# 2. 伏笔状态结算
# ---------------------------------------------------------------------------


def validate_foreshadow_ledger(
    ledger: Any, current_chapter: Any
) -> list[dict[str, Any]]:
    """校验伏笔三态台账，返回 findings（blocker 在场即不过）。"""
    if not isinstance(ledger, list):
        raise CapabilityError("story.foreshadow_ledger: 'ledger' must be a list")
    if not isinstance(current_chapter, int) or isinstance(current_chapter, bool):
        raise CapabilityError(
            "story.foreshadow_ledger: 'current_chapter' must be an integer"
        )
    findings: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for idx, entry in enumerate(ledger):
        label = f"伏笔[{idx}]"
        if not isinstance(entry, dict):
            raise CapabilityError(
                "story.foreshadow_ledger: each ledger entry must be an object"
            )
        fid = entry.get("foreshadow_id")
        if _is_missing(fid):
            findings.append(
                _finding(
                    "foreshadow_ledger",
                    "blocker",
                    f"{label} 缺 foreshadow_id，台账无法引用。",
                    "给每条伏笔一个稳定唯一的 foreshadow_id。",
                )
            )
            continue
        fid = str(fid)
        seen[fid] = seen.get(fid, 0) + 1
        status = entry.get("status")
        if status not in _LEDGER_STATUSES:
            findings.append(
                _finding(
                    "foreshadow_ledger",
                    "blocker",
                    f"伏笔 {fid} 状态非法：{status!r}（只允许 "
                    "registered / planted / paid）。",
                    "把状态改回三态之一，状态只能按 登记 -> 埋设 -> 回收 前进。",
                )
            )
            continue
        planted_ch = entry.get("planted_chapter")
        paid_ch = entry.get("paid_chapter")
        due_ch = entry.get("due_chapter")
        if status in ("planted", "paid") and not isinstance(planted_ch, int):
            findings.append(
                _finding(
                    "foreshadow_ledger",
                    "blocker",
                    f"伏笔 {fid} 已{status}却无 planted_chapter（埋设章节）。",
                    "补上埋设章节；没有埋设章节的伏笔无法证明它被埋过。",
                )
            )
        if status == "paid":
            if not isinstance(paid_ch, int):
                findings.append(
                    _finding(
                        "foreshadow_ledger",
                        "blocker",
                        f"伏笔 {fid} 已回收却无 paid_chapter（回收出处章节）"
                        "：无出处回收判不过。",
                        "补上回收发生的章节号；回收必须有出处章节可查。",
                    )
                )
            elif isinstance(planted_ch, int) and paid_ch <= planted_ch:
                findings.append(
                    _finding(
                        "foreshadow_ledger",
                        "blocker",
                        f"伏笔 {fid} 回收章节（第 {paid_ch} 章）不晚于埋设章节"
                        f"（第 {planted_ch} 章）：未埋先兑。",
                        "回收章节必须晚于埋设章节，否则是无埋之兑。",
                    )
                )
            if isinstance(paid_ch, int) and paid_ch > current_chapter:
                findings.append(
                    _finding(
                        "foreshadow_ledger",
                        "blocker",
                        f"伏笔 {fid} 回收章节第 {paid_ch} 章超出当前章"
                        f"第 {current_chapter} 章：未来兑现。",
                        "只登记已写章节内发生的回收，未写章节的回收不算数。",
                    )
                )
        if status in ("registered", "planted") and isinstance(due_ch, int):
            if due_ch <= current_chapter:
                findings.append(
                    _finding(
                        "foreshadow_ledger",
                        "blocker",
                        f"伏笔 {fid} 已到计划揭示章第 {due_ch} 章（当前"
                        f"第 {current_chapter} 章）仍未回收：悬而未决。",
                        f"要么在本章前兑现 {fid}，要么把 due_chapter 推后并"
                        "写明理由，不能让它无声过期。",
                    )
                )
    for fid, count in seen.items():
        if count > 1:
            findings.append(
                _finding(
                    "foreshadow_ledger",
                    "blocker",
                    f"伏笔 id 重复：{fid} 出现 {count} 次。",
                    "伏笔 id 必须唯一，重复 id 会让埋设与回收指向不明。",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# 3. 安全章节工作区
# ---------------------------------------------------------------------------


def _protected_character_keys(protected: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for char in protected.get("characters", []) or []:
        if isinstance(char, dict):
            for key in ("id", "name"):
                val = char.get(key)
                if isinstance(val, str) and val.strip():
                    keys.add(val.strip())
        elif isinstance(char, str) and char.strip():
            keys.add(char.strip())
    return keys


def validate_new_chapter(
    new_chapter: dict[str, Any],
    last_chapter_no: int | None,
    context: dict[str, Any] | None,
    ledger: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """校验新章节，返回 (findings, 更新后的台账副本)。

    校验不过时调用方不得落盘任何状态；返回的台账副本此时仍是原样。
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(new_chapter, dict):
        raise CapabilityError("story.chapter_workspace: 'new_chapter' must be an object")
    chap_no = new_chapter.get("chapter_no")
    if not isinstance(chap_no, int) or isinstance(chap_no, bool):
        raise CapabilityError(
            "story.chapter_workspace: 'new_chapter.chapter_no' must be an integer"
        )
    expected = 1 if last_chapter_no is None else last_chapter_no + 1
    if chap_no != expected:
        findings.append(
            _finding(
                "chapter_continuity",
                "blocker",
                f"章号不连续：上一章为第 {last_chapter_no} 章时新章应为"
                f"第 {expected} 章，实际第 {chap_no} 章。",
                "按顺序写下一章，跳号会让伏笔埋设/回收章节全部错位。",
            )
        )
    if _is_missing(new_chapter.get("text")):
        findings.append(
            _finding(
                "chapter_content",
                "blocker",
                f"第 {chap_no} 章正文为空：空章节不能落盘。",
                "写出本章正文后再提交。",
            )
        )
    if context is not None:
        protected = context.get("protected", {}) if isinstance(context, dict) else {}
        known = _protected_character_keys(protected) if isinstance(protected, dict) else set()
        for name in new_chapter.get("characters", []) or []:
            if str(name) not in known:
                findings.append(
                    _finding(
                        "chapter_characters",
                        "blocker",
                        f"第 {chap_no} 章出场人物 {name!r} 不在受保护人物表内。",
                        "人物须先登记进 protected 人物表才能出场，"
                        "否则跨章人物会漂移。",
                    )
                )
    updated_ledger = copy.deepcopy(ledger) if isinstance(ledger, list) else None
    if ledger is not None:
        by_id: dict[str, dict[str, Any]] = {}
        for entry in ledger:
            if isinstance(entry, dict) and entry.get("foreshadow_id") is not None:
                by_id[str(entry["foreshadow_id"])] = entry
        for fid in new_chapter.get("foreshadows_planted", []) or []:
            entry = by_id.get(str(fid))
            if entry is None:
                findings.append(
                    _finding(
                        "chapter_foreshadow",
                        "blocker",
                        f"第 {chap_no} 章埋设的伏笔 {fid!r} 未在台账登记。",
                        "先登记伏笔再埋设，未登记的埋设无法结算。",
                    )
                )
            elif entry.get("status") == "paid":
                findings.append(
                    _finding(
                        "chapter_foreshadow",
                        "blocker",
                        f"第 {chap_no} 章埋设的伏笔 {fid!r} 已回收，不能重埋。",
                        "已回收的伏笔不再埋设，如需呼应请登记一条新伏笔。",
                    )
                )
        for fid in new_chapter.get("foreshadows_paid", []) or []:
            entry = by_id.get(str(fid))
            if entry is None:
                findings.append(
                    _finding(
                        "chapter_foreshadow",
                        "blocker",
                        f"第 {chap_no} 章回收的伏笔 {fid!r} 未在台账登记。",
                        "先登记再埋设再回收，未登记的回收是无出处回收。",
                    )
                )
            elif entry.get("status") != "planted":
                findings.append(
                    _finding(
                        "chapter_foreshadow",
                        "blocker",
                        f"第 {chap_no} 章回收的伏笔 {fid!r} 现状为 "
                        f"{entry.get('status')!r}（非 planted）：未埋先兑。",
                        "回收前须先有一章埋设过它，且埋设章节早于回收章节。",
                    )
                )
            elif isinstance(entry.get("planted_chapter"), int) and (
                entry["planted_chapter"] >= chap_no
            ):
                findings.append(
                    _finding(
                        "chapter_foreshadow",
                        "blocker",
                        f"第 {chap_no} 章回收的伏笔 {fid!r} 埋设于第 "
                        f"{entry['planted_chapter']} 章，不早于回收章。",
                        "回收章节必须晚于埋设章节。",
                    )
                )
    if findings and any(f["severity"] == "blocker" for f in findings):
        return findings, copy.deepcopy(ledger) if isinstance(ledger, list) else None
    if updated_ledger is not None:
        by_id_new: dict[str, dict[str, Any]] = {
            str(e["foreshadow_id"]): e
            for e in updated_ledger
            if isinstance(e, dict) and e.get("foreshadow_id") is not None
        }
        for fid in new_chapter.get("foreshadows_planted", []) or []:
            entry = by_id_new.get(str(fid))
            if entry is not None and entry.get("status") == "registered":
                entry["status"] = "planted"
                entry["planted_chapter"] = chap_no
        for fid in new_chapter.get("foreshadows_paid", []) or []:
            entry = by_id_new.get(str(fid))
            if entry is not None and entry.get("status") == "planted":
                entry["status"] = "paid"
                entry["paid_chapter"] = chap_no
    return findings, updated_ledger


# ---------------------------------------------------------------------------
# Capability renders
# ---------------------------------------------------------------------------


def _render_context_store(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    context = params.get("context")
    findings, effective = validate_context(
        context,
        proposed_protected=params.get("proposed_protected"),
        confirm_protected_change=bool(params.get("confirm_protected_change", False)),
        compress_summaries=bool(params.get("compress_summaries", False)),
    )
    counts = _counts(findings)
    passed = counts["blocker"] == 0
    payload = {
        "passed": passed,
        "counts": counts,
        "findings": findings,
        "context": effective,
    }
    out = Path(out_dir)
    report = _write_json(out / "context_report.json", payload)
    _write_json(out / "context.json", effective)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "context_json": str(out / "context.json"), **payload},
    )


def _render_foreshadow_ledger(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    findings = validate_foreshadow_ledger(
        params.get("ledger"), params.get("current_chapter")
    )
    counts = _counts(findings)
    passed = counts["blocker"] == 0
    payload = {
        "passed": passed,
        "counts": counts,
        "findings": findings,
        "ledger": params.get("ledger"),
        "current_chapter": params.get("current_chapter"),
    }
    report = _write_json(Path(out_dir) / "foreshadow_ledger_report.json", payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def _render_chapter_workspace(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    new_chapter = params.get("new_chapter")
    existing = params.get("existing_chapters")
    last_no = params.get("last_chapter_no")
    if existing is not None:
        if not isinstance(existing, list):
            raise CapabilityError(
                "story.chapter_workspace: 'existing_chapters' must be a list"
            )
        nums = [
            e.get("chapter_no")
            for e in existing
            if isinstance(e, dict) and isinstance(e.get("chapter_no"), int)
        ]
        last_no = max(nums) if nums else None
    elif last_no is not None and (
        not isinstance(last_no, int) or isinstance(last_no, bool)
    ):
        raise CapabilityError(
            "story.chapter_workspace: 'last_chapter_no' must be an integer"
        )
    ledger = params.get("ledger")
    if ledger is not None and not isinstance(ledger, list):
        raise CapabilityError("story.chapter_workspace: 'ledger' must be a list")
    findings, updated_ledger = validate_new_chapter(
        new_chapter, last_no, params.get("context"), ledger
    )
    counts = _counts(findings)
    passed = counts["blocker"] == 0
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "passed": passed,
        "counts": counts,
        "findings": findings,
        "chapter_no": new_chapter.get("chapter_no") if isinstance(new_chapter, dict) else None,
        "chapter_file": None,
        "ledger_file": None,
    }
    if passed:
        chap_no = new_chapter["chapter_no"]
        chapter_path = out / f"chapter_{chap_no:02d}.txt"
        body = f"{new_chapter.get('title', '')}\n{new_chapter.get('text', '')}\n"
        _atomic_write(chapter_path, body)
        payload["chapter_file"] = str(chapter_path)
        if updated_ledger is not None:
            ledger_path = _write_json(out / "ledger.json", {"ledger": updated_ledger})
            payload["ledger_file"] = str(ledger_path)
            payload["ledger"] = updated_ledger
    report = _write_json(out / "workspace_report.json", payload)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "protected": {"type": "object"},
        "summaries": {"type": "object"},
    },
}


def register_longform_context_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.context_store",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "context": _CONTEXT_SCHEMA,
                    "proposed_protected": {"type": "object"},
                    "confirm_protected_change": {"type": "boolean"},
                    "compress_summaries": {"type": "boolean"},
                },
                "required": ["context"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_context_store,
            has_media_output=False,
            description=(
                "长篇上下文分层存储：受保护设定（人物/世界/主线）与可压缩"
                "章节摘要分离存放；受保护设定改动须显式确认，未确认判"
                " blocker 且旧设定原样保留；摘要压缩只删不含关键设定词的"
                "句子，关键设定不丢。零 LLM、零成本。"
            ),
            line="longform_context",
        )
    )
    register(
        Capability(
            name="story.foreshadow_ledger",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "ledger": {"type": "array"},
                    "current_chapter": {"type": "integer"},
                },
                "required": ["ledger", "current_chapter"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_foreshadow_ledger,
            has_media_output=False,
            description=(
                "伏笔三态台账结算：登记 -> 埋设 -> 回收；埋设须有埋设章节，"
                "回收须有回收出处章节且晚于埋设；已到揭示章未回收（悬而未决）"
                "与无出处回收都判 blocker。零 LLM、零成本。"
            ),
            line="longform_context",
        )
    )
    register(
        Capability(
            name="story.chapter_workspace",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "new_chapter": {"type": "object"},
                    "existing_chapters": {"type": "array"},
                    "last_chapter_no": {"type": "integer"},
                    "context": _CONTEXT_SCHEMA,
                    "ledger": {"type": "array"},
                },
                "required": ["new_chapter"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_chapter_workspace,
            has_media_output=False,
            description=(
                "安全章节工作区：新章节先校验（章号连续、人物在受保护表内、"
                "伏笔登记/埋设/回收链完整、正文非空）后原子落盘；校验不过"
                "只写门禁报告，不写章节文件、不更新台账，任何状态都不推进。"
                "零 LLM、零成本。"
            ),
            line="longform_context",
        )
    )
    return [
        "story.context_store",
        "story.foreshadow_ledger",
        "story.chapter_workspace",
    ]


register_longform_context_capabilities_once()
