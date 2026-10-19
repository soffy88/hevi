#!/bin/bash
export HTTPS_PROXY=http://127.0.0.1:1091 HTTP_PROXY=http://127.0.0.1:1091 NO_PROXY=localhost,127.0.0.1
cd /data/soffy/projects/platform/3O
for i in $(seq 1 25); do
  grep -q "REPO3O_IMPL DONE" ~/projects/hevi/REPO_3O_IMPL.md 2>/dev/null && break
  echo "=== ROUND $i $(date)" 
  timeout 3600 opencode run --continue --auto -m opencode-go/beam-free "继续执行之前的实现+入库任务（原始要求见 ~/projects/hevi/.repo3oimpl2_prompt.txt，先重读它）。不要只读代码就停下：立即动手在 git worktree 中写代码、写测试、跑 pytest、commit。一直做到全部元素完成并写好 ~/projects/hevi/REPO_3O_IMPL.md（末行 REPO3O_IMPL DONE）再停。"
done
echo LOOP_END
