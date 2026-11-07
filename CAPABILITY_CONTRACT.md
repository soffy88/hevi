# Hevi 能力契约（用户 2026-10-14 16:50："这些能力要能做到各个产品线需要时可以调用"）

每条新能力（3D 场景、手绘、品牌片、Lottie/Satori/图表、转场、特效、音效、短剧资产……）都必须通过统一接口注册。任何产品线（zero 线、talkcraft、短剧、artmotion、explainer、ShotSpec 工作台）都可以按名字调用，不允许各写一套私有入口。

## 接口
- 注册表：`hevi/capabilities/registry.py`
  - 注册：`register(Capability(...))`
  - 查找：`get(name)`
  - 列出：`list(kind=..., aspect=...)`
- `Capability` 的字段：
  - `name`：例如 "scene3d.planet_orbit"、"handdraw.narration"、"lottie.overlay"、"satori.title_card"
  - `kind`：shot | overlay | transition | audio | title | line
  - `aspects`：["16:9","9:16"]
  - `params_schema`：JSON Schema
  - `cpu_cost_hint`：每秒视频大约要多少 CPU 秒
  - `render(params, out_dir, *, duration, aspect, seed) -> CapabilityResult`
- `CapabilityResult` 的字段：mp4/png/wav 路径、实际时长、sha256、qa 报告。
  - 输出要求：同一个 seed 结果可复现。
  - 失败时抛 CapabilityError，不允许返回假成功。

## 接入点
- **ShotSpec**：`shot_spec.capability = {"name": ..., "params": {...}}`。assemble 按名字调用；名字不存在就返回 422。
- **API**：
  - `GET /api/capabilities`：列出全部能力，前端 AI 一键预填时从这里选；
  - `POST /api/capabilities/{name}/preview`：生成 3 秒预览。
- **产品线**：通过 `hevi.capabilities.get(name).render(...)` 调用。

## 测试要求
每个能力至少要有以下测试：
- 注册后能被 `list` 查到；
- 用 schema 校验非法参数，必须报错；
- 渲染 2 秒的产物要通过 ffprobe 检查；
- 删除产物后，测试必须失败。

## 范式化补记（2026-10-25，第 3 阶段：34 项审计清单落地）

### 产物口径：报告／文件类能力（M-15）
`CapabilityResult` 的“至少一个产物”要求对报告／文件类能力改写为：
产物就是报告 JSON 本身（`qa["report_json"]` 指向写盘的报告文件，
`sha256` 是该报告文件的指纹）。报告类能力包括 drama 系 8 项
（season_bible／season_arc／episode_prompts／drama_gates／
reference_decompose／edit_assemble／model_test／script_polish）、
novel 系 3 项与新 story 系 5 项（见下）。preview 端点对这类能力
返回报告 JSON，不伪造 MP4；`Path(None)` 式 TypeError 已根除
（无媒体产物且非报告类时仍返回 500“preview produced no artefact”）。

### aspects 语义（S-03）
报告／文件类能力的 `aspects` 只是声明：`render` 完全忽略 aspect，
preview 端点对它们跳过 aspect 检查（不支持的画幅也不 422）。
只有媒体类能力的 aspects 才参与准入判定。能力上以
`Capability.has_media_output`（报告类为 False）显式区分。

### 唯一对外入口（S-06）
对外调用一律走 `render_safe`（先校验 schema 再渲染）或 preview
端点；直接调 `cap.render` 仅限模块内自测（各模块 `main()`、
测试夹具）。`drama_gates` 对 `story.script_polish` 的调用已改走
registry `render_safe`，不再直调私有 `_render`（S-05）。

### 命名（S-02）
- `story.canvas_workflow`：画布工作流模型（只注册模型，不执行）。
- `story.novel_import`：成书→分集输入映射（只切分不创作）。
- 分工：`novel.*`（novelpipeline）负责成书创作；`story.novel_import`
  只负责把已成书的章节映射为分集输入。两者不得混用。

