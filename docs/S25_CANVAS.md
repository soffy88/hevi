# S25 画布增强（对话建画布 / 模板版本 / 报价 / 备份 / 报错 / 素材 / 技能）

本文件说明 `hevi/canvas/*_s25.py` 与 `/api/canvas/s25/*` 的用法与边界。
能力对标来自 BeefTV 的公开文档，实现全部自写（见 NOTICE）。

## 1. 对话建画布

```
POST /api/canvas/s25/plan
{"prompt":"用 60 秒讲清楚复利为什么反直觉","format":"explainer","use_llm":false}
→ {"plan":{...},"summary":{...},"script_source":"offline"}
POST /api/canvas/s25/plan/patch   # 改单个节点，重算报价与确认令牌
POST /api/canvas/s25/plan/apply   # 校验 confirm_token 后建图（save=true 落库）
```

- 形式解析复用 S21 `resolve_format`；内部 line_id 不出现在方案里。
- 离线路径确定性（无网络、毫秒级）；`use_llm=true` 时调用现有 `script.quick`，
  失败自动退回离线脚本，并在响应里说明 `script_source`。
- 方案包含：节点/连线（只用现有 7 类节点与 16 条合法边）、步骤进度、待确认项、
  逐节点报价与合计、未定价项。确认令牌覆盖方案内容，改过就必须重新确认。
- 确认后仍可改单节点：`patch` 只动该节点（必要时同步分镜时长），不改其它节点。

## 2. 带版本的工作流模板

```
GET  /api/canvas/s25/templates?format=explainer
GET  /api/canvas/s25/templates/{id}?version=1
POST /api/canvas/s25/templates                # 新建（v1）
POST /api/canvas/s25/templates/{id}/versions  # 发布新版本（旧版本不变）
GET  /api/canvas/s25/templates/{id}/diff?from_version=1&to_version=2
POST /api/canvas/s25/templates/{id}/apply     # 指定版本 + 槽位值 → 新画布
```

- 每个出品形式首次读取时生成 1 个内置模板（7 个），不调用模型。
- 槽位只暴露内容字段（topic/content/text/prompt/media_path 等），不暴露结构与工具 id。
- 存储：`output/canvas_templates/`（容器持久卷），原子写；无数据库迁移。

## 3. 生成前费用预估

```
POST /api/canvas/s25/estimate {"graph": {...}}  或  {"graph_id":"..."}
```

- 单价只来自 `hevi.cost.pricing_table`，汇率 `HEVI_USD_CNY`（默认 7.2），
  与 S22 `craft_ledger` 的逐镜报价同一函数。
- 视频/片段按秒；本地音频（edge_tts/voicebox 等）为 0；图片按张计费无统一价 →
  单列 `unpriced`，不计入合计；未知渠道也单列，不按 0 元冒充免费。
- 传 `plan_id` 时返回与账本的偏差（`compare_with_ledger`）。

## 4. 备份导出 / 导入

```
GET  /api/canvas/s25/backup?graph_id=...
POST /api/canvas/s25/backup/verify
POST /api/canvas/s25/backup/import   # save=true 落成新画布
```

- `schema=hevi.canvas.backup.v1` + `checksum`（规范化 JSON 的 SHA-256）。
- 校验：节点 id 唯一、边端点存在、边类型合法（`EDGE_MATRIX`）、媒体存在性。
- 媒体清单只收本地路径且必须在 `data/output/assets` 内；http/`data:` 不收。
- 导入默认拒绝校验和不一致；`allow_checksum_mismatch=true` 仍做结构校验。

## 5. 失败节点可读化

```
GET  /api/canvas/s25/diagnostics/{graph_id}
POST /api/canvas/s25/diagnostics/explain
```

- 归 9 类：额度 / 鉴权 / 限流 / 超时 / 网络代理 / 上游 / 参数 / 素材 / 配置，
  其余归“未归类”；每类给标题、说明、动作、是否可重试。
- 报错文本会脱敏：密钥、Bearer、URL 查询串不原样回显。
- 前端节点与 Inspector 显示原因与“一键重试”；重试走既有单节点重跑。

## 6. 素材加工

```
GET  /api/canvas/s25/material/capabilities
POST /api/canvas/s25/material/op   (multipart: file, op, params)
```

- 离线可用：`crop`（像素框）、`split_grid`（1–10 行/列，最多 100 格）、
  `annotate`（框/箭头/文字）。
- `inpaint` 需要模型/GPU：本机没有 → `available=false`，前端显示“即将开放”，
  不排队、不扣费。上传上限 24MB，只接受 png/jpg/webp/mp4/mov/mp3/wav。

## 7. 技能库 / 个人资产库 / 插件契约

- `GET /api/canvas/s25/skills`：3 个自写文字技能（双镜头文字分镜、采访提纲、
  素材清单与授权记录），带 `version` + `sha256` + 可回退历史版本 + 启停。
- `GET/POST/DELETE /api/canvas/s25/library`：按用户隔离、只存引用、最多 500 条。
- `GET /api/canvas/s25/plugin-contract`：内部插件契约（权限白名单、超时上限 300s、
  `paid_generation` 必须能报价）。**不开放第三方安装**。

## 8. MCP 加固

- `/mcp` 仍要求 Bearer token；新增按用户限流（默认 30 次/60 秒，
  `HEVI_MCP_RATE_LIMIT` 可调）。
- `HEVI_MCP_READ_ONLY=1` 时只放行查询类工具（`.list/.get/.status/.capabilities`），
  写/付费工具 403。
- 风险：插件化 MCP 仍可读工作区允许目录、可外联；对外前需进程隔离、出站白名单与审计。
