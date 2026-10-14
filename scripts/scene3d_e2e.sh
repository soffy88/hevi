#!/usr/bin/env bash
# Render the three SCENE3D production shots and write metrics into
# output/scene3d_e2e. Safe to re-run; re-renders overwrite previous outputs.
set -euo pipefail
export PYTHONPATH=/data/soffy/projects/hevi-scene3d
export JWT_SECRET="${JWT_SECRET:-test-only-dummy}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p output/scene3d_e2e
nohup setsid .venv-scene3d/bin/python scripts/scene3d_e2e.py --out output/scene3d_e2e \
  > output/scene3d_e2e/run.log 2>&1 &
echo $! > output/scene3d_e2e/run.pid
echo "scene3d e2e pid=$(cat output/scene3d_e2e/run.pid)"
