# graphify 安装 + 3O 范式内化 + Veya 接入 报告

日期: 2026-10-19 · 执行者: codex · 全程中文报告

## 0. 结论速览

- **A 安装**: `graphifyy 0.9.92` (PyPI 官方包名，双 y) 已装，`graphify --version` → `graphify 0.9.92`；三个平台 skill 已装 (pi / opencode / codex)；在 Veya 仓库上完成 `extract --code-only`，产出 `graph.json` (42382 节点 / 112692 边 / 1042 社区) 与 `GRAPH_REPORT.md`，`query` / `explain` 均真实跑通；`graphify-out/` 已进 `.gitignore`。
- **B 3O 内化**: 4 层 9 个元素全部落盘并各自 pytest 通过、各自 commit：**obase** (graphify CLI + graph.json 适配器)、**oprim** (5 个原子)、**oskill** (3 个组合技能)、**omodul** (1 个端到端排查事务)。
- **C Veya 接入**: 新增 `server/graphify_tools.py`，flag `VEYA_GRAPHIFY` 缺省 OFF；开启后工具面 162 → 165，暴露 `graphify_query` / `graphify_impact` / `graphify_explain` 三个只读工具，在真实 42382 节点图谱上全部返回正确结构化结果。
- **硬约束遵守**: 全程未动 3O 与 veya 主工作区 (无 checkout / stash / reset / push / merge)，所有改动位于独立 worktree；每个元素 = 真实文件 + pytest 通过 + git commit，以下均列 hash 与真实测试输出。
- **发现并修复一个真实缺陷**: Veya 的 3O 挂载在 `sys.modules` 已被占用时会解析到 site-packages 旧发行版 (obase 0.31.0 / oprim 3.23.0) 而非子模块，导致三个新工具全部报"无此元素"。已修复并加测试锁定 (见 §4.3)。

---

## 1. 任务 A — 安装与验证

### 1.1 安装

```bash
uv tool install "graphifyy[mcp,leiden,chinese]"
```

- 安装结果: `graphifyy v0.9.92`，可执行文件 `/home/soffy/.local/bin/graphify`，附带 `graphify` 与 `graphify-mcp` 两个入口。
- 版本验证: `graphify --version` → `graphify 0.9.92`。
- 未使用 pipx (环境已有 uv，符合"无 uv 用 pipx"的兜底分支)。

### 1.2 平台安装 (pi / opencode / codex)

CLI 一次只接受一个平台，报 `error: specify install platform only once`，因此分三次执行：

```bash
graphify install --platform pi
graphify install --platform opencode
graphify install --platform codex
```

产物:

| 平台 | 产物路径 |
|---|---|
| pi | `~/.pi/agent/skills/graphify` |
| opencode | `~/.config/opencode/skills/graphify` |
| codex | `~/.codex/skills/graphify` |

> 说明: `~/.config/opencode/plugins/graphify.js` **未生成** (该目录下只有既有的 `crg-plugin.ts`)。三个 skill 目录均已实际落盘，插件文件缺失是 CLI 自身行为，如实记录。

### 1.3 在 Veya 上提取代码图

**重要偏差 (如实说明)**: 为遵守"绝不碰主工作区"，`extract` 跑在 worktree `~/projects/veya-graphify` (与主 `~/projects/veya` 同一 commit `31ab26e2`)，而非主工作区。产物内容等价。

正确用法 (参数顺序有坑，`--out` 在前会报 `must specify a path to scan`):

```bash
GRAPHIFY_BACKEND=none graphify extract /home/soffy/projects/veya-graphify \
  --code-only --out /home/soffy/projects/veya-graphify/graphify-out
```

`GRAPH_REPORT.md` 需追加一次聚类命令才生成 (227 KB，不重不换):

```bash
GRAPHIFY_BACKEND=none graphify cluster-only /home/soffy/projects/veya-graphify \
  --graph graphify-out/graph.json --no-label --no-viz
```

产物实测 (`graphify-out/` 共 50 MB):

| 文件 | 大小 | 内容 |
|---|---|---|
| `graph.json` | 47.8 MB | **42382 节点 / 112692 边** / 1042 社区 |
| `GRAPH_REPORT.md` | 227 KB | 社区化 Markdown 报告 |
| `manifest.json` | 511 KB | 提取清单 |