### 文件型能力的写盘规则（C-05）
`novel.*` 的 `book_dir` 是调用方确认的写盘根，不是可忽略的提示：
相对路径一律解析到 `out_dir` 之下（`out_dir` 为默认写盘根）；
绝对路径予以保留（既有调用方与测试均以绝对路径寻址书目），但
须过校验——根目录、家目录、已存在非目录一律拒绝；`write_chapter`
另要求 `book.json` 已存在。每次渲染另向 `out_dir` 写一份收据
（`novel_render_receipt.json`），记明书目实际落盘位置，使预览
临时目录与实际写盘位置不再脱节。

### bundle 门禁（C-06）
`story.reference_bundle` 的 render 自带 `passed`：任一参照块为
`[缺失]` 或任一 issue 为 error 即 `passed=false`。生成步骤引用
bundle 前必须查 `passed`；只看 warnings 不构成门禁。

### 门禁 pending 语义（C-08）
`story.drama_gates` 的 edit-ready 检查：`edit_assemble` 报告干净
但 `ffmpeg.status == "pending"`（如未提供 subtitle_file，组装命令
未生成）时，该检查为 pending——不算通过、不算 blocker。整体
`passed` 仍只由 blocker 决定（pending 单独计数），但检查项本身
不得显示为 passed。

### LLM 成本口径（S-04）
`cpu_cost_hint` 只装 CPU 秒，绝不用来装 LLM 成本。走 LLM 的
能力（`story.script_polish` full 模式、`novel.*`）必须在描述中
明示“按次计费／per-call”，预算门与成本台账不得只读该字段就
认为零成本。`video.blender_mcp` 的 `cpu_cost_hint` 标注实测口径：
30.0 为 BLENDER_WORKBENCH 实测值，EEVEE 值未重测（qa 中按引擎
分档标注，见 C-03）。

### 注册与重名（S-09、S-01）
`register()` 默认 `overwrite=False`：重名即抛 `CapabilityError`，
不再静默顶替；确需替换时显式传 `overwrite=True`，该路径记警告
日志并进 `overwrite_history()`（`describe()` 标注 `overwritten`）。
现有 `register_*_capabilities_once` 守卫不依赖覆盖语义（自带
`_Registered` 标志或预查 `_REGISTRY`），默认改动不破坏它们；
唯一例外是 `motion.rhythm_sheet`（模块导入时注册＋`__init__`
又调一次），已改为预查在册则直接返回。目录完备性测试
（`tests/test_capability_catalogue_completeness.py`）以 AST 扫描
`hevi/capabilities/` 下各 `register_*` 函数构造的 Capability 名，
在全新子进程中只 `import hevi.capabilities` 后断言全部可 `get()`，
G13 式漏接不再靠人工发现。

### 画布执行入口（M-14）与 blender 并发（M-16）
画布执行不进 `Capability.render` 同步签名：`/canvas` 路由提供
`workflow-to-graph`／`graph-to-workflow`／`planned-graph`／
`workflow-preflight`，执行走 `workflow-execute`（先把工作流存为
调用方名下的画布图，再委托 `ExecutorService` 执行，与手绘图同路）。
`video.blender_mcp` 的并发语义是串行排队：单 GUI 会话／单 MCP
端口，一次只跑一个渲染，后来者排队等候（默认上限 600 秒，可用
`HEVI_BLENDER_MCP_QUEUE_TIMEOUT_S` 调），超时报
`CapabilityError`，不等无限期；不做按任务端口隔离（addon 端口
由 addon 调用固定）。

### blender 暴露面（M-17）
`video.blender_mcp` 在目录中可见，但 preview 端点一律 422
（`preview_restricted`）：其 `code` 参数是在 live Blender 会话内
执行的任意 bpy 代码，不对通用调用方开放，仅限受信直接调用
（in-process `render_safe`）。schema 与描述中明示任意代码执行。
会话启停只停自己起的 pid（C-04）：端口被他人会话占用时直接
抛错，绝不杀占用者；启动失败时不停止任何进程。

### 残留（不属本阶段代码范围）
- 入 3O 资产池（`_MANIFEST_ELEMENTS`／主库 `__manifest__`）：
  需用户拍板后另行实施，本阶段不动
  `/data/soffy/projects/platform/3O` 下任何文件（S-08）。
- `story.canvas_workflow` 的“身份 rides config”过渡写法与
  hevi／oprim 双份边矩阵：已有意为之的边界定性，本阶段不收敛。
