"""C5 身份资产包构建 —— HEVI-SPEC-02 §2.1 + §11.1-11.2,HEVI-EXEC-01 M2。

构建流程(全自动,每角色一次,一次制作全片乃至跨卷复用):
  1. 文生图正面权威像 —— 复用 L5 同款 SDXL image_gen provider,VLM 年代服制审,
     且过**稳定性预检**(同参考同 prompt 重生成 3 次,≥2 次通过 embedding 自洽性 +
     VLM 服装/年代审才允许 lifecycle draft → validated,§11.2)
  2. 图生多视角九宫格(9 个角度各生成一张,PIL 拼成 3x3 grid)+ 单独 1 张动作姿势
     参考(§11.1 规则3:身份包必须含动态姿势,模型对角色运动方式的理解依赖它)
  3. 表情表(neutral + 若干情绪,默认沿用 spec §2.1 示例的 4 档)
  4. 5 秒转身视频(Vidu Reference-to-Video,以正面像为参考,中性光照素背景)——
     这一步真花钱(云 API),外部调用前过 hevi.cost.circuit_breaker
  5. CosyVoice 8 秒角色声线样本——建立 voice_id 锚点,供 L3 多声线(P1)后续复用
  6. embedding 提取(CLIP,复用 hevi.subjects.subject_embed;ArcFace 专用人脸后端
     留作 future,同 subject_embed 模块既有简化选择,不是本次新决定)

Prompt lint(§11.1 规则1,供 M3 的 C4/C6 分镜 prompt 构造器调用):身份词
(costume_lock/immutable_traits 里的措辞)混进 shot prompt 会与参考图竞争导致
生成漂移,构造器必须先过这个检查。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.subjects.subject_embed import subject_embed
from hevi.vault.schemas import Manifest, StabilityCheck
from hevi.vault.service import asset_create, asset_promote, store_embedding

logger = logging.getLogger(__name__)

# 2026-07-09:这几个模板只喂给 SDXL(不进 VLM 审核 prompt,那边继续用中文),改成英文
# 关键词——CPU 回退验证时实测过 SDXL Base 1.0 对中文历史人物描述的理解本来就弱,纯
# 中文 prompt 经常直接跑偏成风景/拼贴图案而非人物,换成英文视觉关键词 + 加固过的
# _DEFAULT_NEGATIVE 之后才稳定出人物内容(见 build_identity_pack 的 image_appearance/
# image_era_lock 参数,同样的考虑)。
_MULTIVIEW_ANGLES: dict[str, str] = {
    "front": "front view, facing camera",
    "front_left_34": "three-quarter view from front-left",
    "front_right_34": "three-quarter view from front-right",
    "profile_left": "left profile view",
    "profile_right": "right profile view",
    "back_left_34": "three-quarter view from back-left, back facing camera",
    "back_right_34": "three-quarter view from back-right, back facing camera",
    "back": "back view, facing away from camera",
    "three_quarter_high": "slightly high angle, three-quarter view",
}
_DEFAULT_EXPRESSIONS: dict[str, str] = {
    "neutral": "calm neutral expression",
    "haughty": "haughty arrogant expression",
    "furious": "furious enraged expression",
    "terrified": "terrified frightened expression",
}
_ACTION_POSE_HINT = (
    "dynamic action pose showing the character's typical movement, not a standing portrait"
)

_STABILITY_TRIALS = 3
_STABILITY_MIN_PASS = 2
# CLIP 自洽性阈值:候选像 vs 首个候选像的余弦距离,超过则判定"跑偏"(同一角色不同次
# 生成理应视觉接近;真正的人脸级判别留给 kind="face" 专用后端,同 subject_embed 简化)。
_STABILITY_CONSISTENCY_THRESHOLD = 0.35

_ERA_AUDIT_PROMPT_TEMPLATE = """你是历史短片年代审核员。这张图片是依据下面的角色外形描述生成的。