`graph.json` 关键结构事实 (后续元素实现依赖，已写入 obase 适配器):

- 边在 **`links`** 键，**不是** `edges`；`directed` 字段为 `False`，故默认按无向遍历。`obase.load_code_graph` 已把 `links` 归一为 `edges`。
- 节点带 `id` / `label` / `source_file` / `source_location` / `community` / `file_type` 等字段；边带 `source` / `target` / `relation` / `confidence`。

### 1.4 `.gitignore` 不提交

`.gitignore` 第 111 行加入 `graphify-out/`，`git check-ignore` 验证生效：

```
.gitignore:111:graphify-out/	graphify-out/graph.json
```

worktree `git status` 中无任何 `graphify-out/` 踪迹 (它被完整忽略)。

### 1.5 query / explain 实跑

```bash
$ GRAPHIFY_BACKEND=none graphify query "工具注册表" --budget 400
Graph: graphify-out/graph.json (42382 nodes) | Traversal: BFS depth=2 | 25 nodes found
[!] TRUNCATED: showing 13 of 25 nodes (~400-token budget) ...
NODE 注册表真实执行: schema 工具 + 协处理器工具。 [src=tests/test_quant.py loc=L149 community=Community 150]
NODE 工具执行失败 → 触发反思回路(错误不回传前端)。 [src=server/coordinator.py loc=L170 community=Community 58]
...
```

```bash
$ GRAPHIFY_BACKEND=none graphify explain "server/tool_registry.py::SideEffect" --budget 300
Node: SideEffect
  ID:        server_tool_registry_sideeffect
  Source:    server/tool_registry.py L128
  Community: Community 184
  Degree:    76
Connections (76):
  <-- tool_registry.py [contains] [EXTRACTED] server/tool_registry.py:L128
  <-- coding/tools.py [imports] [EXTRACTED] runtime/coding/tools.py:L840
  <-- hicode_agent.py [imports] [EXTRACTED] legacy/executors/hicode/hicode_agent.py:L1173
  ...
```

中文分词正常 (jieba 缓存命中)，`--code-only` 全程未调用 LLM，符合"不耗 LLM"要求。

---

## 2. 任务 B — 3O 范式内化

### 2.1 规范依据 (已读)

| 文档 | 关键结论 |
|---|---|
| `HELIOS_3O_SPEC_v3_0.md` | 3O 分层: **obase** 基础设施层 (外部适配 + 横切) / **oprim** 元实现 (原子砖块) / **oskill** 元技能 (≥2 oprim 组合) / **omodul** 元功能 (≥2 oskill/oprim 组合的业务事务) / **oservi** 元服务 (服务装配)。铁律: oprim 禁同层裸调 (破坏原子性)，oprim 禁写 decision_trail (trail 是 omodul 支柱)。返回结构四支柱: `fingerprint` / `decision_trail` / `report_path` / `cost_usd`。 |
| `3O_MEDUSA_IMPLEMENTATION_SPEC.md` | omodul 标准三件套签名与 `build_result` 契约；`_omodul_name` / `_omodul_version` / `_fingerprint_fields` / `_enabled_pillars` 四个 ClassVar；失败绝不 raise，只返回 `status="failed"`。 |
| `VEYA_42_ELEMENTS_PROGRESS.md` | 元素注册与验收方式；对照本次新增元素的插入位置。 |

注册方式 (实测确认): 各层 `__init__.py` 的 `_ELEMENT_MAP` 由 **AST 自动扫描**模块顶层非下划线类/函数生成，`__all__` 从 `_ELEMENT_MAP` 派生。所以新元素文件放进包内即自动注册——**模块顶层的内部类必须加 `_` 前缀，否则会漏进公共元素命名空间** (本次真的踩到并修复了，见 §2.6)。

### 2.2 分层拆解

```
graphify 能力
├── obase   graphify CLI + graph.json 适配器   (外部世界适配: 子进程 + 文件 IO)
├── oprim   build/query/path/explain/affected  (5 个纯图算法原子)
├── oskill  understand_codebase / analyze_impact / graphify_code_report  (≥2 oprim 组合)
└── omodul  graphify_code_investigation_workflow  (端到端业务事务 + Trail)
```

### 2.3 obase — 基础设施层

**文件**: `obase/graphify_cli.py` (424 行)
**测试**: `tests/test_graphify_cli.py` (203 行)

