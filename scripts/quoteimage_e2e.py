import asyncio
from pathlib import Path
from hevi.quoteimage.adapter import render_quote_image
import glob

async def run_e2e():
    out_dir = Path("output/quoteimage_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    videos = []
    
    # Run talkcraft video (script mode)
    talkcraft_videos = list(Path(".").glob("**/talkcraft_e2e/*.mp4"))
    if talkcraft_videos:
        videos.extend(talkcraft_videos)
    else:
        print("Warning: talkcraft_e2e mp4 not found")

    # Run hevi-zero videos (native mode)
    hevi_zero_dir = Path("/data/soffy/projects/hevi-zero/out/shorts_clip")
    if hevi_zero_dir.exists():
        videos.extend(list(hevi_zero_dir.glob("*.mp4"))[:2])
    else:
        print(f"Warning: {hevi_zero_dir} not found")
        
    for i, video in enumerate(videos):
        print(f"Running {video} in script mode...")
        await render_quote_image(
            video_path=video,
            mode="script",
            strategy="auto",
            output_dir=out_dir / f"vid_{i}_script",
            font="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        )
        print(f"Running {video} in native mode...")
        await render_quote_image(
            video_path=video,
            mode="native",
            strategy="auto",
            output_dir=out_dir / f"vid_{i}_native",
            font="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        )
        
    print("E2E tests completed.")

if __name__ == "__main__":
    asyncio.run(run_e2e())
