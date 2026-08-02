# Hevi 前端 UI/UX 融合重构实施报告 (Frontend Consolidation Report)

> 版本: v1.0 | 日期: 2026-08-02 | 目标: 符合 Frontend Consolidation SPEC v1.0
> 范围: hevi-web (Next.js 16 App Router + React 19 + @helios/oui)

## 0. 结论摘要

SPEC 所要求的三页面目标架构（首页生成中心 / 导演控制台 / 生产任务中心）与统一提交契约
在迁移前**已基本成型**（仓库既有实现）。本次工作完成**逐条差距核对 + 2 项功能补齐 + §6
CI/回归测试落地**：

| 验证项 | 结果 |
|--------|------|
| `npm run lint`（tsc --noEmit，§6.1） | **通过**（含全部新增测试文件类型检查） |
| `npm run build`（§6.1） | **通过**（22 路由全部静态生成成功） |
| `npm test`（vitest，§6.2） | **20 passed / 0 failed**（5 个测试文件） |
| 后端契约回归 | `test_pipeline_production_route.py` + `test_api_contract.py` **6 passed** |

---

## 1. SPEC 差距核对表（现状 → 动作）

### §1 UI/UX 融合目标架构与路由收拢 — 已满足 ✅

| 页面 | 职责 | 现状 |
|------|------|------|
| `/` | 自动化生成中心（4 适配器切签） | ✅ `src/app/page.tsx` → `SimpleGenerate` |
| `/director` | 人工/专家 8 层要素控制台 | ✅ `src/app/director/page.tsx` → `DirectorConsole` |
| `/production` | 任务监控与资源中心（无表单） | ✅ `src/app/production/page.tsx` → `ProductionConsole` |
| TopNav | 生成 / 任务中心 / 导演 三入口 | ✅ 导航文案已对齐 |

### §2 Phase 1 首页生成中心 — 已满足 + 1 项补齐

- ✅ 模式切签：⚡ 极简单片 / 🎙️ 头像解说 / 📜 资治通鉴 / 🎬 故事短剧（含占位提示词差异化）
- ✅ 时长 / 画幅 / 风格 / 画质 / 模型档位 / 执行档位（💰 省钱 / ⚖️ 均衡 / ⚡ 极速）
- ✅ 角色多选 + 上传照片建角色；生成提交走统一契约 `source_channel=hub_quick`
- ✅ 作品画廊 + OCostConfirmDialog 成本确认 + OTaskProgress SSE 进度
- ✅ 「🎛️ 转入导演控制台精细调优 →」带参跳转（prefillDirector）
- 🔧 **补齐 §2.2 解说适配器契约**：新增「字幕样式」下拉（default/bold_yellow/large_white/compact），
  提交时透传 `config.options.subtitle_style` → 后端 `UnifiedGenerateConfig.options` →
  `ProductionRequest.to_task_args` → 编排层字幕烧录（`subtitle_style` 一等参数）。
  - 同时为两个新下拉补 `htmlFor`/`id` label 关联（a11y）
- 🔧 **补齐 §2.2 通鉴适配器契约**：切通鉴时显示「自动匹配水墨/古风风格预设 + CG2.5 史实出处检测」提示行
  （`hevi-home__adapter-hint` 样式；风格由通鉴渠道内部承担，不虚设首页风格选项）

### §3 Phase 2 导演控制台带参联动 — 已满足 + 1 项增强

- ✅ `prefillDirector`/`consumeDirectorPrefill`（sessionStorage 单次消费）已存在
- ✅ §3.2 映射表全部落地：prompt → ① 立意（text + narrative_hook 双处）、duration & aspectRatio →
  ① 立意、characters → ② 角色（锁脸勾选 + subject_id + num_characters）、presetLevel → ⑧ 生产
- 🔧 **增强（带参带入）**：prefill 增加 adapterMode 感知 —— 来自通鉴适配器时默认
  ④ 视觉风格 =「国风水墨」（导演台 PRESETS 内），用户仍可覆盖

### §4 Phase 3 Production 页面纯粹化 — 已满足 ✅

