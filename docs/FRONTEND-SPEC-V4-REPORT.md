# Hevi 前端 UI/UX 终极重构实施报告 (Frontend SPEC v4.0)

> 版本: v4.0 | 日期: 2026-08-02 | 目标: 符合 Frontend SPEC v4.0「我在历史现场」终极版
> 范围: hevi-web (Next.js 16 App Router + React 19) + 最小后端透传(hevi/api/routers/tongjian.py)

## 0. 结论摘要

SPEC v4.0 五大场景全部落地。新增 8 个回归测试(28 个全绿)，`npm run lint` / `npm run build`
双绿，后端 tongjian 全系 206 用例零回归。

| 验证项 | 结果 |
|--------|------|
| `npm run lint`（tsc --noEmit） | ✅ 通过 |
| `npm run build`（22 路由） | ✅ 全量编译 + 静态生成成功 |
| `npm test`（vitest） | ✅ **28 passed / 0 failed**（9 文件，含 8 个 v4.0 新增） |
| 后端回归 | ✅ tongjian 全系 + pipeline 契约 **206 passed**（零回归） |

---

## 1. 五大场景交付清单

### §2.1 /tongjian — 通鉴通道重塑为「我在历史现场」🏛️
- **主题重塑**：hero 区「🏛️ 历史素材与史料大类 · 通鉴通道 / 【我在历史现场】」，定位语
  「讲解（分析/铺垫）+ 现场高潮演绎 重现历史情境」+ L0-L8 九层流水线徽标
- **① 历史素材与纪实文本**：章节/事件标题 + 史料原文/纪实材料（保留 2 个示例填充）
- **② 演绎与生成模式配置**：
  - **演绎比例**三档：讲解为主(80/20) / 均衡 70+30（默认）/ 演绎为主(50/50) → L2 params
  - **视觉风格**三档按钮：🎨 国风水墨（默认）/ 🎬 拟真电影感 / 🖌️ 连环画·工笔 → L6 params.style
  - **讲解人/数字人**：📜 历史旁白·老张 / 儒生讲史·激昂 / 史官正音·凝重（→ L6 narr_tone）
    + 呈现方式：纯旁白讲解 / 🎙️ 数字人出镜（→ L6 model=cloud_avatar）
  - **史实红线 CG2.5**：显式开关默认开启 → L2 dramatize=false（对白必须有 quote_id 逐字引语，
    无引语事件转纯旁白叙述）；关闭才允许戏剧化创作对白
- **③ 出片规格**：16:9 横屏纪录片式（默认）/ 9:16 / 1:1 + 1080P（默认）/ 720P / 480P
- 启动按钮「🏛️ 重建历史现场（启动 L0-L8 九层流水线）」；目标时长/立意候选/语速/审核/JSON 收进
  折叠「高级参数」区；L0-L8 进度面板 + 剧本人工审核台 + 成片结果完整保留

**后端最小透传（零回归）**：`hevi/api/routers/tongjian.py` L2 新增消费
`include_commentary` 与 `screenwriter_persona`（build_script 原生支持，默认值与现行为一致）。

### §2.2 /director-pipeline — 导演流水线（全自动派发）🚀
- 顶部新增**全自动派发表单**：作品名 + 手稿原文 + 目标集数(1-6) + 季预算上限($150 默认) +
  视频 Provider 选单 + 单集时长档 + 配音引擎
- 「▶ 开始抽取 + 规划」→ 前端按段均分手稿 → 逐集自动执行
  `createWork → ①立意 → ②剧本 → ③设计清单(后台锁资产) → ④分镜(后台) → 产集`（复用后端同一批
  端点，跳过人工确认，自动逐级锁定），季预算按集分账
- 派发队列卡实时显示每集状态（待派发/自动推进中/✓ 已派发产集/失败），可一键「打开精控」载入该集
- 现有**单集精控台完整保留**（每级生成→人工编辑→锁定，含准备台拦截项）作为并行精控入口

### §2.3 /explainer — 纯解说中心（双配方）📋🎙️
- 配方二选一卡片：
  - **short_explainer 图文解说**（默认）：选题 → E0 文案分镜 → E1 结构校验 → E2 配音+渲染
    （hevi.explainer 通道，竖/横屏成片）
  - **digital_presenter 数字人口播**：选题 + 数字人下拉（presenterApi）+ 单集时长档/执行档位/画幅
    → 走主线 `POST /api/pipeline/generate`（adapter_type=explainer + presenter_id +
    options.recipe=digital_presenter）→ 轮询任务进度，成片可下载
- 后端零改动（数字人口播复用既有主线 explainer 适配器）

### §2.4 /production & /studio 工具收拢
- **/production**：已是纯 Task & Asset 看板（表单零残留，由既有测试强制约束），本次零改动
- **/production-tools（制片工具箱）**：**移除 Seedance 2 独立生成表单 Tab**（含 SeedanceTab 组件与
  SeedanceResult 类型），默认 Tab 落在「✂️ 智能拆条」；保留工作流配方 + 数字人预览；
  标题/描述更新为「Seedance 2 已下沉为各页面的模型选单」
- **/studio（画布工作台）**：不动（不属于 SPEC §2.4 的工具箱范畴）

### 全局导航
- TopNav：「通鉴」→「**历史现场**」（SPEC §1 版图命名）；其余路由/文案不变

---

## 2. §3 CC 执行指令核验

| 指令 | 状态 |
|------|------|
| 改造 /tongjian 为「我在历史现场」，突出讲解+高潮演绎与 CG2.5 红线 | ✅ |
| 建立/重构 /director-pipeline 全自动派发（手稿/集数/季预算等） | ✅ |
| 保持 /director 人工控制台独立不动（8 层要素） | ✅ 零改动 |
| 收拢 /explainer 双配方（short_explainer / digital_presenter） | ✅ |
| /production 剥离表单仅留监控 | ✅ 已满足（测试约束） |
| npm run lint + npm run build 全绿、零类型报错 | ✅ |

## 3. 改动文件清单

**前端**：
- `hevi-web/src/components/director/TongjianConsole.tsx`（重写：我在历史现场）
- `hevi-web/src/components/director/ExplainerConsole.tsx`（重写：双配方）
- `hevi-web/src/components/director/DirectorPipelineConsole.tsx`（新增全自动派发）
- `hevi-web/src/components/studio/ProductionToolsConsole.tsx`（移除 Seedance 2）
- `hevi-web/src/components/TopNav.tsx`（通鉴→历史现场）
- `hevi-web/src/app/globals.css`（tj-radio/tj-adv/dp-auto/ex-recipe/ex-grid 等新样式）
- 新增测试 ×4：`TongjianConsole.test.tsx` / `ExplainerConsole.test.tsx` /
  `DirectorPipelineConsole.test.tsx` / `ProductionToolsConsole.test.tsx`

**后端（最小透传）**：`hevi/api/routers/tongjian.py`（L2 include_commentary / screenwriter_persona）

## 4. 遗留与说明

- **导演流水线「全自动派发」为前端编排**：后端无 season_planner/storygraph 批量派发端点，
  前端逐集复用既有 works 端点自动锁定推进（同一后端契约，零新增端点）；季预算为前端按集分账透传
- **tongjian 演绎比例**：映射 L2 `include_commentary`（讲解评论段）+ `dramatize`（创作对白），
  红线模式自动收敛为逐字引语对白；非数值比例（后端无该数值参数）
- 数字人口播配方依赖主线 explainer 适配器已支持的 presenter_id 能力
