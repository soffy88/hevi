#!/usr/bin/env bash
# 启动赛博小雅直播：抖音弹幕 -> 本地 LLM/TTS/半身口型 -> mediamtx 中继 -> OBS
# 用法: scripts/live_xiaoya.sh <抖音直播间号>   （live.douyin.com/<号>；不填则只收本地 HTTP 弹幕）
set -e
cd "$(dirname "$0")/.."
FF=$(command -v ffmpeg || echo /home/soffy/.local/bin/ffmpeg)
M=$HOME/.local/share/mediamtx
systemctl --user is-active --quiet hevi-live-relay || systemd-run --user --unit=hevi-live-relay -p Restart=always "$M/mediamtx" "$M/hevi-live.yml"
systemctl --user stop hevi-live-xiaoya 2>/dev/null || true; systemctl --user reset-failed hevi-live-xiaoya 2>/dev/null || true
ARGS=(); [ -n "$1" ] && ARGS=(--douyin "$1")
mkdir -p audit/live_host/stream
systemd-run --user --unit=hevi-live-xiaoya -p Restart=on-failure -p WorkingDirectory="$PWD" \
  -E PYTHONPATH="$PWD" -E PATH="$(dirname "$FF"):/usr/local/bin:/usr/bin:/bin" -E FFMPEG="$FF" -E HEVI_LIVE_THREADS="${HEVI_LIVE_THREADS:-8}" -E HEVI_LIVE_FPS="${HEVI_LIVE_FPS:-20}" -E HEVI_LIVE_MOUTH="${HEVI_LIVE_MOUTH:-v2}" -E HEVI_LIVE_MOUTH="${HEVI_LIVE_MOUTH:-v2}" \
  -p StandardOutput=file:"$PWD/audit/live_host/stream/live.out" -p StandardError=file:"$PWD/audit/live_host/stream/live.err" \
  /data/soffy/projects/hevi/.venv/bin/python -W ignore -m hevi.live_host.live_stream "${ARGS[@]}" --log "$PWD/audit/live_host/stream/live_events.jsonl"
echo "started. OBS 媒体源输入: rtmp://$(hostname -I | cut -d' ' -f1):1935/xiaoya   停止: systemctl --user stop hevi-live-xiaoya"
