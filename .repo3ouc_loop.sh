cd /data/soffy/projects/platform/3O
for i in $(seq 1 12); do
  [ -f ~/projects/hevi/REPO_3O_UNCOMMITTED.md ] && grep -q 'UNCOMMITTED DONE' ~/projects/hevi/REPO_3O_UNCOMMITTED.md && break
  timeout 5400 codex exec --dangerously-bypass-approvals-and-sandbox resume --last '上次因 429 中断。继续 ~/projects/hevi/.repo3ouc_prompt.txt 中的任务：检查 /tmp/review3o 与已有备份进度，从断点继续，完成全部步骤并写报告，末行 UNCOMMITTED DONE。'
  sleep 300
done
