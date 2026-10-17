# hevi 后端 API 能力清单

> 所有路由前缀均为 `/api`，基于 `hevi/api/main.py` 注册状态。
> 生成日期: 2026-07-31

---

## 🏥 系统 & 监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |
| — | `/mcp` | MCP Agent 入口 (Streamable HTTP) |

---

## 🔐 认证 (`/api/auth`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/register` | 注册 |
| POST | `/login` | 登录 |
| GET | `/me` | 获取当前用户 |
| POST | `/google` | Google OAuth 登录 |

---

## 💰 积分 & 支付

### 积分 (`/api/credits`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/balance` | 查询余额 |
| GET | `/transactions` | 交易流水 |
| POST | `/estimate` | 费用预估 |
| POST | `/topup` | 充值 |

### 支付 (`/api/payment`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/plans` | 套餐列表 |
| POST | `/checkout` | 下单支付 |
| POST | `/webhook` | 支付回调 |
| GET | `/orders` | 订单列表 |

---

## 📋 任务系统 (`/api/tasks`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/estimate` | 任务费用预估 |
| POST | `/` | 创建任务 (2个入口) |
| GET | `` | 任务列表 |
| GET | `/{task_id}` | 任务详情 |
| POST | `/{task_id}/resume` | 恢复任务 |
| POST | `/{task_id}/regenerate` | 重新生成 |
| GET | `/{task_id}/progress` | 进度查询 |
| GET | `/{task_id}/video` | 获取视频 |
| GET | `/{task_id}/cover` | 获取封面 |
| GET | `/{task_id}/export` | 导出 |
| GET | `/{task_id}/dub` | 配音结果 |
| GET | `/{task_id}/continuity-report` | 连贯性报告 |
| GET | `/{task_id}/shots` | 镜头列表 |

---

## 🎬 导演系统

### 导演控制台 (`/api/director`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/plan` | 导演规划 |
| POST | `/episodes` | 生成集数 |
| POST | `/render` | 渲染 |

### 导演流水线 (`/api/director-pipeline`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/works` | 创建作品 |
| GET | `/works` | 作品列表 |
| GET | `/works/{work_id}` | 作品详情 |
| POST | `/works/{work_id}/concept` | 生成概念 |
| POST | `/works/{work_id}/concept/lock` | 锁定概念 |
| POST | `/works/{work_id}/screenplay` | 生成剧本 |
| POST | `/works/{work_id}/screenplay/lock` | 锁定剧本 |
| POST | `/works/{work_id}/design-list` | 生成设计清单 |
| POST | `/works/{work_id}/design-list/lock` | 锁定设计清单 |
| POST | `/works/{work_id}/world-bible` | 生成世界观圣经 |
| POST | `/works/{work_id}/world-bible/lock` | 锁定世界观 |
| POST | `/works/{work_id}/scene-script` | 生成分场脚本 |
| POST | `/works/{work_id}/scene-script/lock` | 锁定分场 |
| POST | `/works/{work_id}/produce` | 启动制作 |
| GET | `/provider-presets` | 供应商预设列表 |
| GET | `/provider-presets/{name}` | 单个预设详情 |
| POST | `/idea2video` | 创意→视频 |
| POST | `/novel2video` | 小说→视频 |
| POST | `/autocameo` | 自动客串 |

---

## 📺 通鉴 (`/api/tongjian`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/run` | 启动运行 |
| GET | `/runs` | 运行列表 |
| GET | `/runs/{run_id}` | 运行详情 |
| GET | `/runs/{run_id}/script` | 获取脚本 |
| PUT | `/runs/{run_id}/script` | 更新脚本 |
| POST | `/runs/{run_id}/resume` | 恢复运行 |
| POST | `/runs/{run_id}/regenerate` | 重新生成 |
| GET | `/runs/{run_id}/video` | 获取视频 |

---

## 🎭 短剧 (`/api/shortdrama`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/runs` | 创建运行 |
| GET | `/runs` | 运行列表 |
| GET | `/runs/{run_id}` | 运行详情 |
| POST | `/runs/{run_id}/replan` | 重新规划 |
| POST | `/runs/{run_id}/develop` | 故事开发 |
| POST | `/runs/{run_id}/characters/{char_id}/upload` | 上传角色图 |
| POST | `/runs/{run_id}/confirm` | 确认运行 |

---

