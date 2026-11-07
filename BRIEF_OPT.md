# 优化 16 条线（hevi-integ，hark/lines-integ）
复核问题：
- explainer 与 cinematic 旁白字幕是同一段文字：按线写不同脚本（各线风格/结构/口吻不同的 LLM 提示，用已有免费 LLM 路径；LLM 不可用时按线的模板也必须不同），加测试保证同一主题下 16 条线两两文本相似度 <0.6。
- podcast_repurpose 36.9s、shorts_clip 23.5s、handdraw 68.4s、localization_dub 90s 不在 30 秒 ±10%，且 3 次出同一片：修时长裁剪/拼接逻辑，关闭缓存或加入随机种子，让 3 次不同（md5 不同）。
- 全量测试 35/36，riso 偶发失败：查原因修掉（多为浏览器启动竞态/超时）。
- 先 commit 现有 19 个未提交改动（排除 samples 大文件，样片不进 git）。
验收：16 线各跑 3 次（主题“橘猫看海”），表格列时长/有声/md5/抽帧切题；pytest 全过。

## 通用规则
只在本 worktree 改并 commit 到当前分支（先 commit 现有未提交改动）；不推送、不碰主仓库 /data/soffy/projects/hevi 与 hevi-pubfix、不动生产容器、不往生产 API 提交。不花钱、不调用 Google Flow、不下载 >200MB。opencode 子调用须加 </dev/null。卡两次就记录跳过。测试用 /data/soffy/projects/hevi/.venv/bin/python -m pytest。PROGRESS_OPT.md 逐项追加。最后写 OPT_REPORT.md（中文：改了什么、commit、验收数据、仍存问题），末行 DONE。限时 3 小时内完成。
