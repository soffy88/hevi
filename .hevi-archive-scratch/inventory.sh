#!/bin/bash
# Inventory all video files under the HEVI project with size + mtime, excluding excluded trees.
find /data/soffy/projects/hevi -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' -o -iname '*.avi' \) 2>/dev/null \
  | grep -viE '/\.git/|/\.veya/worktrees/|/node_modules/|/third_party/|/\.venv' \
  | while read -r f; do
      sz=$(stat -c '%s' "$f" 2>/dev/null)
      mt=$(stat -c '%y' "$f" 2>/dev/null | cut -d. -f1)
      printf '%15s  %s  %s\n' "$sz" "$mt" "$f"
    done | sort -rn > /data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/all_videos.txt
wc -l /data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/all_videos.txt
echo "=== top 60 by size ==="
head -60 /data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/all_videos.txt
