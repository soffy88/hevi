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

from hevi.cost.circuit_breaker import CostLimit, check_before_run
from hevi.cost.estimator import CostEstimate
from hevi.subjects.subject_embed import subject_embed
from hevi.vault.schemas import Manifest, StabilityCheck
from hevi.vault.service import asset_create, asset_promote, store_embedding

logger = logging.getLogger(__name__)

_MULTIVIEW_ANGLES: dict[str, str] = {
    "front": "正面,面朝镜头",
    "front_left_34": "左前四分之三侧面",
    "front_right_34": "右前四分之三侧面",
    "profile_left": "左侧面",
    "profile_right": "右侧面",
    "back_left_34": "左后四分之三侧面,背对镜头",
    "back_right_34": "右后四分之三侧面,背对镜头",
    "back": "背面,背对镜头",
    "three_quarter_high": "略微俯视角度,四分之三侧面",
}
_DEFAULT_EXPRESSIONS: dict[str, str] = {
    "neutral": "平静表情",
    "haughty": "倨傲神情",
    "furious": "暴怒神情",
    "terrified": "惊恐神情",
}
_ACTION_POSE_HINT = "动态姿势,展现人物典型动作,而非站立肖像"

_STABILITY_TRIALS = 3
_STABILITY_MIN_PASS = 2
# CLIP 自洽性阈值:候选像 vs 首个候选像的余弦距离,超过则判定"跑偏"(同一角色不同次
# 生成理应视觉接近;真正的人脸级判别留给 kind="face" 专用后端,同 subject_embed 简化)。
_STABILITY_CONSISTENCY_THRESHOLD = 0.35

_ERA_AUDIT_PROMPT_TEMPLATE = """你是历史短片年代服装审核员。判断这张图片是否存在年代错误,以及是否
符合下面的服饰/外形锁定描述。

服饰/外形锁定: {immutable_traits}
时代要求: {era_lock}

只输出 JSON: {{"passes": true/false, "violations": ["..."]}}"""

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
) -> tuple[StabilityCheck, Path]:
    """spec §11.2:同参考同 prompt 重生成 N 次,≥min_pass 次通过(VLM 服装/年代审 +
    与首个候选的 CLIP 自洽性)才允许晋级。返回(StabilityCheck, 选中的权威像路径)。

    选中策略:取第一个"通过"的候选作为 canonical_portrait(不是任选,保证可复现);
    全部候选都不过时仍返回第一个候选路径,但 stability_check.passed=False,
    调用方(build_identity_pack)不应据此 promote。
    """
    import hashlib

    from hevi.tongjian.character_bible import _call_vlm_json

    prompt = (
        f"{art_direction}风格历史人物肖像,正面权威像,{appearance}。{era_lock}。半身像,背景简洁。"
    )
    audit_prompt = _ERA_AUDIT_PROMPT_TEMPLATE.format(immutable_traits=appearance, era_lock=era_lock)

    candidate_paths: list[Path] = []
    pass_flags: list[bool] = []
    first_vec: list[float] | None = None

    for i in range(num_trials):
        seed = int(hashlib.sha256(f"{character_id}:portrait:{i}".encode()).hexdigest()[:8], 16)
        candidate_path = output_dir / f"portrait_v{i}.png"
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
    cost_limit: CostLimit | None = None,
    build_turnaround_video: bool = True,
    run_id: str | None = None,
) -> Manifest:
    """spec §2.1 全流程:构建 → asset_create(draft)→ 稳定性预检 → asset_promote。

    image_gen/vlm/tts_fn 默认走 ProviderRegistry(同 L5/L6 惯例);video_gen 默认
    hevi.video.vidu_service.vidu_reference_to_video——这一步真花钱,build_turnaround_
    video=False 可跳过(比如先跑一遍看图像/声音/embedding 是否都对,再决定要不要
    花钱生成转身视频)。
    """
    if image_gen is None:
        from obase.provider_registry import ProviderRegistry

        image_gen = ProviderRegistry.get().image_gen("sdxl_local")
    if vlm is None:
        from obase.provider_registry import ProviderRegistry

        vlm = ProviderRegistry.get().vlm("default")
    if tts_fn is None:
        from hevi.audio.cosyvoice_service import cosyvoice_synthesize

        tts_fn = cosyvoice_synthesize
    expressions = expressions if expressions is not None else _DEFAULT_EXPRESSIONS

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
    )

    # 2. 九宫格多视角 + 动作姿势参考
    view_paths: list[Path] = []
    for view_key, view_hint in _MULTIVIEW_ANGLES.items():
        prompt = f"{art_direction}风格历史人物肖像,{view_hint},{appearance}。{era_lock}。"
        path = output_dir / f"view_{view_key}.png"
        try:
            await image_gen(prompt=prompt, output_path=path, extra={})
            view_paths.append(path)
        except Exception as e:
            logger.warning("身份包 %s 视角 %s 生成失败,跳过该格: %s", character_id, view_key, e)
    grid_path = output_dir / "grid9.png"
    if view_paths:
        _compose_grid(view_paths, grid_path)

    action_pose_path = output_dir / "action_pose.png"
    try:
        await image_gen(
            prompt=f"{art_direction}风格历史人物,{_ACTION_POSE_HINT},{appearance}。{era_lock}。",
            output_path=action_pose_path,
            extra={},
        )
    except Exception as e:
        logger.warning("身份包 %s 动作姿势参考生成失败: %s", character_id, e)
        action_pose_path = None

    # 3. 表情表
    expression_paths: dict[str, Path] = {}
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

    # 4. 5 秒转身视频(真花钱,外部调用前过熔断线)
    turnaround_path: Path | None = None
    if build_turnaround_video:
        if video_gen is None:
            from hevi.video.vidu_service import vidu_reference_to_video

            video_gen = vidu_reference_to_video
        estimate = CostEstimate(
            video_cost_usd=_VIDU_TURNAROUND_COST_ESTIMATE_USD,
            audio_cost_usd=0.0,
            total_usd=_VIDU_TURNAROUND_COST_ESTIMATE_USD,
            breakdown={"vidu_turnaround_video": _VIDU_TURNAROUND_COST_ESTIMATE_USD},
            estimated_credits=0,
        )
        await check_before_run(estimate, cost_limit)
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
            "tts_voice_id": f"cosyvoice:{character_id.lower()}_cloned",
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
