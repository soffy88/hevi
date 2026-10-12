# OMQUALITY 返工（2026-10-12 13:40 UTC 独立复核 r4 未通过，HEAD 862f8e5a）

复核方用 ffmpeg 现做 11 条坏片 + 5 条正常片（脚本/结果：审核方 audit/omquality/r4_make_bad_clips.sh、r4_review_results.json；远端坏片在 /tmp/vfy_omq/），逐条跑 `hevi.studio.ops.review_finished_video`（默认配置 frame_count=4）。

## 实测结果
| 片 | 期望 | 实测 | 说明 |
|---|---|---|---|
| bad1 全片随机噪点（真音轨） | FAIL | red ✔ | noise 4/4 |
| bad2 正常片 4–7s 局部噪点花屏 | FAIL | red（侥幸） | 只因 4 个抽帧点之一 5.25s 落在 4–7s；换个时段就漏 |
| bad3 libx264 -qp 51 宏块 | FAIL | **warn / allows_compose=True** | blockiness 2.1–3.2，远低于阈值 40 |
| bad3b mpeg2 qscale31 低分辨率宏块 | FAIL | **warn / True** | blockiness 3.7–5.4 |
| bad4 全片解码绿屏（YUV=0）| FAIL | red，但原因是"平帧/冻结+幻灯片"| 无绿屏判据 |
| bad4b 正常片 6–9s 纯绿闪屏 | FAIL | **warn / True** | 仅 "1/4 帧为平帧" warning |
| bad5 下半屏灰块（整片） | FAIL | **warn / True** | 无任何半屏/区域检测 |
| bad6 黑屏+静音 | FAIL | red ✔ | 但附带错误理由"频谱平坦度 1.000 疑似白噪声" |
| bad7 3–11s 静音段（57%） | FAIL | **warn / True** | 只看总静音占比上限 90%，不看连续静音段 |
| bad8 5–8s +40dB 削波爆音 | FAIL | **warn / True** | 无削波/峰值检测 |
| bad8b 每 0.5s 一次满幅 click | FAIL | **warn / True** | 无瞬态爆音检测 |
| 正常 base / shorts_clip_01 / scene_interview_sub / hf_product_promo | PASS | warn/True ✔ | |
| 正常 hf_v8-chalkboard.mp4 | PASS | **red / False（误报）** | "频谱平坦度 1.000 疑似白噪声"——片头是数字静音 |

## 必须修复（阻断）
1. **频谱平坦度误报**：`spectral_flatness()` 只取文件开头前 4096 个采样（≈0.09s），片头静音时功率全为 epsilon → 平坦度=1.0 → 判 red。正常成片 hf_v8-chalkboard 被拦。要求：全片分窗计算、跳过静音/低能量窗、取中位数或持续时长比例判定；静音片不得报"白噪声"。
2. **宏块检测无效**：`blockiness` 实际是 16px 边界两侧像素差的均值，在噪点上≈local_diff（68），在真实宏块上只有 2–5，阈值 40 永远触发不到。要求：边界差 / 块内差 比值（boundary vs non-boundary），或 8px/16px 周期能量比；用 `-qp 51`、mpeg2 高 qscale 真实编码的片做 fixture，必须 red；正常片不得误报。
3. **局部时段花屏/绿屏漏检**：只抽 4 帧，局部 3s 坏段命中靠运气（bad4b 漏）。要求对全片做密集采样（例如每 0.5s 或复用 dense 抽帧）跑空间质量检测，任一连续坏段 ≥0.5s 即 violation，并报告时间点。
4. **绿屏/纯色/半屏灰块无判据**：增加 ①色度异常（U/V 接近 0 的解码绿、单色占比）②分区检测（上/下/左/右半区或网格中某区域 stdev≈0 且与其余区域差异大）。bad4（理由须为绿屏/色块而非仅"冻结"）、bad4b、bad5 必须 red。
5. **音频坏段漏检**：增加连续静音段检测（例如 >2s 的片中静音段 → violation，可配置），削波检测（astats 采样峰值≥0dBFS 的样本比例/Number of samples clipped），瞬态 click 检测（短时峰值/RMS 突变）。bad7/bad8/bad8b 必须 red，正常片不得误报。
6. **pytest 无新增测试**：FIX 要求的"ffmpeg 现场生成 fixture 的测试"一个都没进 tests/（176b6a73..HEAD 未改动 tests/，仍为 56 passed）。要求在 tests/ 新增真实 ffmpeg 生成坏片的测试（覆盖上表全部 11 类 + 至少 2 条真实正常片 PASS，含 hf_v8-chalkboard 这类片头静音的片），禁止 mock。
7. `is_cut_anomaly` 只写进 reasons，不影响 `is_red`/verdict，要么接进判定要么删掉，不要假装是门禁。

## 非阻断
- 噪点 violation 文案 "local_diff=66.7 > 1.7 阈值" 打印的是 edge_density 之和，不是阈值，改成 NOISE_LOCAL_DIFF_FLOOR。
- E2E 自带 bad_macroblock fixture 是人造棋盘格，不是编码宏块；bad_half_gray 是靠"缺音轨+幻灯片"判 red，不是靠半屏检测——改用真实片叠加坏段。

## 交付
用上面同款方式（正常片叠加坏段、真实低码率编码）重做 fixture，E2E manifest 记录每条 verdict/violations；DONE 如实更新；lint 新失败 0；commit。不得复制 vendor/calesthio__OpenMontage（AGPL）代码。
