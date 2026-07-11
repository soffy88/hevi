#!/usr/bin/env python3
"""「智伯索地」5 镜头场景 —— 本地 SDXL + IP-Adapter 水墨重制(替代 scene_v2 的
happyhorse 卡通版)。

背景:scene_v2(happyhorse reference-to-video)违反 constitution 的
negative_style「夸张漫画风」——4/5 镜头是卡通描线动漫风、智伯两镜两张脸、还跟走
json2video 的水墨建立镜头风格分裂。根因追到底模:sdxl_local 原来是 SDXL Base 1.0
纯 prompt,出不了真水墨,身份包 0.1.2 那批肖像本身就是卡通老年智伯。修复链:接入
Muapi/sdxl-chinese-ink-painting LoRA(触发词 QIEMANCN)→ 身份包重建到 0.1.3(真水墨
+ 壮年黑须智伯)→ 本脚本用同一条 LoRA + 锁新肖像重出这 5 镜头。

与 build_scene_zhibo_suodi.py(cinematic 云 reference-to-video 通道)的区别:
- 复用同一套 C2.5 adapt_scene + C4 plan_shots(拿到 5 个已 lint 的 shot prompt);
- 视频生成换成本地:每镜头 SDXL(+IP-Adapter 锁该镜唯一在场角色的水墨肖像)出一帧,
  再 ffmpeg zoompan 缓推成 clip —— 水墨题材用静帧+缓推比"会动的水墨画"更成立,也绕开
  了云通道的卡通画风/锁脸弱;
- 音轨:质量投诉只针对画面,配音沿用 scene_v2 那条 30.6s 音轨,不重跑 TTS。

必须带 SDXL_LORA_PATH 环境变量跑(worker 才会 fuse LoRA),同身份包重建。免费、本地。
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from obase.ffmpeg import run as ffmpeg_run

from hevi.cinematic.scene_adapt import adapt_scene
from hevi.cinematic.schemas import Beat, BeatDialogue
from hevi.cinematic.shot_planning import plan_shots
from hevi.core.config import settings
from hevi.image.sdxl_local_service import sdxl_local_generate
from hevi.tongjian.schemas import ChapterIR, Constitution, Script
from hevi.vault import asset_resolve, get_minio_client, get_vault_pg_pool, init_vault_schema
from hevi.vault.blob_store import get_blob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_scene_zhibo_suodi_local")

_DATA_DIR = Path("hevi/cinematic/data/zhibo_suodi")
_OUT_DIR = Path("output/tongjian/zhibo_suodi")
_SCENE_AUDIO_SRC = _OUT_DIR / "scene_v2_generated.mp4"  # 沿用其配音音轨
_OUTPUT = _OUT_DIR / "scene_v3_local.mp4"

# 场景 art_direction 保持短:CLIP 只吃前 77 token,真正的建筑/朝堂 staging(见 _SHOT_STAGING)
# 必须挤进前段才不被截掉——所以这里只放触发词 + 水墨风(跟身份包同一条 LoRA、消风格分裂),
# 其余留给 setting。传给 plan_shots 做 lint/一致性,真正喂 SDXL 的 prompt 在循环里重排。
_SCENE_ART_DIRECTION = "QIEMANCN, Chinese ink wash painting, traditional guohua"
_NEG = (
    "cartoon, anime, manga, cel shading, flat vector art, digital illustration, 3d render, "
    "glossy, white beard, old man wizard, blurry, distorted, low quality, deformed, "
    "extra limbs, bad anatomy, watermark, text, modern clothing, national flag, "
    "military uniform, western suit, multiple heads, comic panel, poster, logo, "
    # 压山水先验:这条 LoRA 是山水画训练的,不显式排除会把每镜头都拽成"文人独处山水"
    # (v3 首版就是),而这是府门/朝堂的历史剧,要建筑与人物、不要旷野风景。
    "landscape, mountains, mountain range, river, lake, water, wilderness, outdoor nature, "
    "fishing, solitary hermit, plum blossom scenery, pine forest, misty valley, empty scenery"
)
_IP_ADAPTER_WEIGHT = 0.4  # 只锁脸、尽量不夺构图;配合建筑强提示,让画面是"人在府门/朝堂"而非肖像

# 逐镜头 staging(这是 5 镜头定制脚本,staging/锁脸对象直接写死,同 _EXTRA_BEATS 的做法)。
# setting:府门/朝堂的建筑与调度英文强提示,压过 LoRA 的山水偏置、补足 shot.prompt 里缺的
#   场景信息。lock:该镜头 IP-Adapter 锁哪个角色的水墨肖像(None=宽景不锁,让建筑铺满)。
#   SH03 原文是"韩康子眉头紧锁"的反应镜头,但因无台词被 plan_shots 默认判成全场入镜的
#   wide(on_screen 三人),这里显式锁 hankangzi、按中景朝堂处理,纠回它的真实主体。
_SHOT_STAGING: dict[str, tuple[str, str | None]] = {
    "SH01": (
        "wide establishing shot, outside the tall wooden gate of an ancient Chinese noble "
        "mansion, grand courtyard gate with tiled roof and stone steps, high palace walls, "
        "an envoy in robes holding a letter scroll standing before the closed gate, "
        "solemn architecture, empty courtyard",
        None,
    ),
    "SH02": (
        "interior of a Warring States court hall, tall wooden pillars and carved beams, "
        "a powerful arrogant minister standing haughtily with chin raised, domineering "
        "imposing bearing, indoor palace hall, medium close shot",
        "zhibo",
    ),
    "SH03": (
        "interior of an ancient Chinese court hall, wooden pillars, a troubled nobleman "
        "with deeply knitted brows, worried hesitant expression, standing indoors, "
        "palace hall, medium shot",
        "hankangzi",
    ),
    "SH04": (
        "interior of a court hall, the arrogant minister stepping forward one pace with a "
        "stern threatening gesture, tense confrontation, tall wooden pillars, indoor "
        "palace hall, medium close shot",
        "zhibo",
    ),
    "SH05": (
        "interior of a court hall, a scholar advisor lowering his eyes and bowing slightly "
        "offering respectful counsel, hands clasped, wooden palace hall interior, "
        "medium close shot",
        "duangui",
    ),
}

# 同 build_scene_zhibo_suodi.py:智伯原文无直接引语,这两句索地台词是表演性补充。
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
_SHOT_BEAT_IDS = ["B001", "B_zhibo1", "B_zhibo2", "B002", "B003"]


async def _resolve_portrait(pool, minio_client, character_id: str, tmp_dir: Path) -> Path | None:
    """从 vault canonical 版本(0.1.3)取该角色 canonical_portrait 落到本地临时文件,
    作 IP-Adapter 参考图。取不到(角色没在场/没这个 role)返回 None。"""
    try:
        resolved = await asset_resolve(pool, pack_id=f"identity/{character_id}")
    except Exception as e:
        logger.warning("角色 %s 身份包解析失败,该镜头不锁脸: %s", character_id, e)
        return None
    manifest = resolved["manifest"]
    rel = next((p for p, info in manifest.files.items() if info.role == "canonical_portrait"), None)
    if rel is None:
        logger.warning("角色 %s 身份包无 canonical_portrait,该镜头不锁脸", character_id)
        return None
    data = get_blob(minio_client, bucket="vault-identity", sha256=manifest.files[rel].sha256)
    out = tmp_dir / f"ref_{character_id}.png"
    out.write_bytes(data)
    return out


async def _kenburns_clip(frame: Path, out: Path, duration: float, idx: int) -> None:
    """单帧 → 缓推 clip。奇偶镜头交替推近/拉远,避免整片一个运镜方向发木。"""
    fps = 24
    n = max(int(duration * fps), 1)
    zoom_in = idx % 2 == 0
    zexpr = "min(zoom+0.0012,1.15)" if zoom_in else "if(eq(on,0),1.15,max(zoom-0.0012,1.0))"
    await ffmpeg_run(
        args=[
            "-y",
            "-loop",
            "1",
            "-i",
            str(frame),
            "-vf",
            (
                "scale=1560:878:force_original_aspect_ratio=increase,crop=1560:878,"
                f"zoompan=z='{zexpr}':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                "s=1280x720:fps=24,format=yuv420p"
            ),
            "-t",
            str(duration),
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        expected_output=out,
    )


async def main() -> None:
    await init_vault_schema(settings.vault_database_url)
    pool = await get_vault_pg_pool()
    minio_client = get_minio_client()

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

    logger.info("C4 分镜规划...")
    immutable: dict[str, str] = {}
    for cid in scene.characters:
        try:
            r = await asset_resolve(pool, pack_id=f"identity/{cid}")
            immutable[cid] = r["manifest"].immutable_traits
        except Exception:
            immutable[cid] = ""
    shotlist = await plan_shots(
        scene,
        art_direction=_SCENE_ART_DIRECTION,
        immutable_traits_by_character=immutable,
        beat_ids=_SHOT_BEAT_IDS,
    )
    logger.info("共 %d 个镜头", len(shotlist.shots))

    # 音轨时长 → 5 镜头按 est_duration 比例配平到总时长,narration 连续覆盖画面。
    import subprocess

    audio_dur = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(_SCENE_AUDIO_SRC),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    raw = [s.est_duration_s for s in shotlist.shots]
    scale = audio_dur / sum(raw)
    durations = [d * scale for d in raw]
    logger.info("音轨 %.1fs,5 镜头配平时长: %s", audio_dur, [round(d, 1) for d in durations])

    tmp_dir = Path(tempfile.mkdtemp(prefix="zhibo_local_"))
    clips: list[Path] = []
    for i, (shot, dur) in enumerate(zip(shotlist.shots, durations, strict=True)):
        setting, lock_char = _SHOT_STAGING.get(shot.shot_id, ("", None))
        ref = None
        if lock_char is not None:
            ref = await _resolve_portrait(pool, minio_client, lock_char, tmp_dir)
        extra = {"num_inference_steps": 30, "guidance_scale": 7.0}
        if ref is not None:
            extra["ip_adapter_image"] = str(ref)
            extra["ip_adapter_weight"] = _IP_ADAPTER_WEIGHT
        frame = tmp_dir / f"{shot.shot_id}.png"
        # prompt 重排,把 setting(建筑/朝堂)顶到前段,避免被 CLIP 77-token 截掉——这是压
        # LoRA 山水偏置的关键。顺序:触发词+水墨风 → setting → 动作(中文,从 shot.prompt
        # 剥掉 art_direction 前缀取回)。
        action = shot.prompt.replace(f"{_SCENE_ART_DIRECTION}, ", "", 1)
        prompt = (
            f"QIEMANCN, Chinese ink wash painting, {setting}, {action}" if setting else shot.prompt
        )
        logger.info("[%s] lock=%s | %s", shot.shot_id, lock_char, setting[:50])
        await sdxl_local_generate(
            prompt=prompt,
            negative_prompt=_NEG,
            width=1344,
            height=768,
            output_path=frame,
            seed=1000 + i,
            extra=extra,
            timeout_s=300.0,
        )
        clip = tmp_dir / f"{shot.shot_id}.mp4"
        await _kenburns_clip(frame, clip, dur, i)
        clips.append(clip)

    # concat 5 clips
    concat_txt = tmp_dir / "concat.txt"
    concat_txt.write_text("".join(f"file '{c}'\n" for c in clips))
    silent = tmp_dir / "video_only.mp4"
    await ffmpeg_run(
        args=["-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(silent)],
        expected_output=silent,
    )
    # 复用 scene_v2 音轨
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    await ffmpeg_run(
        args=[
            "-y",
            "-i",
            str(silent),
            "-i",
            str(_SCENE_AUDIO_SRC),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(_OUTPUT),
        ],
        expected_output=_OUTPUT,
    )
    logger.info("完成 → %s", _OUTPUT)
    print(f"\n✓ 输出: {_OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
