# SVFACTORY 独立核验报告 (PATROL4 R3)

- **工作目录**：`/data/soffy/projects/hevi-svfactory`
- **目标分支**：`feat/svfactory` (`136b86ef`)
- **核验时间**：2026-10-16

---

## 一、验收项目与数字证据

### 1. 批量预设生产与断点续跑 (`hevi.svfactory.batch`)
- **测试执行**：在隔离测试环境中运行 `tests/test_svfactory_acceptance.py`。
- **证据数字**：
  - 批量输入 3 个主题（`分享快乐`、`排队轮流`、`安全过马路`）。
  - 真实串行出片：成功生成 3 支短片及对应的 `.manifest.json`。
  - 画幅规格：验证 `9:16` 竖屏视频（分辨率 720x1280），ffprobe 确认视音频流完整、时长符合、无黑屏。
  - **断点续跑（Breakpoint Resume）**：二次运行 `BatchRunner`，3 支已完成片因 manifest 校验通过被瞬间跳过（`resumed`），无重复渲染，状态机确定性恢复。

### 2. 素材文件夹自动混剪 (`hevi.svfactory.montage`)
- **测试执行**：测试 `auto_montage_segments` 在相同 seed 下的哈希确定性。
- **证据数字**：
  - 相同 seed（`2026`）两次运行生成的视频片段序列及时间戳范围完全一致（SHA-256 哈希一致）。
  - 更改 seed 后选段策略发生变化，未出现连续同素材连击。

### 3. Kids Gate 质量与安全合规
- **测试执行**：每支成片均通过 `kids_gate_workflow` 检查。
- **证据数字**：
  - 语速控制在 ≤ 3.5 字/秒以内。
  - 字幕样式采用大字、高对比度描边，无溢出。
  - 音频响度与合规校验通过。

### 4. AGPL 源码合规性核查
- **核查结果**：通过对 `hevi/svfactory/` 模块的静态扫描与比对，代码为基于纯净思路和标准库/OpenCV/FFmpeg 的 clean-room 重新实现，未复制任何 AGPL 3.0 授权的 Electron 桌面端源码。

---

## 二、单元测试与 Lint 状态
- **单元测试**：`uv run pytest tests/test_svfactory.py tests/test_svfactory_acceptance.py -v` 4/4 全过。
- **3O Lint**：无新增违规。

## 三、结论
- **状态**：**PASS**
