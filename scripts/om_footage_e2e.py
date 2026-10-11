import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
from pathlib import Path
from hevi.studio.fulfill import fulfill_order
import logging
import os

logging.basicConfig(level=logging.INFO)

async def main():
    out_dir = Path("output/om_footage_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Chinese narration with piper (60 seconds)
    order1 = {
        "line_id": "documentary_montage",
        "target": "explainer",
        "slate_id": "om_footage_e2e_piper",
        "topic": "The history of space exploration and Apollo program.",
        "tts_engine": "piper",
        "voice": "zh",
        "script_lines": [
            {"text": "在人类探索宇宙的漫长历史中，每一次升空都承载着梦想。", "duration_s": 6},
            {"text": "巨大的火箭在轰鸣声中拔地而起，震撼了整个世界。", "duration_s": 6},
            {"text": "阿波罗计划更是人类航天史上一座不可逾越的丰碑。", "duration_s": 6},
            {"text": "宇航员们穿戴着厚重的宇航服，踏上了未知的星际旅程。", "duration_s": 6},
            {"text": "他们在月球上留下的第一个脚印，象征着跨时代的一步。", "duration_s": 6},
            {"text": "深邃的宇宙中，地球看起来就像一颗脆弱而美丽的蓝色弹珠。", "duration_s": 6},
            {"text": "无数科学家在控制中心夜以继日，确保任务万无一失。", "duration_s": 6},
            {"text": "那些珍贵的黑白影像，永远记录下了探索者的勇气。", "duration_s": 6},
            {"text": "今天，我们依然在仰望星空，渴望飞向更遥远的火星。", "duration_s": 6},
            {"text": "因为对于未知的渴望，是人类文明不断前行的永恒动力。", "duration_s": 6}
        ]
    }
    
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
    
    print("Executing pure music montage...")
    res2 = await fulfill_order(order2, execute=True, output_dir=out_dir / "music", render=True)
    print("Result 2:", json.dumps(res2, indent=2))
    video2 = res2.get("result_video_path")
    
    sys.path.insert(0, "/data/soffy/projects/hevi-zero")
    try:
        from zl import contact_sheet
        if video1 and os.path.exists(video1):
            contact_sheet(video1, str(out_dir / "piper" / "contact_sheet.jpg"))
        if video2 and os.path.exists(video2):
            contact_sheet(video2, str(out_dir / "music" / "contact_sheet.jpg"))
    except ImportError:
        pass
    
if __name__ == "__main__":
    os.environ["HEVI_CORPUS_DIR"] = "/data/soffy/projects/hevi-omfootage/data/corpus"
    asyncio.run(main())
