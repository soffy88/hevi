# 剪辑规则卡（editing basics）

> 出处：内部教学《AI 视频基础·下册：剪辑》（摆好画面 → 调整节奏 → 处理声音
> → 加字幕 → 导出）。本卡把其中可执行的要点逐项对照 hevi 的现有实现：
> 每条写清归哪道检查/能力管、阈值在哪、没落地的部分如实标注。
> 声音响度/峰值的细则不在本卡重复，以 [audio_gate.md](audio_gate.md) 为准。

## 门禁与检查分工

| 层 | 管什么 | 入口 |
|---|---|---|
| 计划层 | 叙事结构、跨镜状态、阶段清单 | `story_check`（`hevi/storyplan/check.py`，C1–C9） |
| 生成/装配层 | 接缝声画错位、卡点、字幕可读性、混音 | `hevi/director/cut_style.py`、`hevi/assembly/*` |
| 声音层 | 响度、真峰值、削波、关键错误词 | `audio.earshot_gate`、ASR 校验（见 audio_gate.md） |
| 交付层 | 成片文件本身：编码/规格/黑帧/同步/结尾/字幕存在性 | `qa.export_gate`（`hevi/quality/export_qa.py`） |
| 修复层 | 失败后按原因分流，不是一种修法包打天下 | `hevi/quality/taxonomy.py` + repair controller/executor |

一条片出门前至少过：计划层（有计划时）→ 声音层 → 交付层。
`film_gate` 查画面运动/硬伤，与本卡各层互补，不互相替代。

## 逐项对照（下册要点 → hevi 落地）

### 1. 叙事四环：准备 → 动作 → 结果 → 反应

- 拍型集合含 `reaction`（`hevi/storyplan/model.py` 的 `BEAT_KINDS`）。
- `autofill_story_plan` 自产计划默认在 result 后补 reaction 拍（末 10%）。
- 检查 C8_REACTION_BEAT（`check.py`）：有 result 拍而其后无 reaction 拍
  （或 reaction 跑到 result 前面）报 **WARN**，不设 hard fail——存量计划
  （如 kids 六拍）只提示不打爆。缺反应环的后果由修复层兜底：
  taxonomy `MISSING_SHOT` → `insert_shot`。

### 2. 切点与镜头时长：看观众在等什么

- 没有"每镜三秒"之类硬规则；时长按拍型给尾（`hevi/storyfilm/pipeline.py`
  的 `tail_for_beat`）：reaction/emotion 0.8 s、result 0.5 s、
  default 0.35 s、末镜下限 1.2 s。拍型由 `infer_beat_kind` 从
  motion_prompt/visual/旁白关键词推断，draft 显式给 `beat_kind` 时优先。
- 旁白语速上限由 story_check 既有检查把关（字/秒超速 FAIL）。

### 3. 动作衔接：同一动作换角度不能重做、不能跳步

- 检查 C9_ACTION_CONTINUITY（`check.py`，WARN）：**同场景内**相邻镜
  比对上一镜 `end_state` 与下一镜 `start_state`（strip 后逐字相等），
  不一致逐镜列出。跨场景状态允许重置，不比对。
- autofill 自产镜头的状态链已对齐（上一镜 end = 下一镜 start）。
- 装配后发现衔接断裂：taxonomy `ACTION_DISCONTINUITY` → `adjust_cut`。

### 4. 节奏与变速（理念项，无专门代码）

- 节奏靠删重复、接紧镜头得到，**不靠整体变速**；变速（atempo/setpts）
  会同时改变动作与声音的质感，只在明确创作意图下用。
- 慢动作 ≠ 长镜头：长镜头是给观众更多观察时间，播放速度不变。
  需要"多留一会儿"时改尾时长（见第 2 条），不要用变速冒充。
- 本条目前只有规则、没有自动检查；评审/审稿时按此口径判断。

### 5. 蒙太奇：先列变化阶段，再生成镜头

- 中间产物 `change_stages`（`hevi/storyplan/model.py` 的 `ChangeStage`：
  name / target_state / description / 可选 phase）。
- `autofill_story_plan(change_stages=[...])` 按阶段等分时间轴生成 beats，
  一阶段至少一拍；阶段声明合法 phase 时尊重声明，否则首=cause、
  尾=result、中间=process。
