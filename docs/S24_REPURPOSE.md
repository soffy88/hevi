# S24：成片审片、字级同步与一稿多发

六个能力都是「计划 + 可执行检查 + 真实产物」。代码在
`hevi/studio/repurpose_s24.py`，接口在 `/api/studio/s24/*`，黑盒在
`scripts/s24_blackbox.py`。

## 1. 口播/讲解成片硬指标

`POST /api/studio/s24/review`（也可从 `POST /api/studio/craft/review` 的
`target=film` 带 `qc.media_path` 进入）：

| 检查 | 阈值 |
|---|---|
| 首句 | ≤5 秒且 ≤19 字 |
| 首个画面信息 | ≤2.5 秒 |
| 画面静止 | ≤5 秒 |
| 旁白语速 | 目标 4.5 字/秒；单句 >5.2 判偏快，重生成后仍快则保音高放慢 ≤15% |
| 字幕 | 单行、同句短语合并 ≤13 字、硬切、1.4 秒内停顿不撤、停留 ≥0.55 秒、<0.6 秒闪断 0 处 |
| 字幕丢帧 | 每条抽 3 帧，0 处 |
| 安全区 | x 5%–95%，y 8%–86% |
| 响度 | -14 LUFS ±1 |

输出 `review.json` + `review-overview.png`；失败项带 `retry.node`，供流水线重做该节点。
`craft/review` 的 `target=film` 会把硬指标嵌进 `hard_review`。

## 2. 字级同步镜头

`POST /api/studio/s24/word-sync`：whisper 实测字级时间戳（本机无
faster-whisper 时走同一容器 `/models/faster-whisper-large-v3-turbo`），
数字滚动、清单、对比、金句在说到的字出现。返回 `word_sync.json` 与
`word_sync.html`；所有文字走 HTML/CSS，生成图的提示词明确写“不生成任何文字”。

## 3. 一稿多发

`POST /api/studio/s24/export-pack`：

- 小红书 3:4 卡片组（1080×1440）+ `caption.md` 发帖文案；
- `wechat.html`：内联样式、图片 base64 内嵌、一键复制按钮、无外链；
- `long-image.png`：1080 宽长图；
- `theme.css`：`--s24-*` CSS 变量，和视频字幕样式共用；
- 传 `source_blocks` 时走原文路径：按块渲染并用 SHA-256 逐块读回比对。

创建页把它作为成片页的“同时导出图文”选项，不新增出品形式卡片。

## 4. 文章输入

`POST /api/studio/s24/article`：网页 / 公众号 / Markdown → `article.md`
（front matter：title/author/platform/date/url）+ `article_blocks.json`
（每块 SHA-256）。`verify_article_render` 逐块读回比对。
视频链接转逐字稿只接受 `rights_basis=self|authorized|licensed`，产出署原作者；
`bulk=true` 或读浏览器 cookie 直接拒绝。

## 5. 翻译校验

`check_localization` 已并入 `localization_dub`：块数、漏译、数字丢失，写
`localization_check.json`；`strict_localization` 时数字丢失会阻止出厂。
独立接口：`POST /api/studio/s24/localize-check`。

## 6. 合规

- 音色分层：随包设计音色可用；克隆音色只接受用户本人授权（`rights_basis=self`）
  且成片前确认一次。
- AIGC：`stamp_aigc` 在首 2 秒画面叠加“AI生成”，并写入 MP4
  `comment/title` 元数据；同目录写 `*.aigc.json`。
- 字体：`GET /api/studio/s24/fonts` 逐个列许可；只用 OFL 或明确可商用。

## 边界

- 不接 VoxCPM2 / mlx（Apple Silicon）；配音沿用现有 TTS 与 S22 许可审计结论。
- 不读浏览器 cookie，不批量抓取，不对外发消息，不新增付费服务。
- 示例内容与上游字体另有版权，未带入；见 `ARTICLE2MEDIA_ATTRIBUTION.md`。
