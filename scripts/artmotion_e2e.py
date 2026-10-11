import asyncio
from pathlib import Path
from hevi.layer4_legacy.talkcraft.oprim_impl.sync import NarrationSegment
from hevi.artmotion.adapter import render_storyboard_artmotion

async def main():
    out_dir = Path("output/artmotion_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    tasks = [
        ("t1_3b1b", "snow", "16:9", "16:9 + 3b1b + snow"),
        ("y5_kinetic_type", "ink", "9:16", "9:16 + kinetic_type + 17_ink"),
        ("t3_finance_chart", "navy", "16:9", "16:9 + finance_chart + navy"),
    ]
    
    segments = [
        NarrationSegment(id="1", role="explainer", sentences=("这段是一句非常长的测试口播。", "我们看看它能不能生成超过二十秒的片段。")),
        NarrationSegment(id="2", role="explainer", sentences=("在这段里多加两句。", "凑够二十秒钟的时长是很容易的。")),
        NarrationSegment(id="3", role="explainer", sentences=("最后再补充一些说明，确保产物能过门禁检查。"))
    ]
    for i, (grammar, theme, aspect, desc) in enumerate(tasks):
        print(f"Running {desc}...")
        
        cues_block = []
        data_block = {}
        if grammar == "t1_3b1b":
            cues_block = [
                {"kind": "line", "data": {"values": [9, 5.8, 3.4, 1.8], "color": "BLUE_C"}},
                {"kind": "equation", "data": {"tokens": [{"s": "L"}, {"s": "(θ)"}]}},
                {"kind": "equation", "data": {"tokens": [{"s": "θ"}, {"s": "←"}]}},
                {"kind": "point"},
                {"kind": "line", "data": {"values": [9, 6.2, 4.4, 3.2], "color": "TEAL_C"}},
                {"kind": "highlight", "data": {"target": "equation"}}
            ]
        elif grammar == "y5_kinetic_type":
            cues_block = [
                {"kind": "number", "data": {"value": 3000, "suffix": " 行"}},
                {"kind": "point", "data": {"label": "从前", "key": "一行"}},
                {"kind": "point", "data": {"label": "现在", "key": "整件事"}},
                {"kind": "highlight", "data": {"word": "代理"}}
            ]
        elif grammar == "t3_finance_chart":
            data_block = {
                "title": "测试图表", "unit": "测试单位", "source": "测试来源", "chart": "bar", "decimals": 1,
                "series": [
                    { "label": "A", "value": 10 }, { "label": "B", "value": 20 },
                    { "label": "C", "value": 30 }, { "label": "D", "value": 40 }
                ],
                "highlight": { "index": 3, "text": "最高", "sub": "40" }
            }
            cues_block = [
                {"kind": "bar", "data": {"index": [0, 1]}},
                {"kind": "bar", "data": {"index": 2}},
                {"kind": "bar", "data": {"index": 3}},
                {"kind": "highlight"}
            ]

        sb_segments = []
        for j, s in enumerate(segments):
            seg_dict = {"id": s.id, "sceneType": s.role, "narration": " ".join(s.sentences), "props": {}}
            if j == 0:
                seg_dict["props"] = {"cues": cues_block, "data": data_block}
            sb_segments.append(seg_dict)
            
        storyboard_data = {
            "topic": "test",
            "segments": sb_segments
        }
        
        task_out = out_dir / f"task_{i}"
        task_out.mkdir(parents=True, exist_ok=True)
        config = {
            "style_id": theme,
            "grammar_id": grammar,
            "aspect_ratio": aspect,
            "language": "zh",
        }
        res = await render_storyboard_artmotion(storyboard_data, task_out, config)
        print(f"Done! {res}")

if __name__ == "__main__":
    asyncio.run(main())
