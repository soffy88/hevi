# G0.2 附带项报告 — A2 cue_id + ffmpeg 静音探测

```yaml
a2_cue_id: DONE (working tree, 待提交)
silence_probe: PASS (ffmpeg 7.0.2-static)
date: 2026-10-02
```

## A2 — BeatCue stable identity

| 文件 | 动作 |
|------|------|
| `hevi/cinematic/shot_intelligence/models.py:38-47` | `BeatCue` 尾部追加 `cue_id: str = ""` + `creative_cue_ref: str = ""`（positional/keyword 调用全兼容） |
| `hevi/cinematic/shot_intelligence/persistence.py:63-70` | `_cue` 反序列化读取两字段（老 payload 缺字段 → 默认为空） |
| `tests/p10/spike/test_beatcue_identity.py` | 3 用例：positional 不变、老 payload 兼容、ID 往返 + 追踪挂接点 |

验证：spike 3/3 + `test_shot_intelligence.py` 5/5 PASS；ruff 干净。`Decision→Cue→Shot` 挂接点就绪（`cue:C21` ↔ `creative_cue_ref`）。

## ffmpeg 静音探测

| 文件 | 动作 |
|------|------|
| `hevi/verdict/silence_probe.py` | 新增：`ffmpeg_version`（pin + 缺失转 `SilenceProbeFailed`）+ `make_tone_silence_tone`（构造即真值）+ `probe_silence_resolution` |
| `tests/p10/spike/test_silence_probe.py` | 4 用例：版本 pin、320ms 分辨、100ms 不误报、缺二进制 fail-loud |

实测：

```text
ffmpeg version 7.0.2-static (d 参数为 duration 类型, 支持小数秒)
320ms @ -60dB: detected, 1 event (start≈1.0s, dur≈0.32s, tol 80ms)
100ms @ d=320ms: 无 320ms 级事件 (无幻觉)
缺二进制: SilenceProbeFailed (已修 FileNotFoundError 直抛缺口)
```

## Gate 影响

G0.2 附带项 = DONE。G0 剩余：G0.3 文件级成本评估（A3/A4/A5/A8/A9/A13）。
P10-S SPEC 已允许启动设计。