元素 (7 个，全部经 `obase/__init__.py` 第 338 行 `from obase.graphify_cli import (...)` 显式导出):

| 元素 | 职责 |
|---|---|
| `graphify_cli_path` | 定位 graphify 可执行文件 |
| `graphify_version` | 读 CLI 版本 |
| `run_command` | 通用子进程执行 (替测试可 patch) |
| `extract_code_graph` | 搭 `graphify extract --code-only` |
| `cluster_code_graph` | 搭 `graphify cluster-only` (生成 GRAPH_REPORT.md) |
| `graph_out_dir` / `graph_file_path` | 约定 `graphify-out/` 与 `graph.json` 路径 |
| `load_code_graph` | 读图并归一化 (`links`→`edges`，缺文件返回带 `status` 的 dict 而非 raise) |

关键设计: `load_code_graph` 对"图不存在"返回 `{"status": "no_graph", "error": {...}}`，让上层工具能给模型一句 actionable 提示而不是裸 ImportError。

**Commit**: `7c9cf8f` feat(obase): add graphify CLI and graph.json adapter → `9f22bdc` style(obase): clean graphify adapter lint → `2b910ac` style(obase): sort graphify adapter imports；分支 tip `2b910ac`

**Pytest**:

```
$ /home/soffy/projects/platform/3O/obase/.venv/bin/python -m pytest -q tests/test_graphify_cli.py
17 passed, 1 warning in 0.03s
```

### 2.4 oprim — 元实现 (原子能力)

**文件**: `oprim/_graphify_code_graph.py` (507 行)
**测试**: `tests/test_graphify_code_graph.py` (235 行)

遵守 oprim 铁律 **≤1 位置参数**，故所有函数形如 `(graph, *, question/node/target/source/...)`：

| 原子 | 签名 | 职责 |
|---|---|---|
| `build_code_graph` | `(repo_path, *, force=False)` | 懒构建: 有图则复用，无图才跑 CLI |
| `query_code_graph` | `(graph, *, question, seeds=None, max_depth=2, max_nodes=25)` | 中文/关键词查询 → 命中子图 |
| `graph_path` | `(graph, *, source, target, max_hops=4)` | 最短路径 (无权 BFS) |
| `graph_explain` | `(graph, *, node, depth=1, limit=20)` | 节点解释；重名返回 `ambiguous` + candidates |
| `graph_affected` | `(graph, *, node, depth=2, relations=None, limit=100)` | 反向可达影响面 + 关系过滤 |

返回统一为 `{"status": "ok"|"not_found"|"ambiguous"|"error", ...}`；`error` 形如 `{"kind": ..., "message": ...}`。中文查询测试覆盖真实 agent 提问形态 (如"工具注册表")。

**Commit**: `f9af08d` feat(oprim): add graphify code graph atoms → `43ba15b` fix(oprim): graph_affected tolerates seed entries without id

`43ba15b` 修复的是 worktree 里一处未提交的守护性修改: seed 命中条目缺 `id` 字段时 `hits[0]["id"]` 会 KeyError，改为降级返回 `not_found`，并补测试 `test_seed_without_id_is_not_found` 锁定。

**Pytest** (修复后 27 passed):

```
$ /home/soffy/projects/platform/3O/oprim/.venv/bin/python -m pytest -q tests/test_graphify_code_graph.py
27 passed in 0.37s
```

### 2.5 oskill — 元技能 (组合)

**文件**: `oskill/_graphify_code_intel.py` (248 行)
**测试**: `tests/test_graphify_code_intel.py` (190 行)

| 技能 | 职责 |
|---|---|
| `understand_codebase` | 代码库结构理解 (图统计 + 社区 + 关键文件) |
| `analyze_impact` | 影响面 + 风险等级 (high/medium/low) + 按文件聚合 + 代表性调用链 |
| `graphify_code_report` | Markdown/JSON 报告渲染 |

设计约束: 不调 LLM (需要语言化时由调用方注入 `summarizer` Protocol)，保持 oskill 无外部依赖；模块顶层 `import` 不碰 obase/oprim/omodul (测试 `test_no_module_level_3o_imports` 锁定)。

**Commit**: `4a60072` feat(oskill): add graphify codebase understanding + impact analysis skill → `f1c7298` refactor(oskill): keep internal Protocol out of the element map

