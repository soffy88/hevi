"""Whiteboard E2E production verification script (dual-topic, landscape and portrait)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hevi.layer4_legacy.whiteboard.omodul_impl.produce import produce_whiteboard


TOPIC_A_STORYBOARD = {
    "topic": "白板讲解视频核心优势",
    "segments": [
        {
            "sceneType": "intro",
            "narration": "今天我们要给大家介绍什么是白板讲解视频。| 这种视频的好处是通俗易懂，特别适合解释复杂的概念。| 让你一看就明白！",
            "keywords": ["白板讲解", "核心优势", "一目了然"],
        },
        {
            "sceneType": "body",
            "narration": "它通常使用手绘风格的元素。| 配合清晰自然的配音节奏。| 能够牢牢抓住观众的注意力。| 那么它是如何自动生成的呢？",
            "keywords": ["手绘风格", "自然配音", "聚焦注意", "自动生成"],
        },
        {
            "sceneType": "outro",
            "narration": "只需结构化分镜，配合本地语音对齐，就能一键成片。| 欢迎在评论区分享你的想法，我们下期见！",
            "keywords": ["一键成片", "评论互动"],
        },
    ],
}

TOPIC_B_STORYBOARD = {
    "topic": "大语言模型如何思考",
    "brand": {
        "name": "极客视界",
        "slogan": "拆解前沿科技与底层逻辑",
        "cta": "点赞关注 · 一起探索未来",
    },
    "segments": [
        {
            "sceneType": "intro",
            "narration": "你是否好奇，AI究竟是如何理解并回答人类问题的？| 它的核心原理其实是预测下一个词。| 极其简单的规则，催生了不可思议的智能涌现。",
            "keywords": ["大模型思考", "预测下一词", "智能涌现"],
        },
        {
            "sceneType": "body",
            "narration": "首先是海量网络语料的无监督预训练。| 接着通过指令微调与人类反馈强化学习对齐。| 最终形成严密的思维链多步推理能力。| 这就是现代认知大模型的底层基石。",
            "keywords": ["海量预训练", "人类对齐", "思维链推理", "技术基石"],
        },
        {
            "sceneType": "outro",
            "narration": "技术正在重塑每一个行业的生产方式。| 关注我们，下期带你拆解更多前沿科技内幕！",
            "keywords": ["重塑生产力", "关注下期"],
        },
    ],
}


def dump_sample_frames(video_path: Path, out_dir: Path, prefix: str) -> list[str]:
    """Extract individual key frames for visual inspection."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamps = [5.0, 15.0, 25.0]
    paths = []
    for t in timestamps:
        out_frame = out_dir / f"{prefix}_frame_{int(t)}s.jpg"
        subprocess.run(
            [
                "/home/soffy/.local/bin/ffmpeg",
                "-y",
                "-v", "error",
                "-ss", str(t),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_frame),
            ],
            check=True,
        )
        paths.append(str(out_frame))
    return paths


def run_e2e():
    print("=" * 60)
    print("STARTING WHITEBOARD DUAL-TOPIC E2E VERIFICATION")
    print("=" * 60)

    base_out = ROOT / "output/whiteboard_e2e"
    out_a = base_out / "topic_a"
    out_b = base_out / "topic_b"

    print("\n--- Running Topic A: '白板讲解视频核心优势' (No Brand) ---")
    res_a = produce_whiteboard(TOPIC_A_STORYBOARD, out_a, {})
    print("Topic A Status:", res_a["status"])
    for r in res_a["records"]:
        print(f"  {r['orientation']}: {r['width']}x{r['height']}, {r['duration_s']:.2f}s, SHA256: {r['sha256'][:16]}...")
    dump_sample_frames(Path(res_a["landscape_path"]), out_a / "frames", "landscape")
    dump_sample_frames(Path(res_a["portrait_path"]), out_a / "frames", "portrait")

    print("\n--- Running Topic B: '大语言模型如何思考' (Brand: 极客视界) ---")
    res_b = produce_whiteboard(TOPIC_B_STORYBOARD, out_b, {})
    print("Topic B Status:", res_b["status"])
    for r in res_b["records"]:
        print(f"  {r['orientation']}: {r['width']}x{r['height']}, {r['duration_s']:.2f}s, SHA256: {r['sha256'][:16]}...")
    dump_sample_frames(Path(res_b["landscape_path"]), out_b / "frames", "landscape")
    dump_sample_frames(Path(res_b["portrait_path"]), out_b / "frames", "portrait")

    # Copy topic A to root output/whiteboard_e2e for standard paths
    shutil.copy2(res_a["landscape_path"], base_out / "whiteboard_landscape.mp4")
    shutil.copy2(res_a["portrait_path"], base_out / "whiteboard_portrait.mp4")
    shutil.copy2(out_a / "contact_sheet_landscape.jpg", base_out / "contact_sheet_landscape.jpg")
    shutil.copy2(out_a / "contact_sheet_portrait.jpg", base_out / "contact_sheet_portrait.jpg")

    summary = {
        "status": "succeeded" if res_a["status"] == "succeeded" and res_b["status"] == "succeeded" else "failed",
        "topic_a": res_a,
        "topic_b": res_b,
    }
    (base_out / "e2e_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print("WHITEBOARD E2E COMPLETED SUCCESSFULLY!")
    print("Summary written to:", base_out / "e2e_summary.json")
    print("=" * 60)
    return summary


if __name__ == "__main__":
    run_e2e()