- 阶段内保持一致的元素（人物、服装、场景）与随阶段变化的元素
  （年龄、季节、熟练度）要在阶段清单里分开写明——变化是叙事，
  无意的一致性漂移是事故，由第 3 条与一致性门禁管。

### 6. J-cut / L-cut：声音先到、或声音留后

- 判定与偏移：`hevi/director/cut_style.py` 的 `classify_seam_cut_style`
  （J = 下一句先入耳，偏移为负；L = 上一句压住反应镜，偏移为正），
  `seam_offset_ms()` 是 produce 侧的单一真源。
- `produce_v2` 两条对白分支（原生对白提取、回退 TTS）都已接线；
  原生分支经 `native_start_ms()` 把偏移只作用于时间线位置，
  **不动 ASR 窗口**——窗口一动，提取的音频就和听到的对不上。
- 单纯一首 BGM 从头放到尾不叫 J/L-cut；同一人在画面内说话时
  口型仍须对齐（见第 8 条）。

### 7. 音乐闪避（ducking）

- 已落地（既有实现）：`hevi/assembly/assembler.py` 的混音段做
  BGM 侧链闪避（旁白出现时压 BGM）+ 响度归一；
  `hevi/audio/storybook_voice.py` 另有增益包络式 ducking（绘本线）。
- 顺序口径（下册五步）：先调人声 → 接环境声 → 补必要音效 →
  加音乐并闪避 → 查突然出现/结束的声音。响度数值标准见 audio_gate.md。

### 8. 声画同步

- 成片级：`qa.export_gate` 的 `av_sync` 检查音视频流时长差 ≤ 0.5 s。
- 词/句级同步靠对齐管线本身保证（whisper_local / elevenlabs_forced
  两档实测时间戳，选档见 audio_gate.md）；字幕侧由第 10 条的不剧透
  检查反向兜住（字幕不得早于词出现）。
- 口型漂移属生成侧问题（taxonomy 既有 `LIPSYNC_DRIFT`），整条挪
  音频修不好，回到生成环节，不要在导出层硬凑。

### 9. 卡点（beat align）

- 能力 `assembly.beat_align`（`hevi/capabilities/beat_align.py`）：
  librosa 检测 BGM 节拍，给定各镜时长时返回**逐接缝**吸附后的
  xfade 时长；检测不到节拍时 `fallback: true` + 均匀时长，
  不假装吸附成功。报告落 `beat_align_report.json`。
- `assemble_longvideo(bgm_beat_align=True)` 已按逐接缝列表消费
  （旧实现只取第一条接缝的值，已修）。
- 卡点是可用则用：观众没看清、一句话没说完时，镜头可以跨过节拍，
  不要为了踩点切碎信息（见第 2 条）。

### 10. 字幕 QA

- 可读性：`hevi/assembly/subtitle_timeline_atoms.py` 的
  `validate_cue_readability` —— CPS 上限（CJK 15 字/秒为硬顶、
  舒适目标 12；拉丁 20 字/秒）与最短显示 0.8 s，混合文本按
  所需时长合并判定。`normalize_cues` / `validate_srt` /
  `validate_ass` 传 `strict_readability=True` 时违规直接报错，
  默认关（不改变历史行为），新管线应显式打开。
- 不剧透：同文件的 `check_cue_early_start` —— 字幕开始时间不得
  早于其首词的实测发声时间（容差 50 ms）；匹配不到词流的 cue
  跳过判定，不误报。
- 识别校对：`hevi/audio/asr_verify.py` 的 `critical_word_errors`
  专门盯 CER 看不见的贵错误——否定词（不/没/无/别/未/非）计数
  与数字序列（阿拉伯/中文数字同值等价）。人名、单位仍需人工过。
- 分句按意思切，不按字数硬切；字幕与关键词条、人物条不要同屏
  重复同一句话（下册 6.1，评审口径，无自动检查）。

### 11. 修复按因分流

