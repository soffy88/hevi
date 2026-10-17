#!/bin/bash
echo "=== 1. docker --network host bind 8767 test ==="
docker run --rm --network host alpine:latest sh -c 'nc -l -p 8767 >/dev/null 2>&1 & sleep 1; kill %1 2>/dev/null; echo "nc_attempt_done"' 2>&1 | tail -3
echo "=== 2. host IPs ==="
ip -4 addr show 2>/dev/null | grep -E "inet " 
echo "=== 3. previous publish artifacts ==="
ls -la /data/soffy/projects/hevi/.veya/runs/ 2>/dev/null | tail -5
grep -rl "8767" /data/soffy/projects/hevi/.veya/worktrees/task-remote-7739211f2d800c159860 2>/dev/null | head
echo "=== 4. hevi venv import test ==="
cd /tmp
unset PYTHONPATH; PYTHONNOUSERSITE=1 /data/soffy/projects/hevi/.venv/bin/python -c "import hevi, sys; print('hevi ok', hevi.__file__); from hevi.production.visual_quality_workflow import execute_visual_quality_task; from hevi.production.delivery_gate import probe_video, assert_explainer_compose; print('imports ok')" 2>&1 | tail -8
