import subprocess

def run_cmd(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.stdout.strip()

raw = run_cmd("git branch --no-merged integration/mergeall-1017")
branches = []
for line in raw.splitlines():
    b = line.lstrip('+* ').strip()
    if b:
        branches.append(b)

plan_lines = [
    "# MERGEALL-1017 分支合并计划与状态",
    "",
    "基线分支：`integration/mergeall-1017` (基于 `a9af1c2e`)",
    "",
    "| 分支名 | 最近提交时间 | 分叉提交数 | 改动文件数 | 状态 | 备注 |",
    "|---|---|---|---|---|---|"
]

branch_data = []
for b in branches:
    last_date = run_cmd(f"git log -1 --format='%ai' {b}")
    commit_count = run_cmd(f"git rev-list --count integration/mergeall-1017..{b}")
    file_count = run_cmd(f"git diff --name-only integration/mergeall-1017...{b} | wc -l")
    branch_data.append({
        "name": b,
        "date": last_date,
        "commits": int(commit_count) if commit_count.isdigit() else 0,
        "files": int(file_count) if file_count.isdigit() else 0,
        "status": "PENDING",
        "note": ""
    })

def sort_key(item):
    name = item["name"]
    is_structural = any(k in name for k in ["architecture/", "platform/", "product/", "release/", "closure/", "pi-attempt-1", "spec-001", "tongjian-v2", "patrol3", "veya/"])
    priority = 1 if is_structural else 0
    return (priority, item["commits"], item["files"])

branch_data.sort(key=sort_key)

for item in branch_data:
    plan_lines.append(f"| `{item['name']}` | {item['date']} | {item['commits']} | {item['files']} | {item['status']} | {item['note']} |")

with open("MERGE_PLAN.md", "w", encoding="utf-8") as f:
    f.write("\n".join(plan_lines) + "\n")

print(f"Generated MERGE_PLAN.md with {len(branch_data)} branches.")