## 🎨 创意工具 (`/api/creative`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/capabilities` | 创意能力列表 |
| POST | `/three-view` | 三视图生成 |
| POST | `/storyboard` | 分镜生成 |
| POST | `/story-predict` | 故事预测 |
| POST | `/multi-angle` | 多角度生成 |
| POST | `/transition` | 转场生成 |
| POST | `/element-edit` | 元素编辑 |
| POST | `/workflow/character-consistency` | 角色一致性工作流 |
| POST | `/workflow/storyboard` | 分镜工作流 |
| POST | `/workflow/comic-to-animation` | 漫画→动画 |

---

## 🖼 角色资产 (`/api/subjects`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `` / `/` | 创建角色 |
| POST | `/from-photo` | 从照片创建 |
| POST | `/{subject_id}/reference` | 上传参考图 |
| POST | `/{subject_id}/references` | 批量上传参考 |
| PUT | `/{subject_id}/references` | 更新参考图 |
| PUT | `/{subject_id}/reference-role` | 设置参考角色 |
| POST | `/{subject_id}/voice` | 绑定语音 |
| POST | `/{subject_id}/wardrobe` | 设置服装 |
| GET | `` / `/` | 角色列表 |
| GET | `/{subject_id}/image` | 获取角色图 |
| GET | `/{subject_id}` | 角色详情 |
| PATCH | `/{subject_id}` | 更新角色 |
| DELETE | `/{subject_id}` | 删除角色 |

---

## 🎨 画布/图引擎 (`/api/canvas`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/reference-image` | 上传参考图 |
| POST | `` | 保存图 (Graph) |
| GET | `` | 图列表 |
| POST | `/graphs` | 保存图 (legacy) |
| GET | `/graphs` | 图列表 (legacy) |
| GET | `/graphs/{graph_id}` | 图详情 (legacy) |
| PATCH | `/graphs/{graph_id}` | 更新图 (legacy) |
| DELETE | `/graphs/{graph_id}` | 删除图 (legacy) |
| POST | `/graphs/{graph_id}/execute` | 执行图 (legacy) |
| GET | `/{graph_id}` | 图详情 |
| PATCH | `/{graph_id}` | 更新图 |
| DELETE | `/{graph_id}` | 删除图 |
| POST | `/{graph_id}/execute` | 执行图 |

---

## 🎙 音频库 (`/api/audio`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `` / `/` | 上传音频 |
| GET | `` / `/` | 音频列表 |
| GET | `/{asset_id}` | 音频详情 |
| DELETE | `/{asset_id}` | 删除音频 |

---

## 📐 模板 (`/api/templates`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `` / `/` | 创建模板 |
| GET | `` / `/` | 模板列表 |
| GET | `/{template_id}` | 模板详情 |
| POST | `/{template_id}/apply` | 应用模板 |
| DELETE | `/{template_id}` | 删除模板 |

---

## 📚 系列 (`/api/series`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `` | 创建系列 |
| GET | `` | 系列列表 |
| GET | `/{series_id}` | 系列详情 |
| GET | `/{series_id}/episodes` | 集数列表 |
| POST | `/{series_id}/episodes` | 添加集数 |

---

## 🎨 风格包 (`/api/style-packs`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `` | 创建风格包 |
| POST | `/draft-from-reference` | 从参考生成草稿 |
| GET | `/{pack_id}` | 风格包详情 |
| GET | `/{pack_id}/resolve` | 解析风格包 |
| PATCH | `/{pack_id}` | 更新风格包 |

---

## 💻 代码解释器 (`/api/explainer`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/run` | 运行解释 |
| GET | `/runs` | 运行列表 |
| GET | `/runs/{run_id}` | 运行详情 |

---

## 🖼 画廊 (`/api/gallery`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `` | 画廊列表 |
| POST | `` | 上传画廊项 |
| GET | `/{item_id}` | 画廊项详情 |

---

## 🔧 制片工具

### v1 (`/api/production`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/reference-analyze` | 参考资料分析 |
| GET | `/stock/search` | 素材搜索 |
| GET | `/stock/match` | 素材匹配 |
| POST | `/enhance/{tool}` | 画面增强 |
| GET | `/playbooks` | 制作手册列表 |
| POST | `/playbooks/compile` | 编译制作手册 |
| POST | `/render/remotion` | Remotion 渲染 |
| POST | `/edit/talking-head-cleanup` | 口播出片清理 |
| POST | `/edit/render-edl` | EDL 渲染 |
| GET | `/media-profiles` | 媒体配置文件 |
| GET | `/media-profiles/{name}/ffmpeg-args` | FFmpeg 参数 |
| GET | `/backlot/{task_id}` | 后台任务状态 |

