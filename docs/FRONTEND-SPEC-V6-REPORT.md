# Hevi 前端 UI/UX 终极重构实施报告 (Frontend SPEC v6.0)

> 版本: v6.0 | 日期: 2026-08-02 | 状态: 最终实施规范 | 执行者: Claude Code (CC)
> 范围: 物理删除 /vimax + ViMax 四大能力全量消化入核心通道（首页/导演流水线/导演控制台/obase）

## 0. 结论摘要

`/vimax` 页面与路由彻底物理删除，Idea2Video / Novel2Video / AutoCameo / Provider Presets
四大能力全量下沉并融入核心通道：首页生成中心（Idea2Video）、导演流水线（Novel2Video + AutoCameo）、
导演控制台（AutoCameo）、后端 obase.ProviderRegistry（Provider Presets）。
导航最终精简为 **6 大主节点 + 工具箱弹层**（SPEC §4）。

| 验证项 | 结果 |
|--------|------|
| 前端 `npm run lint`（tsc --noEmit） | ✅ 零类型报错 |
| 前端 `npm run build` | ✅ 20 路由编译成功（21 → 20，/vimax 已移除） |
| 前端 `npm test` | ✅ **45 passed / 0 failed**（14 文件） |
| 后端 pytest 全量 | ✅ **1308 passed / 0 failed**（新增 test_provider_presets 6 项，零回归） |
| 死链检查 | ✅ vimax 引用清零，/api/providers/presets 已入 API 能力清单 |

---

## 1. 物理删除与能力解构映射（§1 全量落地）

### 物理删除清单
| 项 | 处理 |
|----|------|
| `app/(core)/vimax/page.tsx`（/vimax 路由） | ❌ 已删（`(core)` 目录随之清空删除） |
| `components/vimax/ViMaxConsole.tsx`（4 Tab 控制台） | ❌ 已删 |
| `lib/api-client.ts` `vimaxApi`（listPresets/getPreset/idea2Video/novel2Video/autocameo） | ❌ 已删 |
| `types/api.ts` VimMax 系列接口（Preset/Idea2Video/Novel2Video/AutoCameo） | ❌ 已删 |
| TopNav「更多」中 ViMax 入口 | ❌ 已删 |
| 前端 Provider Presets 管理表单（ViMaxConsole PresetsPanel） | ❌ 随页面删除（能力下沉后端 obase） |

### 能力融合映射（§1 架构图全量落地）
| ViMax 能力 | 新归宿 | 落地方式 |
|------------|--------|----------|
| **Idea2Video** | ➔ 首页生成中心 (/) | 新增「💡 创意极速」适配器：一句话创意 → `lib/prompt-enhancer.ts` Prompt Enhancer 预处理（分镜拆分 + 风格润色 + 画幅指令）→ 增强预览 → 直接调用统一生成能力 `productionApi.generate`（source_channel=hub_idea2video）出片；Provider Preset 选单直选 provider |
| **Novel2Video** | ➔ 导演流水线 (/director-pipeline) | 新增「📖 Novel2Video 解析手稿」：`lib/novel2video.ts` 角色提取（对白发言人 + 「」人名 + 主角/配角分级）+ 章节/节拍切分（第X章/序章/楔子/尾声）+ 分集规划（按目标集数均摊章节 + 每集字数/预算校验）→ 按章节分集全自动派发，角色清单随 hint 透传 |
| **AutoCameo** | ➔ 导演流水线 + 导演控制台 角色配置层 | 流水线：Provider 选单新增「🎭 [云端 AutoCameo 锁脸入戏（推荐）]」+ 锁脸开关 + 照片上传建角色（subjectApi.fromPhoto，主体库即后端 AutoCameo 载体）→ `produce` 透传 character_references + autocameo；控制台 ② 角色：新增「🎭 上传照片建角色（AutoCameo 照片人物入戏）」按钮，上传即建角色并自动锁选（跨镜人脸特征融合/表情自然度） |
| **Provider Presets** | ➔ 后端 obase.ProviderRegistry 预置路由与预设表 | 新建 `hevi/obase/provider_presets.py`：preset 策略字典（wan_local / fal_fast / autocameo_cloud / veo3_cinematic / qwen_plus / qwen_local，含 level/category/provider/strategy{face_lock,preferred,quality_bar}）；新增 `GET /api/providers/presets` + `/api/providers/presets/{name}` 路由；`resolve_preset` 对未知名回落到 wan_local（零成本默认，前端传任何名不挂）；前端仅传 preset 名称 |

