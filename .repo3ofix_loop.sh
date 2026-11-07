#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:1091 HTTP_PROXY=http://127.0.0.1:1091 NO_PROXY=localhost,127.0.0.1
pgrep -f sing-box-all.json >/dev/null || (setsid nohup sing-box run -c ~/.config/sg-proxy/sing-box-all.json >/tmp/sgall.log 2>&1 </dev/null &); sleep 2
cd /data/soffy/projects/platform/3O
timeout 3600 opencode run --auto -m opencode-go/beam-free "$(cat ~/projects/hevi/.repo3ofix_prompt.txt)"
for i in $(seq 1 20); do grep -q 'REPO3O_IMPL DONE' ~/projects/hevi/REPO_3O_IMPL.md 2>/dev/null && break; echo "=== ROUND $i"
 timeout 3600 opencode run --continue --auto -m opencode-go/beam-free '继续修复任务（要求见 ~/projects/hevi/.repo3ofix_prompt.txt），动手改代码跑测试 commit，直到写完报告末行 REPO3O_IMPL DONE。'; done
echo LOOP_END