### v2 (`/api/production/v2`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/seedance/generate` | Seedance 视频生成 |
| POST | `/clip-video` | 视频剪辑 |
| POST | `/clip-video/upload` | 上传剪辑视频 |
| GET | `/recipes` | 配方列表 |
| GET | `/recipes/{name}` | 配方详情 |
| POST | `/recipes/{name}/execute` | 执行配方 |
| POST | `/digital-human/preflight` | 数字人预检 |
| POST | `/digital-human/preview` | 数字人预览 |
| POST | `/digital-human/approve` | 数字人审批 |
| POST | `/digital-human/generate` | 数字人生成 |

---

## 🏢 发布工作室 (`/api/studio`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/publish` | 发布内容 |
| POST | `/publish/batch` | 批量发布 |
| POST | `/publish/confirm` | 确认发布 |
| POST | `/publish/schedule` | 定时发布 |
| GET | `/publish/platforms` | 发布平台列表 |
| GET | `/motion/templates` | 动效模板 |
| POST | `/motion/render` | 动效渲染 |
| GET | `/html-video/templates` | HTML 视频模板 |
| POST | `/html-video/render` | HTML 视频渲染 |
| POST | `/html-video/script-to-video` | 脚本→视频 |
| POST | `/voice/clone` | 语音克隆 |
| POST | `/voice/dub` | 配音 |
| POST | `/voice/audiobook` | 有声书 |
| POST | `/voice/dictate` | 口述转文字 |
| POST | `/voice/diarize` | 说话人分离 |
| POST | `/voice/design` | 语音设计 |
| GET | `/voice/local-voices` | 本地语音列表 |
| POST | `/dance/generate` | 舞蹈生成 |
| GET | `/dance/genres` | 舞蹈风格列表 |
| GET | `/dance/gpu-check` | GPU 状态检查 |

---

## 🎯 专业工作室 (`/api/pro`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/indextts/synthesize` | IndexTTS 合成 |
| POST | `/indextts/emotion-from-text` | 从文字提取情感 |
| GET | `/indextts/emotions` | 情感列表 |
| POST | `/stock/search` | 素材搜索 |
| POST | `/stock/script-to-clips` | 脚本→片段 |
| POST | `/livestream/start` | 开始直播 |
| POST | `/livestream/stop` | 停止直播 |
| GET | `/livestream/status` | 直播状态 |
| POST | `/livestream/products` | 添加直播商品 |
| GET | `/livestream/products` | 直播商品列表 |
| POST | `/livestream/chat-reply` | 直播弹幕回复 |
| POST | `/orchestration/create-plan` | 编排-创建计划 |
| POST | `/orchestration/execute` | 编排-执行 |
| GET | `/orchestration/roles` | 编排角色列表 |
| POST | `/code-explainer/generate` | 代码解释生成 |
| POST | `/code-explainer/highlight` | 代码高亮 |

---

## 🔊 语音工作室 (`/api/voice-studio`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/effects/presets` | 音效预设 |
| POST | `/effects/preview` | 音效预览 |
| GET | `/personality/presets` | 人设预设 |
| POST | `/personality/rewrite` | 人设改写 |
| GET | `/tts/engines` | TTS 引擎列表 |
| POST | `/tts/synthesize` | TTS 合成 |
| POST | `/config/validate` | 配置校验 |

---

## 🤖 AI 模型 (`/api/ai-models`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/execute` | 执行模型 |
| GET | `/analytics` | 模型分析 |
| POST | `/evaluate-model` | 模型评估 |
| POST | `/optimize-request` | 请求优化 |
| GET | `/health` | 模型健康检查 |

---

## 🧠 记忆 (`/api/memory`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/remember` | 存储记忆 |
| POST | `/recall` | 召回记忆 |
| POST | `/summarize` | 记忆摘要 |
| GET | `/{namespace}/stats` | 命名空间统计 |
| DELETE | `/{namespace}` | 删除命名空间 |

---

## 🔌 供应商 (`/api/providers`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `` | 供应商列表 |
| GET | `/yaml` | YAML 格式供应商 |
| POST | `/reload` | 重新加载供应商 |
| POST | `` | 注册供应商 |
| PUT | `/{name}` | 更新供应商 |
| DELETE | `/{name}` | 删除供应商 |
| GET | `/{category}/{name}` | 单个供应商详情 |

---

## 📖 故事图谱 (`/api/storygraph` — 未注册)

> ⚠️ 路由文件存在但未在 `main.py` 中注册，当前不可访问。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/extract` | 提取故事图谱 |
| GET | `` | 图谱列表 |
| GET | `/{record_id}` | 图谱详情 |
| DELETE | `/{record_id}` | 删除图谱 |
| POST | `/{record_id}/chapters` | 章节拆分 |

---

**总计: 25 个模块, 约 140+ 个 API 端点**
