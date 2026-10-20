# 音频门禁（audio gate）

> 出处：[earshot](https://github.com/Leonxlnx/earshot)（Leon Lin，MIT License）。
> 本地部署时不下载 CLAP/AST 模型权重（~1.1 GB），只用无模型路径。

## 门禁分工

- `film_gate`：查**画面**（帧差、转场、硬伤）。
- `audio.earshot_gate`：查**声音**（响度、真峰值、削波、静音）。
- `kids_gate`：查幼儿线内容规范。

三者是互补关系：一条交付物要出门，画面和声音都过门。

## 用法

```python
from hevi import capabilities as caps

result = caps.get("audio.earshot_gate").render_safe(
    {"media_path": "outputs/final_mix.wav", "lufs_target": -14.0},
    out_dir,
    duration=..., aspect="16:9", seed=1,
)
assert result.qa["pass"], result.qa["failed_checks"]
```

失败时按 `failed_checks` 修：响度问题去压限/提降（或改 `lufs_target`），
真峰值超标去压限或重新渲染（`lufs_target: -14` 时建议 master bus 真峰值留到 -1 dBTP 以下），
削波必须回到混音台修。

## 默认阈值（可覆盖）

| 检查 | 默认 | 说明 |
|---|---|---|
| `loudness` | -14 ± 2 LUFS | 流媒体/视频目标；游戏 BGM 用 -16，广播用 -23 |
| `true_peak` | ≤ -1.0 dBTP | 4 倍过采样真峰值 |
| `no_hard_clipping` | 满刻度采样数为 0 | `|x| ≥ 0.999` 的采样计数 |
| `loudness` 测不出 | 直接失败 | 信号太短（<0.4 s）或数字静音 |

注意：**<0.4 s 的短音效单体（如 click/whoosh）不适合进门**，
earshot 的集成响度在这类长度上返回空——它们走 `audio.sfx_render` 的
`checks: clean` 或 `earshot sfx check`，不走这个门。

## 音效库（audio.sfx_render）

earshot 自带 201 个**代码化音效**（合成配方 JSON，不是采样文件）：
按 ID 渲染到 wav（48 kHz），本地 CPU、秒级、无模型、无网络、可复现
（render 的 `seed` 参数来自能力调用的 `seed`）。

```python
result = caps.get("audio.sfx_render").render_safe(
    {"sfx_id": "whoosh_fast/tight", "dur": 1.0, "apex": 0.5},
    out_dir, duration=1.0, aspect="16:9", seed=42,
)
# result.wav 即渲染出的 wav；36 个分类、201 个 ID 见 `earshot sfx list`
```

许可：音效库来自 earshot（MIT），渲染产物可商用，
出处写在 `qa["license"]`。

## 部署

- earshot venv：`~/.venvs/earshot`（模型-free 依赖集：numpy/scipy/soundfile/soxr/librosa/pyloudnorm）
- 静态 ffmpeg：`~/.local/bin/ffmpeg`（imageio-ffmpeg 自带，供 `measure` 解码用）
- `EARSHOT_BIN` 环境变量可覆盖 CLI 路径；找不到时能力抛 `CapabilityError` 明示，不假过。

## 未接的扩展点

- `describe` / `match` / `timeline` / `critique` 需要下载 CLAP+AST 权重
  （~1.1 GB，首次调用时自动下载到 earshot 的 `.cache/hf`），且每次 CLI
  调用要加载模型 20–40 秒。高频使用时建议起 `earshot mcp` 常驻进程
  （模型驻留内存），再接成 `audio.timeline_sync`（声画切点同步检查）、
  `audio.critique`（对标专业发布片的评分卡）两个能力。
- `earshot kit`（整片音效组，按同步点渲染）是代码动画配乐的方向。

## 对齐选档指南

配音词级时间戳（hevi/audio/tts_alignment.py，HEVI_TTS_ALIGNMENT_PROVIDER）三档怎么选：

- **默认 lux_tts 估时（零成本）**：LuxTTS 合成 + 按时长加权估算词界，
  时间戳是估算值（is_estimated=True）。不卡点、不做精细字幕时用这档。
- **字幕/卡点敏感用 elevenlabs_forced 实测**：音色仍是 LuxTTS（soffy），
  合成后用 ElevenLabs forced alignment（经 Monid，约 $0.0012/次量级）
  实测词级时间戳。storyfilm 与 audio.forced_align 能力即直调此路径
  （hevi.audio.forced_alignment.forced_align_words）。
- **edge_tts 仅当可接受换成 Edge 音色时用**：换 TTS 后端才能拿到原生
  词界，音色随之变成 Edge 的，不要在需要 soffy 音色的成片上用。

## 门禁地图

| 查的对象 | 门禁 |
|---|---|
| 故事 dict（计划层） | kids.story_gate（hevi/kids/story_gate.py）+ storyplan story_check（hevi/storyplan/check.py） |
| DirectorBrief | director_lens director_check（hevi/director_lens/gate.py） |
| 成片画面 | film_gate（layer4_legacy 脚本） |
| 成片声音 | audio.earshot_gate（hevi/capabilities/earshot_gate.py） |
| 成片幼儿安全综合 | qa.kids_gate（hevi/quality/kids_gate.py） |

响度阈值有两把尺，勿混用：

- 成人/通用档：**-14±2 LUFS**（audio.earshot_gate 默认）。
- 幼儿档：**-16±1 LUFS、真峰值 ≤ -1.5 dBTP**（kids_gate 的 profile 常量，
  hevi/quality/kids_gate.py 的 KIDS_LOUDNESS_*；其 check_loudness 的测量
  同样走 earshot measure，仅阈值不同，earshot 不可用时回落 ebur128）。
