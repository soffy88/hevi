#!/usr/bin/env python3
"""SPEC-001 短剧通道 阶段1 G1 验收:短篇小说 → StoryGraph → SeasonPlan → 3 集真实出片 →
跨集主角身份一致性核验。见 docs/specs/SPEC-001-shortdrama-eval.md、STATUS.md 的 SPEC-001 条目。

流程(全部走现有骨架,不新建管线):
  手稿 → hevi.storygraph.extract(qwen_cloud) → StoryGraph
       → hevi.season_planner.planner.build_season_plan(qwen_cloud) → SeasonPlan(3集)+ 批判门
       → 建主角 Subject(参考图 + CLIP embedding)
       → hevi.season_planner.dispatch.dispatch_season → Series + 3 个 inheriting VideoTask
       → task_service.run_task 逐集真实生成(--real 时)
       → 查 shot_states.consistency_score,按集聚合,判定 G1 verdict

文本 LLM(StoryGraph 抽取 / SeasonPlan 规划,均走 qwen_cloud)成本可忽略不计,不受
--dry-run/--real 开关影响,两种模式下都是真实调用——这两步本身就是要验证的对象。
--dry-run/--real 只切换真花钱的两段:角色参考图(qwen_image)与集生成视频(happyhorse_1_1_maas)。

用法:
  --dry-run(默认)  参考图用占位图(1x1 PNG,零成本);dispatch_season 建好 Series/3 集
                    VideoTask 后即停,不跑 run_task——验证抽取/规划/派发这几段接线是否正确,
                    不花视频生成的钱。
  --real            参考图真实调 qwen_image_generate;3 集都真实调用 run_task 生成
                    (video_provider=happyhorse_1_1_maas)。脚本自带 CostTracker,配合
                    --cost-limit(默认 $20,同 build_scene_zhibo_suodi.py 既定熔断线)在
                    每次真花钱调用前二次拦截,叠加 task_service 自身的单任务/日预算熔断。
  --episodes        目标集数,默认 3(G1 验收门原文要求)。
  --cost-limit      本次运行的美元熔断线,默认 20.0。
  --lean            2026-07-11 补充:实测下 season_planner.episode_brief() 产出的富文本
                    topic(全集事件+对白+情感弧)会让 oskill 的 script_writer 不管
                    target_duration_s 多小都写出~10个镜头/集(2026-07-11 那次真实跑
                    单集就出了10镜+8镜重生成,远超预期成本)——跳过 season_planner/
                    dispatch_season,直接挑 StoryGraph 里两个相隔较远的事件,各自
                    只用一句话摘要当 topic(内容越少,LLM 写的镜头越少),
                    create_series+create_episode 直接建 2 个"小段",验证跨集(段)身份
                    一致性,成本可控。--episodes 在 --lean 下含义变成"取几个小段"。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import statistics
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.season_planner.dispatch import dispatch_season
from hevi.season_planner.planner import build_season_plan
from hevi.series.repository import SeriesRepository
from hevi.series.series_service import SeriesService
from hevi.storygraph.extract import extract_story_graph
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("g1_shortdrama_run")

_MANUSCRIPT_PATH = Path("output/shortdrama_g1/manuscript.txt")
_OUT_DIR = Path("output/shortdrama_g1")
_ART_DIRECTION = "Chinese ink wash painting style, 古风水墨"
_VIDEO_PROVIDER = "happyhorse_1_1_maas_lock"  # 单参考图锁脸窄接口,见 alibaba_maas_service.py
# "short" 档(target_s=5)会让 longvideo_orchestrator.py 的 `_is_short` 为真,主线管线
# 整段跳过 scorecard/consistency_fn 注入(见 longvideo_orchestrator.py:819)——G1 恰恰
# 要看这个分数,不能用 "short"。改用 "1-5min"(非 short,consistency_fn 会挂载)+
# omodul LongVideoConfig 的 `target_duration_s` 显式覆盖(B12,优先于档位默认的180s),
# 把单集实际时长压到目标秒数附近,不吃 1-5min 档位的默认时长。
_DURATION_ARCHETYPE = "1-5min"
_TARGET_DURATION_S = 10.0
# happyhorse_1_1_maas_lock 沿用 happyhorse_1_1_maas 定价($0.14/s,见 pricing_table.py)。
# estimate_cost() 只认 duration_archetype 的档位默认时长(1-5min=180s→$25+),不知道这里的
# target_duration_s 覆盖,会算出远高于实际的估价——本脚本自己的 CostTracker 预检不调用
# estimate_cost(),改用这个按 target_duration_s 算的手工估价,更贴近真实花费。
_PRICE_PER_SECOND_USD = 0.14

# 1x1 透明 PNG,dry-run 占位参考图(零成本)。
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _protagonist(story: Any) -> Any:
    """挑主角:role == 'protagonist' 优先,否则退化取 source_spans 最靠前的角色。"""
    for c in story.characters:
        if c.role == "protagonist":
            return c
    if not story.characters:
        raise SystemExit("StoryGraph 未抽出任何角色,无法建 Subject")
    return min(story.characters, key=lambda c: (c.first_appearance or (10**9, 0))[0])


async def _build_protagonist_subject(
    story: Any,
    *,
    pool: Any,
    dry_run: bool,
    cost_tracker: CostTracker,
    cost_limit: CostLimit,
) -> tuple[str, str]:
    """建主角 Subject,返回 (char_id, subject_id)。"""
    protagonist = _protagonist(story)
    subject_dir = _OUT_DIR / "subjects" / protagonist.char_id
    subject_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = subject_dir / "portrait_v0.png"

    if dry_run:
        portrait_path.write_bytes(_PLACEHOLDER_PNG)
    else:
        from hevi.image.qwen_image_service import qwen_image_generate

        # 视频生成用同一 CostTracker 累计,qwen_image 单价按官方文生图档估 $0.02/张
        # (远低于视频,不单独设估价函数——同 build_scene_zhibo_suodi.py 的做法:小额度
        # 也要过一次累计检查,避免"单笔不超线但叠加超支")。
        await cost_tracker.check_and_reserve(0.02, cost_limit)
        prompt = (
            f"{_ART_DIRECTION}, portrait of {protagonist.name}, "
            f"{protagonist.description or '书生长衫,清秀'}, front facing, neutral expression"
        )
        await qwen_image_generate(prompt=prompt, output_path=portrait_path)

    subject_service = SubjectService(SubjectRepository(pool))
    subject = await subject_service.create_subject(
        kind="character",
        name=protagonist.name,
        reference_images=[str(portrait_path)],
        description=protagonist.description,
    )
    logger.info(
        "主角 Subject 建好: char_id=%s subject_id=%s name=%s",
        protagonist.char_id,
        subject["id"],
        protagonist.name,
    )
    return protagonist.char_id, str(subject["id"])


def _pick_lean_segments(story: Any, protagonist: Any, n: int) -> list[str]:
    """挑 n 个相隔较远、主角在场的事件,各自摘要单独当 topic(不拼接、不走
    episode_brief() 的富文本),把 LLM script_writer 会写的镜头数压到最低。"""
    candidates = [e for e in story.events if protagonist.char_id in e.actors] or story.events
    if not candidates:
        raise SystemExit("StoryGraph 没有可用事件,无法挑小段")
    if len(candidates) <= n:
        picked = candidates
    else:
        idxs = [round(i * (len(candidates) - 1) / (n - 1)) for i in range(n)] if n > 1 else [0]
        picked = [candidates[i] for i in dict.fromkeys(idxs)]  # 去重,保持顺序
    return [f"{protagonist.name}:{e.summary}" for e in picked]


async def _run_lean(
    story: Any,
    *,
    char_id: str,
    subject_id: str,
    n_segments: int,
    pool: Any,
    series_service: SeriesService,
) -> list[dict[str, Any]]:
    """跳过 season_planner/dispatch_season,直接建 Series + n 个极简 topic 的 episode。"""
    protagonist = next(c for c in story.characters if c.char_id == char_id)
    topics = _pick_lean_segments(story, protagonist, n_segments)
    for i, t in enumerate(topics):
        logger.info("小段 %d topic: %s", i, t)

    series = await series_service.create_series(
        name=f"{story.meta.source}(G1 lean)",
        subject_ids=[subject_id],
        spec={
            "video_provider": _VIDEO_PROVIDER,
            "duration_archetype": _DURATION_ARCHETYPE,
            "target_duration_s": _TARGET_DURATION_S,
        },
    )
    episodes = []
    for topic in topics:
        ep = await series_service.create_episode(str(series["id"]), topic=topic)
        episodes.append(ep)
    return episodes


async def _run_episodes_and_score(
    episodes: list[dict[str, Any]],
    *,
    task_service: TaskService,
    dry_run: bool,
    cost_tracker: CostTracker,
    cost_limit: CostLimit,
) -> None:
    if dry_run:
        logger.info("dry-run:跳过真实生成(不调用 run_task),仅确认 %d 个集任务已建好", len(episodes))
        for ep in episodes:
            logger.info(
                "  episode_index=%s task_id=%s status=%s",
                ep["episode_index"],
                ep["id"],
                ep["status"],
            )
        return

    per_episode_scores: dict[int, list[float]] = {}
    for ep in episodes:
        # 见 _PRICE_PER_SECOND_USD 顶部注释:不用 estimate_cost()(它只认档位默认时长,
        # 不知道 target_duration_s 覆盖,会把 1-5min 档算成 ~$25/集)。
        estimate_usd = _PRICE_PER_SECOND_USD * _TARGET_DURATION_S
        await cost_tracker.check_and_reserve(estimate_usd, cost_limit)
        logger.info(
            "运行第 %s 集(task_id=%s),预估 $%.2f,累计 $%.2f/$%.2f ...",
            ep["episode_index"],
            ep["id"],
            estimate_usd,
            cost_tracker.spent_usd,
            cost_limit.max_per_task_usd,
        )
        result = await task_service.run_task(uuid.UUID(str(ep["id"])))
        logger.info("  完成: status=%s", result.get("status"))

        shots = await task_service.repository.get_shots(uuid.UUID(str(ep["id"])))
        # consistency_score(= identity_score)不是 shot_states 的顶层列,落在
        # selection_json JSONB 里(见 task_service.py::_persist_shots)——之前误当顶层
        # 字段查,永远拿不到数据。
        scores = []
        for s in shots:
            sel = s.get("selection_json") or {}
            v = sel.get("consistency_score")
            if v is not None:
                scores.append(float(v))
        per_episode_scores[int(ep["episode_index"])] = scores
        logger.info("  第 %s 集分镜一致性分: %s", ep["episode_index"], scores)

    print("\n=== G1 跨集主角身份一致性核验 ===")
    all_means = []
    for ep_idx in sorted(per_episode_scores):
        scores = per_episode_scores[ep_idx]
        if not scores:
            print(f"第{ep_idx}集: 无 consistency_score 数据(可能未启用 character_reference)")
            continue
        mean_s = statistics.fmean(scores)
        min_s = min(scores)
        all_means.append(mean_s)
        print(f"第{ep_idx}集: 均值={mean_s:.3f} 最小值={min_s:.3f} (n={len(scores)})")

    if all_means:
        overall = statistics.fmean(all_means)
        # 沿用 hevi/verdict/scorecard.py::shot_scorecard 的 identity_floor 默认值(0.2)——
        # 那是"仅拦全废"的极低阈,不新发明一个更严的数字。
        threshold = 0.2
        passed = overall >= threshold
        print(
            f"跨集总体均值: {overall:.3f} (阈值 {threshold}, 沿用 scorecard.py identity_floor) "
            f"→ G1 {'通过 ✅' if passed else '未通过 ❌'}"
        )
    else:
        print("没有可用的 consistency_score 数据,G1 无法判定(检查 character_reference 是否生效)")

    print(f"本次运行累计花费: ${cost_tracker.spent_usd:.2f} / ${cost_limit.max_per_task_usd:.2f}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--real", action="store_true", help="真实调用参考图生成 + 视频生成(真花钱),默认不开"
    )
    parser.add_argument(
        "--episodes", type=int, default=3, help="目标集数,默认 3(--lean 下含义变成小段数)"
    )
    parser.add_argument(
        "--cost-limit", type=float, default=20.0, help="本次运行美元熔断线,默认 20.0"
    )
    parser.add_argument(
        "--lean",
        action="store_true",
        help="跳过 season_planner/dispatch_season,直接建 N 个极简单句 topic 的小段(见顶部说明)",
    )
    args = parser.parse_args()
    dry_run = not args.real

    # qwen_cloud(文本 LLM)两种模式都要注册——StoryGraph/SeasonPlan 这两步本身就是
    # 要验证的对象,不受 --dry-run 影响;--real 才额外解锁图像/视频 provider。
    from hevi.providers.registry import register_all_providers

    register_all_providers()

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_text = _MANUSCRIPT_PATH.read_text(encoding="utf-8")

    cost_limit = CostLimit(max_per_task_usd=args.cost_limit)
    cost_tracker = CostTracker()

    logger.info("B0: StoryGraph 抽取(qwen_cloud)...")
    story = await extract_story_graph(source_name="崂山道士", raw_text=raw_text)
    (_OUT_DIR / "story_graph.json").write_text(story.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "StoryGraph: %d 角色 / %d 事件 / %d 对白 / %d 地点",
        len(story.characters),
        len(story.events),
        len(story.quotes),
        len(story.locations),
    )
    if not story.characters or not story.events:
        raise SystemExit("StoryGraph 抽取结果为空,检查 qwen_cloud 是否可用/手稿是否可读")

    pool = await get_hevi_pg_pool()
    char_id, subject_id = await _build_protagonist_subject(
        story, pool=pool, dry_run=dry_run, cost_tracker=cost_tracker, cost_limit=cost_limit
    )

    task_repo = TaskRepository(pool)
    task_service = TaskService(task_repo)
    series_service = SeriesService(SeriesRepository(pool), task_service=task_service)

    if args.lean:
        logger.info(
            "--lean: 跳过 season_planner/dispatch_season,直接建 %d 个小段...", args.episodes
        )
        episodes = await _run_lean(
            story,
            char_id=char_id,
            subject_id=subject_id,
            n_segments=args.episodes,
            pool=pool,
            series_service=series_service,
        )
        logger.info("已建好 %d 个小段", len(episodes))
    else:
        logger.info("剧集规划器: build_season_plan(target_episodes=%d)...", args.episodes)
        # build_season_plan 内部按 best-of-n 挑一个候选,但 LLM 抽样有方差,被挑中的候选
        # 仍可能撞上 gate_season_plan 的确定性检查——重试几轮而非人工重跑脚本。
        plan = gate = None
        for attempt in range(1, 6):
            plan, gate = await build_season_plan(story, target_episodes=args.episodes)
            logger.info(
                "G_SEASON(第%d次尝试): passed=%s errors=%s warnings=%s",
                attempt,
                gate.passed,
                gate.errors,
                gate.warnings,
            )
            if gate.passed:
                break
        (_OUT_DIR / "season_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        if not gate.passed:
            raise SystemExit(f"G_SEASON 连续 5 次尝试均未通过,不继续往下走: {gate.errors}")

        logger.info("派发: dispatch_season...")
        dispatched = await dispatch_season(
            plan,
            story,
            series_service=series_service,
            task_service=task_service,
            subject_id_map={char_id: subject_id},
            spec={
                "video_provider": _VIDEO_PROVIDER,
                "duration_archetype": _DURATION_ARCHETYPE,
                "target_duration_s": _TARGET_DURATION_S,
            },
        )
        episodes = dispatched["episodes"]
        logger.info("已派发: series_id=%s episodes=%d", dispatched["series_id"], len(episodes))

    await _run_episodes_and_score(
        episodes,
        task_service=task_service,
        dry_run=dry_run,
        cost_tracker=cost_tracker,
        cost_limit=cost_limit,
    )


if __name__ == "__main__":
    asyncio.run(main())
