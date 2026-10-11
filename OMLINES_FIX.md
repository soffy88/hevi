# OMLINES 返工（2026-10-11 09:35 UTC 核验结果）
13 条产线 ffprobe 均有视频+音轨，但以下不合格：
1. hevi/layer4_legacy/omlines/omodul_impl/lines.py `_localization_dub`：只是"Pexels 开会素材 + 中文 TTS 念‘这是外语配音版本’"，provenance 写着 'localization_dub mock'，并非真配音。必须真做：取一段带人声的源视频（可用本地 piper/edge/CosyVoice 生成的外语源，或已有成片），whisper 转写 → 翻译（免费方案/本地）→ 本地 TTS 生成目标语言 → 替换音轨并对齐时长 → 字幕。provenance 写真实来源，删除 mock 字样。
2. e2e_results.json 里 documentary_montage 的 dark_textcard_ratio 检查为 false、podcast_repurpose 的 motion_mean_ge_min 为 false，但状态仍写 SUCCESS。质检门不通过必须标 FAIL 并修产线（documentary_montage 画面为暗底火箭+字幕，需有足够的真实内容变化；podcast_repurpose motion 0.528 太低，加入真实动态元素如波形/镜头运动）。禁止放宽阈值过关。
3. 仓库根目录残留临时脚本 patch_lines.py、test_dub.py、test_montage.py、test_talking_head.py、run_omlines_e2e.py：删除或移入 scripts/ 与 tests/ 并规范。scripts/qualify_autonomous_production.py 的 placeholder 统计保持诚实。
4. 每条产线：ffprobe + 6 帧 contact sheet 自己 read 看一遍，画面要和主题一致。不得调付费 API（Pexels 免费 key 可，但需在 DONE 标明来源与 key 来自环境变量）。
5. 完成后更新 OMLINES_DONE.md，git commit，lint 新失败数 0。
