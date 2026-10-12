# VIRALCLONE 返工 r2（Hark 独立核验 2026-10-12 08:20 CST，HEAD b72abdff + 未提交改动）

## 本轮已确认修好（不要回退）
- #1 商品卡排版：标题/标签/出处/按钮分区，三变体均无叠字；#2 var_2 无原素材英文字幕叠压；#3 var_3 英文词间空格正确；
- #6 测试：tests/test_viralclone.py + tests/test_zerolines.py 36 passed；#8 diversity 闸门有 test_diversity_gate_rejects_zero_phash；
- #9 中文字幕为填槽原文（“你见过能耐受零下两百度极寒的航天级相机吗？”等），无 ASR 错字；#10 出处 URL 已补；
- 元数据 AIGC 标签三片均有；三片音轨正常；时间对齐 pHash 均值 var1-var2=40、var1-var3=22、var2-var3=31（64bit）。

## 必须修复（阻断）
1. **AI 显式标识仍未达 ≥ 短边 5%（FIX #7 未完成）**：output/viralclone_e2e 现有成片（ASS Watermark Fontsize=49）在 t=1s 实测（var_3 纯黑底，阈值 128）：“AI” 墨迹高 25px、“生” 30px、“成” 32px，含方括号 33px；短边 720 → 3.5%–4.4%，低于 36px。你未提交的 watermark.py（0.085 em + 像素复测）方向正确，完成后：
   - 用新参数**重新跑 e2e 重出全部 3 个变体**（现有 final.mp4 仍是 10-11 14:24 UTC 的旧片）；
   - 在 DONE 写每个变体 t=1s 帧的实测墨迹 bbox 高度（px 与 % ，按汉字“生/成”墨迹，不含描边），须 ≥36px；
   - commit 代码 + 新产物证据。

## 应修复（本轮一并处理）
2. **商品卡标签“实拍商品图”不实**：PIA22103 是 NASA/JPL 示意渲染图，不是实拍。改为“示意图”/“NASA/JPL 渲染图”之类，或删除该标签。
3. **口播/字幕编造参数**：“反射率低于百分之零点一”“钛合金耐高压密封镜身”“零下两百度”等无出处的硬参数不要写进文案；改为不含具体数值的描述，或只用能在素材出处页找到的事实。
4. **变体素材复用**：三变体全部只用同两段 B-roll（ISS 地球画面 + 走廊采访）+ 同一商品图，仅换顺序/配色/画幅。逐帧最近邻 pHash：var_1 有 6/12 帧在 var_2 中有近似重复（≤10）。至少让每个变体有一段别的变体未用的公域素材或不同片段区间（in/out 点不同），并在 DONE 里给出逐对“时间对齐 pHash 均值”和“最近邻近重复帧数”。
5. var_3（720x1280）竖版里横版素材上下黑边约占 70% 画面：改为裁切填充（center-crop/模糊背景填充），不要大黑边。

## 验收
重出 ≥3 变体 → 每个抽 6 帧 contact sheet 亲眼看 → 跑 `JWT_SECRET=testsecret .venv/bin/python -m pytest tests/test_viralclone.py tests/test_zerolines.py` 全绿 + scripts/ci/run_3o_v3_lint.py 不多于基线 4 项 → 更新 VIRALCLONE_DONE.md（数字全部来自本轮实测）→ git commit。不要合并、不要 push。
