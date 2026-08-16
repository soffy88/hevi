"""SPEC-004 v2 B5 端到端集成证明:角度 → 几何选视图 → img2img → 朝向落到画面。

走真实生产函数:compute_shot_views(几何)+ _edit_keyframe(img2img 路)。复用已建的王生 4 视图
(output/gs1_3dtest/,B4 前 TripoSR 跑出)。零云端花费(全本地 sdxl img2img)。

设计:王生 facing_deg=90(面向画右)。三个机位 azimuth=0/90/180,几何应分别算出王生该用
left/front/right 视图。各出一帧 → 看朝向是否随机位变、是否对得上,并实测 _VIEW_BY_DELTA 的
left/right 约定要不要翻。

用法(需 GPU + 已建王生视图):
  HF_HOME=/data/models/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    uv run python scripts/b5_orientation_e2e.py --real
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from hevi.director.pipeline_schemas import (
    CameraSetup,
    CoveragePlan,
    InitialPosition,
    SceneAxis,
    SceneBlocking,
    SceneStage,
    SceneStageSet,
    ShotList,
    ShotListItem,
)
from hevi.director.scene_stage import compute_shot_views

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("b5")

_STYLE = "cinematic realistic photograph"
_APPEARANCE = (
    "a young Chinese male scholar in his early 20s, handsome clean face, black hair topknot, "
    "blue traditional scholar robe"
)
_VIEWS_DIR = Path("output/gs1_3dtest")  # 王生的 front/left/right/back.png(B4 前 TripoSR 已产)


def build() -> tuple[SceneStage, ShotList]:
    """王生 facing_deg=90;三个机位 azimuth 0/90/180 → 几何选 left/front/right。"""
    stage = SceneStage(
        scene_ref=1,
        blocking=SceneBlocking(
            initial_positions=[InitialPosition(char_id="王生", zone_id="z1", facing_deg=90)]
        ),
        axis=SceneAxis(primary_axis=["王生", "老道"]),
        coverage_plan=CoveragePlan(
            setups=[
                CameraSetup(setup_id="cam_az0", azimuth_deg=0, subjects=["王生"]),
                CameraSetup(setup_id="cam_az90", azimuth_deg=90, subjects=["王生"]),
                CameraSetup(setup_id="cam_az180", azimuth_deg=180, subjects=["王生"]),
            ]
        ),
    )
    shots = ShotList(
        shots=[
            ShotListItem(
                shot_id=f"SH_{setup}",
                scene_no=1,
                scene_stage_ref=1,
                camera_setup_ref=setup,
                character_names=["王生"],
            )
            for setup in ("cam_az0", "cam_az90", "cam_az180")
        ]
    )
    return stage, shots


async def _keyframe(view: str, out: Path) -> None:
    from hevi.tongjian.scene_render_avatar import _edit_keyframe, _local_kf_prompt

    canon = _VIEWS_DIR / "front.png"  # front 情形当 2D 真照兜底(此处 canon 用 3D front 近似)
    init = None if view == "front" else _VIEWS_DIR / f"{view}.png"
    if out.exists():
        out.unlink()
    await _edit_keyframe(
        image_path=canon,
        instruction="neutral",
        output_path=out,
        fallback_from=canon,
        engine="local",
        local_prompt=_local_kf_prompt(_STYLE, _APPEARANCE, "神情自然", ""),
        ip_adapter_image=canon,
        init_image=init,
        size=(576, 768),
    )


async def main(args: argparse.Namespace) -> None:
    stage, shots = build()
    views = compute_shot_views(shots, SceneStageSet(stages=[stage]))
    print("=" * 72)
    print("SPEC-004 v2 B5:王生 facing_deg=90,三机位 azimuth 0/90/180 → 几何选视图")
    for shot in shots.shots:
        v = views[shot.shot_id]["王生"]
        print(f"  {shot.shot_id}(azimuth {shot.camera_setup_ref}):王生 → 视图 = {v}")
    print("=" * 72)

    missing = [
        f"{v}.png"
        for v in ("front", "left", "right", "back")
        if not (_VIEWS_DIR / f"{v}.png").exists()
    ]
    if missing:
        print(f"⚠ 缺王生视图 {missing}(先跑 TripoSR:见 B4 或 scripts 里 generate_subject3d)")
        return
    if not args.real:
        print("\n(dry-run:只算几何。加 --real 出每机位的关键帧看朝向。)")
        return

    out_dir = Path("output/b5_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    for shot in shots.shots:
        v = views[shot.shot_id]["王生"]
        out = out_dir / f"{shot.shot_id}_{v}.png"
        log.info("[%s] 视图=%s → 出关键帧 %s", shot.shot_id, v, out)
        await _keyframe(v, out)
        print(f"  → {out}")
    print(f"\n产物:{out_dir}/*.png。请肉眼看三帧朝向是否随机位变:")
    print("  az0→left视图 / az90→front / az180→right。若 left/right 帧的朝向和标签反了,")
    print("  说明 _VIEW_BY_DELTA 约定要翻(改 scene_stage.py 那一行)。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SPEC-004 v2 B5 端到端朝向证明")
    p.add_argument("--real", action="store_true", help="本地 sdxl 真出关键帧(免费,需 GPU)")
    asyncio.run(main(p.parse_args()))
