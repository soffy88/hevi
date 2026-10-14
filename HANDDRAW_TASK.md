# HANDDRAW 单元：把 sweety-handdraw-video（MIT，v1.2.3）内化为 Hevi 的 CPU「手绘口播」线

上游参考：/data/soffy/refs/sweety-handdraw-video（只读）。worktree：/data/soffy/projects/hevi-handdraw，分支 feat/handdraw-line，基于 7087c24a。

## 背景
上游用 Python / Pillow / SciPy / FFmpeg 实现手绘讲解视频：按语义部位逐笔描线 → 同序填色 → 关键句逐字手写 → 手臂/画笔跟随笔尖 → 先合成整篇旁白，再按时间戳排画面 → 单套字幕。上游是 MIT 协议，可以 vendor 渲染脚本，但必须保留 LICENSE 和 THIRD_PARTY_NOTICES，并写入 docs/third_party/provenance-ledger.yaml。
上游有两处要替换：
- 生图：上游用 Codex 生图。Hevi 不能用付费生图，插画来源改成以下三种之一：Hevi 现有 CPU keyframe（国风动漫 style_presets）、Archify 图解、本地素材。
- 配音：上游用 VoxCPM2 MLX（Mac）或 VoiceStudio。Hevi 改用 CosyVoice（gen-engine 127.0.0.1:17600），piper 做兜底。

## 步骤
1. **调研**：写 HANDDRAW_EVAL.md，说明上游流水线各阶段、哪些可以直接 vendor、5 项内置依赖的许可证，以及和 Hevi 现有 artmotion、stickdir、talkcraft 的重叠与差异。
2. **vendor 渲染器**：放到 hevi/layer4_legacy/handdraw/（或参照 stickdir 的线路结构），跑通上游自带的 smoke_test 和 unittest，全过。
3. **接入**：
   - 加 line=handdraw：输入主题或文章 → 口播稿 → 分镜 → 插画（CPU） → 整篇 CosyVoice 旁白 → 时间戳对齐 → 渲染；
   - 画布支持 1920x1080 和 1080x1920 两种，竖屏要重新排构图和字号；
   - 风格至少支持 4 种：1 极简黑白线条、8 水墨写意、10 淡彩速写、17 墨线绘本；
   - 手部至少支持 pen-only 和 1 款手臂。
4. **E2E 样片**：
   - 横屏、竖屏各 1 条，每条 40–70 秒，主题分别是「为什么越生气越容易做错决定」和「复利效应」；
   - 交付物：MP4、封面 PNG、SRT、口播稿、检查记录，并写明 sha256、时长、LUFS；
   - 片中必须真的看得到逐笔描线和逐字书写过程，不能直接贴最终图；
   - 字幕不能断词，也不能溢出画面。
5. **测试**：新增 pytest 覆盖以下几点，跑完后 3O lint 不新增失败：
   - 描线进度单调递增；
   - 删除任意一个产物，测试必须失败；
   - 只允许有一套字幕；
   - 旁白时间戳与画面对齐，误差 ≤0.2s。

## 安全规则
- 只改本 worktree；不删除 worktree 外的任何文件；不清理磁盘。/data 剩余空间小于 5G 时写 DISK_FULL_NOTE.md 并停止。
- 所有命令都设 PYTHONPATH=/data/soffy/projects/hevi-handdraw。长时间的 E2E 用 nohup setsid 后台跑，再轮询结果。
- 不调用付费 API，不使用 GPU，不 push。lint 日志不要提交进仓库。
- 完成后在 HANDDRAW_DONE.md 最后一行写 DONE HANDDRAW-R1。

## 追加要求（2026-10-14 16:50）：能力契约
本线的能力必须按本 worktree 里的 CAPABILITY_CONTRACT.md 注册到 hevi/capabilities/registry.py，让各个产品线都能按名字调用，不要只做私有入口。如果本分支里还没有 registry.py，就按契约建一个最小实现（webkit 单元负责权威版本，最后合并时以它为准）。DONE 报告里要列出本线注册的全部能力名。

## 产品方向（2026-10-14 追加，优先级最高）
阅读 KIDS_ANIME_DIRECTION.md：Hevi 以幼儿（2–6 岁）有营养的动漫故事片为主。本单元的样片、配色、台词、节奏都要符合其中的内容要求和 kids_gate 安全闸门（镜头≥2.5s、闪烁≤3Hz、-16 LUFS、无惊吓/暴力、字幕大号）。manga 单元改为彩色绘本风为主，黑白网点只作可选项；E2E 剧情改成幼儿向。huobao 增加 kids 模式（剧本改写时加入成长主题与重复句式）。