- taxonomy 两类本卡相关失败码：`MISSING_SHOT`（缺镜/叙事缺口，
  严重度 4.0）→ 动作 `insert_shot`；`ACTION_DISCONTINUITY`
  （动作衔接断裂，3.0）→ 动作 `adjust_cut`
  （`hevi/quality/repair_controller.py` 的 `_ACTION_FOR_CODE`）。
- executor 把这两类落成**记录型 patch**（`insert_shots` /
  `cut_adjustments`，含 scope、镜头序号、原因），供导演/任务
  worker 消费执行；executor 本身不直接改产物——不要误以为
  patch 消费完镜头就补上了，补镜结果要重新过门禁。
- 其余老口径不变：一致性突变回素材环节重生成，转场特效修不了
  内容错误（下册 7.2）。

### 12. 素材余量（handles）

- 规格字段：`ShotSpec.handle_head_s` / `handle_tail_s`
  （`hevi/production/shot_spec.py`，默认 0 = 旧行为），
  `requested_generation_duration_s()` = 采用时长 + 首尾余量。
- 时间线校验：`TimelineClip.source_duration_ms` 给出时，
  采用窗口 [source_in, source_in+duration) 必须落在素材总长内
  （`hevi/production/timeline_ir.py`）。
- PixStag 镜头包（storyfilm → livefilm）：请求时长 =
  `ceil(采用 + head + tail)` 后 clamp 到 4–30 s（默认余量各
  0.5 s），超限先保采用时长、压缩余量并置 `handles_clipped`；
  回片按 `source_in_s`（= 有效 head）裁切采用段。字段约定见
  `hevi/video/PIXSTAG_LIVEFILM.md`。

### 13. 导出参数

- 统一口径由 `qa.export_gate` 的期望值校验（单一阈值源在
  `hevi/quality/export_qa.py`）：容器 mov/mp4、视频 h264、
  音频 aac；分辨率/方向按 `expect.aspect`；帧率按 `expect.fps`
  （容差 0.6）；原素材较小时不要为参数好看强行放大。
- 现状如实标注：**校验侧已统一，渲染侧各线的导出预设尚未收敛到
  同一份 preset**；新线接入时以本节口径写 expect，不要另立标准。

### 14. 统一导出 QA 门禁（qa.export_gate）

交付前最后一道，对成片文件本身逐项查（阈值见
`hevi/quality/export_qa.py` 文件头）：

| 检查 | 口径 |
|---|---|
| container_codec | mov/mp4 + h264 + aac（无音轨 → warn） |
| resolution_aspect | 与 expect.aspect 一致 |
| fps | 与 expect.fps 差 ≤ 0.6（可选） |
| black_frames | 黑帧（平均亮度 < 12）比例 ≤ 0.1（zerolines 口径） |
| loudness | earshot measure：-14 ± 2 LUFS、真峰值 ≤ -1 dBTP、零削波 |
| av_sync | 音视频流时长差 ≤ 0.5 s |
| ending_audio | 结尾 0.3 s 高能量硬切 → warn（不 fail，留人工判断） |
| last_frame_black | 末帧黑 → warn（片尾/淡出合法，不 fail） |
| subtitles | expect.subtitles 时：内嵌字幕轨或同名 .srt |

verdict：任一 fail → fail；否则任一 warn → warn；`qa["pass"]`
为 verdict != fail。fail 是数据不是异常——管线自己决定拦不拦；
只有文件不存在/不可探测才抛 `CapabilityError`（看都看不了的
门禁不许静默放行）。报告落 `export_qa_report.json`。

用法：

```python
from hevi import capabilities as caps

result = caps.get("qa.export_gate").render_safe(
    {"media_path": "output/final.mp4",
     "expect": {"aspect": "9:16", "fps": 30, "subtitles": True}},
    out_dir, duration=..., aspect="9:16", seed=1,
)
assert result.qa["pass"], result.qa["verdict"]
```

## 已知未落地（如实清单）

- 第 4 条（节奏/变速）只有规则口径，无自动检查。
- 第 13 条渲染侧导出预设未统一，只有校验侧统一。
- 第 8 条细粒度口型同步不在导出层做，靠生成侧与对齐档。
- 平台上传后的预览检查（按钮遮挡字幕等）不在 hevi 范围内，
  交付后由发布环节人工看一遍（下册 8.3）。
