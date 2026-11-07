# hevi 产线集成与补修（2026-11-07）

你在 worktree /data/soffy/projects/hevi-integ（分支 hark/lines-integ，基于 8da6d735）。参考：/data/soffy/projects/hevi-audit-1106/AUDIT_1106_REPORT.md、/data/soffy/projects/hevi-linefix-a/LINEFIX_A_REPORT.md、/data/soffy/projects/hevi-linefix-b/LINEFIX_B_REPORT.md。

## 步骤
1. 合并：先 git merge hark/linefix-b，再 git merge hark/linefix-a，认真解决 zerolines 等冲突（两边的修复都要保留），提交。两个旧 worktree 各有约 10 个未提交文件，检查是否是需要的修复（如是则带入并说明）。
2. 补修（每项单独 commit + 单测）：
   - A 线时长：character_animation(12s)、comic_narration(24.5s)、documentary_montage(25.5s)、handdraw(2s)、localization_dub(11.5s)、reference_adapt(7.2s)、scene3d(12s)、shorts_clip(19.4s) 都要尊重请求时长 30 秒（±10%）。shorts_clip/localization_dub/reference_adapt/podcast_repurpose 这类依赖源素材的线，时长受源素材限制时：准备一份 ≥60 秒的本地测试源素材（用 Piper 生成中文旁白 + 已有画面合成，放 samples/_fixtures/），按请求时长裁切。
   - scene3d 必须有音轨（旁白 + BGM）。
   - handdraw 必须是真正的逐笔手绘动画且有旁白，不是 2 秒占位。
   - 同质化：explainer / cinematic / director_pipeline / history_scene 不能共用同一组素材。按线区分检索策略（例如 explainer 偏特写与图解卡片、cinematic 偏广角与慢镜调色、history_scene 偏档案质感），同一 job 内按线做素材去重；验收时两线素材重合率 ≤30%（用素材 id 统计）。
   - podcast_repurpose 三次 md5 一致：查明是否缓存；默认每次真实重渲染，缓存需显式开关，并在报告说明。
   - 字幕中英混杂（如 "curled up"）：中文题材的旁白与字幕全中文，加校验。
3. 测试：/data/soffy/projects/hevi/.venv/bin/python -m pytest 跑 tests/ 中 zerolines、studio_slate、flowgen、riso 相关测试，全部通过。
4. 验收：16 条线（explainer、cinematic、director_pipeline、kinetic_promo、history_scene、talking_head、avatar_spokesperson、podcast_repurpose、character_animation、shorts_clip、reference_adapt、comic_narration、handdraw、scene3d、localization_dub、documentary_montage）本地各跑 3 次，题材“一只橘猫第一次看海”，30 秒。记录成功数、耗时、ffprobe 时长/分辨率/音轨、volumedetect、md5；每条抽 6 帧拼 contact sheet。产物放 samples/<线>/run{1,2,3}/。

## 规则
- 只在本 worktree 改代码和 commit；不推送、不碰主仓库 /data/soffy/projects/hevi 工作区、不重启/改动生产容器、不往生产 API 提交任务。
- 不花钱；不下载 >200MB。同一问题卡两次就记录并继续。每完成一项追加 PROGRESS.md。

## 输出
INTEG_REPORT.md（中文）：合并与冲突处理；每项补修 | commit；16 条线总表（3 次结果、平均耗时、时长、有声、字幕、md5 是否不同、素材重合率）；测试结果；仍存问题。最后一行 DONE。
