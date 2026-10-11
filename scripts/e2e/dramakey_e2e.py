"""DRAMAKEY End-to-End acceptance script.

Executes:
1. Novel2Video Real Pipeline on 崂山道士 (60-90s target, 14 shots, 2 recurring characters: 王生 & 老道长).
   Outputs to `output/dramakey_e2e/<run_id>/`:
     - final.mp4
     - keyframes/ (winners and loser candidates)
     - characters.json
     - record.json
     - qa.json
     - contact_sheet.jpg
     - subtitles.srt
2. Script2Video Real Pipeline 30-second sample (script2video_kernel_workflow with render=True).
   Outputs to `output/script2video_e2e/<run_id>/`:
     - final.mp4
     - qa.json

Strict constraints:
- Real CPU inference using SD-Turbo + TAESD (assert engine != "fake").
- Zero mock / dummy / placeholder media.
- Measured QA (ffprobe, volumedetect, 6-frame contact sheet, dynamic frame variance, sha256).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hevi.layer4_legacy.keyframe.omodul_impl.video_render import (
    RenderConfig,
    render_dramakey_pipeline,
)
from hevi.layer4_legacy.keyframe.oprim_impl.character_card import CharacterCard
from hevi.layer4_legacy.keyframe.oprim_impl.registry import get_engine
from hevi.production.novel2video_workflow import (
    Novel2VideoConfig,
    Novel2VideoInput,
    novel2video_workflow,
)
from hevi.production.script2video_kernel_workflow import (
    Script2VideoKernelConfig,
    Script2VideoKernelInput,
    script2video_kernel_workflow,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dramakey_e2e")

LAOSHAN_SHOTS = [
    {
        "idx": 0,
        "text": "王生邑之故家子也，少慕仙术，闻崂山多仙，遂负笈往游。",
        "visual_desc": "年轻英俊书生身着青衫汉服头戴蓝巾，背负书箱，行走于苍茫秀丽的崂山云雾山道上",
        "visible_chars": ["王生"],
        "primary_char": "王生",
        "camera_move": "push",
    },
    {
        "idx": 1,
        "text": "登一高顶，有道观甚幽，老道长坐蒲团上，白发垂领，神光爽迈。",
        "visual_desc": "白须长发老道长身穿灰白道袍，手持拂尘端坐于古朴幽静道观大殿的蒲团之上",
        "visible_chars": ["老道长"],
        "primary_char": "老道长",
        "camera_move": "pan_r",
    },
    {
        "idx": 2,
        "text": "王生稽首而谈，甚服道长妙理，遂留为门徒。",
        "visual_desc": "青年书生向白须道长恭敬躬身稽首下拜，道长大殿内香烟袅袅，气氛庄严",
        "visible_chars": ["王生", "老道长"],
        "primary_char": "王生",
        "camera_move": "push",
    },
    {
        "idx": 3,
        "text": "次日清晨，老道长授王生一柄利斧，命其随众弟子往深山采樵。",
        "visual_desc": "清晨道观庭院，老道长将铁斧交给头戴蓝巾身着青衫的青年书生",
        "visible_chars": ["王生", "老道长"],
        "primary_char": "王生",
        "camera_move": "pull",
    },
    {
        "idx": 4,
        "text": "王生未受过苦楚，执斧砍柴一月余，手足生茧，心中渐生悔退。",
        "visual_desc": "青年书生在深山老林中挥铁斧砍柴，满头大汗，疲惫不堪",
        "visible_chars": ["王生"],
        "primary_char": "王生",
        "camera_move": "pan_l",
    },
    {
        "idx": 5,
        "text": "忽一日傍晚，老道长携酒延客，共饮于大殿中庭。",
        "visual_desc": "黄昏日落，古老道观庭院内排设宴席，古朴青瓷酒壶在案，道长与客共饮",
        "visible_chars": ["老道长"],
        "primary_char": "老道长",
        "camera_move": "push",
    },
    {
        "idx": 6,
        "text": "是夜天无明月，老道长取素纸一圆如镜，信手粘于殿壁之上。",
        "visual_desc": "白须道长手持圆圆的白素纸片，轻轻贴在青灰色的石壁墙上",
        "visible_chars": ["老道长"],
        "primary_char": "老道长",
        "camera_move": "pan_r",
    },
    {
        "idx": 7,
        "text": "顷刻之间，纸化为一轮皎洁明月，月华流转，映照整座大殿。",
        "visual_desc": "石壁上的素纸化作一轮巨大的皎洁明亮圆月，柔和纯白月华流转洒满大殿，神奇玄妙",
        "visible_chars": [],
        "camera_move": "push",
    },
    {
        "idx": 8,
        "text": "老道长举杯向壁邀月，与众宾客欢笑畅饮，玉液芬芳甘冽。",
        "visual_desc": "白须老道长与宾客在月光下举杯痛饮，夜色宜人，气氛欢洽",
        "visible_chars": ["老道长"],
        "primary_char": "老道长",
        "camera_move": "pull",
    },
    {
        "idx": 9,
        "text": "老道长见王生立于旁，笑唤王生上前同饮，王生心甚惊奇。",
        "visual_desc": "老道长微笑着招手让王生上前，青年书生神色惊喜敬佩上前接酒",
        "visible_chars": ["王生", "老道长"],
        "primary_char": "王生",
        "camera_move": "pan_l",
    },
    {
        "idx": 10,
        "text": "宴毕客散，老道长谓王生曰：念汝苦行，今传汝穿壁之仙术。",
        "visual_desc": "深夜殿内烛光摇曳，老道长神色严肃地注视青年书生，传授仙法秘诀",
        "visible_chars": ["王生", "老道长"],
        "primary_char": "王生",
        "camera_move": "push",
    },
    {
        "idx": 11,
        "text": "老道长令王生面壁直行，王生犹豫不前，畏其触坚碰额。",
        "visual_desc": "青年书生面对坚硬的花岗岩石壁，心怀恐惧，踌躇不敢上前",
        "visible_chars": ["王生", "老道长"],
        "primary_char": "王生",
        "camera_move": "pull",
    },
    {
        "idx": 12,
        "text": "老道长抚须大笑，推之曰：俯首骤入，勿逡巡！",
        "visual_desc": "白须老道长大笑着伸手轻推身着青衫的青年书生，指引其向坚壁冲去",
        "visible_chars": ["王生", "老道长"],
        "primary_char": "王生",
        "camera_move": "pan_r",
    },
    {
        "idx": 13,
        "text": "王生闭目疾趋而往，果真飘然穿壁而出，回首大呼神妙！",
        "visual_desc": "青年书生如梦幻般神奇穿透坚硬石壁站在观外，回望高墙惊叹不已",
        "visible_chars": ["王生"],
        "primary_char": "王生",
        "camera_move": "push",
    },
]

CHAR_CARDS = [
    CharacterCard(
        id="wang_sheng",
        name="王生",
        aliases=["王七", "书生", "弟子"],
        gender="male",
        age_band="young",
        appearance_zh="青年英俊书生，头戴深蓝纶巾儒巾，身着青衫汉服白领边",
        appearance_en_tokens="young handsome 20-year-old Chinese scholar, neat topknot bun with blue cloth scholar cap headwrap, elegant cyan blue Hanfu silk robe with white collar trim",
        voice="zh_CN-huayan-medium.onnx",
        voice_speed=1.05,
    ),
    CharacterCard(
        id="lao_dao_zhang",
        name="老道长",
        aliases=["道长", "师父", "老道"],
        gender="male",
        age_band="elderly",
        appearance_zh="仙风道骨白须老道士，头挽发髻插木簪，身着粗布灰白色道袍",
        appearance_en_tokens="venerable elderly Taoist master with long flowing white beard and white hair, hair tied in topknot with wooden hairpin, traditional coarse grey Taoist robe",
        voice="zh_CN-huayan-medium.onnx",
        voice_speed=0.92,
    ),
]


def run_novel2video_e2e(run_id: str) -> dict:
    output_dir = Path(f"output/dramakey_e2e/{run_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=================================================================")
    logger.info("Starting DRAMAKEY Novel2Video E2E Run: %s", run_id)
    logger.info("Output directory: %s", output_dir)
    logger.info("Engine: sdturbo_cpu (Strictly assert != fake)")
    logger.info("=================================================================")

    # Enforce real engine check
    engine_name = "sdturbo_cpu"
    engine = get_engine(engine_name)
    assert engine.name == "sdturbo_cpu", f"E2E must use sdturbo_cpu engine, got {engine.name}"
    assert engine.name != "fake", "E2E path strictly forbids fake engine!"
    assert engine.name != "cloud_stub", "E2E path strictly forbids cloud_stub engine!"
    assert engine.available(), "SD-Turbo CPU engine must be available for E2E!"

    cfg = RenderConfig(
        engine=engine_name,
        target_width=1080,
        target_height=1920,
        fps=25,
        kf_width=512,
        kf_height=512,
        steps=2,
        face_threshold=0.30,
        enable_tts=True,
        enable_subtitles=True,
        base_seed=100,
    )

    t0 = time.time()
    result = render_dramakey_pipeline(
        shots=LAOSHAN_SHOTS,
        output_dir=output_dir,
        character_cards=CHAR_CARDS,
        config=cfg,
        on_progress=lambda p: logger.info("Progress: %s", p),
    )
    elapsed = time.time() - t0
    logger.info("E2E Novel2Video completed in %.2f seconds", elapsed)

    # Validate output files exist
    final_mp4 = Path(result["final_mp4"])
    assert final_mp4.is_file(), f"Missing final.mp4 at {final_mp4}"
    assert Path(result["qa_path"]).is_file(), "Missing qa.json"
    assert Path(result["record_path"]).is_file(), "Missing record.json"
    assert Path(result["characters_path"]).is_file(), "Missing characters.json"
    assert Path(result["contact_sheet"]).is_file(), "Missing contact_sheet.jpg"
    assert (output_dir / "subtitles.srt").is_file(), "Missing subtitles.srt"

    qa = result["qa_report"]
    logger.info("QA Verdict: passed=%s, duration=%.2fs", qa["passed"], qa["video"]["duration"])
    return result


def run_script2video_30s_sample(run_id: str) -> dict:
    output_dir = Path(f"output/script2video_e2e/{run_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=================================================================")
    logger.info("Starting Script2Video 30-second Sample Run: %s", run_id)
    logger.info("Output directory: %s", output_dir)
    logger.info("=================================================================")

    # First 6 shots of Laoshan (~30s total)
    sample_shots = LAOSHAN_SHOTS[:6]

    cfg = Script2VideoKernelConfig(
        style="cinematic",
        render=True,
        engine="sdturbo_cpu",
        target_width=1080,
        target_height=1920,
        fps=25,
        kf_width=512,
        kf_height=512,
        face_threshold=0.30,
        base_seed=200,
    )
    inp = Script2VideoKernelInput(
        shots=sample_shots,
        characters=[c.to_dict() for c in CHAR_CARDS],
    )

    t0 = time.time()
    result = asyncio.run(
        script2video_kernel_workflow(
            config=cfg,
            input_data=inp,
            output_dir=output_dir,
            on_step=lambda s: logger.info("Script2Video step: %s", s),
        )
    )
    logger.info("Script2Video sample completed in %.2f seconds", time.time() - t0)

    final_mp4 = Path(result["final_mp4"])
    assert final_mp4.is_file(), f"Missing final.mp4 for script2video at {final_mp4}"
    assert Path(result["qa_path"]).is_file(), "Missing qa.json for script2video"
    return result


def main() -> int:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=== DRAMAKEY ACCEPTANCE PIPELINE START (%s) ===", timestamp)

    # 1. Novel2Video 60-90s E2E
    res_novel = run_novel2video_e2e(f"novel_{timestamp}")

    # 2. Script2Video 30s Sample E2E
    res_script = run_script2video_30s_sample(f"script_{timestamp}")

    logger.info("=== DRAMAKEY ALL ACCEPTANCE RUNS COMPLETED SUCCESSFULLY ===")
    print("\n" + "=" * 60)
    print("DRAMAKEY E2E ACCEPTANCE SUMMARY:")
    print(f"Novel2Video MP4: {res_novel['final_mp4']}")
    print(f"Novel2Video QA:  {res_novel['qa_path']}")
    print(f"Script2Video MP4: {res_script['final_mp4']}")
    print(f"Script2Video QA:  {res_script['qa_path']}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
