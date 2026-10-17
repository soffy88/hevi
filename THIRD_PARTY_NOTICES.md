# 第三方许可台账

## archify

- **来源**: `third_party/archify/` (tt-a1i/archify v3.0.1, MIT)
- **许可证**: MIT License
- **版权**: Copyright (c) 2026 tt-a1i (Archify); Copyright (c) 2025 Cocoon AI
- **完整许可证文本**: `third_party/archify/LICENSE`
- **附加通知**: `third_party/archify/THIRD_PARTY_NOTICES.md`
- **用途**: Hevi 解说视频自动生成结构化图示(架构/流程/时序/数据流/生命周期)
- **入库日期**: 2026-10-12
- **备注**: `.git` 目录已移除(vendor 化),node 依赖通过 PATH 上的 node v26.4.0 运行。
  Archify 自带 schema 校验、provenance 校验、browser-check(含 containment/readability)。
  本项目通过 `hevi/visuals/archify_source.py` 封装 CLI, 调用方不直接依赖 node 模块。
