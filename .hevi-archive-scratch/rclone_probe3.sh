#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost,192.168.0.0/16,100.64.0.0/10,172.16.0.0/12,10.0.0.0/8
R=/home/soffy/.config/rclone/rclone.conf
echo "=== list HEVI after mkdir ==="
timeout 90 rclone --config "$R" lsf gdrive:HEVI 2>&1
echo "--- HEVI/ probe listed ---"
echo "=== try a tiny write+readback ==="
echo "rclone write probe $(date -u +%FT%TZ)" > /tmp/nonexist 2>/dev/null
mkdir -p /data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch
printf 'probe\n' > /data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/probe.txt
timeout 90 rclone --config "$R" copyto /data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/probe.txt gdrive:HEVI/.rclone-write-probe/probe.txt 2>&1
echo "copy rc=$?"
timeout 60 rclone --config "$R" lsjson gdrive:HEVI/.rclone-write-probe 2>&1
