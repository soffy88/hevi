# HUOBAO 单元：吸收火宝短剧（chatfire-AI/huobao-drama v4.x）的剧本→资产→分镜智能体层
上游参考：/data/soffy/refs/huobao-drama（只读，浅克隆）。worktree：/data/soffy/projects/hevi-huobao，分支 feat/huobao-agents，基于 origin/closure/3o-v3-architecture-creative-baseline 当前 HEAD（其中已包含 dramaplan/dramakey/comicnarr）。
许可证：上游是 CC BY-NC-SA。用户 2026-10-11 说明 Hevi 现阶段非商用、不管许可证，所以可以阅读并改写上游的 skill 提示词。来源要登记到 docs/third_party/provenance-ledger.yaml，并标注 NC 限制，方便以后商用时整体替换。

## 背景
上游的出片环节全靠云视频 API（Seedance、Wan、MiniMax），这部分不要。只取它的 4 个 Mastra 智能体，定义在 backend/workspace/skills 和 backend/src 里：
- script_rewriter：小说 → 分集剧本，标出场景和角色；
- extractor：抽取角色、场景、道具，并去重；
- storyboard_breaker：剧本 → 分镜序列，含时长；
- prompt_generator：为角色、场景、道具生成参考图提示词，为镜头生成提示词，用 @角色 引用自动绑定参考图。
另外还有工作台上的几项交互：分集进度轨、批量生成前的确认（镜头数、总时长、模型、分辨率）、失败任务一键重试、只合并选中的镜头，合并前先校验文件存在。

## 步骤
1. **调研**：写 HUOBAO_EVAL.md，逐个对比 4 个智能体和 Hevi 现有的 hevi/shortdrama/screenwriter.py、storygraph/extract.py、dramaplan 的 script_to_storyboard、keyframe 的 prompt 生成，列出谁更强、缺什么。
2. **补齐 Hevi**（只补短板，不推翻 dramaplan 已通过的逻辑）：
   a. 资产表：角色、场景、道具三类，跨集去重合并（同人不同称谓要合成一个），每个资产生成一张参考 keyframe（CPU 国风动漫 style_presets）。
   b. 分镜提示词支持 @角色/@场景/@道具 引用，渲染时自动带上对应参考图或 seed，保证跨镜一致。
   c. 小说 → 分集剧本改写，要能选语气；台词不能丢，dramaplan r6 的逐字检查继续生效。
   d. API 侧补上三项：批量生成前的预估（镜头数、总时长、预计 CPU 耗时）、失败镜头一键重试、合并前校验文件存在。不改前端。
3. **E2E**：输入一段约 1500 字的原创小说片段（自己写，国风题材），走完 改写 → 资产 → 分镜 → CPU keyframe → CosyVoice → 合成，出 1 集 60–90 秒的 9:16 成片。交付以下内容：
   - 资产表 JSON 和参考图联系表；
   - 分镜表；
   - MP4（附 sha256、时长、LUFS）；
   - 至少 3 个镜头的抽帧证据，证明同一角色跨镜一致。
4. **测试**：pytest 覆盖以下几点，跑完后 3O lint 不新增失败：
   - 去重（别名合并）；
   - @引用解析（不存在的引用要报错）；
   - 台词逐字保留；
   - 重试只重跑失败的镜头；
   - 合并时缺文件要报错；
   - 删除任意一个产物，测试必须失败。

## 规则
- 纯 CPU，不调用付费 API，不使用云视频或云生图。LLM 只用现有的免费通道。
- 只改本 worktree；不删 worktree 外的任何文件；不清理磁盘。/data 剩余空间小于 5G 时写 DISK_FULL_NOTE.md 并停止。
- 不 push。所有 python 设 PYTHONPATH=本 worktree。长时间的 E2E 用 nohup setsid 后台跑，再轮询结果。
- 完成后在 HUOBAO_DONE.md 最后一行写 DONE HUOBAO-R1。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-huobao；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 HUOBAO_DONE.md 最后一行写 DONE HUOBAO-R1。

## 追加要求（2026-10-14 16:50）：能力契约
本线的能力必须按本 worktree 里的 CAPABILITY_CONTRACT.md 注册到 hevi/capabilities/registry.py，让各个产品线都能按名字调用，不要只做私有入口。如果本分支里还没有 registry.py，就按契约建一个最小实现（webkit 单元负责权威版本，最后合并时以它为准）。DONE 报告里要列出本线注册的全部能力名。

## 产品方向（2026-10-14 追加，优先级最高）
阅读 KIDS_ANIME_DIRECTION.md：Hevi 以幼儿（2–6 岁）有营养的动漫故事片为主。本单元的样片、配色、台词、节奏都要符合其中的内容要求和 kids_gate 安全闸门（镜头≥2.5s、闪烁≤3Hz、-16 LUFS、无惊吓/暴力、字幕大号）。manga 单元改为彩色绘本风为主，黑白网点只作可选项；E2E 剧情改成幼儿向。huobao 增加 kids 模式（剧本改写时加入成长主题与重复句式）。