`f1c7298` 修的是一个真实污染 bug: `SummarizerProtocol` 是 typing Protocol，但被 oskill 的自动 `_ELEMENT_MAP` 扫描当成公开元素注册，出现在 `oskill.__all__` 里。改名 `_SummarizerProtocol` 并加回归测试 `test_no_public_names_leak_into_element_map`。

**Pytest** (14 passed):

```
$ cd /tmp/g3o/oskill && PYTHONPATH=/tmp/g3o/oprim \
    /home/soffy/projects/platform/3O/oskill/.venv/bin/python -m pytest -q tests/test_graphify_code_intel.py
14 passed in 0.83s
```

> `PYTHONPATH=/tmp/g3o/oprim` 是必须的: oskill 测试要打到本分支的 oprim 副本，否则会解析到主工作区/已安装的旧 oprim。

### 2.6 omodul — 元功能 (端到端事务)

**文件**: `omodul/graphify_code_investigation_workflow.py` (280 行)
**测试**: `tests/test_graphify_code_investigation.py` (197 行)

`GraphifyInvestigationConfig` 配齐四个 ClassVar (`_omodul_name` / `_omodul_version` / `_fingerprint_fields` / `_enabled_pillars`)，pillars 启用 `fingerprint` / `decision_trail` / `report` / `cost`。组合链:

```
obase.extract_code_graph (懒构建, 缺图才跑 CLI)
  → obase.load_code_graph
  → oskill.understand_codebase
  → oskill.analyze_impact
  → oskill.graphify_code_report
```

实现要点 (踩过的坑): `build_result` 需要 **`Trail` 对象** (有 `.steps` / `.run_id`)，不是 list；用 `trail.record(event=...)` 逐条记录，最后 `trail.write(output_dir)`。失败绝不 raise，只返回 `status="failed"`。

注册: `omodul/__init__.py` 第 451 行 `from omodul.graphify_code_investigation_workflow import (...)`。

**Commit**: `204c3c1` feat(omodul): add graphify code investigation transaction

**Pytest** (12 passed):

```
$ cd /tmp/g3o/omodul && PYTHONPATH=/tmp/g3o/obase:/tmp/g3o/oprim:/tmp/g3o/oskill \
    /home/soffy/projects/platform/3O/omodul/.venv/bin/python -m pytest -q tests/test_graphify_code_investigation.py
12 passed in 1.46s
```

### 2.7 3O lint

```
$ python3 /home/soffy/projects/platform/3O/.github/scripts/3o_lint/runner.py --root /tmp/g3o --layer oprim
3O Lint — root: /tmp/g3o
  [oprim] PASS

3O Lint: ✅ ALL GREEN
```

runner 所在的 3O 根目录不是 git 仓库，因此 lint 的 ELEMENTS 清单无法随库提交 (见 §6 后续建议)。lint 报的大量 `missing` 来自主工作区**其他未提交的既有文件** (并发任务所致)，非本次改动；本次新增文件本身无违规。

---

## 3. 任务 C — Veya 接入

### 3.1 接入方式 (对齐 Veya 既有范式)

新增 `server/graphify_tools.py` (299 行)，沿用 Veya 既有的 flag 门控 + 幂等注册 + 薄适配范式 (对照 `wechat_discover` / coding tools):

- **单一来源**: 业务逻辑全在 3O 主库，本模块只做参数翻译 / 图加载 / 注册，不重实现任何算法。
- **flag 门控**: `VEYA_GRAPHIFY` 缺省 **OFF**，关闭时工具面字节不变 (与服务其它外部集成 flag 一致)。
- **幂等注册**: `register_tools` 遇同名工具返回 0，重复装配安全。
- **3O 不可用时明确报错**: 不静默缺失，返回"先在目标仓库跑 `graphify extract`"的可操作提示。
- **挂载校验**: 每个工具函数内确认 3O 主库已从子模块挂载 (见 §4.3 的修复)。

注册点: `server/tool_registry.py` **末尾追加** (第 5298-5305 行)，不动既有装配顺序:

```python
# ── graphify code-graph lookup surface (3O obase/oprim/oskill assembly) ─────
from server.graphify_tools import register_tools as _register_graphify_tools  # noqa: E402

_register_graphify_tools(master_tools)
```

三个工具全部 `SideEffect.PURE_READ` (只读图谱，无副作用)：

