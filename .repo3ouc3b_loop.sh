cd /data/soffy/projects/platform/3O
for i in $(seq 1 20); do
  tail -3 ~/projects/hevi/REPO_3O_UNCOMMITTED.md | grep -q "UNCOMMITTED3 DONE" && break
  timeout 5400 codex exec --dangerously-bypass-approvals-and-sandbox resume --last "继续 ~/projects/hevi/.repo3ouc3_prompt.txt 的任务（务必先读文件末尾【复查结论】一节），从断点继续，直到报告文件末行写入 UNCOMMITTED3 DONE。"
  sleep 120
done
