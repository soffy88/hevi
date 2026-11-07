# OPT_REPORT

## 改了什么
- hevi/collage_broll/assets.py：新增 Pexels 图片检索（橘猫/海）+ rembg 本地抠图，User-Agent 修复 403。
- hevi/collage_broll/render.py：切题出图；海为底、猫抠图前景，半调网点+撕纸边+纸纹，视差动画；支持 duration/narration；TTS 旁白（piper）+ 字幕；B-roll 静音。
- hevi/collage_broll/capabilities.py：接入 studio CapabilityResult 契约（mp4/duration_s/sha256/qa）。
- hevi/collage_broll/__main__.py：--mode/--duration/--narration。

## commit
c22bb4e979babf04ee2a670d6872333c988738d6

## 验收数据
- 主题“橘猫看海”运行 3 次，均 30.0s，含 AAC 音轨。
- contact sheet: samples/opt/contact_sheet.png（6 帧）。

## 仍存问题
- 渲染 30s 约 105s/次，偏慢；GIF 为 5s 预览。
- 未调用 Codex（按规则开发/单测用 procedural）。
DONE
