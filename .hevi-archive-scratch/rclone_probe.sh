#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost,192.168.0.0/16,100.64.0.0/10,172.16.0.0/12,10.0.0.0/8
R=/home/soffy/.config/rclone/rclone.conf
echo "=== about ==="
timeout 60 rclone --config "$R" about gdrive: 2>&1 | head -20
echo
echo "=== root listing (lsd) ==="
timeout 90 rclone --config "$R" lsd gdrive: 2>&1 | head -40
