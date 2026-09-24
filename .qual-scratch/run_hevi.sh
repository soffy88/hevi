#!/usr/bin/env bash
# Canonical HEVI runtime runner: canonical project venv with PYTHONPATH unset so
# the Hicode-managed PYTHONPATH shadow can never win.  Usage: run_hevi.sh <args...>
set -euo pipefail
unset PYTHONPATH
cd /data/soffy/projects/hevi/.veya/worktrees/task-remote-c76043b5bf32d3c16227
exec /data/soffy/projects/hevi/.venv/bin/python "$@"
