#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost,192.168.0.0/16,100.64.0.0/10,172.16.0.0/12,10.0.0.0/8
R=/home/soffy/.config/rclone/rclone.conf
timeout 90 rclone --config "$R" purge gdrive:HEVI/.rclone-write-probe 2>&1
echo "purge rc=$?"
timeout 60 rclone --config "$R" lsf gdrive:HEVI 2>&1
echo "HEVI listing above (empty = clean) rc=$?"
