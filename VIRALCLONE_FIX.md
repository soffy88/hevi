# VIRALCLONE 返工（巡检 2026-10-11 21:10 CST 实看 3 个变体成片）
通过项：3 个 MP4（1280x720、有音轨、AI生成 角标可见）、rembg 商品卡已出。
## 必须修复
1. **商品卡画面文字互相重叠**：变体里的商品卡镜头（NASA Mars 2020 Rover Camera）标题“Aerospace Hardware”与橙色卖点文字、红色按钮“Explore Specs”相互叠压，底部字幕又压在按钮上，视觉混乱。重排版：标题/卖点/按钮分区不重叠，字幕安全区避开按钮。
2. **烧录字幕重叠**：var_2 底部同时出现素材原有英文字幕（“I was a young boy when…”）和新烧的中文字幕，叠在一起。要么裁掉/遮盖素材原字幕区域，要么换用无字幕片段，要么把新字幕放到不重叠的位置。
3. **var_3 英文字幕无空格**（“Whysettleforordinarylenseswhenyoucan…”）：修复词间空格（词锚定模板里词级时间戳拼接时必须带空格）。
4. **变体素材过于单一且互相雷同**：var_1 与 var_3 视觉几乎相同（同一段 ISS 画面 + 同一商品卡），只换字幕语言。差异度数值必须真实反映，要求 3 个变体在镜头顺序/素材选择/节奏/转场/配色上有可见差异，并在 DONE 里给出差异度数值（例如逐变体 pHash/镜头序列/文案词差）。
5. 商品卡视频 product_card.mp4 无音轨、仅 2.48s，作为变体内镜头可以，但请确认变体里商品卡停留足够读完文字。
## 验收
重出 ≥3 变体，抽 6 帧 contact sheet 亲眼看（无重叠、无无空格字幕、有 AI 标识），更新 DONE，跑新增测试与 3O lint，提交。

## 独立核验补充（2026-10-11 21:35 CST，Hark 独立审计，以下问题同样必须修复）
6. **新增测试实际失败，DONE 报告 "15 passed" 不实**：`JWT_SECRET=testsecret .venv/bin/python -m pytest tests/test_viralclone.py tests/test_zerolines.py` 结果 `1 failed, 33 passed`，失败项 `test_real_media_compile_and_variants`：`rep["metadata_qa"]["has_implicit_watermark"]` 为 False（tests/test_viralclone.py:368）。说明 compile 路径（非 e2e 脚本路径）没有写入/读回 AIGC 隐式标识。修复 compile/render 路径的 metadata 注入，测试必须真实通过，不得改断言放水。
7. **AI 显式标识尺寸数据不实**：DONE 写 "40px / 720px = 5.56%"，但 subtitles.ass 中 Watermark 样式 Fontsize=36，实测 1280x720 帧里 "[ AI生成 ]" 字形高度约 22px（约 3%），并非 ≥5%。按 GB 45438 要求把标识字形实际像素高度做到 ≥ 短边 5%（≥36px 实测字形高度，不是字号），并用像素测量（裁剪帧求文字 bbox）计算比例，不要用字号冒充。
8. **差异度闸门逻辑失效**：diversity_matrix.json 中 var_3 vs var_1 `phash_distance: 0` 仍判 PASS（min_phash_distance=3）。画面距离为 0 必须判 FAIL，不能靠"语言不同→文本相似度 0"放过。修闸门（画面与文案都需达标或明确的加权规则）并补单测覆盖 phash=0 必须失败。
9. **中文文案/字幕是乱码级错字**：var_1 字幕 "你见过能耐树林夏两百度极寒的航天极香剂吗?"、"钛合金奈高压密封合升级断真空环境依然从容稳定点"、var_2 "普通镜头一镜低问就起雾结丼那时你没用过航天极光学元件"——看起来是把 TTS 音频再 ASR 回写成字幕，错字严重。字幕文本必须用模板填槽后的原文案，词级时间只用于对齐（强制对齐/按字符比例分配），不得用 ASR 识别结果替换原文。
10. **参考片出处补全**：DONE 里参考片/B-roll 只写标题和 Public Domain，补上原始 URL（NASA 页面/images.nasa.gov id）；商品图补 https://photojournal.jpl.nasa.gov/catalog/PIA22103 （"Cameras on Mars 2020 Rover"，Credit NASA/JPL-Caltech）。注意该图是整车示意，商品卡标题写 "Camera" 可接受但卖点不要编造参数。
## 验收补充
- `tests/test_viralclone.py` + `tests/test_zerolines.py` 全绿；3O lint 失败项不得多于基线 4 项（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only，均为 .venv 既有）。
- DONE 里所有数字必须来自本轮实测输出（ffprobe、sha256、像素测量、diversity_matrix.json），与文件一致。
