import asyncio
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hevi.quoteimage.adapter import render_quote_image
import glob

async def run_e2e():
    out_dir = Path("output/quoteimage_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    videos = []
    
    # Run talkcraft video (script mode and native mode)
    talkcraft_videos = [
        Path("/data/soffy/projects/hevi-talkcraft/output/talkcraft_e2e/explainer/explainer_landscape.mp4"),
        Path("/data/soffy/projects/hevi-talkcraft/output/talkcraft_e2e/talking_head/talking_head_landscape.mp4")
    ]
    for p in talkcraft_videos:
        if p.exists():
            videos.append(p)
        else:
            print(f"Warning: {p} not found")

    # Run hevi-zero videos (native mode)
    hevi_zero_dir = Path("/data/soffy/projects/hevi-zero/out/shorts_clip")
    if hevi_zero_dir.exists():
        videos.extend(list(hevi_zero_dir.glob("*.mp4"))[:2])
    else:
        print(f"Warning: {hevi_zero_dir} not found")
        
    from hevi.layer4_legacy.quoteimage.omodul_impl.quality_gates import QualityGateError
    
    for i, video in enumerate(videos):
        print(f"Running {video} in script mode...")
        try:
            await render_quote_image(
                video_path=video,
                mode="script",
                strategy="auto",
                output_dir=out_dir / f"vid_{i}_script",
                font="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            )
        except QualityGateError as e:
            print(f"  Script mode quality gates failed for {video.name}: {e}")
        print(f"Running {video} in native mode...")
        try:
            await render_quote_image(
                video_path=video,
                mode="native",
                strategy="auto",
                output_dir=out_dir / f"vid_{i}_native",
                font="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            )
        except QualityGateError as e:
            print(f"  Native mode quality gates failed for {video.name}: {e}")
        
    print("E2E tests completed.")

if __name__ == "__main__":
    asyncio.run(run_e2e())
