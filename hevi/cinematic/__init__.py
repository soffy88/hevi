"""hevi.cinematic —— SPEC-02"电影级"分支的 C 系列阶段(C2.5/C4/C6),EXEC-01 M3。

跟 hevi.tongjian(SPEC-01 L 系列)并列:消费 tongjian 的 ChapterIR/Constitution/
Script 作为输入,产出场景化改编(Scene)→ 分镜(CineShotList)→ 调用 Vidu 生成
视频并过质量门(CG6)。这次只做 animated 分支、单场景 P0 需要的部分,不做全片/
两遍制/风格包(那些是 SPEC-02 C-P1/C-P2 范围)。
"""

from hevi.cinematic.schemas import (
    Beat,
    BeatDialogue,
    CG6Result,
    CineShot,
    CineShotCamera,
    CineShotList,
    Scene,
    ShotResult,
)

__all__ = [
    "Beat",
    "BeatDialogue",
    "CG6Result",
    "CineShot",
    "CineShotCamera",
    "CineShotList",
    "Scene",
    "ShotResult",
]
