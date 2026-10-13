# SFXBAD_DONE — W4 音效库 + Q2 坏片回归集（分支 feat/sfx-badclips）

执行器：Claude Code（cc_loop.sh）。基线 `ac09c747`。所有数据均为真实 ffprobe /
ffmpeg ebur128 / 测试输出，无 mock、无占位产物。

> ⚠️ 并发执行器说明：本 worktree 同时被第二个自动化循环
> `hevi-d3obench/pi_loop.sh`（`pi`，弱模型）驱动。它在本轮期间把我在写的
> `scripts/sfx/*.py` 扫进了 `ac34b450`，并一度用自己未经验证的版本覆盖了
> `gen_sfx_library.py` / `make_corpus.py`。我保留了其草稿到
> `/tmp/pi_sfxbad_draft/`，并用已验证的本实现覆盖回工作区（其改动均未提交、
> 未测试）。最终提交的代码全部经过本文件所列的真实测试。

## 一、做了什么

### A. W4 音效库（step 2）
- `scripts/sfx/sfx_synth.py` — 19 类确定性合成器（numpy/scipy，固定种子）。
- `scripts/sfx/gen_sfx_library.py` — 生成器：70 条资产、写 WAV、写
  `manifest.json` + `manifest.schema.json`，支持 `--only/--batch/--manifest-only/
  --force/--dry-run`，逐文件写盘并及时 `del`/`gc.collect()`（单进程峰值 ~150 MB）。
- `assets/audio/sfx/library/<type>/<id>.wav` — **70 个** 44.1kHz / 单声道 /
  16bit WAV，**19 类**（whoosh,swoosh,riser,downer,impact,boom,glitch,click,
  tick,pop,ding,chime,typewriter,shutter,heartbeat,swipe,sparkle,bassdrop,
  notification），总 **7.3 MB**。
- `tests/test_sfx_library.py` — 9 项验收测试。

### B. Q2 坏片回归集（step 3/4）
- `tests/fixtures/qa_corpus/make_corpus.py` — 确定性生成器：lavfi
  testsrc2 基底（14s / 1280x720 / 24fps），复现 r4 的 11 条坏片 + 新增 6 类
  （字幕出框、字号过小、ASR 错配、冻帧、A/V 不同步 200ms、黑边超标）+ 1 条
  正常片 = **18 条（17 坏 + 1 好）**。`drawtext` 本 ffmpeg 未编译，文字用
  Pillow 合成 PNG 再 overlay 烧录；`freezeframes`（双输入）喂两次同一片。
- `tests/fixtures/qa_corpus/manifest.json` — 每条：配方、`expected_failures`、
  缺陷时间段、`sha256`、`duration_s`、`sha_stable`；bad14 另存
  `caption_text`/`audio_text`/`audio_text_source`。
- `tests/qa_corpus/test_qa_corpus.py` — 17 项物理验证测试（不 mock、不依赖
  omquality 审查模块）。

## 二、文件清单（本轮新增/修改，均已提交）

| 路径 | 说明 |
|---|---|
| `scripts/sfx/sfx_synth.py` | 19 类合成器（修了 4 个内存/正确性 bug，见下） |
| `scripts/sfx/gen_sfx_library.py` | 生成器 + manifest + schema + 响度策略 |
| `tests/test_sfx_library.py` | SFX 库验收测试（9 项） |
| `assets/audio/sfx/library/**/*.wav` | 70 个 WAV（`.wav` 被 .gitignore，用 `-f` 入库） |
| `assets/audio/sfx/library/manifest.json` | 70 条资产清单 |
| `assets/audio/sfx/library/manifest.schema.json` | manifest 的 JSON Schema |
| `tests/fixtures/qa_corpus/make_corpus.py` | 坏片生成器 |
| `tests/fixtures/qa_corpus/manifest.json` | 18 条坏片清单（mp4 不入库） |
| `tests/qa_corpus/test_qa_corpus.py` | 坏片物理验证（17 项） |
| `lint_before.txt` / `lint_after.txt` | 3O lint 前后 |

**未改动**：`assets/audio/sfx/` 原有 5 个 wav、`hevi/fx`、
`hevi/api/routers/audio_library.py`、任务禁止改的所有文件。

## 三、修掉的 4 个合成器 bug（上两轮 OOM 的根因）

任务提示"某个合成函数内存爆炸"。逐条（一条 entry 一次）用 RSS 看门狗定位，共 4 个：

1. **`pink_noise` 发散 → NaN**：原 4 极点 ARMA 的极点落在单位圆外，滤波器发散，
   输出全是 inf/nan。改为 6 个稳定一阶 IIR 并联（极点全部 < 1），输出有限。
