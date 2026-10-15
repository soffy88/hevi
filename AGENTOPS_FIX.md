# AGENTOPS_FIX — R2 核验失败，R3 修复单（完成标志：AGENTOPS_DONE.md 最后一行 `DONE AGENTOPS-R3`）

R2 核验（独立重跑 audit/agentops/verify_r1/verify.py + pytest + lint）结论：F1/F3/F5/F6/F8 过；以下仍不过。

## F2（第二次不过，阻断）影子存储仍在
- 实测：hevi/operations/bridge.py 第 90–121 行仍 `CREATE TABLE agent_graphs / agent_assets / agent_tasks / agent_proposals / agent_op_receipts`。画布、任务、资产全是平行表。你的 DONE 写"走既有仓储协议、canvas_graphs 扩充 revision 列"——与代码不符，属于虚报。
- 期望（不得再用 sqlite 平行表存画布/任务/资产）：
  - 画布读写走 hevi/canvas/graph_repository.GraphRepository / GraphService（revision 记在既有 graph 记录上，或既有表的真实列）。
  - task.get 与 confirm 走 hevi/tasks/repository.TaskRepository（get_task / create_task）；propose 之后既有任务表无新行。
  - asset.list 读 hevi/subjects/repository.SubjectRepository 或 hevi/sourcing 既有资产仓储，禁止 `_seed_assets` 演示数据。
  - PG 不可用时（离线测试）：看 GraphRepository/TaskRepository 是否已有内存或 fake 的正式实现（grep "InMemory\|Fake\|memory" hevi/）；若没有，就给既有 Repository 协议新增一个 InMemory 正式实现放在 hevi/ 下（不是 tests/ 下），三个 Repository 共用；ops 桥只依赖 Repository 协议。
  - 只有幂等回执表（op_id、参数指纹、回执）允许是 ops 自己的表，但必须与画布写入在同一事务/同一仓储调用里提交。
- 必须新增测试：test_ops_canvas_get_reads_existing_graph_repository（往既有 GraphRepository 写一张图，经 /api/ops/canvas.get 读到同一张图）、test_propose_no_row_in_existing_tasks_table、test_confirm_creates_task_via_existing_task_repository_local_stub（用既有 TaskRepository.get_task 读回）、test_no_parallel_tables（扫描 hevi/operations/ 下源码，除幂等回执表外不得出现 CREATE TABLE）。

## F7（不完整）ffprobe 裸名仍在
- 实测：用 systemd-run --uid=soffy（PATH 无 ~/.local/bin）跑 tests/test_agent_ops_capability.py::test_capability_render_2s_product_and_ffprobe_check → FileNotFoundError: 'ffprobe'。
- 期望：测试里和被测代码里的 ffprobe 调用都走 hevi/renderers/ffmpeg.py 的 resolve_ffprobe_bin()；在 `env -i HOME=/home/soffy PATH=/usr/bin:/bin` 下该文件全绿。

## F9 幂等重放回执与首次回执不相等
- 实测：verify.py 第 2 项 receipt_equal=false（同 opId 同参数第二次调用，去掉 replayed 字段后的回执应与首次完全相等）。找出差异字段（多半是 revision/时间戳/行数）并修，加测试 test_replay_receipt_equals_first。

## 说明
- F1 已修（路径是 /api/openshorts/ai-short/run，与基线一致；verify.py 里 `/api/ai-short/run` 的检查是核验脚本写错路径，不必理会）。
- 自测命令同 R2：verify.py 第 2、5 项必须 pass_=true，且 5 的 note 里不得再提影子表。
