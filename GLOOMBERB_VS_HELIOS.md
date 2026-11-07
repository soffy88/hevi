# Gloomberb 与 Helios 能力对比报告

本报告对标开源金融终端 **Gloomberb** (`https://github.com/gloom-sh/gloomberb`) 与单用户加密多维度信号决策平台 **Helios** (`~/projects/helios` 及其周边模块)，从多维度进行系统性对比并分析潜在融合点。

## 一、 能力对比总表

| 维度 | Gloomberb (依据: README.md, docs/, plugin-manifest.json) | Helios (依据: helios/README.md, 各 helios-* 模块) | 差异与优势判定 |
 | :--- | :--- | :--- | :--- |
 | **形态与架构** | Desktop (macOS/Windows)、TUI (Mac/Linux/Win)、Browser (`term.gloom.sh`) 三端统一；OpenTUI 驱动。 | Docker + Docker Compose 微服务架构；Web 面板 (`helios-web` Next.js) + FastAPI 后端 (`helios-api`) + Telegram Bot。 | Gloomberb 在客户端形态（桌面、TUI、Web）和跨平台体验上更强；Helios 侧重后端服务与独立微服务部署。 |
 | **资产与市场** | 股票（美股/全球）、加密货币、外汇、期权、宏观、期权/财报/新闻/大宗商品等全品类。 | 纯加密货币 (`crypto`)，聚焦单用户加密多维度信号决策。 | Gloomberb 品类极度全面；Helios 专精加密深度信号。 |
 | **数据源与流动** | 依托 Gloom Cloud (`gloom.sh/cloud`)：支持免费15分钟延迟或 Pro 实时数据。 | 采集 ~15 个外部数据源，写入 Redis `external:*`，经 environ 处理写 `environ:*`，持久化至 TimescaleDB。 | Gloomberb 依靠商业/托管云服务；Helios 自建多源采集与 Redis/TimescaleDB 流水线，数据治理更透明。 |
 | **核心算法与决策** | 丰富图表、财务报表、分析师预估、估值、AI 问答 (`Ask Gloom`)、Kelly仓位计算。 | 13 维加权融合模型 (ADR-037 三层模型：红线否决/协同核心/调整项) 生成 Fusion Score；双轨权重 Pack (`default`/`long_term`)。 | Helios 在量化合议与决策模型（13维、三层否决、双轨Pack）上极具深度；Gloomberb 偏综合终端与投研浏览。 |
 | **回测与交易** | 支持经纪商同步 (IBKR Gateway 等)、选股器、回测、仓位与风险 (PORT/MARS)。 | 当前为**顾问性质**（明确规定：不下单、不回测、不学习），但周边有 `helios-rsibt` 等部分回测模块。 | Gloomberb 具备经纪商接入与实盘/回测闭环；Helios 保持决策顾问定位。 |
 | **扩展与插件** | 完善的插件体系 (`PLUGINS.md`, `plugin-manifest.json`)：支持自定义Pane、数据源、券商接入，CLI管理(`gloomberb install`)。 | 周边模块化拆分 (`helios-tv`, `helios-linetools`, `helios-cndata`, `helios-journal`, `helios-hxbtview`, `helios-rsibt`, `helios-rsivol`, `helios-sfp`)。 | Gloomberb 插件体系标准化且生态繁荣；Helios 依赖多仓微服务协同。 |
 | **技术栈** | TypeScript / Bun / OpenTUI / Electrobun / Cloudflare workers。 | Python (FastAPI/Pandas/Redis/Postgres) + TypeScript (Next.js/React)。 | Gloomberb 强在现代 TS/TUI 与桌面端栈；Helios 强在 Python 数据管道与量化后端。 |
 | **开源许可** | MIT License (部分后端/云服务如 Gloom Cloud 闭源)。 | 私有/单用户核心。 | Gloomberb 开源生态更成熟。 |

## 二、 Helios 缺而 Gloomberb 有、值得借鉴的 Top5

1. **统一的多端架构（Desktop + 极致 TUI + Web 浏览器端）**
   - **说明**：Gloomberb 提供基于 OpenTUI 的终端 TUI、Electrobun 桌面端以及 `term.gloom.sh` 网页版，用户可在终端、桌面无缝切换。
   - **依据**：`README.md` (“Desktop app for macOS and Windows. Terminal UI for macOS, Linux, and Windows.” / “Open in browser”)。
   - **对 Helios 的借鉴意义**：Helios 目前前端依赖 Next.js (`helios-web`)，若能引入 TUI 或桌面端封装，将极大地提升量化交易员在命令行环境下的使用效率。

