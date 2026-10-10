import sys
from pathlib import Path

def main():
    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root))
    
    from hevi.layer4_legacy.whiteboard.omodul_impl.produce import produce_whiteboard
    
    storyboard = {
        "topic": "什么是白板讲解",
        "segments": [
            {
                "sceneType": "intro",
                "narration": "今天我们要给大家介绍什么是白板讲解视频。| 这种视频的好处是通俗易懂，特别适合解释复杂的概念。| 让你一看就明白！",
                "keywords": ["白板讲解", "通俗易懂"]
            },
            {
                "sceneType": "body",
                "narration": "它通常使用手绘风格的元素。| 配合清晰的配音。| 能够很好的抓住观众的注意力。| 那么如何制作呢？",
                "keywords": ["手绘风格", "清晰配音"]
            },
            {
                "sceneType": "outro",
                "narration": "其实非常简单，只需要几行代码，就可以自动生成。| 如果你对自动生成视频感兴趣，欢迎在评论区留言！",
                "keywords": ["自动生成", "评论区见"]
            }
        ]
    }
    
    output_dir = root / "output/whiteboard_e2e"
    print("Running Whiteboard E2E...")
    res = produce_whiteboard(storyboard, output_dir, {})
    print(f"Whiteboard E2E completed. Output in {output_dir}")
    print(res)

if __name__ == "__main__":
    main()
