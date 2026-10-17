#!/bin/bash
W=/data/soffy/projects/hevi/.veya/worktrees/task-remote-7739211f2d800c159860
touch /data/soffy/projects/hevi/.veya/.v5wtest 2>/dev/null && echo "MAIN_VEYA_WRITABLE" || echo "MAIN_VEYA_READONLY"
rm -f /data/soffy/projects/hevi/.veya/.v5wtest
touch /data/soffy/projects/hevi/.v5wtest 2>/dev/null && echo "MAIN_ROOT_WRITABLE" || echo "MAIN_ROOT_READONLY"
rm -f /data/soffy/projects/hevi/.v5wtest
touch "$W/.v5wtest" 2>/dev/null && echo "WT_WRITABLE" || echo "WT_READONLY"
rm -f "$W/.v5wtest"
echo "=== git status of worktree ==="
git -C "$W" status --porcelain | head -20
echo "=== git status main ==="
git -C /data/soffy/projects/hevi status --porcelain 2>&1 | head -20
echo "=== /tmp writable really? ==="
echo hello > /tmp/.v5wtest && cat /tmp/.v5wtest && echo TMP_WRITABLE || echo TMP_READONLY
rm -f /tmp/.v5wtest
