# LT-R1 执行结果

## 变更

- 分支：`feat/linetools`，基于 `origin/main` 的 `caa41b4`。
- `c515ff3 feat(tape): integrate lightweight chart line tools`：升级 Lightweight Charts v5、八类绘图工具、绘图状态 API 与隔离存储测试、其他折线图 API 迁移。
- `0ef466c build(web): allow pinned line-tool package build scripts`：为精确列出的八个上游插件增加构建脚本 allowlist。
- 当前分支比 `origin/main` ahead 2；遵守用户之前的明确要求，没有 push，没有 merge，没有重启服务。

## 验收

| 检查 | 结果 |
|---|---|
| `npm run build`（标准环境） | PASS，exit 0；`/[locale]/tape` 路由产出 |
| `uv run --frozen --with pytest pytest -q tests/test_chart_drawings.py` | PASS，6 passed，1 warning |
| `uv run --frozen python -m compileall -q app/routers/chart_drawings.py app/main.py` | PASS |
| `git diff --check` | PASS |
| headless browser `/en/tape` | PASS：8 个可见绘图工具按钮，10 个非空 canvas |
| 前端绘图保存烟测 | PASS：趋势线按钮激活后在图表上放置两点，API 捕获到 `PUT /api/chart-drawings/BTCUSDT`，状态 910 bytes |

## 截图与证据

- `/home/soffy/projects/lt3o/evidence/btc-kline-linetools.png`（1600×1114）
- `/home/soffy/projects/lt3o/evidence/btc-kline-linetools-selected.png`（1600×1114）
- `evidence/playwright-smoke.log`：浏览器检查、按钮/画布计数、请求日志与持久化状态长度。
- `evidence/web-build.log`、`evidence/backend-test.log`：最终构建与单测日志。
- 行情 fixture 来源为 Coinbase Exchange 公开 BTC-USD 1 分钟 candles，转换后用于本机浏览器 smoke。由于网络侧 Binance API 返回 HTTP 451，且 `localhost:18081` 没有正在运行的 tape API，smoke 使用本地短生命周期 test double；它验证了页面绘图交互及请求契约，但不等价于连接生产 API/Redis 的端到端测试。
- Playwright 提供的 Chromium 安装器拒绝 Ubuntu 26.04 平台，因此实际截图由 Mozilla Firefox 158 headless + WebDriver 采集；没有伪称为 Playwright 浏览器执行。

## 未完成/范围说明

- 严格限制在当前 `lt3o` 工作区内，所以本结果与兼容性评估也保存在 `lt3o/LT_R1.md`、`lt3o/LINETOOLS_VS_HELIOS.md`；没有写入工作区外的 `~/projects/hevi/`。
- 后续在真实集成环境仍需验证实际会话 Cookie、API/Redis、websocket 行情、刷新后恢复；本轮未连接或重启运行中的服务。
- 分支保持本地 ahead 2，未推送。嵌套 Helios worktree 只留 Local2 创建的未跟踪 `.veya/` 元数据；未将该目录加入提交。

LT_DONE
