#!/bin/bash
cd /data/soffy/projects/hevi
SRC=/data/soffy/projects/hevi/.veya/worktrees/task-remote-f6a5c69f516233eb7e20/.hevi-archive-scratch/all_videos.txt
echo "=== distinct parent dirs (2-3 levels) and counts+total bytes ==="
awk '{sz=$1; p=$3; n=split(p,a,"/"); dir=""; for(i=1;i<=n-1;i++){dir=dir a[i] "/"}; print sz"\t"dir}' "$SRC" \
 | awk -F'\t' '{c[$2]++; b[$2]+=$1} END{for(d in c) printf "%6d files %14d bytes  %s\n", c[d], b[d], d}' \
 | sort -k3 | sed 's#/data/soffy/projects/hevi/##'
