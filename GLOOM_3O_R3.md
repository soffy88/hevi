# Gloom 3O 内化第三轮执行报告

日期：2026-10-20  
分支：各代码库均为 `feat/gloom-3o`  
结果：a–g 的实现均已提交；未 push、未 merge、未重启生产容器。所有市场快照和 API 响应证据均来自本轮真实运行。根目录 `/home/soffy/projects/gloom3o` 不是 Git 仓库，`NET.md` 与 `evidence/` 保留在该目录。

## 网络前置检查

- `/home/soffy/projects/gloom3o/NET.md`（`wc -l`: 15）记录实测代理。宿主机 `http://127.0.0.1:7890` 可访问 Deribit 和 OKX；Helios Docker 网络内使用 `http://proxy:2080`。`helios-proxy` 没有发布宿主端口。
- HTTPS 客户端通过 `HTTPS_PROXY` 使用代理；不在宿主机上把 Docker 别名 `proxy` 当作可解析主机名。

## a. oprim Kelly 与风险计算

- **提交**：`oprim` `7e516c204cbb5e9553e53ffc8832370059e38e3f`
- **实现**：离散 Kelly、连续 Kelly、分数 Kelly、上下限截断；历史/参数 VaR、CVaR、最大回撤；补齐 Pearson/Spearman/Kendall 相关矩阵校验。移除旧版按敞口硬编码 2% 的 VaR 代理，缺收益观测时 fail-closed。
- **新增/修改文件（路径：wc -l）**：
  - `oprim/oprim/risk/kelly_position.py` — 207
  - `oprim/oprim/risk/__init__.py` — 31
  - `oprim/oprim/_signal_analysis.py` — 486
  - `oprim/tests/risk/test_kelly_position.py` — 113
- **pytest 原始输出末行**：`============================== 86 passed in 1.04s ==============================`
- **Evidence**：纯计算项，无市场样例文件。
- **未完成**：无。

## b. Deribit/OKX 期权适配器与指标

- **提交**：
  - `obase` `7198136531654f185dccafe839bf056d2d78458a`
  - `oprim` `e941da2b7a810a00273491c4f7ea8aa9102f73fc`
- **实现**：公共适配器具备 timeout、重试、进程内 TTL cache，并读取 `HTTPS_PROXY`；指标包括按到期 OI、max pain、OI PCR、ATM IV、25d skew、带明示符号假设的 GEX 近似。Deribit/OKX 返回字段统一成同一链格式。
- **新增/修改文件（路径：wc -l）**：
  - `obase/obase/options_marketdata.py` — 265
  - `obase/tests/test_options_marketdata.py` — 149
  - `oprim/oprim/derivatives/analytics.py` — 291
  - `oprim/oprim/derivatives/__init__.py` — 34
  - `oprim/tests/derivatives/test_analytics.py` — 128
  - `oprim/tests/derivatives/test_options_live_integration.py` — 78
- **pytest 原始输出末行**：
  - 全量相关计算测试：`======================== 373 passed, 1 skipped in 7.70s ========================`
  - obase 适配器单测：`7 passed, 1 warning in 0.23s`
  - 真实联网 integration：`============================== 1 passed in 2.37s ===============================`
- **Evidence**：`evidence/options_live.json`（`wc -l`: 434），含两家 provider 时间戳和本轮真实 API 摘要。抓取到 Deribit 880 条/11 个到期桶、OKX 914 条/13 个到期桶；详细数值以该文件为准。GEX 明确标为持仓侧近似，不声称是 dealer 实际净仓。
- **未完成**：无。期权链数值随市场变化，报告不复制成固定报价。

## c. oservi 命令解析、分发与 CLI

- **提交**：`oservi` `19f7ec985be44fe7d2601aac3de6b14422ab80dd`
- **实现**：QUOTE/DES/GP/OPX/KELLY/RISK/PORT/FUSION/HELP 的 shell quoting、位置参数、键值参数与 handler 分发；新增 `gloom3o` CLI。Kelly/Risk/OPX 调真实库逻辑；需要 Helios 数据的命令无数据源时显式报错，不返回占位数值。
- **新增/修改文件（路径：wc -l）**：
  - `oservi/README.md` — 83
  - `oservi/pyproject.toml` — 59
  - `oservi/oservi/cli.py` — 41
  - `oservi/oservi/gloom3o/__init__.py` — 21
  - `oservi/oservi/gloom3o/commands.py` — 273
  - `oservi/tests/test_gloom3o_commands.py` — 149
- **pytest 原始输出末行**：`22 passed in 1.26s`
- **Evidence**：无固定行情数据。
- **未完成/限制**：GP 目前没有已确认的数据后端，API 返回明确 unavailable；外部命令需要设置 `GLOOM3O_HELIOS_URL`。

## d. 插件 manifest、发现与版本/依赖校验

- **提交**：`helios` `650ef9e2ed9e754aca9563601573b0f7894a6b34`
- **实现**：严格 manifest schema 校验、内存注册与重名拒绝、依赖缺失/版本约束检查；只读发现 `~/projects/helios-*` 目录，不 import/执行被发现代码。
- **新增文件（路径：wc -l）**：
  - `helios/api/app/services/gloom3o_plugins.py` — 333
  - `helios/api/tests/test_gloom3o_plugins.py` — 182
- **pytest 原始输出末行**：`20 passed in 0.04s`
- **Evidence**：`evidence/plugins_discovery.json`（`wc -l`: 133）。实际扫描到 11 个 Helios 仓库；0 个仓库含本服务认可的显式 manifest，全部是 `metadata_only`，没有虚报为已注册插件。
- **未完成/限制**：当前工作区没有可注册的 Helios 插件 manifest，因此本轮没有活动插件实例；为其他仓库补 manifest 需要各模块维护者提供声明。

