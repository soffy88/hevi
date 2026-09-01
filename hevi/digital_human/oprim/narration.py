"""digital_human oprim:内容锁定与旁白生成原子。"""

from __future__ import annotations

from typing import Any

from hevi.digital_human.schemas import JobStatus, PresenterJob


def build_narration_spine(
    topic: str,
    language: str = "auto",
    duration_s: int = 60,
) -> dict[str, Any]:
    """从主题构建旁白脊柱。

    对应 lanshu generation.md: "hook → promise → 2–4 useful beats → synthesis → close"
    """
    return {
        "hook": f"关于 {topic} 的核心问题",
        "promise": f"接下来 {max(1, duration_s)} 秒为你讲清楚",
        "beats": [
            f"{topic} 的核心概念",
            f"{topic} 的关键细节",
            f"{topic} 的实际应用",
            f"{topic} 的常见误区",
        ][:4],
        "synthesis": f"总结 {topic} 的关键点",
        "close": "感谢观看，点赞关注",
    }


def topic_to_script(topic: str, duration_s: int = 60) -> str:
    """把主题展开为可审阅的确定性旁白草稿。"""
    spine = build_narration_spine(topic, duration_s=duration_s)
    parts = [spine["hook"], spine["promise"]] + spine["beats"] + [spine["synthesis"], spine["close"]]
    return "。".join(parts) + "。"


def lock_content(job: PresenterJob) -> PresenterJob:
    """锁定内容阶段：主题→脚本+Beat Sheet。"""
    job.status = JobStatus.CONTENT_LOCKED
    job.script = topic_to_script(job.topic, job.duration_target_s)
    job.beat_sheet = "hook → promise → 2–4 useful beats → synthesis → close"
    return job