- ✅ 无任何生成表单（`<input>`/`<textarea>`/`<form>`/生成按钮，由测试强制约束）
- ✅ Header「生产看板 & 任务中心 (Task & Asset Manager)」
- ✅ 顶部指标概览（运行中 / 队列等待 / 已交付 / 质检通过率）
- ✅ 任务列表（Task ID / 模式适配器 / 进度条 / 阶段 / 状态 / 查看 / 下载）+ 3s 轮询刷新
- ✅ 媒体交付库（已完成成片卡片 + 下载 MP4）
- 注：SPEC 示例中的「实时 Cost」「导出日志 / Dub 重烧」依赖后端产物索引字段，现有
  `TaskInfo` 未暴露 cost 字段、无对应后端端点 —— 不做假数据占位，留待后端补齐后接入。

### §5 API 提交契约与参数映射表 — 已满足 ✅

- ✅ 后端 `POST /api/pipeline/generate`（`hevi/api/routers/pipeline.py`）：
  `source_channel ∈ {hub_quick, director_console}`、`adapter_type ∈ {default, explainer, tongjian, shortdrama}`、
  `config{ prompt, duration_archetype, aspect_ratio, execution_preset, character_references,
  presenter_id, emotion_aware_voiceover, locked_shot_list, quality_profile, options }` —— 与 SPEC §5.1 逐字段对齐
- ✅ 前端首页提交即此契约；导演控制台走独立 director 端点（含 8 层要素 + locked_shot_list 语义）

---

## 2. §6 本次新增交付

### 2.1 测试基建
- `vitest.config.ts`（jsdom 环境 + `@/` 别名 + `NEXT_PUBLIC_USE_MOCK=false`）
- `src/test/setup.ts`（jest-dom matchers + RTL 自动 cleanup）
- devDependencies：`jsdom`、`@testing-library/react`、`@testing-library/jest-dom`、`@testing-library/user-event`

### 2.2 §6.2 UX 回归测试集（20 用例）
| 文件 | 覆盖流程 | 用例数 |
|------|---------|--------|
| `src/lib/director-prefill.test.ts` | §3.1 带参传输契约（全字段往返/单次消费/脏数据兜底/默认值） | 5 |
| `src/components/home/SimpleGenerate.test.tsx` | §6.2 flow 1 自动化出片（解说切签→字幕样式→极速档→统一契约断言）+ 通鉴提示 | 3 |
| `src/components/director/DirectorConsole.test.tsx` | §6.2 flow 2 带参平滑跳转（16:9+刘备→立意/角色/生产预填+国风水墨默认） | 2 |
| `src/components/production/ProductionConsole.test.tsx` | §6.2 flow 3 纯粹性（无表单/指标概览/任务列表/交付库） | 4 |
| `src/lib/errorMessages.test.ts`（既有） | — | 6 |

> 说明：SPEC §6.2 点名 Cypress/Playwright，但仓库无对应基础设施且本环境无法安装浏览器；
> 以仓库既有 vitest + Testing Library 实现**组件级 E2E 等价回归**（三条流程的交互与契约断言全覆盖），
> 待有浏览器环境时可直接扩展为真 E2E。

### 2.3 §6.1 静态校验
- `npm run lint`（tsc --noEmit）：全量类型检查通过（含测试文件）
- `npm run build`：22 路由全部编译成功、静态生成成功

---

## 3. 改动文件清单

| 文件 | 动作 |
|------|------|
| `hevi-web/src/components/home/SimpleGenerate.tsx` | 解说适配器补字幕样式 + label 关联；通鉴适配器风格提示；提交透传 subtitle_style |
| `hevi-web/src/components/director/DirectorConsole.tsx` | prefill 增加 adapterMode 感知（通鉴→国风水墨默认风格） |
| `hevi-web/src/lib/director-prefill.ts` | 校验增强：空 prompt 视为脏数据拒绝 |
| `hevi-web/src/app/globals.css` | 新增 `.hevi-home__adapter-hint` 样式 |
| `hevi-web/vitest.config.ts` / `src/test/setup.ts` | 新增测试基建 |
| `hevi-web/src/{lib,components}/*.test.ts(x)` ×4 | 新增 §6.2 回归测试集 |
| `hevi-web/package.json` / `package-lock.json` | 新增测试 devDependencies |

## 4. 遗留与后续

- Production 页「实时 Cost」「导出日志 / Dub 重烧」待后端 `TaskInfo` 补 cost 字段与产物索引端点后接入（不做假数据）。
- 真浏览器 E2E（Playwright/Cypress）留待具备浏览器安装条件的环境扩展。
- 后端零改动；`test_pipeline_production_route.py` + `test_api_contract.py` 契约回归全绿。
