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
- [ ] 1. LLM 通道（free_llm + llm_channel 配置 + 探测脚本）
- [ ] 2. shot_budget_for_duration（bug1）
- [ ] 3. 章节事件图（storygraph）
- [ ] 4. 三层审稿 agent
- [ ] 5. bug2（定向返工 + 阈值系统性错配）
- [ ] 6. 单测 + E2E 真跑 + DONE + commit

## 关键发现
- bug1 根因：`oskill.script_writer._chapters_for_duration` <300s 至少 2 章；`storyboard_planner`
  每场景 3-10 镜不受 target_duration_s 约束。longvideo_orchestrator 只在 short 档裁到 1 镜。
- bug2：定向返工机制（`regenerate_shots`/`regenerate_task_shots`）其实已存在且只重烧目标镜；
  真正的系统性问题是 `editor.review` 的 `consistency_floor=0.75` 与 scorecard 身份分尺度
  （identity_floor=0.2，实测 mean 0.591）严重错配 → 全部镜头被判“参考图角色错配” → 整轮重烧。
