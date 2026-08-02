# Hevi 前端 UI/UX 终极重构实施报告 (Frontend SPEC v5.0)

> 版本: v5.0 | 日期: 2026-08-02 | 状态: 最终实施规范 | 执行者: Claude Code (CC)
> 范围: hevi-web (Next.js 16 App Router + React 19) —— 纯前端页面删除/归位，后端零改动

## 0. 结论摘要

彻底物理删除 `/pro-studio` 与 `/production-tools` 两个冗余页面（路由、页面文件、组件、入口全删），
五大能力精准归位至 5 个接收页面，导航精简为 SPEC §3 的 10 个职责纯粹节点 + 「更多」折叠。
`npm run lint` / `npm run build` / `npm test` 三绿，无死链。

| 验证项 | 结果 |
|--------|------|
| `npm run lint`（tsc --noEmit） | ✅ 通过 |
| `npm run build` | ✅ 21 路由编译 + 静态生成成功（22 → 21，-2 删除 +1 `/studio/clipper` 新增） |
| `npm test`（vitest） | ✅ **34 passed / 0 failed**（12 文件，含 7 个 v5.0 新增） |
| 死链检查 | ✅ 代码/路由/导航零引用残留（仅注释文字提及） |

---

## 1. §1 物理删除与能力拆解归位（完成）

### 删除清单（物理删除，无路由残留）
| 项 | 处理 |
|----|------|
| `app/(studio)/pro-studio/page.tsx` | ❌ 已删 |
| `app/(studio)/production-tools/page.tsx` | ❌ 已删 |
| `components/studio/ProStudioConsole.tsx` | ❌ 已删 |
| `components/studio/ProductionToolsConsole.tsx` | ❌ 已删（ClipperTab 迁移至独立页） |
| `components/studio/ProductionToolsConsole.test.tsx` | ❌ 已删（由 ClipperConsole.test.tsx 替代） |
| TopNav「制片工具 / 专业工作室」入口 | ❌ 已删（整体重构为 10 节点导航） |

### 能力归位表（§1 全量落地）
| 散落能力 | 新归宿 | 落地方式 |
|----------|--------|----------|
| 情感 TTS | ➔ `/voice-studio` | VoiceStudioConsole 新增「❤️‍🔥 情感配音」Tab：逐行推断情感（emo_vector）+ 语速/音高 + 多说话人（复用 `proStudioApi.indextts*`，原 IndexTTSTab 迁移） |
| 素材搜索 | ➔ `/gallery` | ShowcaseWall 新增「🔍 云端素材检索」切签：Pexels/Pixabay/Videvo 关键词 + 风格包检索、对位预览（`proStudioApi.stockSearch`，原 StockTab 迁移） |
| 数字人直播 | ➔ `/presenters` | PresenterLibrary 新增「应用模式」区：卡片1 出镜视频渲染（跳解说中心/导演台）+ 卡片2 实时数字人直播（推流地址 + 互动脚本 + 直播预检 + start/stop，`proStudioApi.livestream*`，原 LivestreamTab 迁移） |
| Agent 编排 | ➔ `/director-pipeline` & `/explainer` 底座 | 两页均新增「🤖 Agent 编排底座」面板（`orchestrationCreatePlan/Execute/Roles`）：StoryGraph 抽取 + 分集规划 + 导演自批判 Gate（导演流水线）；文本分析 → Remotion 渲染 → 音视频同步（解说中心） |
| 代码解说 (Remotion) | ➔ `/explainer` 高级代码动态渲染 | ExplainerConsole 新增第三配方卡「💻 代码解说 · Remotion 动态渲染」：代码高亮 + 逐行动画 + 图表/公式（语言/讲解深度选择，`proStudioApi.codeExplainerGenerate`，原 CodeTab 迁移） |
| 智能拆条 | ➔ 独立二创工具页 `/studio/clipper` | **新建** `app/studio/clipper/page.tsx` + `ClipperConsole.tsx`（原 ClipperTab 迁移 + capability gate，SPEC §3 导航节点） |
| Seedance 2 | ➔ 通用模型 Provider | 已下沉（v4.0 完成），无独立表单 |

## 2. §3 终极精简导航（完成）

TopNav 重构为 10 个职责纯粹节点（SPEC §3 精确顺序）：
⚡ 极速生成 `/` · 🎙️ 解说中心 `/explainer` · 🏛️ 历史现场 `/tongjian` · 🎬 导演流水线 `/director-pipeline` ·
🎛️ 导演控制台 `/director` · ✂️ 智能拆条 `/studio/clipper` · 👤 数字人预设 `/presenters` ·
🔊 语音工作室 `/voice-studio` · 📁 数字资产 `/gallery` · 📊 生产看板 `/production`

「更多 ▾」折叠收纳次要工作台（系列 / 短剧台 / 画布工作台 / 发布工作室 / ViMax / 我的 / 价格），
保留功能入口（短剧台/系列等页面路由未删，仅导航收敛）；登录/退出入口保留。
新增 `hevi-topnav__more*` 下拉样式。

## 3. 改动文件清单

**删除**：`(studio)/pro-studio/page.tsx`、`(studio)/production-tools/page.tsx`、`ProStudioConsole.tsx`、
`ProductionToolsConsole.tsx`、`ProductionToolsConsole.test.tsx`

**新增**：`app/studio/clipper/page.tsx`、`components/studio/ClipperConsole.tsx`、
测试 ×4（`ClipperConsole.test` / `ShowcaseWall.test` / `PresenterLibrary.test` / `VoiceStudioConsole.test`）

**修改**：`TopNav.tsx`（10 节点 + 更多折叠）、`VoiceStudioConsole.tsx`（+情感配音 Tab）、
`ShowcaseWall.tsx`（+云端素材检索）、`PresenterLibrary.tsx`（+应用模式/直播）、
`ExplainerConsole.tsx`（+代码解说配方 + Agent 底座）、`DirectorPipelineConsole.tsx`（+Agent 底座）、
`app/globals.css`（hevi-topnav__more / hevi-stock / hevi-presenters__app / dp-agent / ex-code / ex-agent 等）

**后端**：零改动。

## 4. 说明与遗留

- **路由数 22 → 21**：删除 pro-studio + production-tools 两个路由，新增 /studio/clipper 一个路由
  （/studio 画布工作台与 /studio/clipper 共存，clipper 页自带 TopNav + RequireAuth）
- **Agent 编排为"底座"形态**：导演流水线与解说中心各嵌入精简编排面板（创建/执行规划），
  无独立页；原 `/api/pro/orchestration/*` 契约不变，前端调用点从删除页迁入
- **Remotion 代码解说**：前端配方卡 + 代码输入区调用既有 `code-explainer/generate` 契约；
  专业动态代码视频渲染能力由后端通道提供（前端不做假数据）
- 数字人直播的推流地址为可选配置（后端提供默认流），未配置时按钮以 capability 预检禁用
