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
