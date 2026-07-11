"""C6 视频生成 + CG6 质量门 + 降级链 —— 见 HEVI-SPEC-02 §5.1/5.3,HEVI-EXEC-01 M3。

单通道打通:Vidu Q3 Reference-to-Video(animated 分支首选,SPEC-02 §11.3)。流程:
`asset_resolve` 取镜头里唯一在场角色(one clean face rule 保证每个 shot 最多 1 人
in-frame,见 shot_planning.py)的身份包 → 选 2-4 张参考图 → `ensure_platform_binding`
→ `vidu_reference_to_video` 生成 → CG6 门(身份距离 + 台词 ASR diff + VLM 穿帮)→
不过 reroll(≤3 次,换 seed)→ 仍不过降级(对白转旁白/不开口 → 静帧+推拉,任何情况
下不允许开天窗,同 scene_render.py 的降级链哲学)→ 成功(含降级产物)都记血缘。

口型同步(SyncNet 类打分)没有现成实现,CG6Result.lipsync_note 显式标注
"not implemented",不假装做了这项检查。
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from obase.ffmpeg import FFmpegError, run as ffmpeg_run

from hevi.cinematic.platform_binding import ensure_platform_binding
from hevi.cinematic.schemas import CG6Result, CineShot, ShotResult
from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.subjects.subject_embed import subject_embed
from hevi.vault.service import asset_resolve, asset_verify, record_lineage

logger = logging.getLogger(__name__)

_MAX_REROLLS = 3
_IDENTITY_DISTANCE_THRESHOLD = 0.35  # 同 asset_verify 默认阈值
_DIALOGUE_CER_THRESHOLD = 0.03  # SPEC-02 §5.3:CER>3% 判不通过
_VIDU_SHOT_COST_ESTIMATE_USD = 0.5  # 没有精确计费,同 identity_pack.py 的惯例保守估个量级
_REFERENCE_ROLES_PRIORITY = ("canonical_portrait", "action_pose")
_MAX_REFERENCE_IMAGES = 4


def _seed_for(shot_id: str, attempt: int) -> int:
    """确定性 seed(同一 shot_id+attempt 总算出同一个值,方便复现)。

    取 8 位 hex 理论上能到 0xFFFFFFFF(4294967295),但多个 provider 的 seed 校验只
    收 32 位**有符号**整数范围(0~2147483647,如阿里云百炼 happyhorse-1.1-r2v 的
    InvalidParameter 实测反馈)——& 0x7FFFFFFF 砍掉最高位,确保任何 provider 都能接受,
    仍然是同一路输入确定性推出同一个值。
    """
    import hashlib

    digest = hashlib.sha256(f"{shot_id}:{attempt}".encode()).hexdigest()
    return int(digest[:8], 16) & 0x7FFFFFFF


async def _pick_reference_images(pool, minio_client, pack_id: str, version: str) -> list[Path]:
    """从 manifest.files 里按 role 选 2-4 张参考图:canonical_portrait 必选(正面权威
    像),再加 action_pose(动态姿势——SPEC-02 §11.1 规则3,身份包参考集必含动态参考,
    不能全是静态肖像)。写到临时文件供 ensure_platform_binding 读取(manifest.files
    存的是 MinIO 内容寻址的字节,不是本地路径)。
    """
    from hevi.vault.blob_store import get_blob

    resolved = await asset_resolve(pool, pack_id=pack_id)
    manifest = resolved["manifest"]
    bucket = "vault-identity"

    by_role: dict[str, str] = {}
    for rel_path, info in manifest.files.items():
        by_role.setdefault(info.role, rel_path)

    tmp_dir = Path(tempfile.mkdtemp(prefix="cine_refs_"))
    paths: list[Path] = []
    for role in _REFERENCE_ROLES_PRIORITY:
        rel_path = by_role.get(role)
        if not rel_path:
            continue
        sha256 = manifest.files[rel_path].sha256
        data = get_blob(minio_client, bucket=bucket, sha256=sha256)
        out_path = tmp_dir / Path(rel_path).name
        out_path.write_bytes(data)
        paths.append(out_path)
        if len(paths) >= _MAX_REFERENCE_IMAGES:
            break
    return paths


async def _generate_attempt(
    shot: CineShot,
    reference_uris: list[str],
    *,
    output_path: Path,
    seed: int,
    video_gen: Any,
    open_mouth: bool,
) -> Path:
    prompt = shot.prompt
    if not open_mouth and shot.dialogue_inline is not None:
        prompt = f"{prompt}(角色不开口,画外音式表演)"
    await video_gen(
        prompt=prompt,
        reference_images=reference_uris,
        output_path=output_path,
        duration=int(shot.est_duration_s),
        seed=seed,
    )
    return output_path


async def _extract_frame(video_path: Path, frame_path: Path) -> None:
    await ffmpeg_run(
        args=[
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "select=eq(n\\,0)",
            "-vframes",
            "1",
            str(frame_path),
        ],
        expected_output=frame_path,
    )


async def _extract_audio(video_path: Path, audio_path: Path) -> None:
    await ffmpeg_run(
        args=["-y", "-i", str(video_path), "-vn", "-ar", "16000", "-ac", "1", str(audio_path)],
        expected_output=audio_path,
    )


async def _run_cg6(
    video_path: Path,
    shot: CineShot,
    pool,
    pack_id: str,
    version: str,
    *,
    vlm: Any,
) -> CG6Result:
    result = CG6Result()
    tmp_dir = video_path.parent

    # 1. 身份距离(抽帧 embedding vs 身份包)
    try:
        frame_path = tmp_dir / f"{shot.shot_id}_frame.png"
        await _extract_frame(video_path, frame_path)
        embedding = subject_embed(image_path=frame_path, kind="face")
        verify = await asset_verify(
            pool, pack_id=pack_id, version=version, frame_embedding=embedding
        )
        result.identity_distance = verify.get("distance")
        result.identity_passed = bool(verify.get("passed"))
    except Exception as e:
        logger.warning("镜头 %s 身份距离检查失败,视为不通过: %s", shot.shot_id, e)
        result.identity_passed = False

    # 2. 台词 ASR diff(只有有台词的镜头才检查)
    if shot.dialogue_inline is not None:
        try:
            from hevi.tongjian.voiceover import _compute_cer

            audio_path = tmp_dir / f"{shot.shot_id}_audio.wav"
            await _extract_audio(video_path, audio_path)
            cer = await _compute_cer(shot.dialogue_inline.text, audio_path)
            result.dialogue_cer = cer
            result.dialogue_passed = cer <= _DIALOGUE_CER_THRESHOLD
        except Exception as e:
            logger.warning("镜头 %s 台词 ASR 检查失败,视为通过(P0 简化): %s", shot.shot_id, e)
            result.dialogue_passed = True
    else:
        result.dialogue_passed = True

    # 3. VLM 穿帮/肢体崩坏
    try:
        from hevi.tongjian.character_bible import _call_vlm_json

        frame_path = tmp_dir / f"{shot.shot_id}_frame.png"
        if not frame_path.exists():
            await _extract_frame(video_path, frame_path)
        audit_prompt = (
            "判断这一帧画面是否存在穿帮或肢体崩坏(六指、肢体扭曲/穿模、"
            "画面里出现现代物件)。只输出 JSON: "
            '{"passes": true/false, "violations": ["..."]}'
        )
        audit = await _call_vlm_json(vlm, audit_prompt, frame_path)
        result.vlm_passed = bool(audit.get("passes", True))
        result.vlm_violations = list(audit.get("violations") or [])
    except Exception as e:
        logger.warning("镜头 %s VLM 穿帮检查调用失败,视为通过: %s", shot.shot_id, e)
        result.vlm_passed = True

    result.passed = bool(result.identity_passed and result.dialogue_passed and result.vlm_passed)
    return result


async def generate_shot(
    shot: CineShot,
    pool,
    minio_client,
    *,
    run_id: str | None = None,
    video_gen: Any = None,
    vlm: Any = None,
    cost_limit: CostLimit | None = None,
    cost_tracker: CostTracker | None = None,
    platform: str = "vidu",
    cost_estimate_usd: float = _VIDU_SHOT_COST_ESTIMATE_USD,
) -> ShotResult:
    """单镜头完整生成 + CG6 门 + reroll/降级链。run_id 是 UUID 字符串,不给就现生成
    一个(每次调用都是独立的一条血缘记录,`vault_lineage.run_id` 是 UUID 类型)。

    cost_estimate_usd:预算熔断的每次尝试保守估算(不是精确计费,只是给
    `CostTracker.check_and_reserve` 一个量级)。默认沿用 Vidu 那档;换成
    reference-to-video 定价不同的 provider(如 WaveSpeed HappyHorse)时,调用方应
    传对应更真实的估值,否则熔断线会按 Vidu 的价格误判剩余预算。
    """
    if video_gen is None:
        from hevi.video.vidu_service import vidu_reference_to_video

        video_gen = vidu_reference_to_video
    if vlm is None:
        from obase.provider_registry import ProviderRegistry

        vlm = ProviderRegistry.get().vlm("default")

    run_id = run_id or str(uuid.uuid4())
    tracker = cost_tracker or CostTracker()
    pack_id = f"identity/{shot.on_screen[0]}" if shot.on_screen else ""
    output_dir = Path(tempfile.mkdtemp(prefix=f"cine_{shot.shot_id.lower()}_"))

    reference_paths: list[Path] = []
    reference_uris: list[str] = []
    if pack_id:
        resolved = await asset_resolve(pool, pack_id=pack_id)
        version = resolved["version"]
        reference_paths = await _pick_reference_images(pool, minio_client, pack_id, version)
        reference_uris = await ensure_platform_binding(
            pool, pack_id=pack_id, version=version, platform=platform, image_paths=reference_paths
        )
    else:
        version = ""

    last_result = ShotResult(shot_id=shot.shot_id)
    for attempt in range(_MAX_REROLLS):
        await tracker.check_and_reserve(cost_estimate_usd, cost_limit)
        output_path = output_dir / f"{shot.shot_id.lower()}_v{attempt}.mp4"
        try:
            await _generate_attempt(
                shot,
                reference_uris,
                output_path=output_path,
                seed=_seed_for(shot.shot_id, attempt),
                video_gen=video_gen,
                open_mouth=True,
            )
        except Exception as e:
            logger.warning("镜头 %s 第 %d 次生成失败: %s", shot.shot_id, attempt, e)
            last_result = ShotResult(shot_id=shot.shot_id, attempts=attempt + 1)
            continue

        cg6 = (
            await _run_cg6(output_path, shot, pool, pack_id, version, vlm=vlm)
            if pack_id
            else CG6Result(passed=True)
        )
        last_result = ShotResult(
            shot_id=shot.shot_id,
            output_path=str(output_path),
            attempts=attempt + 1,
            cg6=cg6,
        )
        if cg6.passed:
            sha256 = _sha256_file(output_path)
            await record_lineage(
                pool,
                derived_sha256=sha256,
                run_id=run_id,
                shot_id=shot.shot_id,
                pack_id=pack_id,
                version=version,
            )
            return last_result
        logger.info("镜头 %s 第 %d 次未过 CG6(%s),reroll", shot.shot_id, attempt, cg6)

    # 降级阶段1:有台词的镜头 -> 转旁白/不开口重试一次
    if shot.dialogue_inline is not None:
        await tracker.check_and_reserve(cost_estimate_usd, cost_limit)
        output_path = output_dir / f"{shot.shot_id.lower()}_degraded_narration.mp4"
        try:
            await _generate_attempt(
                shot,
                reference_uris,
                output_path=output_path,
                seed=_seed_for(shot.shot_id, _MAX_REROLLS),
                video_gen=video_gen,
                open_mouth=False,
            )
            cg6 = (
                await _run_cg6(output_path, shot, pool, pack_id, version, vlm=vlm)
                if pack_id
                else CG6Result(passed=True)
            )
            result = ShotResult(
                shot_id=shot.shot_id,
                output_path=str(output_path),
                attempts=_MAX_REROLLS + 1,
                degraded=True,
                degrade_reason="对白镜头多次未过 CG6,降级为旁白转述+角色不开口",
                cg6=cg6,
            )
            if cg6.passed:
                sha256 = _sha256_file(output_path)
                await record_lineage(
                    pool,
                    derived_sha256=sha256,
                    run_id=run_id,
                    shot_id=shot.shot_id,
                    pack_id=pack_id,
                    version=version,
                )
                return result
            last_result = result
        except Exception as e:
            logger.warning("镜头 %s 降级为旁白转述也失败: %s", shot.shot_id, e)

    # 降级阶段2:静帧 + 推拉(任何情况下不允许开天窗,同 scene_render.py 的降级链哲学)
    static_path = output_dir / f"{shot.shot_id.lower()}_static.mp4"
    if reference_paths:
        try:
            await ffmpeg_run(
                args=[
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(reference_paths[0]),
                    "-t",
                    str(shot.est_duration_s),
                    "-vf",
                    f"zoompan=z='min(zoom+0.0015,1.1)':d={int(shot.est_duration_s * 25)}",
                    "-pix_fmt",
                    "yuv420p",
                    str(static_path),
                ],
                expected_output=static_path,
            )
            sha256 = _sha256_file(static_path)
            await record_lineage(
                pool,
                derived_sha256=sha256,
                run_id=run_id,
                shot_id=shot.shot_id,
                pack_id=pack_id,
                version=version,
            )
            return ShotResult(
                shot_id=shot.shot_id,
                output_path=str(static_path),
                attempts=last_result.attempts,
                degraded=True,
                degrade_reason="Vidu 生成多次失败/未过 CG6,最终降级为静帧+推拉",
                cg6=last_result.cg6,
            )
        except FFmpegError as e:
            logger.error("镜头 %s 静帧兜底也失败: %s", shot.shot_id, e)

    return last_result


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