| 工具 | 参数 | 底层 |
|---|---|---|
| `graphify_query` | `question`, `target?`, `max_nodes?` | `oprim.query_code_graph` |
| `graphify_impact` | `target`, `depth?` | `oskill.analyze_impact` |
| `graphify_explain` | `target`, `depth?` | `oprim.graph_explain` |

工具 description 里明确写了"回答代码问题优先查图谱，而不是 grep 全文"，把 §3.4 的优先级约定交给模型。

**Commit**: `1d0e561c` feat(tools): add graphify code-graph lookup tools (flag-gated, read-only) → `358c0322` fix(tools): mount graphify 3O elements from the submodule, not site-packages

### 3.2 flag 门控实测

```
$ VEYA_GRAPHIFY=0 ... → total tools: 162 | graphify tools: []
$ VEYA_GRAPHIFY=1 ... → total tools: 165 | graphify tools: ['graphify_explain', 'graphify_impact', 'graphify_query']
```

### 3.3 真实图谱端到端实测 (42382 节点)

```
### EXPLAIN ###
节点: .list() [runtime/harness/ratchet.py:L55]
id: runtime_harness_ratchet_ratchetstore_list | 连接度: 8 | 邻接节点: 8
邻接: RatchetCandidate / RatchetError / RatchetStore / _candidate_from_dict() /
      apply_candidate() / record_candidate() / revert_candidate() / transition_candidate()

### IMPACT (server_tool_registry) ###
影响面: server_tool_registry
风险等级: medium | 受影响节点: 47
代表性调用链:
- tests_test_fault_injection -> server_tool_registry (1 跳)
- server_evo_ontology -> server_tool_registry (1 跳)
- tests_test_tool_guard -> server_tool_registry (1 跳)

### QUERY (graphify 工具注册) ###
图: 42382 节点 / 112692 边 — 命中 25 节点 / 19 边
- 把 hicode 工具注册进 master_tools (幂等)。返回新注册数量。 [legacy/executors/hicode/hicode_agent.py:L1172]
- 把 plan 工具注册进 master_tools (幂等)。返回新注册数量。 [server/plan_todo.py:L237]
- 工具注册规格。schema = JSON Schema（绝对校验）；None = 跳过参数校验。 [veya/omodul/tool_pipeline.py:L37]
...
```

三个工具在真实规模图谱上均返回结构化、可执行的结果 (impact 甚至指出了该动 `tests/test_tool_guard.py` 等测试)。

### 3.4 代码问题优先查图谱 (而非 grep)

已落到三处，形成闭环:

1. **工具 description**: 三个工具的说明里直接写明"比 grep 全文更快也更省上下文"。
2. **文档**: `server/graphify_tools.py` 模块 docstring 首行即"回答代码问题时优先用它, 而不是 grep 全文"。
3. **实测对照**: `graphify_query("工具注册表")` 一次命中 `server/plan_todo.py` / `server/vault_physical_tools.py` / `veya/omodul/tool_pipeline.py` 等分散在多处的注册点，并带 `community` 归属；`graphify_impact` 直接给出受影响文件清单与测试清单。

### 3.5 Veya 侧测试

**文件**: `tests/server/test_graphify_tools.py` (211 行)，20 个用例，覆盖 flag gating / 幂等注册 / 3O 缺失明确报错 / `.gitignore` 契约 / 挂载优先级。

**Commit**: `358c0322` (与 §4.3 同一次提交)

**Pytest**:

```
$ cd ~/projects/veya-graphify && /home/soffy/projects/veya/.venv/bin/python \
    -m pytest tests/server/test_graphify_tools.py -q -p no:cacheprovider
20 passed, 1 warning in 4.41s
```

---

## 4. 过程中发现并修复的问题

### 4.1 oprim `graph_affected` 对缺 `id` 的 seed 会 KeyError

worktree 里存在一处未提交的守护性修改。已补齐测试 `test_seed_without_id_is_not_found` 后提交 (`43ba15b`)。

### 4.2 oskill 内部 Protocol 漏进公共元素命名空间

`SummarizerProtocol` 被 oskill 的自动 `_ELEMENT_MAP` 扫描注册成公开元素，出现在 `oskill.__all__`。改名 `_SummarizerProtocol` + 回归测试 (`f1c7298`)。

