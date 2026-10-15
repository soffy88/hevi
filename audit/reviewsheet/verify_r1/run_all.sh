#!/bin/bash
# 核验员反例总验收：重跑全部反例脚本，任何 LEAK / FALSE_POSITIVE / ERROR 即非零退出。
# 用法（soffy 身份，worktree 根目录）：bash audit/reviewsheet/verify_r1/run_all.sh
set -u
cd "$(dirname "$0")/../../.."
W=$PWD
A=audit/reviewsheet/verify_r1
export JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$W PATH=$HOME/.local/bin:/home/soffy/.local/bin:$PATH
PY=/data/soffy/projects/hevi/.venv/bin/python
mkdir -p .tmp
# kids_gate 脚本会跳过已有结果的样本：重跑前把旧结果挪走
[ -f $A/results_kids_gate.json ] && mv $A/results_kids_gate.json .tmp/results_kids_gate.prev.json
rm -f $A/samples/*.mp4
$PY $A/ce_review_sheet.py > .tmp/rerun_review_sheet.out 2>&1
$PY $A/ce_annotation.py  > .tmp/rerun_annotation.out 2>&1
$PY $A/ce_kids_gate.py   > .tmp/rerun_kids_gate.out 2>&1
$PY $A/e2e_verify.py     > .tmp/rerun_e2e.out 2>&1
$PY - <<'EOF'
import json, sys
A = "audit/reviewsheet/verify_r1"
bad = 0
for f in ("results_review_sheet.json", "results_annotation.json", "results_kids_gate.json"):
    d = json.load(open(f"{A}/{f}", encoding="utf-8"))
    leaks = [r.get("case") or r.get("sample") for r in d
             if str(r.get("verdict")).startswith(("LEAK", "FALSE", "ERROR"))]
    print(f, "total", len(d), "leaks", len(leaks), leaks)
    bad += len(leaks)
e = json.load(open(f"{A}/results_e2e.json", encoding="utf-8"))
e2e_bad = []
if not e.get("render_deterministic"): e2e_bad.append("render 非确定")
if not e.get("patch_unmapped_fields_byte_equal"): e2e_bad.append("非映射字段被改")
if not e.get("camera_only_patch_changes_render"): e2e_bad.append("camera patch 对渲染无效果")
if e.get("gate_ext", {}).get("status") != "ok": e2e_bad.append(f"合法 patch 重渲染后 gate={e.get('gate_ext',{}).get('status')}")
print("e2e problems", e2e_bad)
bad += len(e2e_bad)
print("TOTAL_BAD", bad)
sys.exit(1 if bad else 0)
EOF
