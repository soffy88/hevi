set -e
export PATH=/home/soffy/.local/bin:$PATH
D=/tmp/vfy_omq; mkdir -p $D; cd $D
B=/data/soffy/projects/hevi-quoteimage/artifacts/real_video/20261005T160434Z/artifacts/nasa-collins-0001_finecut.mp4
ffprobe -v error -show_entries format=duration:stream=codec_type,width,height -of compact $B
# trim base to 14s 1280x720 for speed
ffmpeg -nostdin -hide_banner -y -loglevel error -i $B -t 14 -vf scale=1280:720,fps=24 -c:v libx264 -preset veryfast -crf 20 -c:a aac -ar 44100 -ac 2 base.mp4
E="-c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac"
# 1 full random noise video + real audio
ffmpeg -nostdin -y -loglevel error -f lavfi -i "nullsrc=s=1280x720:r=24:d=14" -i base.mp4 -map 0:v -map 1:a -vf "geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'" $E -shortest bad1_noise_full.mp4
# 2 local glitch 4-7s
ffmpeg -nostdin -y -loglevel error -i base.mp4 -f lavfi -i "nullsrc=s=1280x720:r=24:d=14" -filter_complex "[1:v]geq=lum='random(1)*255':cb='random(2)*255':cr='random(3)*255'[n];[0:v][n]overlay=enable='between(t,4,7)'[v]" -map "[v]" -map 0:a $E bad2_glitch_local.mp4
# 3 macroblock: qp 51 low bitrate
ffmpeg -nostdin -y -loglevel error -i base.mp4 -c:v libx264 -preset veryfast -qp 51 -pix_fmt yuv420p -c:a copy bad3_macroblock_qp51.mp4
# 3b macroblock: mpeg2 qscale 31 at low res upscaled
ffmpeg -nostdin -y -loglevel error -i base.mp4 -vf scale=320:180 -c:v mpeg2video -qscale:v 31 -an -f mpeg2video tmp_lq.m2v
ffmpeg -nostdin -y -loglevel error -i tmp_lq.m2v -i base.mp4 -map 0:v -map 1:a -vf scale=1280:720:flags=neighbor $E bad3b_macroblock_mpeg2.mp4
# 4 green screen (decoder-failure green Y=0,U=0,V=0) with real audio
ffmpeg -nostdin -y -loglevel error -f lavfi -i "nullsrc=s=1280x720:r=24:d=14" -i base.mp4 -map 0:v -map 1:a -vf "geq=lum=0:cb=0:cr=0" $E -shortest bad4_green.mp4
# 4b green flash 2s in normal clip
ffmpeg -nostdin -y -loglevel error -i base.mp4 -vf "drawbox=x=0:y=0:w=iw:h=ih:color=0x00FF00:t=fill:enable='between(t,6,9)'" $E bad4b_green_local.mp4
# 5 bottom half gray
ffmpeg -nostdin -y -loglevel error -i base.mp4 -vf "drawbox=x=0:y=ih/2:w=iw:h=ih/2:color=0x808080:t=fill" $E bad5_halfgray_bottom.mp4
# 6 black + silent
ffmpeg -nostdin -y -loglevel error -f lavfi -i "color=c=black:s=1280x720:r=24:d=14" -f lavfi -i "anullsrc=r=44100:cl=stereo" -t 14 $E bad6_black_silent.mp4
# 7 audio silence gap 3-11s
ffmpeg -nostdin -y -loglevel error -i base.mp4 -c:v copy -af "volume=enable='between(t,3,11)':volume=0" -c:a aac bad7_audio_silence_gap.mp4
# 8 audio pops/clipping: +40dB clip 5-8s plus clicks
ffmpeg -nostdin -y -loglevel error -i base.mp4 -c:v copy -af "volume=enable='between(t,5,8)':volume=40dB,alimiter=limit=1:level=false" -c:a aac bad8_audio_clip.mp4
ffmpeg -nostdin -y -loglevel error -i base.mp4 -f lavfi -t 14 -i "aevalsrc='if(lt(mod(t,0.5),0.004),0.99*sgn(sin(2*PI*900*t)),0)':s=44100:c=stereo" -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0[a]" -map 0:v -map "[a]" -c:v copy -c:a aac bad8b_audio_pops.mp4
rm -f tmp_lq.m2v
for f in *.mp4; do echo "$f $(ffprobe -v error -show_entries format=duration -of csv=p=0 $f) $(sha256sum $f|cut -c1-12)"; done
