#!/usr/bin/env python3
"""HEVI-EXEC-01 M2 里程碑第3项:为智伯、韩康子、段规构建 animated@guofeng-ink 身份包
并 promote 至 validated。见 docs/specs/导演台/HEVI-EXEC-01-CC执行任务书.md §1 M2。

三个角色没有跑过 L0-L2 + L5 character_bible(那需要能用的 LLM,本机 DashScope 账户
欠费停用、本地 ollama 对这种结构化输出不可靠——见 memory: E2E local-LLM JSON
blocker)。appearance/era_lock/character_id 不是这次编的:延续 2026-07-08 08:17 那次
被 GPU Xid 79 打断的真实构建留在 vault identity/zhibo|hankangzi|duangui@0.1.0 里的
draft manifest(智伯做完权威像+九宫格、韩康子/段规只做完声音就断了)。

用法:
  --dry-run   image_gen 换成本地 PIL 占位图(不碰 GPU/云端),vlm 换成恒 pass 的
              mock,tts_fn 走真实 edge_tts(云端、免本地 GPU)。用来在本地 GPU 挂掉
              时仍能验证 vault 落库/lint/promote/cost breaker 这些非 GPU 环节。
  (默认)      image_gen 留空(None),走 build_identity_pack 的默认路径:批量本地
              SDXL(模型只加载一次)+ GPU 探活,批内单张失败或 GPU 直接不健康时逐张
              自动降级到 fal.ai Flux 云端(见
              hevi.image.resilient_image_gen.resilient_image_gen_batch;json2video
              2026-07-08 实测过不能用在人物肖像上,生成内容系统性文不对题,已从这条
              兜底链里剔除,详见该模块 docstring)。vlm 走 ProviderRegistry 默认
              (本地 qwen2.5vl,同样需要本地 GPU,目前没有云端兜底)。
  --turnaround-video  额外生成 5s Vidu 转身视频(真花钱,过 $20 熔断线)。默认不开,
              先跑一遍确认图像/声音/embedding 都对(同 identity_pack.py 模块docstring
              的建议),再决定要不要花这笔钱。

单个角色构建失败不应该拖累其余角色——每个角色独立 try/except,最后汇总打印
成功/失败清单。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from hevi.core.config import settings
from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.vault import build_identity_pack, get_minio_client, get_vault_pg_pool, init_vault_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_identity_packs_exec01")

# 喂给 SDXL 的 art_direction(art_direction 只是生成时的 prompt 素材,不落 manifest,
# 所以直接用英文,不需要像 appearance/era_lock 那样分中英两份)——原本是"国风水墨插画",
# 2026-07-09 CPU 回退验证实测过,SDXL Base 1.0 对"进贤冠""深衣"这类中文专有名词理解
# 很弱,纯中文 prompt 经常直接跑偏成风景/拼贴图案甚至国旗大杂烩,完全不是历史人物
# 肖像——换成英文视觉关键词 + 加固过的 _DEFAULT_NEGATIVE(sdxl_local_service.py)之后,
# 连续多轮实测才稳定出可用人物内容,appearance/era_lock 也改成英文版(见下面
# image_appearance/image_era_lock,同 identity_pack.py 的同名参数)。
# 2026-07-10:接入 Muapi/sdxl-chinese-ink-painting LoRA(触发词 QIEMANCN)。SDXL Base
# 1.0 纯 prompt 出不了真水墨(实测只出扁平数字插画/漫画风,违反 constitution 的
# negative_style"夸张漫画风",身份包 0.1.2 那批卡通像就是这么来的)。触发词放最前——
# 肖像/表情/角度 prompt 都把 art_direction 前置,CLIP 77-token 截断先保住风格词。跑这个
# 脚本时必须带 SDXL_LORA_PATH 环境变量,worker 才会 fuse 这条 LoRA(见 _sdxl_worker.py)。
# art_direction 会被前置到所有图(肖像/表情/多视角/动作)的 prompt 最前段——所以只放
# "画风 + 素净背景",不放"特写/正脸"这类取景词(会和 action_pose 的动态姿势、back view
# 背视图冲突;各图的取景由各自模板负责)。"plain pale empty background" 是抗山水的关键:
# 这条 LoRA 是山水训练的,不压背景会把人物塞进整片山水里(实测 0.1.3 首轮就这样),而
# IP-Adapter 锁脸参考需要干净主体。这几个词也要靠前,CLIP 77-token 截断先保住它们。
_IMAGE_ART_DIRECTION = (
    "QIEMANCN, Chinese ink wash portrait, traditional guohua, plain pale empty background"
)

# character_id/appearance/era_lock(中文)不是这次手写的:2026-07-08 08:17 已有一次
# 真实构建跑到一半被 GPU Xid 79 掉总线打断(vault_versions 里
# identity/zhibo|hankangzi|duangui@0.1.0 还留着那次的 draft manifest,智伯做完权威像
# +九宫格、韩康子/段规只做完声音就断了)。这里延续同一份 character_id 和外形/年代
# 文案,而不是另起一套新 ID——否则同一个角色会在 vault 里分裂成两个不相干的 pack_id。
#
# image_appearance/image_era_lock(英文)是这次新加的,2026-07-09 CPU 回退逐个实测过
# 才定下来的版本(见会话记录/memory:每个角色都试了不止一版,确认能稳定生成单人历史
# 人物肖像、没有多人重影/国旗拼贴/戏曲脸谱这些跑偏内容才收进来)。
_CHARACTERS = [
    {
        "character_id": "zhibo",
        "name": "智伯",
        "appearance": (
            "晋国正卿,四十余岁,身材高大魁伟,美须髯,浓眉深目,神态倨傲自负,"
            "头戴玄色进贤冠,身着黑地云纹深衣,腰佩长剑"
        ),
        "era_lock": "东周·周贞定王年间,三家分晋前夕,晋国朝堂",
        # black hair / short black beard / vigorous, not elderly 前置——没有 LoRA 时 SDXL
        # 对"古代中国大臣"的先验强行把智伯拉成白须老者(0.1.2 那版就是),这些判别词必须
        # 挤进 CLIP 77-token 窗口前段才压得住;年代/服制细节在后段被截断不影响主体正确。
        "image_appearance": (
            "a powerful ancient Chinese minister and warlord, single person, vigorous "
            "middle-aged man in his 40s, jet black hair, short black beard, not elderly, "
            "tall imposing muscular build, arrogant proud domineering expression, thick "
            "eyebrows, deep-set eyes, black ancient Chinese robe with dark cloud pattern, "
            "tall black lacquered scholar-official's cap"
        ),
        "image_era_lock": "Spring and Autumn period, Jin state, Eastern Zhou dynasty, 5th century BC.",
        "voice": "zh_male_standard",
    },
    {
        "character_id": "hankangzi",
        "name": "韩康子",
        "appearance": (
            "韩氏宗主,三十余岁,面容清癯,神情隐忍谨慎,头戴玄色进贤冠,"
            "身着深青色深衣,腰束革带,不佩兵器"
        ),
        "era_lock": "东周·周贞定王年间,三家分晋前夕,晋国朝堂",
        "image_appearance": (
            "one ancient Chinese nobleman, single person, man in his 30s, thin gaunt face, "
            "cautious reserved worried expression, thin build, wearing a tall black "
            "lacquered scholar-official's cap on head, dark blue-green ancient Chinese "
            "robe, leather belt, no weapon"
        ),
        "image_era_lock": "Spring and Autumn period, Jin state, Eastern Zhou dynasty, 5th century BC.",
        "voice": "zh_male_standard",
    },
    {
        "character_id": "duangui",
        "name": "段规",
        "appearance": (
            "韩康子家臣谋士,三十岁上下,身形清瘦,眼神机警沉稳,头戴幅巾,身着素色深衣,持简牍侍立"
        ),
        "era_lock": "东周·周贞定王年间,三家分晋前夕,晋国朝堂",
        "image_appearance": (
            "one ancient Chinese strategist advisor, single person, man around 30 years "
            "old, thin slender build, alert calm shrewd eyes, simple cloth headscarf, "
            "plain unadorned ancient Chinese robe, lower rank retainer clothing, holding "
            "a bamboo slip scroll in hands"
        ),
        "image_era_lock": "Spring and Autumn period, Jin state, Eastern Zhou dynasty, 5th century BC.",
        "voice": "zh_male_standard",
    },
    # 2026-07-10 追加:完整「智伯索地」魏/任章版所需(智伯索地于魏宣子→任章进言→予邑)。
    {
        "character_id": "weihuanzi",
        "name": "魏宣子",
        "appearance": (
            "魏氏宗主,四十许,面容方正沉稳,神情持重多虑,美须,头戴玄色进贤冠,"
            "身着深褐色深衣,腰佩玉,气度端凝"
        ),
        "era_lock": "东周·周贞定王年间,三家分晋前夕,晋国朝堂",
        "image_appearance": (
            "one ancient Chinese feudal lord, single person, dignified middle-aged man in "
            "his 40s, black hair, well-groomed short black beard, square composed face, "
            "thoughtful prudent cautious expression, wearing dark brown ancient Chinese "
            "robe with a jade pendant, tall black lacquered scholar-official's cap"
        ),
        "image_era_lock": "Spring and Autumn period, Jin state, Eastern Zhou dynasty, 5th century BC.",
        "voice": "zh_male_standard",
    },
    {
        "character_id": "renzhang",
        "name": "任章",
        "appearance": (
            "魏氏谋臣,四十上下,身形清健,目光睿智从容,颔下短须,头戴幅巾,"
            "身着素色深衣,拱手侍立,智谋深沉"
        ),
        "era_lock": "东周·周贞定王年间,三家分晋前夕,晋国朝堂",
        "image_appearance": (
            "one ancient Chinese wise strategist advisor, single person, middle-aged man in "
            "his 40s, black hair, short black beard, calm confident shrewd intelligent "
            "expression, wearing a plain cloth scholar's headscarf, plain grey ancient "
            "Chinese robe, hands clasped in front, sagacious"
        ),
        "image_era_lock": "Spring and Autumn period, Jin state, Eastern Zhou dynasty, 5th century BC.",
        "voice": "zh_male_standard",
    },
]

_OUTPUT_ROOT = Path("output/vault/identity")


def _placeholder_image_gen():
    """--dry-run 用:本地 PIL 生成纯色占位图,不碰 GPU/云端,只为验证 vault 落库链路。"""
    from PIL import Image

    async def _gen(*, prompt, output_path, extra=None, seed=None, **_):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        color = (60 + (seed or 0) % 180, 80, 120)
        Image.new("RGB", (64, 64), color).save(output_path)
        return {"output_path": str(output_path), "seed": seed}

    return _gen


def _mock_vlm_always_pass():
    async def _vlm(*, messages, image_paths, max_tokens=300):
        return {"content": '{"passes": true, "violations": []}'}

    return _vlm


async def _build_one(
    *,
    pool,
    minio_client,
    char: dict,
    dry_run: bool,
    build_turnaround_video: bool,
    cost_limit: CostLimit,
    cost_tracker: CostTracker,
) -> tuple[str, bool, str]:
    # vault 版本是一次写入不可变的(asset_promote 从 DB 读回 manifest,同 pack_id+version
    # 二次 asset_create 会因 ON CONFLICT DO NOTHING 静默不生效)。0.1.0 已经是 08:17 那次
    # 被打断的 draft(见上面 _CHARACTERS 的注释),复用它只会把新结果悄悄丢掉——正式跑
    # 用 0.1.1 起一个干净版本;dry-run 再单独隔开,不跟正式版本混。
    # output_dir 同理隔开:_add_file 只看"这个路径下有没有文件",不区分是这次真生成的
    # 还是上次(dry-run 占位图/失败重试)遗留的——两次跑共用目录会把旧文件误当成这次
    # 生成成功(实测踩过:dry-run 的 64x64 占位图被正式跑当作 refs/front.png 落库)。
    # 0.1.3:水墨 LoRA 重建。vault 版本不可变(同版本二次 asset_create 走 ON CONFLICT DO
    # NOTHING 静默丢弃),0.1.0/0.1.1/0.1.2 都已存在、canonical 停在 0.1.2 的卡通像上——
    # 必须起新版本号,写入时 asset_promote 会把 canonical_version 更新到 0.1.3。output_dir
    # 也带上版本后缀:_add_file 只看路径下有没有文件、不辨新旧,跟旧版 pngs 共目录会把
    # 上一批卡通像误当成这次生成的收进 manifest(见类内注释踩过的坑)。
    version = "0.1.3-dryrun" if dry_run else "0.1.3"
    output_dir = _OUTPUT_ROOT / f"{char['character_id'].lower()}{'-dryrun' if dry_run else '-v013'}"
    kwargs: dict = dict(
        pool=pool,
        minio_client=minio_client,
        character_id=char["character_id"],
        name=char["name"],
        appearance=char["appearance"],
        era_lock=char["era_lock"],
        art_direction=_IMAGE_ART_DIRECTION,
        output_dir=output_dir,
        version=version,
        voice=char["voice"],
        cost_limit=cost_limit,
        cost_tracker=cost_tracker,
        build_turnaround_video=build_turnaround_video,
        image_appearance=char["image_appearance"],
        image_era_lock=char["image_era_lock"],
    )
    if dry_run:
        kwargs["image_gen"] = _placeholder_image_gen()
        kwargs["vlm"] = _mock_vlm_always_pass()
    # 正式跑不传 image_gen:build_identity_pack 默认路径本身就是"批量本地 SDXL(模型只
    # 加载一次)+ GPU 探活 + 批内单张失败/GPU 不健康时逐张云端兜底"(见
    # hevi.image.resilient_image_gen.resilient_image_gen_batch),cost_limit/cost_tracker
    # 已经在上面 kwargs 里带上了,会被 build_identity_pack 自动传给这条内部路径。

    try:
        manifest = await build_identity_pack(**kwargs)
    except Exception as e:
        logger.exception("角色 %s 构建失败", char["name"])
        return char["name"], False, f"{type(e).__name__}: {e}"

    ok = manifest.lifecycle == "validated"
    detail = (
        f"lifecycle={manifest.lifecycle} "
        f"stability={manifest.stability_check.passed if manifest.stability_check else None} "
        f"files={sorted(manifest.files.keys())}"
    )
    return char["name"], ok, detail


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--turnaround-video", action="store_true")
    parser.add_argument(
        "--only", nargs="*", default=None, help="character_id 子集,如 ZHIBO HANKANGZI"
    )
    args = parser.parse_args()

    if not args.dry_run:
        # 非 dry-run 才需要:sdxl_local/vlm 默认 provider 平时由 app 启动时
        # (hevi.api.main)注册,这个脚本是独立入口,不走那条启动路径,不显式调用
        # 就会在 build_identity_pack 里解析 image_gen=None 时炸 ProviderNotFoundError。
        from hevi.providers.registry import register_all_providers

        register_all_providers()

    await init_vault_schema(settings.vault_database_url)
    pool = await get_vault_pg_pool()
    minio_client = get_minio_client()
    cost_limit = CostLimit(max_per_task_usd=20.0)  # EXEC-01 §0 项2:单 run 预算熔断线
    # 三个角色共用同一个 tracker——单张云端兜底图 ~$0.01-0.05 远低于 $20,但不共享
    # 累计的话,拦不住"三个角色 x 十几张图 + 转身视频"叠加超支(见 CostTracker docstring)。
    cost_tracker = CostTracker()

    characters = _CHARACTERS
    if args.only:
        characters = [c for c in _CHARACTERS if c["character_id"] in args.only]

    logger.info(
        "开始构建 %d 个角色身份包(dry_run=%s, turnaround_video=%s)",
        len(characters),
        args.dry_run,
        args.turnaround_video,
    )

    results = []
    for char in characters:
        name, ok, detail = await _build_one(
            pool=pool,
            minio_client=minio_client,
            char=char,
            dry_run=args.dry_run,
            build_turnaround_video=args.turnaround_video,
            cost_limit=cost_limit,
            cost_tracker=cost_tracker,
        )
        results.append((name, ok, detail))
        logger.info("[%s] %s — %s", name, "OK" if ok else "FAILED", detail)

    print("\n=== 汇总 ===")
    for name, ok, detail in results:
        print(f"{'✓' if ok else '✗'} {name}: {detail}")
    print(f"累计预估花费: ${cost_tracker.spent_usd:.2f} / ${cost_limit.max_per_task_usd:.2f}")

    if not all(ok for _, ok, _ in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