## e. oskill 自然语言路由与 oservi MCP

- **提交**：
  - `oskill` `497089ea5366200d84a20023d5a734b58e3ce97c`
  - `oservi` `9fc9b9d3b0d602e759f1f82c47b4019ff834a3d5`
- **实现**：无 LLM key 时确定性规则路由；只有显式 key 与注入的 LLM caller 同时存在才调用 LLM，失败或非法结果退回规则，不补造参数。MCP server 使用官方 Python SDK，提供与九个命令对应的工具；移除了旧 Q&A/MCP stub 中的硬编码行情与持仓数。
- **新增/修改文件（路径：wc -l）**：
  - `oskill/oskill/gloom3o_router.py` — 231
  - `oskill/oskill/ai_qa/copilot_skill.py` — 42
  - `oskill/tests/test_gloom3o_router.py` — 119
  - `oskill/tests/ai_qa/test_copilot_skill.py` — 17
  - `oservi/oservi/mcp_helios/server.py` — 148
  - `oservi/oservi/mcp_helios/mcp_exposure.py` — 15
  - `oservi/tests/mcp_helios/test_mcp_exposure.py` — 84
  - `oservi/pyproject.toml` — 59
  - `oservi/uv.lock` — 2756
- **pytest 原始输出末行**：
  - oskill：`============================== 19 passed in 0.89s ==============================`
  - oservi CLI + MCP：`25 passed in 2.50s`
  - MCP SDK v1.27.1 tools/list：`3 passed in 0.73s`
- **Evidence**：`evidence/mcp_tools_list.json`（246 行，SDK v2.0.0）及 `evidence/mcp_tools_list_v1.json`（290 行，SDK v1.27.1）。均由 SDK client 对本地 MCP server 实际执行 `initialize` 和 `tools/list` 得到，列出 9 个工具。
- **未完成/限制**：没有真实 LLM key，本轮只实测规则降级和注入式 LLM 单测，没有调用外部 LLM 服务。

## f. OKX v5 只读签名与 portfolio 降级

- **提交**：
  - `obase` `5109df33e224ca1a3eefc0f958222a02377da624`
  - `omodul` `740cf4833bfd534059f4eb7c70a8b5dcc686fa24`
- **实现**：按 OKX v5 timestamp + uppercase method + requestPath + body 做 Base64 HMAC-SHA256；只允许 GET balance/positions，没有下单/转账方法。无凭据时不发 HTTP 请求并降级。同步模块移除了旧的 `15000/45000` 假持仓额。
- **新增/修改文件（路径：wc -l）**：
  - `obase/obase/brokers/okx_readonly.py` — 157
  - `obase/tests/test_okx_readonly_signing.py` — 155
  - `omodul/omodul/brokers/portfolio_sync.py` — 58
  - `omodul/tests/brokers/test_portfolio_sync.py` — 60
- **pytest 原始输出末行**：`7 passed, 1 warning in 0.02s`；`omodul`：`============================== 3 passed in 1.41s ===============================`
- **Evidence**：`evidence/okx_readonly.json`（22 行），记录无 key 降级及官方文档签名向量的实测计算结果。
- **未完成/限制**：未提供 OKX API 凭据，因此没有请求真实私有 balance/positions；这两个私有端点仅由签名/MockTransport 单测覆盖，未声称验证了真实账户数据。

## g. Helios Gloom API

- **提交**：`helios` `e773965b1132d93bfb847400bf056ca8f15083b5`
- **实现**：新增 `/api/gloom/options`、`/commands`、`/risk`、`/plugins`，`GLOOM3O_ENABLED` 默认关闭；Fusion 路径只读，不修改现有 Fusion Score。新增真实网络 opt-in 测试与 API 返回 evidence。另在回环地址启动本地 Uvicorn、`--lifespan off`，测试后停止；没有启动/重启生产容器，也没有连 Redis/DB。
- **新增/修改文件（路径：wc -l）**：
  - `helios/api/app/main.py` — 732
  - `helios/api/pyproject.toml` — 29
  - `helios/api/app/routers/gloom.py` — 239
  - `helios/api/tests/test_gloom3o_routes.py` — 136
  - `helios/api/tests/test_gloom3o_routes_integration.py` — 86
- **pytest 原始输出末行**：
  - TestClient：`8 passed, 1 warning in 3.01s`
  - 真实公开 API integration：`1 passed, 1 warning in 3.85s`
- **Evidence**：`evidence/api_options.json`（437 行）、`api_commands.json`（21 行）、`api_risk.json`（38 行）、`api_plugins.json`（120 行）、`api_local_server.json`（580 行）。Risk 输入收益来自同轮 OKX BTC-USDT 日线收盘数据；所有响应均保存原始 JSON。
- **未完成/限制**：GP 的数据源尚未配置，接口明确返回 unavailable；插件 API 实际发现 0 个显式 manifest；单独 Uvicorn 使用 `--lifespan off` 仅验证路由与公网期权连接，不是完整 Redis/DB 生产栈启动。

## 共享工作区与安全边界

- `NET.md` 和 `evidence/` 已写入 `/home/soffy/projects/gloom3o/`。各组件代码仅在对应 `feat/gloom-3o` 仓库提交；没有 push/merge。
- `oservi` 中已有的 `__pycache__` 跟踪文件修改/未跟踪缓存未纳入提交，保持原样。
- `hevi` 工作区本来有其他未提交文件；本报告只新增到用户指定路径，没有暂存或提交那些文件。
- Gloomberb 按 MIT 许可检查并在相关代码头注明；本轮没有复制其源码。OKX 签名公式引用其官方 REST Authentication 文档。

G3O3_DONE