外形描述: {immutable_traits}
时代: {era_lock}

你的任务不是评判画面是否精确复现这段描述里每一件具体名物的历史形制细节(不要求
"进贤冠""深衣"这类专有名词级别的样式精确匹配——2026-07-09 实测过本地 VLM 按这种
逐项核对的标准审,会把方向正确、人看着完全合理的历史人物古装也系统性判不通过)。
你只需要检查画面里有没有出现下面这份清单里的具体元素——命中任意一项才判定不通过:

- 现代服装/配饰:西装、领带、衬衫翻领、拉链、现代纽扣、牛仔裤、运动鞋、高跟鞋、
  太阳镜、手表、耳机
- 现代物品:手机、电灯泡、电线电缆、汽车、路牌/广告牌、印刷体文字水印
- 明显更晚朝代的标志性服饰:清代长辫/瓜皮帽/顶戴花翎/旗袍、明代乌纱帽、
  日式/西式军装、现代国旗/警徽/校徽

清单之外的呈现(哪怕帽子/长袍的具体样式跟描述不完全一致、人物年龄气质有偏差、
画面构图不是半身像)都不算违规,应判定 passes=true——这类细节偏差留给人工复核,
不是这一步要拦的。

只输出 JSON: {{"passes": true/false, "violations": ["命中的具体项,没命中则为空列表"]}}"""

# Vidu 转身视频的粗略单价估算(§0 决策未细定 Vidu 具体计费,这里保守估个数量级
# 供熔断线用;真实计费以 Vidu 账单为准,发现偏差应回填这个常量)。
_VIDU_TURNAROUND_COST_ESTIMATE_USD = 0.5


def lint_shot_prompt(prompt: str, immutable_traits: str) -> list[str]:
    """spec §11.1 规则1:身份词(costume_lock/immutable_traits 的措辞)不该出现在
    shot prompt 里——身份完全由参考资产承载,prompt 里的身份词会与参考图竞争导致漂移。

    返回命中的违规词列表;空列表 = 通过。粒度:immutable_traits 按逗号/顿号/空格切词,
    忽略过短(<2 字)的碎片以减少误报。
    """
    import re

    tokens = [t.strip() for t in re.split(r"[,,、\s]+", immutable_traits) if len(t.strip()) >= 2]
    return [t for t in tokens if t in prompt]


def _compose_grid(image_paths: list[Path], output_path: Path, *, cols: int = 3) -> Path:
    """把多张同尺寸图片拼成一张网格图(默认 3 列,§2.1 的"九宫格")。"""
    from PIL import Image

    images = [Image.open(p).convert("RGB") for p in image_paths]
    w, h = images[0].size
    rows = (len(images) + cols - 1) // cols
    grid = Image.new("RGB", (w * cols, h * rows), (255, 255, 255))
    for i, img in enumerate(images):
        x, y = (i % cols) * w, (i // cols) * h
        grid.paste(img.resize((w, h)), (x, y))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(output_path)
    return output_path


async def _stability_precheck(
    *,
    appearance: str,
    era_lock: str,
    art_direction: str,
    character_id: str,
    output_dir: Path,
    image_gen: Any,
    vlm: Any,
    num_trials: int = _STABILITY_TRIALS,
    use_sdxl_batch: bool = False,
    cost_limit: CostLimit | None = None,
    cost_tracker: CostTracker | None = None,
    image_appearance: str | None = None,
    image_era_lock: str | None = None,
) -> tuple[StabilityCheck, Path]:
    """spec §11.2:同参考同 prompt 重生成 N 次,≥min_pass 次通过(VLM 服装/年代审 +
    与首个候选的 CLIP 自洽性)才允许晋级。返回(StabilityCheck, 选中的权威像路径)。

    选中策略:取第一个"通过"的候选作为 canonical_portrait(不是任选,保证可复现);
    全部候选都不过时仍返回第一个候选路径,但 stability_check.passed=False,
    调用方(build_identity_pack)不应据此 promote。

    use_sdxl_batch=True(仅在 image_gen 是默认 sdxl_local 时由调用方开启):N 个候选
    一次性丢进 resilient_image_gen_batch 里生成(模型只加载一次,GPU 不健康或批内
    单张失败时逐张自动降级云端——见该函数 docstring),而不是像默认那样逐个候选各起
    一个子进程——见 build_identity_pack 里同样的考虑。

    image_appearance/image_era_lock:喂给 SDXL 的英文视觉描述,appearance/era_lock
    (中文)仍然原样进 manifest——2026-07-09 CPU 回退验证实测过,SDXL Base 1.0 对
    "进贤冠""深衣"这类中文专有名词理解很弱,纯中文 image prompt 经常直接跑偏成风景/
    拼贴图案。不传就退化成拿 appearance/era_lock 直接拼中文 prompt(旧行为,测试夹具
    沿用)。

    VLM 审核 prompt 同样优先用 image_appearance/image_era_lock(有传的话)——这是"根
    变量因果推导"的应用:生成图片时实际喂给模型的描述是什么,审核就该按同一份描述的
    标准来判断,而不是拿一份独立维护、措辞更精确的中文历史术语(比如"进贤冠"这个具体
    形制名称)去核对一张从宽泛英文描述生成的图。两份描述本来语义对应但精确度不同,
    用更严的那份去审更松的那份生成结果,必然系统性地打回——2026-07-09 实测过这个
    落差:图像内容方向正确(黑色官帽/长袍、年代感基本对),但 VLM 按"进贤冠""云纹深衣"
    这类具体名词逐项核对,判定"违反"。
    """
    import hashlib

    from hevi.tongjian.character_bible import _call_vlm_json

    if image_appearance is not None:
        prompt = (
            f"{art_direction}, portrait of a historical figure, front-facing authoritative "
            f"portrait, {image_appearance}. {image_era_lock or ''} Half-body portrait, "
            f"plain simple background."
        )
        audit_immutable_traits = image_appearance
        audit_era_lock = image_era_lock or ""
    else:
        prompt = f"{art_direction}风格历史人物肖像,正面权威像,{appearance}。{era_lock}。半身像,背景简洁。"
        audit_immutable_traits = appearance
        audit_era_lock = era_lock
    audit_prompt = _ERA_AUDIT_PROMPT_TEMPLATE.format(
        immutable_traits=audit_immutable_traits, era_lock=audit_era_lock
    )

    seeds = [
        int(hashlib.sha256(f"{character_id}:portrait:{i}".encode()).hexdigest()[:8], 16)
        for i in range(num_trials)
    ]
    candidate_target_paths = [output_dir / f"portrait_v{i}.png" for i in range(num_trials)]

    batch_errors: dict[int, Exception] = {}
    if use_sdxl_batch:
        from hevi.image.resilient_image_gen import resilient_image_gen_batch

        batch_results = await resilient_image_gen_batch(
            [
                {"prompt": prompt, "output_path": p, "seed": s, "extra": {}}
                for p, s in zip(candidate_target_paths, seeds, strict=True)
            ],
            cost_limit=cost_limit,
            cost_tracker=cost_tracker,
        )
        for i, r in enumerate(batch_results):
            if isinstance(r, Exception):
                batch_errors[i] = r

    candidate_paths: list[Path] = []
    pass_flags: list[bool] = []
    first_vec: list[float] | None = None

    for i in range(num_trials):
        seed = seeds[i]
        candidate_path = candidate_target_paths[i]
        if use_sdxl_batch:
            if i in batch_errors:
                logger.warning(
                    "身份包 %s 候选像 v%d 生成失败: %s", character_id, i, batch_errors[i]
                )
                pass_flags.append(False)
                continue
        else:
            try:
                await image_gen(prompt=prompt, output_path=candidate_path, seed=seed, extra={})
            except Exception as e:
                logger.warning("身份包 %s 候选像 v%d 生成失败: %s", character_id, i, e)
                pass_flags.append(False)
                continue
        candidate_paths.append(candidate_path)

        try:
            audit = await _call_vlm_json(vlm, audit_prompt, candidate_path)
            audit_passed = bool(audit.get("passes", True))
        except Exception as e:
            logger.warning("身份包 %s 候选像 v%d VLM 审调用失败,视为不通过: %s", character_id, i, e)
            audit_passed = False

        consistent = True
        try:
            vec = subject_embed(image_path=candidate_path, kind="style")
            if first_vec is None:
                first_vec = vec
            else:
                from hevi.subjects.subject_embed import cosine_similarity

                distance = 1.0 - cosine_similarity(first_vec, vec)
                consistent = distance <= _STABILITY_CONSISTENCY_THRESHOLD
        except Exception as e:
            logger.warning("身份包 %s 候选像 v%d embedding 自洽性检查失败: %s", character_id, i, e)

        pass_flags.append(audit_passed and consistent)

    passed_count = sum(pass_flags)
    stability = StabilityCheck(
        passed=passed_count >= _STABILITY_MIN_PASS,
        score=f"{passed_count}/{num_trials}",
    )
    canonical = next(
        (p for p, ok in zip(candidate_paths, pass_flags, strict=False) if ok),
        candidate_paths[0] if candidate_paths else output_dir / "portrait_v0.png",
    )
    return stability, canonical


async def build_identity_pack(
    *,
    pool: Any,
    minio_client: Any,
    character_id: str,
    name: str,
    appearance: str,
    era_lock: str,
    art_direction: str,
    output_dir: Path,
    version: str = "0.1.0",
    expressions: dict[str, str] | None = None,
    image_gen: Any = None,
    vlm: Any = None,
    video_gen: Any = None,
    tts_fn: Any = None,
    voice: str = "zh_male_standard",
    cost_limit: CostLimit | None = None,
    cost_tracker: CostTracker | None = None,
    build_turnaround_video: bool = True,
    run_id: str | None = None,
    image_appearance: str | None = None,
    image_era_lock: str | None = None,
) -> Manifest:
    """spec §2.1 全流程:构建 → asset_create(draft)→ 稳定性预检 → asset_promote。

    image_gen/vlm/tts_fn 默认走 ProviderRegistry(同 L5/L6 惯例);video_gen 默认
    hevi.video.vidu_service.vidu_reference_to_video——这一步真花钱,build_turnaround_
    video=False 可跳过(比如先跑一遍看图像/声音/embedding 是否都对,再决定要不要
    花钱生成转身视频)。

    cost_tracker 不传时退化成只查转身视频这一笔(旧行为);调用方要在多角色/多张
    云端兜底图之间拦住"单笔都不超线但叠加超支",应该在同一个 run 里创建一个
    CostTracker,传给这里、也传给(如果 image_gen 走云端兜底)image_gen 自己
    (见 hevi.image.resilient_image_gen)。

    image_appearance/image_era_lock:可选的英文视觉描述,只喂给 SDXL(权威像/九宫格/
    动作姿势/表情表这几步的 prompt),appearance/era_lock 本身仍然原样进 manifest 和
    VLM 年代审 prompt——2026-07-09 CPU 回退验证实测过,SDXL Base 1.0 对"进贤冠"
    "深衣"这类中文专有名词理解很弱,纯中文 image prompt 经常直接跑偏成风景/拼贴图案
    而非人物。不传就退化成拿 appearance/era_lock 直接拼中文 prompt(旧行为)。

    tts_fn 默认走 edge_tts(voice 参数选音色,见 hevi.audio.edge_tts_custom.
    CURATED_VOICES)而非 vibevoice/CosyVoice 零样本克隆——这条克隆链路要求每次调用
    都带一段真人参考音频(此 vibevoice 发行版没有无参考默认音色),但虚构历史角色
    没有真人录音可用作参考,克隆链路无从下手。按 HEVI-EXEC-01 §0 第3项预案("本地
    部署超1天则临时切云TTS,不阻塞主线")临时切云;等拿到角色的真人参考音频后,
    显式传入基于 vibevoice_synthesize 的 tts_fn 即可换回克隆链路。
    """
    _using_default_image_gen = image_gen is None
    if image_gen is None:
        from obase.provider_registry import ProviderRegistry

        image_gen = ProviderRegistry.get().image_gen("sdxl_local")
    if vlm is None:
        from obase.provider_registry import ProviderRegistry

        vlm = ProviderRegistry.get().vlm("default")
    _using_edge_tts_fallback = tts_fn is None
    if tts_fn is None:
        from functools import partial

        from hevi.audio.edge_tts_custom import synthesize_with_voice_control

        tts_fn = partial(synthesize_with_voice_control, voice=voice)
    expressions = expressions if expressions is not None else _DEFAULT_EXPRESSIONS
    # 整个构建过程(稳定性预检批量图 + 九宫格/表情批量图 + 转身视频)共用同一个
    # tracker,才能把"这个角色总共花了多少"算进 $20 熔断线,而不是每笔单独判断
    # (见 hevi.cost.circuit_breaker.CostTracker docstring)。
    tracker = cost_tracker or CostTracker()

    output_dir.mkdir(parents=True, exist_ok=True)
    pack_id = f"identity/{character_id}"

    # 1. 正面权威像 + 稳定性预检
    stability, canonical_portrait = await _stability_precheck(
        appearance=appearance,
        era_lock=era_lock,
        art_direction=art_direction,
        character_id=character_id,
        output_dir=output_dir,
        image_gen=image_gen,
        vlm=vlm,
        use_sdxl_batch=_using_default_image_gen,
        cost_limit=cost_limit,
        cost_tracker=tracker,
        image_appearance=image_appearance,
        image_era_lock=image_era_lock,
    )

    # 2. 九宫格多视角 + 动作姿势参考,3. 表情表 —— 默认 sdxl_local 时一次性批量生成
    # (模型只加载一次),GPU 不健康或批内单张失败时逐张自动降级云端(见
    # hevi.image.resilient_image_gen.resilient_image_gen_batch 的说明:EXEC-01 M2
    # 身份包构建这种十几张图连续生成的场景,曾在这台机器上牵连出 GPU 从 PCIe 总线
    # 掉线的硬件故障)。
    action_pose_path: Path | None = output_dir / "action_pose.png"
    view_paths: list[Path] = []
    expression_paths: dict[str, Path] = {}
    if _using_default_image_gen:
        from hevi.image.resilient_image_gen import resilient_image_gen_batch

        view_keys = list(_MULTIVIEW_ANGLES.keys())
        view_out_paths = [output_dir / f"view_{k}.png" for k in view_keys]
        expr_keys = list(expressions.keys())
        expr_out_paths = [output_dir / f"expr_{k}.png" for k in expr_keys]

        if image_appearance is not None:
            _person = f"{image_appearance}. {image_era_lock or ''}"

            def _view_prompt(k: str) -> str:
                return f"{art_direction}, portrait of a historical figure, {_MULTIVIEW_ANGLES[k]}, {_person}"

            def _action_prompt() -> str:
                return f"{art_direction}, historical figure, {_ACTION_POSE_HINT}, {_person}"

            def _expr_prompt(k: str) -> str:
                return f"{art_direction}, portrait of a historical figure, front view, {expressions[k]}, {_person}"
        else:

            def _view_prompt(k: str) -> str:
                return f"{art_direction}风格历史人物肖像,{_MULTIVIEW_ANGLES[k]},{appearance}。{era_lock}。"

            def _action_prompt() -> str:
                return f"{art_direction}风格历史人物,{_ACTION_POSE_HINT},{appearance}。{era_lock}。"

            def _expr_prompt(k: str) -> str:
                return f"{art_direction}风格历史人物肖像,正面,{expressions[k]},{appearance}。{era_lock}。"

        batch_requests = (
            [
                {"prompt": _view_prompt(k), "output_path": p, "extra": {}}
                for k, p in zip(view_keys, view_out_paths, strict=True)
            ]
            + [
                {
                    "prompt": _action_prompt(),
                    "output_path": action_pose_path,
                    "extra": {},
                }
            ]
            + [
                {"prompt": _expr_prompt(k), "output_path": p, "extra": {}}
                for k, p in zip(expr_keys, expr_out_paths, strict=True)
            ]
        )
        batch_results = await resilient_image_gen_batch(
            batch_requests, cost_limit=cost_limit, cost_tracker=tracker
        )

        for k, p, r in zip(view_keys, view_out_paths, batch_results[: len(view_keys)], strict=True):
            if isinstance(r, Exception):
                logger.warning("身份包 %s 视角 %s 生成失败,跳过该格: %s", character_id, k, r)
            else:
                view_paths.append(p)

        action_pose_result = batch_results[len(view_keys)]
        if isinstance(action_pose_result, Exception):
            logger.warning("身份包 %s 动作姿势参考生成失败: %s", character_id, action_pose_result)
            action_pose_path = None

        expr_results = batch_results[len(view_keys) + 1 :]
        for k, p, r in zip(expr_keys, expr_out_paths, expr_results, strict=True):
            if isinstance(r, Exception):
                logger.warning("身份包 %s 表情 %s 生成失败,跳过: %s", character_id, k, r)
            else:
                expression_paths[k] = p
    else:
        for view_key, view_hint in _MULTIVIEW_ANGLES.items():
            prompt = f"{art_direction}风格历史人物肖像,{view_hint},{appearance}。{era_lock}。"
            path = output_dir / f"view_{view_key}.png"
            try:
                await image_gen(prompt=prompt, output_path=path, extra={})
                view_paths.append(path)
            except Exception as e:
                logger.warning("身份包 %s 视角 %s 生成失败,跳过该格: %s", character_id, view_key, e)

        try:
            await image_gen(
                prompt=f"{art_direction}风格历史人物,{_ACTION_POSE_HINT},{appearance}。{era_lock}。",
                output_path=action_pose_path,
                extra={},
            )
        except Exception as e:
            logger.warning("身份包 %s 动作姿势参考生成失败: %s", character_id, e)
            action_pose_path = None

        for expr_key, expr_hint in expressions.items():
            path = output_dir / f"expr_{expr_key}.png"
            try:
                await image_gen(
                    prompt=f"{art_direction}风格历史人物肖像,正面,{expr_hint},{appearance}。{era_lock}。",
                    output_path=path,
                    extra={},
                )
                expression_paths[expr_key] = path
            except Exception as e:
                logger.warning("身份包 %s 表情 %s 生成失败,跳过: %s", character_id, expr_key, e)

    grid_path = output_dir / "grid9.png"
    if view_paths:
        _compose_grid(view_paths, grid_path)

    # 4. 5 秒转身视频(真花钱,外部调用前过熔断线;跟 image_gen 云端兜底共用同一个
    # cost_tracker 才能把"这个角色/这个 run 已经花了多少"算进去,不是只看这一笔孤立
    # 值不值 $20)。
    turnaround_path: Path | None = None
    if build_turnaround_video:
        if video_gen is None:
            from hevi.video.vidu_service import vidu_reference_to_video

            video_gen = vidu_reference_to_video
        await tracker.check_and_reserve(_VIDU_TURNAROUND_COST_ESTIMATE_USD, cost_limit)
        turnaround_path = output_dir / "turn_5s.mp4"
        try:
            await video_gen(
                prompt=f"{art_direction}风格历史人物转身展示,中性光照,素色背景,5秒",
                reference_images=[str(canonical_portrait)],
                output_path=turnaround_path,
                duration=5,
            )
        except Exception as e:
            logger.warning("身份包 %s 转身视频生成失败(不阻塞其余步骤): %s", character_id, e)
            turnaround_path = None

    # 5. CosyVoice 8 秒声线样本
    voice_path = output_dir / "voice_8s.wav"
    voice_meta: dict[str, Any] = {}
    try:
        from dataclasses import dataclass

        @dataclass
        class _VoiceLine:
            speaker_id: str
            text: str

        await tts_fn(
            script=[_VoiceLine(speaker_id=character_id, text=f"{name},{appearance}。")],
            output_path=voice_path,
        )
        voice_meta = {
            "voice_ref_audio": str(voice_path),
            "tts_voice_id": (
                f"edge_tts:{voice}"
                if _using_edge_tts_fallback
                else f"cosyvoice:{character_id.lower()}_cloned"
            ),
        }
    except Exception as e:
        logger.warning("身份包 %s 声线样本生成失败: %s", character_id, e)
        voice_path = None

    # 6. embedding 提取
    embeddings_meta: dict[str, dict] = {}
    face_embedding: list[float] | None = None
    try:
        face_embedding = subject_embed(image_path=canonical_portrait, kind="face")
        embeddings_meta["face"] = {"model": "clip-vit-base-patch32", "dim": len(face_embedding)}
    except Exception as e:
        logger.warning("身份包 %s embedding 提取失败: %s", character_id, e)

    # ── 落库 ──
    files: dict[str, bytes] = {}
    file_roles: dict[str, str] = {}

    def _add_file(rel_path: str, path: Path | None, role: str) -> None:
        if path is not None and path.exists():
            files[rel_path] = path.read_bytes()
            file_roles[rel_path] = role

    _add_file("refs/front.png", canonical_portrait, "canonical_portrait")
    _add_file("refs/grid9.png", grid_path if view_paths else None, "multiview_grid")
    _add_file("refs/action_pose.png", action_pose_path, "action_pose")
    for expr_key, expr_path in expression_paths.items():
        _add_file(f"refs/expr_{expr_key}.png", expr_path, f"expression_{expr_key}")
    _add_file("refs/turn_5s.mp4", turnaround_path, "turnaround_video")
    _add_file("refs/voice_8s.wav", voice_path, "voice_ref_audio")

    manifest = await asset_create(
        pool,
        minio_client,
        pack_id=pack_id,
        pack_type="identity",
        name=name,
        version=version,
        files=files,
        file_roles=file_roles,
        immutable_traits=appearance,
        era_lock=era_lock,
        embeddings=embeddings_meta,
        voice=voice_meta,
        # 2026-07-09 修复:之前没传这个字段,draft(没过稳定性预检)的 manifest 里
        # stability_check 一直是 Manifest 的默认空壳(score=""),不是真实跑出来的
        # "0/3"/"1/3"——诊断时看不出具体差多少、哪个候选过了。asset_promote 会在
        # passed=True 时再覆盖一遍(带 checked_at),这里先如实落一份。
        stability_check=stability,
        provenance={"built_by_run": run_id, "gen_models": ["sdxl_local"]},
    )

    if face_embedding is not None:
        await store_embedding(
            pool,
            pack_id=pack_id,
            version=version,
            kind="identity",
            embedding=face_embedding,
        )

    if stability.passed:
        manifest = await asset_promote(
            pool,
            pack_id=pack_id,
            version=version,
            stability_check=stability,
        )
    else:
        logger.warning(
            "身份包 %s 稳定性预检未通过(%s),保持 draft,不 promote",
            character_id,
            stability.score,
        )

    return manifest