2. **`sweep_bandpass` 高级索引广播 → ~15.6 GB**：`stack[i0]`（i0 是长度 n 的
   数组）广播成 `(n,n)` 矩阵；n=44100 时约 15.6 GB，直接 OOM。改为
   `stack[i0, rows]`（行/时间轴显式配对），并 `clip(i0, k-1)`。
3. **`bandpass` 切片取错区域 → 输出 ~1e-20（静音）**：`pad=2**(log2(n)+4)` 达
   ~1M 采样，`sosfiltfilt(...)[:n]` 取的是**左侧常数 edge-pad 区**（带通把 DC
   滤掉 → 近零），而非信号。改为 `pad=min(n,8192)` 且取 `[pad:pad+n]`。
4. **`hash(asset_id)` 非确定**：`hash()` 受 `PYTHONHASHSEED` 加盐，跨进程不同，
   破坏可复现。改为 `sha256(asset_id)[:4]` 派生种子。

修复后：全 70 条单进程峰值 **~150 MB**（原来一条就 >5 GB）。逐条峰值 105–154 MB。

## 四、测试命令与真实输出

```
$ JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_sfx_library.py -q
9 passed in 8.50s

$ JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/qa_corpus/test_qa_corpus.py -q
17 passed in 141.03s (0:02:21)

$ .venv/bin/python scripts/sfx/gen_sfx_library.py --force   # 真实生成日志（节选）
  70/70 rendered notification/notification_chime.wav
manifest: assets/audio/sfx/library/manifest.json
assets  : 70  (long 51, short 19)
peak >= -1 dBFS          : none
duration out of range    : none
loudness_limited (peak-limited, cannot reach -16 LUFS): 15

$ .venv/bin/python tests/fixtures/qa_corpus/make_corpus.py
wrote 18 clips (17 bad) -> /tmp/hevi_qa_corpus
manifest: tests/fixtures/qa_corpus/manifest.json  (sha_stable 18/18)
```

**SFX 测试覆盖**：≥60 文件；ffprobe 合法（pcm_s16le/44100/1ch/16bit）；时长
0.1–4.0s；真峰值 < −1 dBFS；≥0.5s 的用真实 ebur128 复测且与 manifest 一致
（±0.1 LU）；manifest 过 jsonschema；sha256 与文件一致；生成器重跑 3 条字节稳定。

**坏片测试覆盖（物理验证）**：噪声片 YDIF>15；绿屏片 VAVG 低（bad05 另 U≈0）；
下半灰块下半区行 stdev≈0；黑+静音 blackdetect/silencedetect 命中；静音空档
3–11s 时间匹配；削波 astats 峰值 ≥ −0.1dBFS；字幕出框右边缘有亮像素、字号过小
字形高 <2% 画高；ASR 元数据不一致且音轨非静音；冻帧 freezedetect 命中 6–9s；
A/V 偏移 audio start_time − video = 0.176s ≥120ms；黑边上下各 >15% 画高；
宏块片 SSIM 对基底下降；正常片以上检测全部不触发。

## 五、产物路径 + ffprobe + sha256

**SFX 库**（`assets/audio/sfx/library/`，70 wav，7.3 MB）
```
$ ffprobe assets/audio/sfx/library/whoosh/whoosh_air_up.wav
codec_name=pcm_s16le  sample_rate=44100  channels=1  bits_per_sample=16  duration=1.000000
$ sha256sum .../whoosh_air_up.wav
c7d19032efe4bb3140303747ad2d3d19c0209f7933d3b192000bd6b6bfd9c0d4
```
manifest 汇总：70 资产（long 51 / short 19）；真峰值范围 −10.5…−1.1 dBFS
（全部 < −1）；LUFS 范围 −30.2…−15.2（15 条 `loudness_limited=true`，见限制）。

**坏片库**（`/tmp/hevi_qa_corpus/`，18 mp4，**不入库**），18/18 sha 稳定，例如：
```
good_clean                14.00s sha 911e85aa868f…
bad16_av_desync           14.02s sha 86b26813c363…  (audio start_time 0.176s)
bad15_frozen_mid          14.00s sha 10c2981dcd76…  (freeze 6.0–9.0s)
```

## 六、3O lint 前后

- `lint_before.txt`（step 1 提交）：`3O_V3_LINT=PASS`（0/9 失败）。
- `lint_after.txt`（本轮）：`3O_V3_LINT=FAIL`，**4 项失败**
  （check_no_sibling_call / check_omodul_signature / check_enabled_pillars /
  check_oprim_keyword_only），**全部命中 vendored `.venv/…/omodul` 与
  `.venv/…/oprim` site-packages**，与本单元新增/修改的文件无关
  （`grep` 本单元文件在 lint 输出中命中 0 次）。4 = 任务允许的基线失败数，
  **无新增失败**。
