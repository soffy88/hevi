cd /data/soffy/projects/platform/3O
timeout 5400 codex exec --dangerously-bypass-approvals-and-sandbox "$(cat ~/projects/hevi/.repo3ouc2_prompt.txt)"
for i in $(seq 1 12); do
  grep -q 'UNCOMMITTED2 DONE' ~/projects/hevi/REPO_3O_UNCOMMITTED.md && break
  sleep 300
  timeout 5400 codex exec --dangerously-bypass-approvals-and-sandbox resume --last '上次中断。继续 ~/projects/hevi/.repo3ouc2_prompt.txt 的任务，从断点继续直到末行 UNCOMMITTED2 DONE。'
done
