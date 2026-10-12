# OMQUALITY 返工（2026-10-12 08:15 UTC 独立核验未通过，HEAD 176b6a73）

核验已确认真实的部分：增强四件套真跑（rembg u2net RGBA 透明 83%；Real-ESRGAN x2 320→640 有可见锐化；GFPGAN 脸部明显重建且默认关闭需 opt-in；LUT 真改像素，before/after 平均差 R4.9/G2.7/B4.4）；三个 mp4（lut_video 13.96s、slideshow_stress_case 12.0s、replay_approved 36.69s sha 8bcdd7d3… 与 DONE 一致）均为真实画面、音轨 mean≈-21dB；指定 5 个测试 56 passed；3O lint 仅基线 4 项；AGPL 长行比对 0 命中。审核方自造劣质片测 review.finished_video：黑屏+静音 → red（4 条 violation）✔；单帧冻结+静音 → red ✔。

## 必须修复
1. **花屏/破图检测无效（硬伤）**：审核方用 ffmpeg 生成 10s 1280x720 全帧随机噪点（`nullsrc,geq=random(1)*255:128:128`）+ 白噪声音频的片，`review.finished_video` 返回 verdict=warn、**allows_compose=True**、violations=[]；幻灯片风险反而 0.0 green（20 个 dense 帧全部当成"切点"）。DONE 声称有"破图"检测，实际没有。要求：
   - 抽帧增加真实破图/花屏度量（例如高频能量/空间自相关、块效应、相邻帧完全不相关比例、边缘密度异常），全帧噪点、宏块花屏、绿屏/半屏灰块必须判 red；
   - "每个 dense 帧都是切点"（cut 比例≈100%、帧间差异极大且无连续性）应判为异常，而不是"运动充足"；
   - 音频：持续宽带白噪声（频谱平坦度极高）应至少给 warn/violation；
   - 新增真实 fixture 测试：用 ffmpeg 现场生成①全帧噪点 ②正常片中间插入 1s 宏块花屏/绿屏 ③半屏灰块，三者都必须 allows_compose=False；FINAL.mp4 等好片仍须通过。禁止 mock。
2. 审片 E2E（scripts/om_quality_e2e.py）中补上上述三类劣质片 + 黑屏静音片的审片报告与 contact sheet，manifest 里记录 verdict/violations 实测值。
3. 小问题：matte 对 FINAL 帧只抠出了白衣老人和蓝衣人的头，蓝衣人身体被丢掉（u2net 只取最显著主体）。在 DONE 里如实写明局限，或提供 isnet-general-use / 人像模型选项并在对比图展示。

## 交付要求
- 重跑 E2E，逐张看对比图与 contact sheet；DONE 更新路径 + ffprobe + sha256 + 门禁实测值；lint 新失败 0；git status 干净后 commit。
- 不得复制 /data/soffy/projects/vendor/calesthio__OpenMontage（AGPL）任何代码或文本。