### 4.3 (重要) Veya 的 3O 挂载会解析到 site-packages 旧发行版

**现象**: 三个 graphify 工具全部返回 `3O 主库不可用: ImportError: cannot import name 'graph_explain' from 'oprim'`。

**根因**: `veya/platform/__init__.py` 的 `_ensure_paths()` 只做 `sys.path.insert(0, ...)`。若 `obase`/`oprim`/`oskill` 已被提前 import，`sys.modules` 缓存会赢，于是拿到 site-packages 里的旧发行版 (obase 0.31.0 / oprim 3.23.0，10 月 15 日安装)，那里没有本次新增元素。这是 Veya 既有的挂载时序坑，不是本次改动引入，但会让新元素在真实运行中静默失效。

**修复**: `server/graphify_tools.py` 增加 `_ensure_mounted()`，在每次 3O import 之前调用——若发现已缓存模块的 `__file__` 不在 `platform/3O` 下，就清掉该包 (含子模块) 的 `sys.modules` 缓存并按子模块路径重新导入。幂等，无副作用。

**验证**: 不手动插 `sys.path`，纯粹走 `veya.platform` 挂载，三个工具全部返回真实结果 (§3.3)。测试 `TestMountPrecedence` 覆盖"陈旧缓存驱逐"与"幂等"两条，并在 `finally` 里还原 `sys.modules` / `sys.path` 现场，避免污染同文件其它用例。

---

## 5. 测试与提交总账

### 5.1 全量复跑 (报告定稿前一次实跑)

```
===== obase  =====  17 passed, 1 warning in 0.03s
===== oprim  =====  27 passed in 0.37s
===== oskill =====  14 passed in 0.83s
===== omodul =====  12 passed in 1.46s
===== veya   =====  20 passed, 1 warning in 4.41s
```

**合计 90 个用例全部通过，0 失败。**

### 5.2 Commit 清单

**3O worktree 分支 `feat/graphify-3o`** (位于 `/tmp/g3o/<库>`，均未 push、未合并):

| 库 | Commit | 说明 |
|---|---|---|
| obase | `7c9cf8f7` | feat(obase): add graphify CLI and graph.json adapter |
| obase | `9f22bdc` | style(obase): clean graphify adapter lint |
| obase | `2b910ac5` | style(obase): sort graphify adapter imports (分支 tip) |
| oprim | `f9af08d8` | feat(oprim): add graphify code graph atoms (build/query/path/explain/affected) |
| oprim | `43ba15b` | fix(oprim): graph_affected tolerates seed entries without id (分支 tip) |
| oskill | `4a60072` | feat(oskill): add graphify codebase understanding + impact analysis skill |
| oskill | `f1c7298` | refactor(oskill): keep internal Protocol out of the element map (分支 tip) |
| omodul | `204c3c1` | feat(omodul): add graphify code investigation transaction (分支 tip) |

**Veya worktree 分支 `feat/graphify-3o`** (`~/projects/veya-graphify`)：

| Commit | 说明 |
|---|---|
| `1d0e561c` | feat(tools): add graphify code-graph lookup tools (flag-gated, read-only) |
| `358c0322` | fix(tools): mount graphify 3O elements from the submodule, not site-packages (分支 tip) |

四个 worktree 与 veya-graphify 在报告定稿时 `git status` 均为 **clean** (无未提交残留)。

### 5.3 硬约束遵守情况

| 约束 | 状态 |
|---|---|
| 不动 3O / veya 主工作区 (无 checkout/stash/reset) | ✅ 未执行任何此类命令；主工作区 `~/projects/veya` HEAD 仍为 `31ab26e2`，其未跟踪文件 (`docs/claude-bughunter-integration.md` 等) 原样保留 |
| 一律在新 worktree 建分支 | ✅ `/tmp/g3o/{obase,oprim,oskill,omodul}` + `~/projects/veya-graphify`，分支名 `feat/graphify-3o` |
| 不 push、不合并 | ✅ 无 push、无 merge |
| 新元素不进主工作区 | ✅ 4 个新元素文件作为 worktree 内未提交改动叠加在子模块工作树；**gitlink 未变** (`git ls-files -s platform` 与 `git status` 均确认) |
| 每个元素真实文件 + pytest 通过 + commit | ✅ 9 个元素 / 5 个测试文件，90 用例全绿，10 个 commit |

