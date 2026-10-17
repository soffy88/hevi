# Third-Party Dependencies and Attributions

## native-subtitle-quote-image
- Location: `third_party/native-subtitle-quote-image/LICENSE`
- Source: `/data/soffy/projects/vendor/chengyi-ai__native-subtitle-quote-image`
- Original Author: 程意 (Copyright (c) 2026 程意)
- License: MIT License
- Usage: `hevi/layer4_legacy/quoteimage/oprim_impl/vendor_stitch.py` is derived from upstream `scripts/native_subtitle_stitch.py` with customizations for Hevi 3O pipeline.

## anatomy
- Location: `third_party/anatomy/` (LICENSE + NOTICE inside)
- Upstream: https://github.com/wheresryan22/anatomy (MIT, Copyright (c) 2026 Ryan)
- Vendored commit: `e9488296a44211c42701ff71705b7901470ec78f` (2026-10-16, "Merge pull request #81")
- Usage: `hevi/capabilities/anatomy_explainer/` builds kid-friendly isometric
  machinery figures with the vendored kit (`kit/iso-kit.mjs`, `lathe.mjs`,
  `tube.mjs`, `audit.mjs`), the turning 3D mode (`kit/turn*.mjs`), the
  reference examples under `examples/` (dial-indicator, ripple-tank,
  turning-dial) and the verification scripts under `scripts/`
  (`capture.mjs`, `drive.mjs`, `lines.mjs`, `turn-check.mjs`). The React kit
  (`kit/react/`, `references/react.md`) is intentionally not vendored.

## archify
Archify 是交互式图示生成器, 将类型化 JSON IR 渲染成
standalone HTML(内联 SVG, dark/light 主题, 可选 trace 动效),
并支持 PNG/JPEG/WebP/SVG/WebM 导出。

- **位置**: `third_party/archify/`
- **版本**: 3.0.1
- **仓库**: https://github.com/tt-a1i/archify
- **许可证**: MIT (见 `third_party/archify/LICENSE`)
- **附加通知**: `third_party/archify/THIRD_PARTY_NOTICES.md`
  (Simple Icons CC0 1.0 向量数据, 仅作品牌标识识别用途)
- **使用方式**: Hevi 通过 `hevi/visuals/archify_source.py`
  调用 `node third_party/archify/archify/bin/archify.mjs deliver`
  渲染结构化图示, 不修改 archify 源码。
