import os
import json
import sys
from pathlib import Path

from hevi.publishkit.adapter import generate_publish_bundle

def main():
    root = Path(__file__).parent.parent
    video_dir = root / "output/talkcraft_e2e/explainer"
    
    # Try finding an mp4
    mp4s = list(video_dir.glob("*.mp4"))
    if not mp4s:
        print(f"Error: Could not find output/talkcraft_e2e/explainer video.")
        sys.exit(1)
        
    video_path = mp4s[0]
    script_path = video_dir / "shotbook.json" # using shotbook as script
    if not script_path.exists():
        script_path = video_path # fallback just so it exists
    
    output_dir = root / "output/publishkit_e2e"
    print(f"Running Publishkit E2E on {video_path} ...")
    
    res = generate_publish_bundle(
        video_path=video_path,
        script_path=script_path,
        output_dir=output_dir
    )
    
    print(f"Publish Bundle Generated:")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"Output saved to: {output_dir}")

if __name__ == "__main__":
    main()