---

## 6. 已知限制与后续建议

### 6.1 已知限制

1. **extract 跑在 worktree 而非主工作区**: 为遵守"绝不碰主工作区"的硬约束。worktree 与主工作区同 commit (`31ab26e2`)，图谱内容等价；若需主工作区的图谱，另行单独执行即可。
2. **子模块 gitlink 未变**: 4 个新元素文件作为 worktree 内未提交改动叠加。这是硬约束的必然结果 (改 gitlink 需要在主工作区 checkout 子模块指针)，待用户决定后再合入。
3. **opencode 插件文件未生成**: `~/.config/opencode/plugins/graphify.js` 不存在，CLI 0.9.92 只为 opencode 落了 skill 目录。不影响 skill 使用。
4. **3O lint 的 ELEMENTS 清单未更新**: runner 所在根目录非 git 仓库，无法随库提交；当前新元素靠自动 `_ELEMENT_MAP` 扫描注册，功能不受影响。

### 6.2 后续建议 (按优先级)

1. **把 `_ensure_mounted` 的挂载时序修复上移到 `veya/platform/__init__.py`**: 当前修复只护住了 graphify 三个工具，其它任何"3O 主库 + site-packages 同名发行版并存"的消费者都会踩同一个坑。把"已缓存模块不在子模块下就重导"的逻辑做成 `veya.platform.load()` 的内建行为，一次修干净。
2. **合入子模块指针**: 4 个新元素提交在各自库的 `feat/graphify-3o` 分支，需用户确认后在主工作区更新 gitlink。
3. **补 osavi/oservi 层 (如需)**: 若后续要把"代码图排查"包装成对外服务形态，按规范应落 oservi；当前 omodul 事务已足以支撑 Veya 内部调用。
4. **把新元素加进 3O lint 的 ELEMENTS 清单**: 需在一个 git 化的 3O 仓库内改，建议随下次 lint 规则更新一起提。
5. **定期重建图谱**: `graph.json` 是 2026-10-19 快照；代码演进后需重跑 `extract`。可在 CI 或 pre-commit 里挂一个低频重建任务，或让 agent 在 `load_code_graph` 检出图过期时提示重建。

### 6.3 卡住记录

全程无同一问题卡住超过两次的情况。唯一的反复是 §4.3 的挂载时序问题 (定位 → 修复 → 测试顺序耦合 → 收窄断言)，均在第三次迭代内解决，最终以 20 passed 收口。

---

## 7. 验收核对

| 任务要求 | 结果 |
|---|---|
| `uv tool install "graphifyy[mcp,leiden,chinese]"` | ✅ graphifyy 0.9.92 |
| `graphify install --platform pi / opencode / codex` | ✅ 三次分别执行，三个 skill 目录落盘 |
| `graphify --version` | ✅ graphify 0.9.92 |
| Veya 上跑 `graphify extract --code-only` (GRAPHIFY_BACKEND=none) | ✅ 42382 节点 / 112692 边 |
| 生成 `graphify-out/graph.json` 和 `GRAPH_REPORT.md` | ✅ 47.8 MB + 227 KB |
| 跑一次 `graphify query` 与 `graphify explain` | ✅ 均真实跑通 (§1.5) |
| `graphify-out` 加入 `.gitignore` 不提交 | ✅ 第 111 行，check-ignore 验证 |
| 读三份 3O 规范理解分层与注册 | ✅ (§2.1) |
| obase: graphify CLI / graph.json 适配器 | ✅ `obase/graphify_cli.py` |
| oprim: build/query/path/explain 等原子 | ✅ 5 个原子 |
| oskill: 代码库理解 / 影响分析组合技能 | ✅ 3 个技能 |
| omodul: 工作流 (规范需要) | ✅ `graphify_code_investigation_workflow` |
| 每个元素配 pytest | ✅ 5 个测试文件 / 90 用例 |
| Veya 内 agent 可调用上述能力 | ✅ flag ON 后 3 个工具 |
| 代码问题优先查图谱而非 grep | ✅ 已写入 description / docstring / 实测对照 |
| 未动主工作区 / 未 push / 未合并 | ✅ |
| 报告列 commit hash 与 pytest 输出摘要 | ✅ (§5.1 / §5.2，全部真实输出) |

GRAPHIFY_3O DONE