2. **标准化且开箱即用的插件中心 (`gloomberb install`)**
   - **说明**：Gloomberb 允许用户一键安装第三方或官方插件（面板、数据源、券商网关如 IBKR），插件与核心系统动态注册。
   - **依据**：`PLUGINS.md` (“Plugins add panes, data providers, broker connections, and commands... `gloombberb install user/repo`”) 与 `plugin-manifest.json`。
   - **对 Helios 的借鉴意义**：Helios 的各个周边能力（如 `helios-linetools`, `helios-rsibt`, `helios-sfp`）目前分散在多个 independent git repo 中，缺乏统一的插件动态挂载与市场机制。

3. **券商实盘与资产同步对接（Broker Position Sync & IBKR Gateway）**
   - **说明**：支持直接同步券商持仓、现金、目标权重和再平衡，支持 IBKR 等主流券商。
   - **依据**：`docs/usage.md` (“Broker position sync”) 与 `README.md`。
   - **对 Helios 的借鉴意义**：Helios 目前明确标注为“顾问性质（不下单）”，若未来需要打通交易闭环，可借鉴 Gloomberb 的券商集成与持仓同步设计。

4. **全面资产覆盖与内置多维度投研工具（财务、期权定价、Kelly仓位、13F导入）**
   - **说明**：内置期权定位 (`OPX`)、债务到期日分析、13F 机构持仓导入、Kelly 仓位公式 (`KELLY`)、高级财报与估值参考。
   - **依据**：`docs/usage.md` 与 `docs/` 下各类 reference 文档。
   - **对 Helios 的借鉴意义**：Helios 专注于加密信号，但在衍生品深度分析（如期权定位、机构持仓、Kelly 资金管理公式）上可吸收 Gloomberb 的专业投研模型。

5. **AI 助手原生集成 (`Ask Gloom` / MCP)**
   - **说明**：内置 AI 助手支持通过自然语言提问与查询金融数据，并支持 MCP 连接。
   - **依据**：`README.md` 与 `docs/usage.md` (“Connect an AI assistant (MCP)”)。
   - **对 Helios 的借鉴意义**：Helios 侧重固定指标与 Radar 合议，缺少自然语言交互的 AI 投研 Copilot。

## 三、 Helios 独有优势

1. **严谨的 13 维加权融合与三层否决架构（ADR-037 模型）**
   - **说明**：采用 Layer0（红线否决）、Layer1（协同核心）、Layer2（调整项）的 13 维信号融合机制，计算严密的 Fusion Score。
   - **依据**：`helios/README.md` (“13 维加权融合(ADR-037 三层模型) → Fusion Score”)。

2. **双轨权重 Pack 与合议雷达、关键时刻穿越回溯**
   - **说明**：支持 `default` 与 `long_term` 双轨权重并行对照，提供 13 维合议雷达（Signal / Weights 双模式）及历史关键时刻穿越（net_score ±5 穿越、regime 切换事件标注）。
   - **依据**：`helios/README.md` (“Pack 双轨”, “13 维合议雷达”, “历史关键时刻穿越”)。

3. **完备的数据管道与异常监测架构**
   - **说明**：数据采集写入 Redis `external:*`，经 environ 处理写入 `environ:*`（ADR-046），时序数据落地 TimescaleDB，并配有黑天鹅异常检测与数据源 stale 告警。
   - **依据**：`helios/README.md` (“采集与处理”, “告警”)。

## 四、 可行的结合方式

1. **Helios 作为 Gloomberb 的加密/量化信号插件**
   - **方案**：将 Helios 的 13 维合议雷达、Fusion Score 及加密多源采集能力封装为 Gloomberb 的一个官方插件（如 `gloom-sh/gloom-helios`），使 Gloomberb 用户在终端内即可直接查看 Helios 的加密决策看板。
   - **依据**：Gloomberb 插件机制 (`PLUGINS.md`) 支持添加自定义 Pane 与数据源。

2. **数据管道与微服务架构复用**
   - **方案**：Gloomberb 依赖云端 (`Gloom Cloud`)，而 Helios 拥有成熟的 Python 异步采集与 TimescaleDB 时序落库能力。Gloomberb 的自托管节点可借鉴 Helios 的 Redis/TimescaleDB 流水线来实现离线/自托管的高性能行情存储。
   - **依据**：Helios README 中的采集与 Redis/TimescaleDB 架构说明。

3. **命令系统与交互体验互相渗透**
   - **方案**：Helios 的 Web 面板结合 Gloomberb 快捷的命令栏 (`Ctrl+P` / `` ` `` 快捷键与命令语意) 和 OpenTUI 技术栈，打造专为量化交易员设计的全功能终端/桌面混合客户端。
   - **依据**：Gloomberb `docs/usage.md` 的命令参考与 Helios 前端交互需求的互补。
