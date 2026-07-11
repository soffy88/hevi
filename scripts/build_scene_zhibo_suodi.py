#!/usr/bin/env python3
"""HEVI-EXEC-01 M3:单场景「智伯索地」5 镜头闭环 —— C2.5 场景化改编 → C4 分镜 →
C6 视频生成(Vidu)+ CG6 门 + 降级链 + 血缘记录。见 docs/specs/导演台/
HEVI-EXEC-01-CC执行任务书.md §1 M3、HEVI-SPEC-02 §4-5。

ChapterIR/Constitution/Script 是手写的(output/tongjian/zhibo_suodi/*.json,
scripts/../tmp 里的 author_scene_data.py 生成),没有跑真实 L0-L2 LLM 调用——
这个章节的原文智伯和韩康子之间没有任何直接引语,只有段规对韩康子的进言和韩康子
的应答两句真实引语,详见 chapter_ir.json 里的 quotes。

镜头设计(5 镜头,对应 EXEC-01"建立镜头+智伯正打×2+韩康子反打+段规反应"):
智伯的两句索地台词是"表演性台词"(is_performative=True,不是原文引语,因为原文里
智伯本人没有任何直接引语)——CG2.5 门对这类台词走宽松的"是否符合人物设定"检查,
不要求匹配 chapter_ir.quotes。段规反应镜头的台词才是真实引语改写。

用法:
  --dry-run(默认)  video_gen/vlm 全部换成 mock,不碰 Vidu/WaveSpeed/本地 VLM,完全
                    免费——验证 C2.5/C4/C6/CG6/血缘记录/平台绑定这些非生成环节。
  --real            真实调用参考图锁脸生成(真花钱,过 $20 熔断线)+ 本地 VLM。
                    **默认不开**,这是故意的:C6 从第一步就是付费 API,不应该因为
                    忘记传 flag 就意外真花钱——真跑前必须显式传这个 flag。
  --platform        vidu(默认,HEVI-EXEC-01 M3 验收用的既定通道)/ happyhorse_1_1
                    (WaveSpeed 转售,需要真实 WAVESPEED_API_KEY)/ happyhorse_1_1_maas
                    (阿里云百炼官方直连,happyhorse-1.1-r2v,需要 ALIBABA_MAAS_API_KEY
                    + ALIBABA_MAAS_HOST——见 alibaba_maas_service.py)。三个都是刚接入
                    (2026-07),没有在这类国风水墨历史题材上跑过,质量未知——第一次用
                    建议先小范围验证,不要直接当正式验收通道。只有 --real 时这个选项
                    才有意义。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from hevi.cinematic.schemas import Beat, BeatDialogue
from hevi.cinematic.scene_adapt import adapt_scene, gate_scene_adapt
from hevi.cinematic.shot_planning import gate_shotlist, plan_shots
from hevi.cinematic.video_gen import generate_shot
from hevi.core.config import settings
from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.tongjian.schemas import ChapterIR, Constitution, Script
from hevi.vault import asset_resolve, get_minio_client, get_vault_pg_pool, init_vault_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_scene_zhibo_suodi")

_DATA_DIR = Path("hevi/cinematic/data/zhibo_suodi")
_ART_DIRECTION = "Chinese ink wash painting style"

# 智伯在原文里没有任何直接引语(唯一两句真实引语是段规进言 + 韩康子应答),这两句
# 索地台词是电影化演绎补充,显式标记 is_performative=True——不能跟真实引语混着来,
# 见 hevi.cinematic.scene_adapt 模块 docstring。
_EXTRA_BEATS: dict[str, list[Beat]] = {
    "LN001": [
        Beat(
            beat_id="B_zhibo1",
            action="智伯昂首而立,傲然睥睨",
            dialogue=BeatDialogue(
                speaker="zhibo", text="韩康子,速割地予我。", is_performative=True, emotion="倨傲"
            ),
        ),
    ],
    "LN002": [
        Beat(
            beat_id="B_zhibo2",
            action="智伯逼近一步,语气转厉",
            dialogue=BeatDialogue(
                speaker="zhibo", text="莫非你要抗我军令?", is_performative=True, emotion="威胁"
            ),
        ),
    ],
}

# 这次 P0 只出 5 个镜头:建立 + 智伯正打×2 + 韩康子反打 + 段规反应。B002(叙事桥接
# "韩康子踌躇难决,唤来家臣段规商议")复用做韩康子反打的反应镜头(hint 覆盖默认的
# "无台词 beat = 全场入镜的建立镜头"推断)。B004("好。")/B005(致邑,智伯悦)是这段
# 故事的后续决定/收尾,不在这 5 镜头 P0 范围内。
_SHOT_BEAT_IDS = ["B001", "B_zhibo1", "B_zhibo2", "B002", "B003"]


async def _mock_video_gen(*, prompt, reference_images, output_path, duration, seed=None):
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x240:d={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


async def _mock_vlm(*, messages, image_paths, max_tokens=300):
    return {"content": '{"passes": true, "violations": []}'}


async def _mock_llm(*, messages, max_tokens=1024):
    """gate_scene_adapt 用的是纯文本 LLM(判断台词语义一致性/表演性台词合理性),
    不是 VLM——没有 image_paths 参数,跟 _mock_vlm 签名不同,不能混用。"""
    return {"content": '{"violations": []}'}


_PLATFORM_VIDEO_GEN: dict[str, tuple[Any, float]] = {}  # 延迟填充,见 main() 里的说明


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", help="真实调用生成 API(真花钱),默认不开")
    parser.add_argument(
        "--platform",
        choices=["vidu", "happyhorse_1_1", "happyhorse_1_1_maas"],
        default="vidu",
        help="真实生成走哪个参考图锁脸通道,默认 vidu(见模块 docstring)",
    )
    args = parser.parse_args()
    dry_run = not args.real

    if not dry_run:
        from hevi.providers.registry import register_all_providers

        register_all_providers()

        # 三个 provider 的调用约定相同(prompt/reference_images/output_path/duration/
        # seed),但计价差很多——cost_estimate_usd 用各自真实单价按 5s 估,不能沿用
        # video_gen.py 默认的 Vidu 那档,否则后两个熔断线形同虚设。
        from hevi.video.alibaba_maas_service import happyhorse_1_1_maas_reference_to_video
        from hevi.video.vidu_service import vidu_reference_to_video
        from hevi.video.wavespeed_service import happyhorse_1_1_reference_to_video

        _PLATFORM_VIDEO_GEN.update(
            {
                "vidu": (vidu_reference_to_video, 0.5),
                "happyhorse_1_1": (
                    happyhorse_1_1_reference_to_video,
                    0.75,
                ),  # WaveSpeed $0.14/s × 5s
                "happyhorse_1_1_maas": (
                    happyhorse_1_1_maas_reference_to_video,
                    0.7,
                ),  # 阿里官方 $0.14/s @720P × 5s
            }
        )

    await init_vault_schema(settings.vault_database_url)
    pool = await get_vault_pg_pool()
    minio_client = get_minio_client()
    cost_limit = CostLimit(max_per_task_usd=20.0)  # EXEC-01 §0 项2
    cost_tracker = CostTracker()

    chapter_ir = ChapterIR.model_validate_json((_DATA_DIR / "chapter_ir.json").read_text())
    constitution = Constitution.model_validate_json((_DATA_DIR / "constitution.json").read_text())
    script = Script.model_validate_json((_DATA_DIR / "script.json").read_text())

    logger.info("C2.5 场景化改编...")
    scene = await adapt_scene(
        script,
        chapter_ir,
        scene_id="SC01",
        slug="韩府·索地",
        space_anchor="S001",
        extra_beats=_EXTRA_BEATS,
    )
    llm = _mock_llm if dry_run else None
    gate_cg25 = await gate_scene_adapt(scene, chapter_ir, llm=llm)
    logger.info("CG2.5: passed=%s errors=%s", gate_cg25.passed, gate_cg25.errors)
    if not gate_cg25.passed:
        raise SystemExit("CG2.5 未通过,不继续往下走")

    logger.info("C4 分镜规划...")
    immutable_traits_by_character: dict[str, str] = {}
    for character_id in scene.characters:
        resolved = await asset_resolve(pool, pack_id=f"identity/{character_id}")
        immutable_traits_by_character[character_id] = resolved["manifest"].immutable_traits

    shotlist = await plan_shots(
        scene,
        art_direction=_ART_DIRECTION,
        immutable_traits_by_character=immutable_traits_by_character,
        beat_ids=_SHOT_BEAT_IDS,
    )
    gate_c4 = gate_shotlist(shotlist, scene)
    logger.info(
        "G4: passed=%s errors=%s, 共 %d 个镜头", gate_c4.passed, gate_c4.errors, len(shotlist.shots)
    )
    if not gate_c4.passed:
        raise SystemExit("G4 未通过,不继续往下走")

    total_duration = sum(s.est_duration_s for s in shotlist.shots)
    if (
        abs(total_duration - constitution.target_duration_sec)
        > constitution.target_duration_sec * 0.5
    ):
        logger.warning(
            "镜头总时长 %.0fs 与宪法目标时长 %ds 偏差较大,仅供参考(单场景 P0 不做硬性配平)",
            total_duration,
            constitution.target_duration_sec,
        )

    logger.info("C6 视频生成 + CG6 门(dry_run=%s, platform=%s)...", dry_run, args.platform)
    run_id = str(uuid.uuid4())
    video_gen = _mock_video_gen if dry_run else _PLATFORM_VIDEO_GEN[args.platform][0]
    cost_estimate_usd = 0.5 if dry_run else _PLATFORM_VIDEO_GEN[args.platform][1]
    vlm = _mock_vlm if dry_run else None

    results = []
    for shot in shotlist.shots:
        result = await generate_shot(
            shot,
            pool,
            minio_client,
            run_id=run_id,
            video_gen=video_gen,
            vlm=vlm,
            platform=args.platform,
            cost_estimate_usd=cost_estimate_usd,
            cost_limit=cost_limit,
            cost_tracker=cost_tracker,
        )
        results.append(result)
        logger.info(
            "[%s] passed=%s degraded=%s attempts=%d",
            shot.shot_id,
            result.cg6.passed,
            result.degraded,
            result.attempts,
        )

    print("\n=== 汇总(run_id=%s) ===" % run_id)
    for r in results:
        mark = "✓" if r.cg6.passed and not r.degraded else ("△" if r.output_path else "✗")
        print(
            f"{mark} {r.shot_id}: cg6_passed={r.cg6.passed} degraded={r.degraded} ({r.degrade_reason})"
        )
    print(f"累计预估花费: ${cost_tracker.spent_usd:.2f} / ${cost_limit.max_per_task_usd:.2f}")

    if not all(r.output_path for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
