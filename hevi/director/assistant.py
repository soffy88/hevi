"""导演助理 —— 会话式生产助理的确定性审计内核(3O 内化 Phase C,来源 dramaclaw Xia)。

dramaclaw 的 Xia Director 是会话式生产助理:检查项目进度、推进剧本/镜头任务、
审计交付完整性、建议下一步。这里是其**确定性审计内核**(不吃模型,可测):
输入项目状态(任务/镜头/评分)→ 输出:进度摘要 + 交付完整性审计 + 下一步建议。

3O 归属(待上游): `oskill.director_assistant`(审计内核;会话层留 hevi)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 镜头任务状态机(与 readiness 对齐)。
#: 2026-08:h3_local 后处理工序入状态机 —— generating 产出 h3_raw 后,
#: post_upscale(FlashVSR)→ post_rife(可选)再进 verdict;两道 post 均可降级跳过
#: (见 hevi/post/pipeline.py,产物侧车 .post.json 记 no_interp)。
SHOT_STATUSES = (
    "draft",
    "ready",
    "generating",
    "post_upscale",
    "post_rife",
    "verdict",
    "done",
    "rework",
)


@dataclass
class ShotState:
    """一个镜头的可审计状态。"""

    index: int
    status: str
    passed: bool | None = None  # verdict 结果(None = 未裁决)
    diagnosis: str = ""  # 失败诊断分类(失败时)


@dataclass
class EpisodeState:
    """一集的可审计状态。"""

    episode_id: str
    title: str = ""
    status: str = "planned"
    shots: list[ShotState] = field(default_factory=list)


@dataclass
class AuditResult:
    """审计结果:进度 + 完整性 + 建议。"""

    progress_pct: float
    completeness: list[str]  # 未达标交付项
    suggestions: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "progress_pct": self.progress_pct,
            "completeness": self.completeness,
            "suggestions": self.suggestions,
            "summary": self.summary,
        }


def _shot_progress(shot: ShotState) -> float:
    if shot.status == "done":
        return 1.0
    if shot.status == "rework":
        return 0.6
    if shot.status == "verdict":
        return 0.8
    if shot.status == "post_rife":
        return 0.6
    if shot.status == "post_upscale":
        return 0.55
    if shot.status == "generating":
        return 0.5
    if shot.status == "ready":
        return 0.3
    return 0.1


def audit_production(episodes: list[EpisodeState]) -> AuditResult:
    """审计整季:进度百分比 + 交付完整性缺口 + 下一步建议。

    Rules(确定性):
      - 进度 = 已 done 镜头占比。
      - 完整性:planned 状态无镜头 = 剧本/规划未完成;rework 镜头无诊断分类 =
        返工缺诊断;verdict 未裁决 = 待审。
      - 建议:按最紧急缺口给一条(先规划 → 再生成 → 再裁决 → 再返工)。
    """
    all_shots = [s for ep in episodes for s in ep.shots]
    total = len(all_shots)
    done = sum(1 for s in all_shots if s.status == "done")
    progress = (done / total * 100.0) if total else 0.0

    completeness: list[str] = []
    suggestions: list[str] = []

    if any(not ep.shots for ep in episodes):
        completeness.append(
            f"episode {episodes[0].episode_id if episodes else '?'}: 无镜头 → 剧本/分镜未完成"
        )
        suggestions.append("推进剧本与分镜,产出首镜 shot list")

    rework_no_diag = [s for s in all_shots if s.status == "rework" and not s.diagnosis]
    if rework_no_diag:
        completeness.append(
            f"{len(rework_no_diag)} 个 rework 镜头缺诊断分类(先诊断根因,再改 prompt)"
        )
        suggestions.append("为 rework 镜头补诊断分类,按 retake-protocol 五档处置")

    stuck_post = [s for s in all_shots if s.status in ("post_upscale", "post_rife")]
    if stuck_post:
        completeness.append(
            f"{len(stuck_post)} 个镜头停在 post 后处理(post_upscale/post_rife)"
        )
        suggestions.append(
            "跑后处理工序(FlashVSR/RIFE,见 hevi/post);失败镜可降级交付 raw + 标记 no_interp"
        )

    unjudged = [s for s in all_shots if s.status == "verdict" and s.passed is None]
    if unjudged:
        completeness.append(f"{len(unjudged)} 个镜头在 verdict 态待裁决")
        suggestions.append("运行分层校验,裁决待审镜头")

    failed = [s for s in all_shots if s.passed is False]
    if failed:
        completeness.append(f"{len(failed)} 个镜头 verdict 未通过")
        suggestions.append(f"按诊断 {failed[0].diagnosis or '未知'} 定向返工,一次只改一个变量")

    if not suggestions:
        suggestions.append("所有镜头已交付:可选出口 → 连续性报告 / 翻译配音 / 切片分发")

    if total == 0:
        summary = f"{len(episodes)} 集规划中,尚无镜头"
    elif done == total:
        summary = f"{done}/{total} 镜头全部交付,进度 100%"
    else:
        summary = f"{done}/{total} 镜头已交付({progress:.0f}%),最紧急: {suggestions[0]}"

    return AuditResult(
        progress_pct=round(progress, 1),
        completeness=completeness,
        suggestions=suggestions,
        summary=summary,
    )
