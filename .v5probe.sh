#!/bin/bash
IN=/data/soffy/projects/hevi/.veya/worktrees/task-remote-7739211f2d800c159860/.v5inputs
for f in nasa_accretion nasa_binary nasa_orrery; do
  echo "===== $f ====="
  ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,codec_type,width,height,r_frame_rate -of default=noprint_wrappers=1 "$IN/$f.webm"
done
echo "===== audio ====="
ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,sample_rate,channels -of default=noprint_wrappers=1 "$IN/tts_master.wav"
echo "===== filters ====="
ffmpeg -hide_banner -filters 2>/dev/null | grep -E "subtitles|drawtext|scale |crop |setpts" | head
echo "===== fonts ====="
fc-list 2>/dev/null | grep -iE "cjk|noto|wqy|han" | head -5
echo "===== done ====="
