# OMRENDER 返工（核验未通过）
DONE 报告与实际产物严重不符：
1. output/om_render_e2e/hf_v4-paper_styled、hf_v6-cinematic_styled、hf_v8-chalkboard_styled、hf_v9-clay_styled 四个目录里只有 script.md，没有任何 mp4/jpg，报告却写"已生成"。要求：四种（最好九种全部）lanshu 风格真正用 HyperFrames 渲染出 mp4（本地 piper 旁白+whisper 逐字时间，≥20s，含音轨），抽帧能看到该风格的画面（不是起手 placeholder「待演绎」草稿卡）。如果 lanshu kit 的 starter beats 只画 placeholder，必须自己为每条旁白写出真正的 beat（按各风格 SKILL/说明）。
2. character_animation.mp4：1920x1080 20s，但整个视频只是浅蓝底 + 左上角一行 "Hello OMRENDER!"，是静态文字，不是 SVG 角色动画，且无音轨。要求：真正的 SVG 骨骼角色（用 CMU mocap 动作数据驱动关节）在画面里走动/挥手，帧间有明显运动（报告 motion_ratio），带旁白音轨。
3. blender_shot.mp4：1280x720 5s，抽 6 帧全是同一块纯灰（#3b3b3b），没有任何场景/物体/光照。要求：有物体、灯光、相机运动的真实 Cycles/Eevee CPU 渲染，帧间有变化，≥5s，带音乐/旁白。
4. 仓库根有大量临时补丁脚本（fix_blender*.py、patch_*.py）和 blender.tar.xz 未跟踪：删除，git status 干净；blender 便携版放 /home/soffy/opt/blender 即可，不要进仓库。
5. third_party/lanshu_explainer 保留 MIT 署名（LICENSE+NOTICE）；cdn 本地化已做可保留。
6. 重跑 scripts/om_render_e2e.py，ffprobe+sha256+亲自看 contact sheet，把真实数据写入 OMRENDER_DONE.md；跑新增测试和 lint（不得多于基线 4 项失败）并 commit。clean-room（OpenMontage 部分）；禁止 mock/占位兜底/造假。
