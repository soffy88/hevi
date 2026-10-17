# VIRALCLONE 返工 r3（Hark 独立核验 2026-10-12 10:05 CST，HEAD 287dbb37，工作树干净）

## 本轮已确认修好（不要回退）
- 测试：tests/test_viralclone.py + tests/test_zerolines.py **43 passed**（289s）；3O lint 仅基线 4 项（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），无新增。
- 成片 sha256/ffprobe 与 DONE 一致：var_1 46618d8c… 9.24s 1280x720；var_2 684955c1… 11.04s 1280x720；var_3 bda28316… 8.84s 720x1280；h264/aac，mean_volume -19~-20dB。
- AI 标识（真实成片帧实测，t=0.5/1.0s，白色填充、不含描边）：“生”38px(5.28%)、“成”39px(5.42%)、方括号 41px，≥36px ✓。
- 商品卡标签已改“渲染示意图”；无“零下两百度/钛合金/反射率”等编造参数；var_3 竖版已是模糊背景填充，无大黑边；中途黑帧已消除（blackdetect 仅片头 0.04/0.08s 淡入）；无双字幕、无错字；无 mock/云 API。
- 帧级复用：1fps pHash 逐对时间对齐均值 34.7 / 23.3 / 32.2，最近邻近重复帧 0。

## 必须修复（阻断）
1. **画面与旁白语义不匹配（核心问题，三片全中）**：旁白/字幕全是“火星车/避障相机/桅杆相机”，但画面是 ISS 俯瞰地球+联盟号飞船、以及 Apollo 宇航员 Michael Collins 走廊采访：
   - var_1 0–3s “火星车靠什么看清脚下的路？”配 ISS 地球画面；6–9s “想看火星车影像…”配走廊采访。
   - var_2 0–4s “在火星表面移动，避障相机就是眼睛”配走廊两人行走；7–11s “更多火星车影像…”配 ISS 画面。
   - var_3 0–2.4s “How does a rover see the path ahead on Mars?”配走廊；6–9s 配 ISS。
   修法：下载 **NASA/JPL 公有领域的火星车相关视频**（例如 images.nasa.gov / science.nasa.gov 上 Perseverance 着陆/行驶/相机工作的视频或 NASA/JPL 动画，或 Perseverance Navcam/Hazcam 原始图序列做 Ken Burns），记录标题/URL/许可/sha256；B-roll 必须与对应旁白句语义一致（说火星车就出火星车/火星地表/相机画面）。不得用 AI 生成画面冒充，不得用付费 API。在 DONE 里给出每个变体“每句旁白 ↔ 画面来源片段（文件+in/out）”对照表。
2. **素材来源复用 100%**：三变体用的是完全相同的 3 个来源（ISS 片、走廊采访、PIA22103），仅换 in 点/顺序/调色。换素材时请保证每个变体至少有 1 段其他变体未用的来源片段，并在 DONE 给出“来源级复用表”（每个变体用了哪些源文件）+ 逐对 1fps pHash 对齐均值与近重复帧数。

## 应修复（本轮一并处理）
3. **“AI”两个拉丁字母只有 31px（4.31%）**：GB 45438 要求提示文字高度≥短边 5%，字母也是提示文字的一部分。把字号提到使 “A”“I” 墨迹也 ≥36px（约 Fontsize 72），并在真实成片帧（非重渲染）上按字逐个测量写入 DONE（方法：解码 t=0.5/1.0s 帧，取 min(RGB)>215 且低饱和像素，按列分段量高度）。
4. **商品卡 CTA“Explore Specs”名不副实**：卡上没有任何参数，改成“了解更多 / Learn more（NASA/JPL）”之类；标题“Mars 2020 Rover Camera”配整车渲染图，建议改 “Mars 2020 Rover · Cameras”。
5. var_1 第二句“前后避障相机，一路记录着陆和行驶”：着陆过程主要由 EDL 相机记录，避障相机用于行驶避障，改为有出处的表述（参考 https://mars.nasa.gov/mars2020/mission/rover/cameras/ ）。

## 验收
重跑 e2e 重出 ≥3 变体 → 每片抽 6 帧 contact sheet 亲眼看（画面必须是火星车/火星相关）→ `JWT_SECRET=testsecret PYTHONPATH=. .venv/bin/python -m pytest tests/test_viralclone.py tests/test_zerolines.py` 全绿 + scripts/ci/run_3o_v3_lint.py 不多于基线 4 项 → 更新 VIRALCLONE_DONE.md（数字全部来自本轮实测，含上面三张表）→ git commit。不要合并、不要 push。
**长任务（e2e 渲染、pytest）必须用 nohup setsid 独立启动，轮询到产物/结果文件完成后再结束会话，不得中途退出。**
