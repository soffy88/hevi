# G0.2-B Spike Report — TTS Alignment Artifact

```yaml
status: PASS (with one SPEC assumption invalidated and superseded, see below)
current_owner: audio-tts
date: 2026-10-02
spec: docs/p10/g0_2_spike_spec.md (G0.2-B)
```

## 结论

`word timing survives as artifact` 成立：真实 edge-tts 合成（非 mock），100 词覆盖率达标，词时间单调、整数 ms，对齐随 `audio_id = tts:{unit_id}#r{revision}` 绑定，revision 间不交叉污染。

## 改动（minimal）

| 文件 | 动作 |
|------|------|
| `hevi/audio/tts_alignment.py` | 新增：`WordTiming/PhraseTiming/AudioAlignment` + `synthesize_with_alignment` + `probe_duration_ms` + `alignment_to_json`（~130 行；provider 未动，包的是 `oprim.edge_tts_word_boundary` 原子） |
| `tests/p10/spike/test_tts_alignment.py` | 新增 4 用例（T1/T2/T3 + 反向空文本） |

禁止项遵守：无 refactor、无 provider 改动、无 architecture rewrite。

## 验证

- spike 测试 4/4 PASS（真实合成；T1 100 词、T3 双 revision、反向空文本 fail-loud）；ruff 干净
- 全 spike 套件 10/10 PASS（含 PR-A 6 用例）

## SPEC 偏离（实测推翻假设，已修正）

- **T2 原假设** `last_word.end ≈ duration（±500ms）` **不成立**：实测 `The black hole bends light.` last_word.end=1612ms，wav 解码后 duration=2496ms，gap=884ms 为**真实尾静音**（非 mp3 头估计误差，已用 wav 解码排除）。
- **修正规则**：`duration >= last_word.end`（不截断）+ 尾静音 `<= 2000ms` 有界；**dialogue-end 事件用 `last_word.end_ms`，不用 duration**。该修正已写入测试注释，此发现直接输入 Spike C（Dialogue End Event 定义）。
- 单次合成 = 一个 phrase（`phrase_id=audio_id`）；多行拼接的分行 phrase 是后续工作。

## migration_cost（生产化估计，工程判断）

```yaml
files: [edge_tts_custom.py 逐行合成保留边界并落盘对齐, voiceover.py 透传 unit_id->audio_id, Timeline 读取侧契约]
tests: [多音色/中文对齐测试, 长文本分段 phrase 测试, 尾静音界--provider 相关校准]
magnitude: M
breaking_changes: [无 — 新模块, 现有合成路径未动]
```

## Gate 影响

G0.2-B = PASS。PR-C（Anchor resolver）的 TTS 输入契约（`AudioAlignment.words[-1].end_ms` = dialogue end）已就绪。
