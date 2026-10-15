# TOONFLOW-R1 差距分析 (GAP.md)

对照 HBAI-Ltd/Toonflow-app (MIT, 17.8k★) 与 Hevi 现有架构 (huobao agents, kidsmanifest, storyplan, shotspec, scene3d, motion-director, capabilities registry, workbench)，进行深入的架构真缺口对照与排优。

## 1. 资产圣经 (asset_bible)
- **Toonflow 特性**：角色/场景/道具实体管理、外观卡、三视图参考、配色方案、负向/禁忌约束，镜头通过 id 引用，生成前自动注入提示词，生成后执行一致性检查（配色/轮廓近似度），不一致的镜头标红重做。
- **Hevi 现状**：已有 `shotspec` 及 `kidsmanifest`，但缺乏统一的 `asset_bible` 实体状态管理、多视图参考绑定以及跨镜头的自动一致性检查/标红重做流水线。
- **排期/优先级**：P0（本次核心实现）。

## 2. MCP 服务 (Model Context Protocol)
- **Toonflow 特性**：独立 `@toonflow/mcp` 包，支持标准 Model Context Protocol（stdio + HTTP Streamable 传输、鉴权、资源发现、工具调用、取消信号），暴露画布、节点、文件与应用管理能力。
- **Hevi 现状**：已有 `GET /api/capabilities` 统一能力注册表与 agent.ops_bridge，但未暴露标准的 MCP server (stdio/http) 接口供外部 MCP 客户端调用。
- **排期/优先级**：P0（本次核心实现）。

## 3. 剧本→分镜 Agent 提示词/技能库
- **Toonflow 特性**：分镜创作团队 (`storyboardTeam`)：Director 统筹、Writer 编写、Reviewer 审阅，拥有私有技能和连续性知识（`continuity.md`），将剧情分解为有目的、带景别与时长的文字分镜。
- **Hevi 现状**：已有 `storyplan` 和 `shotspec`，但缺少结构化的儿童动画安全词表、导演/编剧/审阅三权分立提示词体系及连续性校验逻辑。
- **排期/优先级**：P0（本次核心实现）。

## 4. 评估项（本次暂不实现，仅做架构记录）
- 3D 导演台/镜头预演 (`scene3dNode`)：Hevi 已有 `scene3d` 基础渲染。
- 节点工作流画布 UI：画布前端交互留白。
- 供应商抽象：Hevi 已有本地/API 供应商路由，暂无需大改。
- 插件机制：依赖现有 `capabilities registry`。
