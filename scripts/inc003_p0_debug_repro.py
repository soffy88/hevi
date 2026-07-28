"""INC-003 P0 排查(2026-07-18):真实链路里双人镜头为什么退化成单人。

不花钱:happyhorse_animate / i2v_animate 打桩(直接不调用),qwen_image_edit 打桩成立即失败
(逼近本地 sdxl 免费路,不触云端付费 edit)。走的是 2026-07-18 那次真实产集(work_id=
21a72719-fba3-462d-ae11-76c3dde1444e)已经锁定的**真实**concept/screenplay/design_list/
scene_stage/shot_list(从当时抓的 JSON 快照重建,不是手造数据)+ 真实 SubjectService(读
同一个 dev postgres,Subject3D 视图/参考图路径都是那次产集真实建好的)。

跑完看 DEBUG-CHAIN A-E 这几行 warning log,定位 present 从 2 掉到 1 的具体环节。

用法:python scripts/inc003_p0_debug_repro.py
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inc003_p0_repro")

_SNAPSHOT = Path(
    "/tmp/claude-1000/-data-soffy-projects-hevi/4a0f0fb0-ad19-46e1-9134-c4798f665874/scratchpad/after_shot_list_lock.json"
)
_OUT = Path("output/inc003_p0_debug_repro")
_OUT.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    from hevi.providers.registry import register_all_providers

    register_all_providers()

    from hevi.api.routers.director_pipeline import (
        _has_multichar_shots,
        _resolve_scene_ref_paths,
        _resolve_subject3d_views,
        _resolve_subject_ref_paths,
    )
    from hevi.db.pg_pool import get_hevi_pg_pool
    from hevi.director.pipeline_schemas import Concept, DesignList, SceneStageSet, ShotList
    from hevi.director.tongjian_render import render_director_episode
    from hevi.subjects.repository import SubjectRepository
    from hevi.subjects.subject_service import SubjectService

    snap = json.loads(_SNAPSHOT.read_text())
    concept = Concept.model_validate(snap["concept"])
    design_list = DesignList.model_validate(snap["design_list"])
    scene_stage = SceneStageSet.model_validate(snap["scene_stage"])
    shot_list = ShotList.model_validate(snap["shot_list"])

    log.info(
        "重建真实锁定数据:characters=%s scenes=%s shots=%d",
        [c.name for c in design_list.characters],
        [s.name for s in design_list.scenes],
        len(shot_list.shots),
    )

    pool = await get_hevi_pg_pool()
    subject_svc = SubjectService(SubjectRepository(pool))

    has_multichar = _has_multichar_shots(shot_list)
    log.info("_has_multichar_shots = %s", has_multichar)

    subject_ref_paths = await _resolve_subject_ref_paths(design_list, subject_svc=subject_svc)
    log.info("subject_ref_paths (真实 canon 参考图) = %s", subject_ref_paths)

    subject3d_views = await _resolve_subject3d_views(design_list, subject_svc=subject_svc)
    log.info(
        "subject3d_views (真实) keys=%s per-char view keys=%s",
        list(subject3d_views.keys()),
        {k: list(v.keys()) for k, v in subject3d_views.items()},
    )

    scene_bg_paths = await _resolve_scene_ref_paths(design_list, subject_svc=subject_svc)
    log.info("scene_bg_paths (真实) = %s", scene_bg_paths)

    voice_by_speaker = {c.name: (c.voice_id or "zh_male_deep") for c in design_list.characters}

    # 六个外部付费调用全部打桩(清单见脚本头注释),不留一个漏网——上次漏了
    # alibaba_maas_keyframe_generate 才真花了钱。全部瞬时返回,不碰网络。
    async def _no_video(*, image_path=None, prompt=None, output_path, **kw):
        Path(output_path).write_bytes(b"stub" * 300)  # >1024B,过 _edit_keyframe 有效性门槛
        return output_path

    async def _no_sdxl(*, prompt, output_path, width, height, extra=None, negative_prompt="", **kw):
        # 假设检验:img2img(compose,extra 里有 init_image)瞬时崩溃一次,
        # IP-Adapter(单人锁脸,extra 里有 ip_adapter_image)照常成功——
        # 复现"两条腿都在,但 compose 那条随机抽风一次,悄悄退到单人锁脸,
        # 还判定为成功"这个假设。
        if extra and "init_image" in extra:
            raise RuntimeError("DEBUG-REPRO: 模拟 img2img(compose)瞬时崩溃,验证退化假设")
        Path(output_path).write_bytes(b"stub" * 300)
        return {"output_path": str(output_path), "seed": 0}

    async def _fail_qwen_edit(*, image_path, instruction, output_path):
        from hevi.image.qwen_image_service import QwenImageError

        raise QwenImageError("DEBUG-REPRO: qwen_image_edit 打桩拒绝,逼近本地免费路")

    async def _no_qwen_generate(*, prompt, output_path, size, seed=None):
        Path(output_path).write_bytes(b"stub" * 300)
        return output_path

    with (
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate", AsyncMock(side_effect=_no_video)
        ),
        patch("hevi.tongjian.scene_render_avatar.i2v_animate", AsyncMock(side_effect=_no_video)),
        patch(
            "hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate",
            AsyncMock(side_effect=_no_video),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_edit",
            AsyncMock(side_effect=_fail_qwen_edit),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.qwen_image_generate",
            AsyncMock(side_effect=_no_qwen_generate),
        ),
        patch(
            "hevi.tongjian.scene_render_avatar.sdxl_local_generate",
            AsyncMock(side_effect=_no_sdxl),
        ),
    ):
        try:
            result = await render_director_episode(
                shot_list=shot_list,
                design_list=design_list,
                concept=concept,
                run_dir=_OUT,
                subject_ref_paths=subject_ref_paths,
                voice_by_speaker=voice_by_speaker,
                aspect_ratio="9:16",
                target_duration_sec=180,
                scene_stage=scene_stage,
                subject3d_views=subject3d_views,
                scene_bg_paths=scene_bg_paths,
            )
            log.info("跑完,shots=%d", len(result.get("shots", [])))
        except Exception as e:  # 排查脚本:失败也没关系,DEBUG-CHAIN log 已经打过了
            log.warning("render_director_episode 抛出(排查用不影响,log 已足够): %r", e)


if __name__ == "__main__":
    asyncio.run(main())
