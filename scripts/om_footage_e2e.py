import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hevi.studio.fulfill import fulfill_order

logging.basicConfig(level=logging.INFO)

async def main():
    out_dir = Path("output/om_footage_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Chinese narration with piper (60-90 seconds) + research
    order1 = {
        "line_id": "documentary_montage",
        "target": "explainer",
        "slate_id": "om_footage_e2e_piper",
        "topic": "The history of space exploration and Apollo program.",
        "tts_engine": "piper",
        "voice": "zh",
        "do_research": True,
        "script_lines": [
            {"text": "在人类探索浩瀚宇宙的漫长历史长河中，每一次火箭升空都承载着全人类的科学梦想与非凡勇气。", "duration_s": 8, "visual_search_query": "rocket launch space exploration"},
            {"text": "巨大的土星五号火箭在轰鸣声中拔地而起，炽热的烈焰与翻滚的浓烟瞬间震撼了整个世界。", "duration_s": 8, "visual_search_query": "saturn v rocket blastoff"},
            {"text": "阿波罗登月计划更是人类现代航天史上的一座不可逾越的丰碑，彻底开启了行星际探索的新纪元。", "duration_s": 8, "visual_search_query": "apollo space mission spacecraft"},
            {"text": "宇航员们穿戴着厚重的白色宇航服，神情坚定地迈向发射架，踏上了未知的深空星际旅程。", "duration_s": 8, "visual_search_query": "astronaut spacewalk space helmet"},
            {"text": "当阿姆斯特朗在月球静海基地留下了第一个脚印时，这象征着人类文明跨越时代的巨大飞跃。", "duration_s": 8, "visual_search_query": "lunar surface moon landing footstep"},
            {"text": "从几十万公里外的深邃太空中回望故乡，我们的地球看起来就像一颗脆弱而瑰丽的蓝色弹珠。", "duration_s": 8, "visual_search_query": "earth from space blue marble"},
            {"text": "地面控制中心的科学家与工程师们夜以继日，用无与伦比的严谨与智慧确保每一次任务的万无一失。", "duration_s": 8, "visual_search_query": "nasa mission control center engineers"},
            {"text": "那些泛黄而珍贵的胶片档案影像，永远定格了那个时代探索者们无畏险阻、开拓进取的崇高精神。", "duration_s": 8, "visual_search_query": "vintage space exploration archive footage"},
            {"text": "今天，我们依然在仰望璀璨星空，向着更深远的火星与外太阳系深空探测任务不断奋勇前行。", "duration_s": 8, "visual_search_query": "mars rover surface deep space"},
            {"text": "因为对于宇宙终极未知的无尽渴望与追寻，正是人类文明历经万难依然不断前行的永恒精神动力。", "duration_s": 8, "visual_search_query": "galaxy stars nebula universe"}
        ]
    }
    
    run_piper = "--music" not in sys.argv
    run_music = "--piper" not in sys.argv

    video1 = None
    if run_piper:
        print("Executing piper narration montage...")
        res1 = await fulfill_order(order1, execute=True, output_dir=out_dir / "piper", render=True)
        print("Result 1:", json.dumps(res1, indent=2))
        video1 = res1.get("result_video_path")
    
    # 2. Pure music, no narration (60 seconds)
    order2 = {
        "line_id": "documentary_montage",
        "target": "explainer",
        "slate_id": "om_footage_e2e_music",
        "topic": "Beautiful natural landscapes and wildlife.",
        "tts_engine": "piper",
        "script_lines": [
            {"text": " ", "duration_s": 6, "visual_search_query": "forest landscape aerial view"},
            {"text": " ", "duration_s": 6, "visual_search_query": "wild animals in nature savanna"},
            {"text": " ", "duration_s": 6, "visual_search_query": "ocean waves crashing on the beach"},
            {"text": " ", "duration_s": 6, "visual_search_query": "sunset over the snow mountains"},
            {"text": " ", "duration_s": 6, "visual_search_query": "birds flying in the blue sky"},
            {"text": " ", "duration_s": 6, "visual_search_query": "macro photography of a flower"},
            {"text": " ", "duration_s": 6, "visual_search_query": "river flowing through a green valley"},
            {"text": " ", "duration_s": 6, "visual_search_query": "stars moving in the night sky time lapse"},
            {"text": " ", "duration_s": 6, "visual_search_query": "desert dunes blown by wind"},
            {"text": " ", "duration_s": 6, "visual_search_query": "beautiful sunrise landscape"}
        ]
    }
    
    video2 = None
    if run_music:
        print("Executing pure music montage...")
        res2 = await fulfill_order(order2, execute=True, output_dir=out_dir / "music", render=True)
        print("Result 2:", json.dumps(res2, indent=2))
        video2 = res2.get("result_video_path")
    
    sys.path.insert(0, "/data/soffy/projects/hevi-zero")
    try:
        from zl import contact_sheet
        if video1 and os.path.exists(video1):
            contact_sheet(video1, str(out_dir / "piper" / "contact_sheet.jpg"))
            if os.path.exists(out_dir / "piper" / "landscape.mp4"):
                contact_sheet(str(out_dir / "piper" / "landscape.mp4"), str(out_dir / "piper" / "contact_sheet_landscape.jpg"))
        if video2 and os.path.exists(video2):
            contact_sheet(video2, str(out_dir / "music" / "contact_sheet.jpg"))
            if os.path.exists(out_dir / "music" / "landscape.mp4"):
                contact_sheet(str(out_dir / "music" / "landscape.mp4"), str(out_dir / "music" / "contact_sheet_landscape.jpg"))
    except ImportError:
        pass
    
if __name__ == "__main__":
    os.environ["HEVI_CORPUS_DIR"] = "/data/soffy/projects/hevi-omfootage/data/corpus"
    asyncio.run(main())
