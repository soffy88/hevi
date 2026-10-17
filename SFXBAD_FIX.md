# SFXBAD_FIX — 独立复核不通过（2026-10-13 15:50 CST，复核 HEAD 9aaed762）

复核人实测证据在主会话 audit/feature4/verify_sfxbad/。以下是已确认通过、**不要改坏**的部分，以及必须修的问题。

## 已通过（保持）
- 内存爆炸已修：`sweep_bandpass` 用 `stack[i0, rows]`，全量 `--force` 重生成 70 条峰值 RSS 161 MB、32 s；70/70 与库内文件逐字节一致。
- 70 个 wav，sha256 全部唯一；manifest 的 sha/时长/LUFS 与实测一致；无削波（峰值 ≤ −1.5 dBFS）；时长 0.10–3.8 s。
- 18 条坏片 ffprobe 合法，tests/test_sfx_library.py 9 passed，tests/qa_corpus 17 passed（232 s）；3O lint 只有基线 4 项失败。
- 坏片肉眼核对：噪声、局部 glitch、qp51/mpeg2 宏块（SSIM 0.933/0.888）、全绿、局部绿、下半灰、黑+静音、静音空档 3.02–11.01 s、冻帧 6.0–9.04 s、A/V 偏移 0.176 s、字幕出框、字号过小、黑边，都真实存在。

## 必须修
1. **【SFX 方向 bug，导致近似重复】`scripts/sfx/sfx_synth.py::sweep_bandpass` 把 f0/f1 排序后总是从低往高扫**（`lo, hi = ...; freqs = np.geomspace(lo, hi, k)`），f0>f1 的下行扫频实际变成上行。频谱图实测：`whoosh_air_down` 和 `whoosh_air_up` 一样都是上行（特征余弦 0.979），`swipe_right` ≈ `swipe_left`（0.998），`swipe_down` ≈ `swipe_up`（0.991）；`downer_*` 的噪声层也在上行，和下行音调层方向相反。修复：保持频率中心序列的方向（f0→f1），保留 O(k·n) 的内存写法，不得回退到 (n,n) 广播。修好后重新生成并重测 manifest。
2. **【多样性测试】新增测试**：(a) 所有 source 里 f0>f1 的扫频类资产（whoosh/swipe/downer 的噪声层），用 STFT 频谱质心随时间的斜率断言是下行，f0<f1 的断言是上行；(b) 同类资产两两之间，用「32 个对数频带平均谱（去均值后归一化）+ 20 段包络（归一化）」拼接特征的余弦相似度（两部分各占一半），不得 >0.99；不满足就修改参数让声音听得出不同（目前 click_mech/click_soft 0.993、impact_hard/impact_punch 0.992、glitch_break/glitch_stutter 0.991、riser_classic/riser_long 0.986 只是长度不同，也要拉开差异）。
3. **【响度不达标】15 条 ≥0.5 s 的资产积分响度不在 −16±1.5**（impact×4、boom_short、typewriter×4、shutter×3、heartbeat_single/double/slow；实测低到 −30.2 LUFS）。"物理上不可能"这个说法不成立。按规格二选一：(a) 重新设计，加入持续成分（机械共振/箱体/房间尾音，例如工作区里未提交的 `body_bed` 思路）+ 压缩/限幅，使积分响度达到 −16±1.5，同时真峰值 < −1 dBFS；(b) 某些类型确实应该很短的，把时长改到 <0.5 s，按短片规则做峰值归一。最终要求：**所有 ≥0.5 s 的资产都达到 −16±1.5 LUFS**，删除 `loudness_limited` 豁免（或者 0 条为 true），并保持 ≥60 个合规资产；测试同步改严（不允许豁免）。
4. **【坏片带入了第二种缺陷】bad14_asr_mismatch 的烧录字幕 "please remember … morning" 超出了右边缘**（t=5 s 时右侧 4 px 列有 76 个 >220 的亮像素，和 bad12 一样），等于同时带了一个没标注的 subtitle.out_of_frame。把字号或文本改到能完整放进画面安全区内；测试断言 bad14 右边缘干净。
5. **【坏片带入了第二种缺陷】bad11_audio_pops 同时也是削波片**：峰值 +5.2 dBFS，|x|>0.99 的采样有 5003 个。改成 pops/clicks 是瞬态冲激，但峰值 < −1 dBFS、没有削波；测试改为用一阶差分/冲激计数检测 pops（bad11 冲激数 > 阈值，good_clean 为 0），并断言 bad11 **没有**削波；bad10 的削波测试要求有连续 ≥3 个采样贴顶（不是只看 peak）。
6. **【测试太松】** 宏块测试 SSIM 阈值 <0.99 太松（实测 0.933/0.888，good 0.989）：改成坏片 <0.95，good_clean >0.98。clean 片测试再加：silencedetect 无静音段、右/下边缘无字幕溢出、无黑边。
7. **工作区卫生**：`scripts/sfx/sfx_synth.py` 里有一个旧 pi 进程留下的未提交 `body_bed()`（之前没有被调用）。旧 pi 进程已经被复核人停掉。要么在第 3 点里正式用上并提交，要么 `git checkout` 这个文件丢掉它；不要留下未提交的改动。

## 验收（复核会逐条复测）
- 重新生成后 ≥60 个 wav，sha 唯一，重跑逐字节一致，生成器峰值 RSS < 1.5 G（用 `/usr/bin/time -v` 记录到 DONE）。
- 频谱图：所有 *_down/downer 都是下行；同类两两相似度 ≤0.99。
- 所有 ≥0.5 s 的资产 ebur128 都在 −16±1.5，真峰值 < −1 dBFS。
- 18 条坏片每条只带标注的缺陷（bad14 不出框，bad11 不削波），sha 稳定，测试全部通过。
- 3O lint 失败数 ≤4。不 push、不 merge。DONE 追加 R2 段，最后一行 `DONE SFXBAD-R2`。
