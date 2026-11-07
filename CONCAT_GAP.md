# CONCAT_GAP — jub0t/Concat 与 hevi 口播/成片流水线差距评估

## 1. Concat 项目概述
- **名称**：`jub0t/Concat` (https://github.com/jub0t/Concat)
- **定位**：免费、开源、跨平台的 CapCut（剪映）替代品，使用 Rust 编写（原生 Rust 引擎 + GPU 合成器），支持 macOS、Windows、Linux、Android、iOS。
- **核心能力**：
  - 本地 Whisper 自动字幕、TTS（Text-to-Speech）与语音克隆、背景抠图。
  - 关键帧动画（位置、缩放、旋转、透明度、音量、效果参数）、曲线编辑器。
  - 100+ 视频效果、滤镜与转场（GPU 渲染）。
  - 多轨道/多时间线剪辑、磁性时间线、字幕排版。
  - 脚本化接口：内置 **MCP 服务器 (`concat --mcp`)** 和 **JSON-RPC API**，允许 AI 代理直接驱动剪辑。

---

## 2. hevi 现有模块盘点
- **hevi 核心功能**：
  - 中文口播、短视频、漫剧、有声故事、知识解说流水线。
  - 语音生成与对齐（如 VoxCPM、TTS、Word-level timestamps）。
  - 视频渲染（如 Remotion / FFmpeg 多比例合成：9:16、16:9）。
  - 自动化审核、QA 抽帧（SHOTLANG QA）、资产对账。

---

## 3. Gap 分析矩阵 (已有 / 部分 / 缺失 / 不相关)

| Concat 能力模块 | hevi 现有状态 | 评估分类 | 说明与互补性 |
| :--- | :--- | :--- | :--- |
| **GUI 桌面编辑器 (Rust + GPU)** | 无桌面 GUI，主打脚本与无头自动化流水线 | **不相关** | hevi 是后端自动化和 AI 智能体流水线，不涉及跨平台桌面 GUI 应用开发。 |
| **本地 Whisper 字幕生成** | 部分集成（如 Faster-Whisper / 各种转写模块） | **已有 / 部分** | hevi 已具备转写与字幕时间戳对齐，但 Concat 的精细化字幕样式更为丰富。 |
| **MCP 服务器 / JSON-RPC API 驱动剪辑** | 缺失类似标准 MCP/JSON-RPC 视频剪辑控制服务 | **缺失 (高价值)** | Concat 提供的 `--mcp` 和 API 协议对于 AI Agent 远程操控时间线剪辑极具参考价值。 |
| **关键帧动画与 GPU 特效/转场** | 部分支持（基于 Remotion/FFmpeg 模板渲染） | **已有 / 部分** | hevi 通过 Remotion/FFmpeg 实现了强大的自动化视频特效，但缺乏桌面级的曲线关键帧交互微调。 |
| **背景抠图与语音清理** | 基础支持 | **已有** | hevi 流水线已具备基本的降噪与背景处理。 |

---

## 4. 结论与技术裁决
1. **不直接合入 Concat 的 Rust GUI 源码**：因为 hevi 是 Python/Remotion 驱动的自动化短视频流水线，直接引入一个大型 Rust 桌面应用在架构上不匹配。
2. **值得借鉴与复用的部分**：
   - **MCP / 脚本化控制思路**：Concat 的 MCP 剪辑服务设计可以启发 hevi 未来对 AI Agent 剪辑指令的标准化封装。
   - **自动化剪辑元数据契约**：参考其时间线与关键帧 JSON 结构。
