# 第三方许可台账

## anidoodle

- **来源**: https://github.com/alexgreensh/anidoodle（v0.10.1，Apache-2.0）
- **版权**: Copyright 2026 Alex Greenshpun
- **完整许可证文本**: `third_party/anidoodle/LICENSE`
- **上游通知**: `third_party/anidoodle/NOTICE`（含可选音色包的 VCSL CC0 与 OpenAIR CC BY 4.0 条目）
- **用途**: 32 种代码手绘风格、绘制过程片、代码作曲、确定性渲染。
- **入库日期**: 2026-11-10
- **修改**: HEVI 在 `hevi/anidoodle/` 写封装（Node 调用、风格目录、缓存、门禁），
  并新增 `hevi/anidoodle/drawing_deadair.mjs`（按上游 `meta.kind:"drawing"` 的既有 0.02% 死空镜标准读取像素）。
   vendored Remotion 适配器有两行补丁（`tools/adapters/remotion.mjs`、`remotion/canvas.tsx`）：
   上游用影片的中文长标题当 Remotion composition id，Remotion 只接受字母数字/`-`；改用固定 id `film`，其余未改。
- **可选音色包（S30）**: 374 MB，宿主 `/data/soffy/projects/anidoodle-sounds`，只读挂载到容器 `/anidoodle-sounds`；
   不进仓库、不进镜像。8 个乐器为 **VCSL CC0 1.0**（公有领域，可商用、可再分发，无需署名）；
   3 个 room 为 **OpenAIR / University of York CC BY 4.0**（可商用，需署名，署名文本见 `NOTICE`）。
   包内无非商用/禁止再分发条目；缺包时逐槽位回退代码乐器。
- **边界**: Remotion 后端为可选项，复用仓库既有 Remotion 4.0.486（`hevi-remotion`）链接，不新增重复依赖；
   上游示例片、README 图片/音频与 launch 片素材不作为 HEVI 示例或默认内容。
- **署名位置**: 本文件、仓库根 `NOTICE`、`/anidoodle` 页面底部、`/acknowledgements` 页、风格选择器页头。

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

## pyJianYingDraft

- **来源**: https://github.com/GuanYixuan/pyJianYingDraft (PyPI `pyJianYingDraft` 0.3.1)
- **许可证**: Apache License 2.0
- **版权**: Copyright (c) pyJianYingDraft contributors
- **使用方式**: **仅作为 Python 运行时依赖**（`pip install pyJianYingDraft`），
  不 vendor、不复制其源码进 hevi 仓库或闭源模块；由
  `hevi/studio/jianying_native.py` 在服务端生成剪映专业版草稿。
- **用途**: 导出可被剪映专业版打开的原生草稿（draft_content.json +
  draft_meta_info.json + materials + 关键帧 + 字幕/音频轨）。
- **许可边界**: Apache-2.0 允许商业使用与再分发；保留其 LICENSE/NOTICE。
  未修改上游源码。
- **入库日期**: 2026-11-09

## creator-generalist (codepawl)

- **来源**: https://github.com/codepawl/creator-generalist (MIT)
- **许可证**: MIT License
- **版权**: Copyright (c) 2026 CodePawl
- **完整许可证文本**: `third_party/creator-generalist/LICENSE`
- **用途**: **只重述方法**，不复制 SKILL 文本/模板/引擎代码。吸收 3D 剖面与时代场景、
  2D 编辑部（地图/真实比例时间轴/档案拼贴）、角色动作规则与穿模/滑步检查、
  手机外放与遮蔽/同步检查、看片翻拍配方、Shorts 剪辑规范；
  实现见 `hevi/studio/generalist_s23.py`，详情见 `CREATOR_GENERALIST_ATTRIBUTION.md`。
- **入库日期**: 2026-11-10
- **备注**: 不调用 ElevenLabs / HunyuanVideo-Foley / Google Flow；不新增付费，
  不新增运行时依赖，不自动下载资产。

## article2media (threerocks)

- **来源**: https://github.com/threerocks/article2media (MIT)
- **许可证**: MIT License
- **版权**: Copyright (c) 2026 LeiLiu
- **完整许可证文本**: `third_party/article2media/LICENSE`
- **用途**: **只重述方法**，不复制 SKILL 文本/模板/引擎代码/示例内容/主题/字体。
  吸收口播成片硬指标审片、whisper 字级同步镜头、一稿多发（3:4 卡片 + 公众号内联
  HTML + 长图）、文章块 SHA-256 账本、翻译校验并入 localization_dub、音色分层与
  AIGC 标识；实现见 `hevi/studio/repurpose_s24.py`，详情见
  `ARTICLE2MEDIA_ATTRIBUTION.md`。
- **入库日期**: 2026-11-10
- **备注**: 示例内容与上游字体另有版权，未带入；不接 VoxCPM2/mlx（Apple Silicon）；
  不读浏览器 cookie；不批量抓取；不新增付费服务。

---

## handraw-style (yang0/handraw-style)

- **来源**: https://github.com/yang0/handraw-style
- **作者**: yang0
- **许可证**: MIT License with Attribution Requirement（允许商用，须在文档、
  产品说明或界面中保留作者与仓库链接）
- **使用内容**: 370 种视觉风格、170 种排版图型、36 种主题色的结构化数据
  （编号、名称、类别、特征、适用场景），未使用其 images/ 示例图。
- **去名**: 在世或无法确认的在世艺术家真名按政策隐去，只保留风格特征；
  184 个条目，178 个唯一参考名。策略哈希见
  `hevi/image/handraw_data/credit_policy.json`。
- **署名**: `NOTICE`、`/acknowledgements`、风格选择器页脚、
  `assets/style_library/ATTRIBUTION.md`。

## BeefTV (glanderness/BeefTV)

- **来源**: https://github.com/glanderness/BeefTV
- **许可证**: BeefTV Source Available License 1.0（非 OSI 开源；禁止商业转售/套壳/
  收费部署/向第三方提供托管，未经书面授权）
- **用途**: **只做能力对标**（无限画布、对话建画布、模板版本、报价、备份、MCP、
  素材加工等），不复制其代码、图片、文案、提示词、模板或设计资源。
- **实现**: `hevi/canvas/agent_build.py`、`pricing_s25.py`、`backup_s25.py`、
  `diagnostics_s25.py`、`templates_s25.py`、`material_ops_s25.py`、
  `skills_s25.py`、`library_s25.py`、`plugin_contract_s25.py`，以及
  `hevi/api/routers/canvas_s25.py` 与本仓库自写前端组件。
- **入库日期**: 2026-11-10
- **备注**: README 中的赞助商广告「ll2.cn 提供 MiniMax-H3 0.05 元/秒」未经核实，
  未接入、未报价、未宣传。
