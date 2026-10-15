#!/bin/bash
# R1D verifier chain — sequential, one renderer at a time.
cd /data/soffy/projects/hevi-scene3d || exit 1
export JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD PATH=$HOME/.local/bin:/home/soffy/.local/bin:$PATH
PY=/data/soffy/projects/hevi/.venv/bin/python
A=audit/scene3d/verify_r1d
echo "START $(date)" > $A/chain.log
# 1) independent full-video determinism re-render (one 1080 clip)
$PY $A/determinism.py > $A/determinism.log 2>&1; echo "determinism rc=$? $(date)" >> $A/chain.log
# 2) API probe (small 270px render + capability duration gate)
$PY $A/probe_api.py > $A/probe_api.log 2>&1; echo "api rc=$? $(date)" >> $A/chain.log
# 3) full scene3d pytest suite
$PY -m pytest -q -p no:cacheprovider tests/test_scene3d*.py > $A/pytest.log 2>&1; echo "pytest rc=$? $(date)" >> $A/chain.log
# 4) 3O lint
$PY scripts/ci/run_3o_v3_lint.py > $A/lint.log 2>&1; echo "lint rc=$? $(date)" >> $A/chain.log
echo CHAINDONE >> $A/chain.log
