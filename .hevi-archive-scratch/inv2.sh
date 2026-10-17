#!/bin/bash
OUT=/data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/videos.tsv
: > "$OUT"
find /data/soffy/projects/hevi -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' -o -iname '*.avi' \) 2>/dev/null \
  | grep -viE '/\.git/|/\.veya/worktrees/|/node_modules/|/third_party/|/\.venv' \
  | while read -r f; do
      sz=$(stat -c '%s' "$f" 2>/dev/null)
      mt=$(stat -c '%Y' "$f" 2>/dev/null)
      printf '%s\t%s\t%s\n' "$sz" "$mt" "$f" >> "$OUT"
    done
wc -l "$OUT"
