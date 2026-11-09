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

## raea (Render Anything Engine)

- **来源**: https://github.com/shinyobjectz/raea (FSL-1.1-ALv2)
- **许可证**: Functional Source License, Version 1.1, ALv2 Future License
- **入库方式**: **不 vendor、不入库**。hevi 仅在服务器内部按需调用本地安装的
  `raea` CLI；运行时从固定路径 `/opt/raea/bin/raea` 或 `HEVI_RAEA_BIN` 读取，
  缺失则自动跳过。未修改 raea 源码，未分发其二进制。
- **用途**: 可选成片质检旁路（`HEVI_RAEA_CHECK`，默认 0）与 kinetic_promo
  内部 A/B 模板（`HEVI_KINETIC_ENGINE=raea`，默认 default）。不向用户暴露
  raea CLI/API/TSX/HTML 编辑或渲染能力。
- **许可边界**: FSL-1.1-ALv2 明确允许 internal use；对客户提供“写代码渲染”
  能力或再分发二进制可能构成 Competing Use，须先法务评估。
- **入库日期**: 2026-11-09（仅台账记录，无文件入库）
## ai_drama / MiniMax H3

- **来源**: MiniMax 开放平台 H3 视频生成 API；RunningHub OpenAPI H3 工作流
- **许可证**: MiniMax H3 社区许可（排除 EU/UK/韩国/美国；商用界面标注 “MiniMax H3”）
- **文档**: https://platform.minimaxi.com/docs/guides/video-generation ; https://www.runninghub.cn/runninghub-api-doc-cn/
- **用途**: ai_drama 视频段 provider（有 key 时付费调用；无 key 自动 Offline）
- **合规**: 不使用真人/明星照片或声音作参考；成片带“AI 生成”标识
- **入库日期**: 2026-11-09

## Noto Sans CJK

- **来源**: https://github.com/notofonts/noto-cjk
- **许可证**: SIL Open Font License 1.1
- **用途**: ai_drama 字幕、游戏对话框、UI 提示与“AI 生成”标识
