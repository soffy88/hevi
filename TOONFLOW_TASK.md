# TOONFLOW-R1：吸收 HBAI-Ltd/Toonflow-app（MIT，17.8k★，Bun+Vue 短剧/漫剧无限画布平台）
来源 https://github.com/HBAI-Ltd/Toonflow-app （ghfast.top clone 到 /data/soffy/refs/Toonflow-app，只读；记录 commit）。MIT，可借鉴代码/提示词，需在 third_party/NOTICE 署名。
产品定位：Hevi = 2–6 岁幼儿教育动画短片，规则见 audit/kids/KIDS_ANIME_DIRECTION.md，所有产出过 kids_gate。CPU-only，不接 Seedance/GPT-Image/MiniMax 等付费模型。

## 第一步：差距分析 audit/toonflow/GAP.md
读 apps/ packages/ 里的：剧本→分镜 Agent 提示词与工具、角色/场景/道具资产管理（三视图、参考图绑定）、3D 导演台/镜头预演、节点工作流与画布数据结构、供应商抽象（含 ComfyUI/本地 LLM）、MCP/A2A、Skill Hub、插件机制。逐项对照 Hevi 已有（huobao agents、kidsmanifest、storyplan、shotspec、scene3d、motion-director、capabilities registry、workbench），只列真缺口并排优先级。

## 第二步：实现前 3 个高价值缺口（预期，按 GAP 调整）
1. 资产圣经 asset_bible：角色/场景/道具实体（名字、外观卡、三视图参考、配色、禁忌），镜头通过 id 引用；生成前注入提示，生成后一致性检查（配色/轮廓近似度），不一致的镜头标红重做。
2. MCP 服务：把 Hevi capabilities（GET /api/capabilities 已有）以 MCP tools 暴露（stdio + http），可列能力、提交短片任务、查状态、取成片；不开放无鉴权公网端口。
3. 剧本→分镜 Agent 提示词/技能库借鉴：吸收它开放的 prompt 结构，接入 storyplan/director brief，保持幼儿安全词表。
画布 UI 只在 GAP 里评估，不做。全部注册 capabilities（audit/CAPABILITY_CONTRACT.md）。

## 验收（巡检独立重做）
- 一个 3 角色幼儿故事：asset_bible 建档 → 真实出 1 支 1080p 16:9 + 1 支 9:16（30–60s），ffprobe/有声/抽帧，角色跨镜头配色一致性指标给数字；故意改坏一个角色配色，检查必须报出。
- MCP：用真实 MCP 客户端（如 mcp python sdk）列 tools、提交任务、拿到成片路径。
- 新 pytest 全过，全量回归无新增失败，3O lint ≤4。
- 报告 audit/toonflow/REPORT.md，最后一行 `DONE TOONFLOW-R1`。

## 规则
worktree /data/soffy/projects/hevi-toonflow，分支 feat/toonflow-assets（基于 closure 远端 HEAD）；只 git add 自己的文件；不 push。单进程渲染；禁止付费 API、禁止 mock 伪造验收；不删 worktree 外文件、不清理磁盘，/data<5G 写 DISK_FULL_NOTE.md 停止；不改主 checkout；不碰生产容器。
