"""R3: render whip (testsrc2->smptehdbars, 1s transition) and dump 0/25/50/75/100% frames as PNG for eyeballing."""
import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/data/soffy/projects/hevi-xfadepack")
from hevi.assembly.assembler import build_xfade_chain
FFMPEG="ffmpeg"; W,H,FPS,D,CLIP=320,240,30,1.0,2.0
def run(c):
    r=subprocess.run(c,capture_output=True)
    if r.returncode: print(r.stderr.decode()[-400:]); sys.exit(1)
tmp=Path(tempfile.mkdtemp()); out=tmp/"out.mp4"
a=tmp/"A.mp4"; b=tmp/"B.mp4"
run([FFMPEG,"-y","-f","lavfi","-i",f"testsrc2=duration={CLIP}:size={W}x{H}:rate={FPS}","-pix_fmt","yuv420p",str(a)])
run([FFMPEG,"-y","-f","lavfi","-i",f"smptehdbars=duration={CLIP}:size={W}x{H}:rate={FPS}","-pix_fmt","yuv420p",str(b)])
fc,label,_=build_xfade_chain([CLIP,CLIP],["whip"],D)
run([FFMPEG,"-y","-i",str(a),"-i",str(b),"-filter_complex",fc,"-map",label,"-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p",str(out)])
off=int((CLIP-D)*FPS)  # 30
idxs={0:off,25:off+round(0.25*D*FPS),50:off+round(0.5*D*FPS),75:off+round(0.75*D*FPS),100:off+int(D*FPS)}
dest=Path("/data/soffy/projects/hevi-xfadepack/output/r3_whip")
dest.mkdir(parents=True,exist_ok=True)
for pct,f in idxs.items():
    p=dest/f"whip_{pct}.png"
    run([FFMPEG,"-y","-i",str(out),"-vf",f"select=eq(n\,{f})","-frames:v","1",str(p)])
    print(p, p.stat().st_size)
