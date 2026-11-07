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

## collage_broll (gbro-collage-broll)

- **来源**: https://github.com/pyang5166/gbro-collage-broll (MIT)
- **许可证**: MIT License
- **版权**: Copyright (c) 2026 pyang5166 (gbro-collage-broll)
- **完整许可证文本**: `hevi/collage_broll/LICENSE_gbro`
- **用途**: 半调纸拼贴 B-roll 隐喻/visual-spec/QA 模板复用；视频脚本未采用，不使用 GEMINI_API_KEY。
- **入库日期**: 2026-11-07

## livliv-player (hevi/avatar_livliv)

- **来源**: https://github.com/livliv-dev/player (Apache-2.0)
- **许可证**: Apache License 2.0 (代码); 角色另有许可 (个人非商用，署名 "Characters: LivLiv (livliv.ai)"，不得用于训练 AI，保留角落 LivLiv 标记，公开展示注明 AI 制作)
- **完整许可证文本**: `hevi/avatar_livliv/licenses/LICENSE-player`, `NOTICE-player`
- **角色许可/署名**: `hevi/avatar_livliv/licenses/CHARACTERS-LICENSE.md`, `CHARACTERS-CREDITS.md`
- **用途**: 2.5D 角色口型/表演离线渲染器 (Playwright + Chromium 软件 GL)
- **入库日期**: 2026-11-07
- **备注**: vendor 只读引用 `/data/soffy/vendor/livliv-player`，不进 hevi git；hevi 内仅构建产物与许可证文件。