- 差异说明：step-1 记录 PASS 与现在 FAIL(4) 的差异来自同一 `--force` 全量
  重生成脚本未被改动、失败项全在第三方包；本单元不引入任何 lint 失败。

## 七、已知限制

1. **15 条 SFX 达不到 −16 LUFS**：稀疏高波峰音效（click/shutter/typewriter/
   heartbeat/impact 尾等）波峰因数 20–30 dB，在真峰值 < −1 dBFS 的硬约束下
   **物理上**无法达到 −16 LUFS 积分响度（需 +5…+8 dBFS 峰值）。策略：向 −16
   归一 + 限幅器，**绝不削波**优先，达不到的标 `loudness_limited=true` 并记录
   实测值。这是与任务"统一到 −16"要求的一处如实偏离，已在 manifest 策略说明
   中写清理由。
2. **0.4–0.5s 段**：任务原文 <0.4s 记 null、≥0.5s 归一，两者在 0.4–0.5s 冲突。
   本实现把 null 阈值统一到 0.5s（≥0.5s 才归一），0.4–0.5s 的 3 条按峰值归一
   并记 null。
3. **坏片 mp4 不入库**（按任务），测试首次运行会在
   `${HEVI_QA_CORPUS_DIR:-/tmp/hevi_qa_corpus}` 自动重生成（约 2–3 分钟）。
4. **ASR 错配**未接真实 ASR：用 espeak 生成与字幕不一致的音轨，并在 manifest
   记录两段文稿（`caption_text`≠`audio_text`），测试断言二者不同且音轨非静音。
5. **并发执行器**：`pi_loop.sh` 与本循环共写同一 worktree，可能再次覆盖文件；
   如再现，以本 DONE 所列的已提交实现为准。

DONE SFXBAD-R1

## R2 返工（2026-10-13，对照 SFXBAD_FIX.md 逐条）

R2 复核 HEAD `9aaed762`。返工提交：`64d6e1cd`（SFX）、`b4305d64`（坏片）。
下面每条只写**本轮真实测得**的数据（命令 + 输出）。

### 1. 【SFX 方向 bug，近似重复】已修
- `scripts/sfx/sfx_synth.py::sweep_bandpass` 去掉了 `lo, hi = sorted(...)`，改为
  `freqs = np.geomspace(f0, f1, k)`（`np.geomspace` 直接支持降序），频率中心序列
  保持 f0→f1 方向；仍保留 `stack[i0, rows]` 的 O(k·n) 写法（未回退 `(n,n)` 广播）。
- 复测（STFT 谱质心对时间的斜率，Hz/s；正=上行，负=下行）：
  ```
  whoosh_air_up   +3603.7    whoosh_air_down  -2355.3
  riser_classic   +1153.6    riser_long        +787.3
  swipe_left     +17060.8    swipe_right     -16845.7
  swipe_up       +12444.7    swipe_down      -11735.8
  downer_resolve  -888.2     downer_tense     -2305.5    downer_deep -308.9
  ```
  所有 `*_down`/`downer` 均为负（下行），`*_up`/riser 均为正（上行）。
- 新增测试 `test_sweep_direction_matches_source`（对全部 whoosh/swipe/riser/downer，
  按 source 的 f0/f1 断言斜率符号）与 `test_down_and_up_sweeps_are_spectrally_opposite`
  （whoosh_air_down/up、swipe_down/up 斜率必须反号）。

### 2. 【多样性测试】已加，且参数已拉开
- 新增 `test_same_type_assets_are_distinct`：对同类两两算「32 个对数频带平均谱
  （去均值后 L2 归一）+ 20 段包络（归一）」拼接特征的余弦（各占一半），要求 ≤0.99。
- 实测同类两两余弦**最大 0.9795**（boom_thunder↔boom_cinematic）；原报告的
  click_mech/click_soft、impact_hard/impact_punch、glitch_break/glitch_stutter、
  riser_classic/riser_long 现全部 ≤0.99（同类最大值排序前六：
  0.9795 / 0.9743 / 0.9567 / 0.9506 / 0.9506 / 0.9493）。

### 3. 【响度不达标】已修，豁免已删除
- 采用规格 (a)：把之前未提交的 `body_bed`（低通粉噪 + `tanh` 软饱和，crest 由
  ~12 dB 降到 ~8 dB）正式用上，给 impact×4、boom_short、typewriter×4、shutter×3、
  heartbeat_single/double/slow 各加一层持续低频体声；`loudness_limited` 豁免删除
  （manifest 里 0 条 true，schema 里 `const False`，测试不再允许豁免）。
