import json, subprocess, os, sys
from pathlib import Path
sys.path.insert(0, "/data/soffy/projects/hevi-storyplan")
from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.take_select import select_best_take, TakeCandidate

# 1) determinism of autofill for non-preset topic (hash randomization?)
p = autofill_story_plan("小猫学数数", aspect="16:9")
print("AUTOFILL_NONPRESET_NARRATION=", p.narration_text[:40])
print("HOOK=", p.narrative.hook.text)

# 2) take_select on real videos: frozen vs motion
d = Path(".tmp/vfy"); d.mkdir(parents=True, exist_ok=True)
frozen = d/"frozen.mp4"; motion = d/"motion.mp4"
if not frozen.exists():
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","color=c=blue:s=320x240:d=5","-r","30","-c:v","libx264","-pix_fmt","yuv420p",str(frozen)],check=True,capture_output=True)
if not motion.exists():
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","testsrc=s=320x240:d=5","-r","30","-c:v","libx264","-pix_fmt","yuv420p",str(motion)],check=True,capture_output=True)
best, allr = select_best_take([
    TakeCandidate(take_id="t_frozen", video_path=str(frozen), duration_sec=5.0),
    TakeCandidate(take_id="t_motion", video_path=str(motion), duration_sec=5.0),
], "动作完整到达结束状态", target_duration_sec=5.0)
scores = {r.take_id: (r.score, r.motion_completeness, r.stability) for r in allr}
print("REAL_VIDEO_SCORES=", json.dumps(scores, ensure_ascii=False))
print("BEST=", best.take_id)
print("DISCRIMINATES=", scores["t_frozen"][0] != scores["t_motion"][0])