## 2. §3 后端 API 整理（按 3O 规范归类）

- **Idea2Video → oprim/oskill**：统一生成能力即既有 `POST /api/pipeline/generate`（0 新增端点）；Prompt 增强在前端引擎完成，经 hub_idea2video 通道入主线。
- **Novel2Video → season_planner/omodul**：前端编排复用既有 works 端点逐集锁定（后端无季派发端点，v4.0 约束保留），解析引擎在前端。
- **AutoCameo → subjects/digital_human**：照片建角色走既有 `POST /api/subjects/from-photo`（主体库）；`ProduceRequest` 增加可选字段 `character_references` + `autocameo`（落 config_json，零回归）。
- 原 vimaxApi 指向的 `/api/director-pipeline/idea2video|novel2video|autocameo|provider-presets` 后端端点**本不存在**（纯前端演示壳），无需迁移既有 Service 函数；能力以真实通道落地。

## 3. §4 最终极简导航（6 大主节点 + 工具箱）

⚡ 极速生成 `/` · 🎙️ 解说中心 `/explainer` · 🏛️ 历史现场 `/tongjian` ·
🎬 导演流水线 `/director-pipeline` · 🎛️ 导演控制台 `/director` · 📊 生产看板 `/production`

「工具箱 ▾」弹层收纳辅助二级页：✂️ 智能拆条 `/studio/clipper` · 👤 数字人预设 `/presenters` ·
🔊 语音工作室 `/voice-studio` · 📁 数字资产 `/gallery`
「更多 ▾」折叠收纳次要工作台（系列/短剧台/画布/发布工作室/我的/价格，路由保留）

## 4. 改动文件清单

**删除**：`app/(core)/vimax/page.tsx`、`components/vimax/ViMaxConsole.tsx`、vimaxApi、VimMax 类型

**新增**：`lib/prompt-enhancer.ts`（+test）、`lib/novel2video.ts`（+test）、
后端 `hevi/obase/provider_presets.py`、`hevi/api/routers/provider_presets.py`、
`tests/test_provider_presets.py`、`docs/API-CAPABILITIES.md`（重新生成含 providers 段）

**修改**：`TopNav.tsx`（6 节点 + 工具箱）、`SimpleGenerate.tsx`（idea2video 适配器 + 增强预览 + preset 选单）、
`DirectorPipelineConsole.tsx`（Novel2Video 解析 + AutoCameo + preset）、`DirectorConsole.tsx`（②角色照片上传）、
`api-client.ts`（providerApi 替换 vimaxApi）、`types/api.ts`（ProviderPreset + DpProduceRequest + source_channel）、
`globals.css`（dp-novel/dp-cameo/hevi-home__idea/dc-char-upload）、
`hevi/api/main.py`（注册 providers 路由）、`hevi/api/routers/director_pipeline.py`（ProduceRequest 扩展）、
测试 ×3 更新（SimpleGenerate/DirectorPipelineConsole）+ 新增 2 lib 测试

## 5. 说明与遗留

- **后端 API 能力清单**：新 providers 段已通过 `scripts/export_api_inventory.py` 重新生成并入 CI 门禁。
- **AutoCameo 后端消费**：`character_references`/`autocameo` 目前透传进 config_json 供生成层读取；人脸融合原语由数字人/主体参考图链路承担（happyhorse_1_1_maas_lock 云端锁脸 provider），未新增独立 autocameo 端点（零回归约束）。
- **Novel2Video 解析为启发式前端引擎**（章节标题/对白发言人正则），非 LLM 抽取——长文本正式分集仍以 storygraph 抽取 + 立意/剧本生成闭环为准。
- 首页 idea2video 未登录时 provider 预置列表不加载（fallback wan_local），登录后自动刷新。
