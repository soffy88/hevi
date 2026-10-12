# 第三方组件

本项目使用以下第三方组件:

| 组件 | 版本 | 许可证 | 位置 |
|---|---|---|---|
| archify | 3.0.1 | MIT | `third_party/archify/` |

完整许可证文本与附加通知见 `THIRD_PARTY_NOTICES.md`。

## archify

Archify 是交互式图示生成器, 将类型化 JSON IR 渲染成
standalone HTML(内联 SVG, dark/light 主题, 可选 trace 动效),
并支持 PNG/JPEG/WebP/SVG/WebM 导出。

- **仓库**: https://github.com/tt-a1i/archify
- **许可证**: MIT (见 `third_party/archify/LICENSE`)
- **附加通知**: `third_party/archify/THIRD_PARTY_NOTICES.md`
  (Simple Icons CC0 1.0 向量数据, 仅作品牌标识识别用途)
- **使用方式**: Hevi 通过 `hevi/visuals/archify_source.py`
  调用 `node third_party/archify/archify/bin/archify.mjs deliver`
  渲染结构化图示, 不修改 archify 源码。
