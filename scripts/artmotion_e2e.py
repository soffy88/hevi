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
        NarrationSegment(id="1", role="explainer", sentences=("这段是一句非常长非常长的测试口播。", "我们看看它能不能成功生成出超过二十秒钟的片段。", "代码画的艺术风格真的很有趣，解说动画语法也很强大。", "不仅如此，这个系统的分层架构也非常清晰。")),
        NarrationSegment(id="2", role="explainer", sentences=("这是第二段解说。", "在这段里我们再多说一点点，让它足够撑起至少二十秒的时长。", "其实只要语速慢一点，或者多加几句有深度的解说，凑够三十秒也是轻而易举的。")),
        NarrationSegment(id="3", role="explainer", sentences=("最后再补充一些细节说明。", "为了确保单元测试和端到端测试都能稳定通过，产物还需要经过严格的门禁检查。", "而且在这个过程中，本地渲染不会调用任何外部付费API，完全实现了零成本本地生成。"))
    ]
    storyboard_data = {
        "topic": "test",
        "segments": [
            {"id": s.id, "sceneType": s.role, "narration": " ".join(s.sentences)}
            for s in segments
        ]
    }
    
    for i, (grammar, theme, aspect, desc) in enumerate(tasks):
        print(f"Running {desc}...")
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
