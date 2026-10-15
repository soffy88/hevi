# 第三方许可声明 / Third-Party Notices — 发布前套件 (publishkit)

本模块基于开源调查视频产线（trustfuture__simon-skills / video-common 与
investigation-video，MIT 协议）的发布前检查规范与文案模板内化实现。
封面排版使用 `hevi-remotion-whiteboard/assets/fonts/Xiaolai-Regular.ttf`
（SIL Open Font License 1.1，声明见
`hevi-remotion-whiteboard/THIRD_PARTY_NOTICES.whiteboard.md`）。

## 内化的上游规范

| 上游文件 | 内化到 |
|---|---|
| `skills/video-common/references/compliance.md` | `oskill_impl/compliance.py`（三条红线 → 六条规则检查） |
| `skills/video-common/references/cover-qa.md` | `omodul_impl/cover.py`（3:4 / 4:3 两种独立比例 + 实测比例校验） |
| `skills/video-common/references/delivery-qa.md` | `omodul_impl/qa.py`（ffprobe 机器检查 / 黑帧 / 静音 / 字幕区间） |
| `skills/video-common/references/fact-check.md` | `oskill_impl/fact_check.py`（来源台账 + 口径一致节 + 估算标注） |
| `skills/video-common/references/platform-copy.md` | `oskill_impl/platform_copy.py`（每平台一套：主推/备选标题、正文、话题、置顶评论） |
| `skills/investigation-video/assets/publishing-reference/八平台发布文案-模板.md` | `oskill_impl/platform_copy.py` + `render_copy_md()` 排版 |

## 1. simon-skills (video-common / investigation-video)
- 源码来源：trustfuture__simon-skills
- 许可协议：MIT License
- 版权信息：Copyright (c) 2026 trustfuture

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 2. 小赖字体 (Xiaolai Font)
- 字体路径：`hevi-remotion-whiteboard/assets/fonts/Xiaolai-Regular.ttf`
- 许可协议：SIL Open Font License 1.1 (OFL)
- 版权信息：Copyright (c) 2020-2023, Sean (lxgw@github)

## 已知偏差（与上游规则的差异，如实记录）

上游 `cover-qa.md` 要求用 imagegen 生成整幅 AI 封面。本机零成本约束下无 imagegen，
`omodul_impl/cover.py` 改为「取成片帧 + 本地中文字体排版标题」，并在
`cover_qa.json` 的 `provenance` 中标记 `upstream_ai_cover_rule_met: false`。