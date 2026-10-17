#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost,192.168.0.0/16,100.64.0.0/10,172.16.0.0/12,10.0.0.0/8
R=/home/soffy/.config/rclone/rclone.conf
echo "=== HEVI folder id check (lsjson) ==="
timeout 90 rclone --config "$R" lsjson --drive-root-folder-id 11ZoaWMf7vWuhjk5VJpGZ8j-N1_l3ysu4 gdrive: 2>&1 | head -40
echo
echo "=== HEVI folder contents via path ==="
timeout 90 rclone --config "$R" lsl gdrive:HEVI 2>&1 | head -40
echo
echo "=== write capability test (mkdir) ==="
timeout 90 rclone --config "$R" mkdir gdrive:HEVI/.rclone-write-probe 2>&1 | head -10
echo "mkdir rc=$?"
