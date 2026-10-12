# DRAMAPLAN 进度

任务：DRAMAPLAN（章节事件图 + 三层审稿 + 修短剧两 bug）
分支：feat/dramaplan-3o　基线：98e216af

## 基线记录（2026-10-11）
- `run_3o_v3_lint.py` 基线：FAIL，4 个 check 失败，**全部在 site-packages 上游**
  （check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only）。
  hevi/ 本地无失败。结束需 ≤ 4。
- LLM 通道实测：NIM `nvidia/nemotron-3-super-120b-a12b` 可用（免费，JSON 干净，快）；
  ollama llama3.2:3b 可用但慢（离线兜底）；omniroute auto/* 超时、oc/* 401；
  opencode 缺 x-opencode-session；teamo 连接失败（DNS 有、TCP 不通）。
  主仓 `/data/soffy/projects/hevi/.env` 有 HEVI_NIM_KEYS（本 worktree .env 只有 JWT_SECRET）。

## 阶段状态
- [x] 侦察 + 基线
- [x] 1. LLM 通道（free_llm + llm_channel 配置 + 探测脚本）
- [x] 2. shot_budget_for_duration（bug1）
- [x] 3. 章节事件图（storygraph）
- [x] 4. 三层审稿 agent
- [x] 5. bug2（定向返工 + 阈值系统性错配）
- [x] 6. 单测 + E2E 真跑 + DONE + commit

## 续做记录（接手 agent，2026-10-11）
前任在阶段 6 前被额度中断，`DRAMAPLAN_DONE.md` 已写好但**未 commit**。接手后逐条独立复核：
- 重跑 E2E `--run-id run2`（真实 NIM）→ 与 run1 结论一致，qa passed=true。
- 重跑 NIM 探测 → 仍 OK（1.52s，json_stable）。
- 重算 run1 产物 sha256 → 与 DONE 表内值逐字一致。
- 新增单测 35 passed；旧测试分四批复跑合计 357 passed、0 failed。
- lint 与基线逐字相同（4 个上游失败，hevi/ 零新增）。
- 修正两处不实表述：产物实际未 `git add -f`（已补齐）；测试数字改为实测值。
- 未改上游包（mtime 扫描确认）、无新增依赖、未 push。

## 续做记录（第三位接手 agent，2026-10-12）
前两位 agent 的工作已 commit（`420a5475`）。本次**不沿用任何既有结论**，逐条独立复核：
- 12 个声称新增文件全部真实存在且非空。
- `sha256sum run1/run2` 全部产物 → 与 DONE 第 3 节表格**逐字一致**（无事后篡改）。
- 新增单测 35 passed；旧测试 20 文件一批 317 passed + `test_director_pipeline_orchestrator_integration`
  5 passed，0 failed。
- 3O v3 lint：仍 FAIL，但失败清单与基线逐字相同（4 个全在 site-packages），新增 0。
- **新增一次独立真实 E2E `--run-id run3`**：通道 nim、probe latency 1.02s、json_stable、
  3 章/4 角色/7 事件、rounds=[2,1,1]、qa passed=true、EXIT=0。run3 产物 sha256 与
  run1/run2 两两不同（三次都是真调用）。抽查内容：跨章因果边 `CH01E002.effects=["CH02E001"]`
  真实存在；监督层是真实 LLM 长评；EP1 `score 60→80`、`revised_scenes=[1,2]`、带 before/after 哈希。
- **接线复核（关键，防"只写工具函数+单测"）**：
  - bug1 真在 `longvideo_orchestrator._counting_shot_gen_fn` 里生效（:1146-1157），门控正确。
  - bug2 真在 `task_service.py:1796-1800` 透传到 `editor.review`。
- 造假审计：6 个新文件 `mock|placeholder|dummy|fake|stub|hardcod` **0 命中**；
  `qa.passed` 是 `all(...)` 纯计算（e2e 脚本 :199）。
- 付费通道审计：`FREE_CHANNEL_ORDER` 无任何付费端点；`default` 实测未注册（`ProviderNotFoundError`）
  → `auto` 不可能落到付费端点。已作为已知问题 #10 记入 DONE。
- 改动测试是否放水：`tests/test_director.py` 仅 `0.55→0.30`，关键断言
  `regen_calls == [[1]]` / `delivered is True` 原样保留 —— 修复失效仍会红。
- **未发现前任造假或代码缺陷**；本轮唯一新增事实是 run3 产物 + DONE/PROGRESS 补充复核章节。

## 关键发现
- bug1 根因：`oskill.script_writer._chapters_for_duration` <300s 至少 2 章；`storyboard_planner`
  每场景 3-10 镜不受 target_duration_s 约束。longvideo_orchestrator 只在 short 档裁到 1 镜。
- bug2：定向返工机制（`regenerate_shots`/`regenerate_task_shots`）其实已存在且只重烧目标镜；
  真正的系统性问题是 `editor.review` 的 `consistency_floor=0.75` 与 scorecard 身份分尺度
  （identity_floor=0.2，实测 mean 0.591）严重错配 → 全部镜头被判“参考图角色错配” → 整轮重烧。
- `free_llm` 的 `default` 兜底通道依赖 obase 注册表，跨环境不安全，应显式配 `dramaplan_llm_channel`。