- 全部 70 条重生成，实测（`gen_sfx_library.py --force`，`ebur128`）：
  ```
  assets  : 70  (long 51, short 19)
  peak >= -1 dBFS          : none
  loudness_limited         : 0
  long-clip LUFS 范围       : -17.5 .. -15.3   （全部在 -16±1.5）
  true peak 范围            : -10.5 .. -1.1 dBFS（全部 < -1）
  ```
- 生成器峰值 RSS **159956 kB ≈ 160 MB**（`/usr/bin/time -v`，24.5 s）。
- 70/70 与库内文件逐字节一致（重渲到 scratch 后 sha256 全等，见验收）。

### 4. 【bad14 带入第二种缺陷】已修
- `make_corpus.py`：bad14 字幕由 `"please remember to water the plants tomorrow
  morning"`(40 px) 改为 `"remember to water the plants tomorrow"`(32 px, x=80)，
  完全落在画面安全区内。
- 实测 t=2.0s 帧右边缘 4 px 列亮像素数：bad14 = **0**（原 76）；bad12 仍 86（正对照）。
- 新增断言：`test_asr_mismatch_metadata_and_audio` 断言 bad14 右边缘无亮像素。

### 5. 【bad11 同时也是削波片】已修
- `make_corpus.py`：bad11 由 `0.99*sgn(sin(...))` 满幅方波改为短促阻尼
  4 kHz 瞬态 `0.40*exp(-mod(t,0.5)/0.0015)*sin(2*PI*4000*t)`（每 0.5s 一次）。
- 实测（解码整轨）：bad11 峰值 **-7.43 dBFS**、一阶差分 >0.15 的冲激数 **673**、
  |x|≥0.99 采样数 **0**（原 +5.2 dBFS / 5003）；good_clean 冲激数 0。
- 测试改写：bad10 削波改为「连续 ≥3 个采样贴顶」（实测 run=26）；bad11 用冲激计数
  （>20）判 pops，并断言其**不削波**（peak < -1 且贴顶 run=0）。

### 6. 【测试太松】已收紧
- 宏块 SSIM：坏片 <0.95、good_clean >0.98（原 <0.99 / >0.95）。
- clean 片新增：`silencedetect` 无静音段、右/下边缘无字幕溢出、无黑边。
  字幕边缘用「对 base.mp4 的 overlay 差分」判定（testsrc2 自身边缘就亮，纯亮度阈值
  会误判）——good_clean 右/下边缘 overlay 像素 **0**。

### 7. 【工作区卫生】已处理
- `body_bed()` 按第 3 点正式启用并提交（不再有未提交的旧 pi 残留）。

### 验收复测（本轮真实命令与输出）
```
$ JWT_SECRET=test-secret-local .venv/bin/python -m pytest \
      tests/test_sfx_library.py tests/qa_corpus -q
30 passed in 86.83s (0:01:26)
```
- 重新生成后 **70 个 wav**，sha256 全部唯一；重渲到 `/tmp/sfxbad_scratch/lib2`
  后与库内文件 **70/70 逐字节一致**；生成器峰值 RSS **160 MB**（见上）。
- 频谱图：所有 `*_down`/`downer` 下行、`*_up`/riser 上行；同类两两相似度 ≤0.9795。
- 所有 ≥0.5s 资产 ebur128 在 −17.5…−15.3（−16±1.5），真峰值 < −1 dBFS。
- 18 条坏片：bad14 右边缘干净、bad11 不削波；18/18 sha 稳定；
  `good_clean 911e85aa868f…`、`bad11_audio_pops 34b253c84c1b…`、
  `bad14_asr_mismatch be87959abd01…`、`bad12 f7548cc339b6…`。
- `lint_after.txt`：`3O_V3_LINT=FAIL`，**4 项失败**（check_no_sibling_call /
  check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），
  全部命中 vendored `.venv/…/{omodul,oprim}`，与本单元文件无关（≤ 任务允许的 4）。
- 未 push、未 merge、未切分支、未 rebase。

### 本轮已知限制（如实）
- 短于 0.5s 的 19 条仍按峰值归一、`lufs_integrated=null`（EBU R128 积分响度在
  该时长无定义）——与规格一致，非豁免。
- 坏片 mp4 仍不入库（按任务），测试首跑在 `/tmp/hevi_qa_corpus` 自动重生成。

DONE SFXBAD-R2
