# G0.2-C Spike Report — Anchor Resolver

```yaml
status: PASS
current_owner: studio-timeline (infrastructure, not P10 creative)
date: 2026-10-02
spec: docs/p10/g0_2_spike_spec.md (G0.2-C)
```

## 结论

`semantic anchor resolves deterministically` 成立：`AFTER_DIALOGUE(scene1.line004)+500ms` 经真实契约（ScriptUnit ID + `AudioAlignment.words[-1].end_ms` + fps）换算为 `{time_ms, frame}`，附 `evidence=[audio_alignment_hash, timeline_hash]`（why this frame 可审计）。`fallback to seconds only` 不成立——`ABSOLUTE` 类型被显式拒绝。

## 改动（minimal）

| 文件 | 动作 |
|------|------|
| `hevi/studio/anchor_resolver.py` | 新增：`Anchor/ResolvedAnchor` + `resolve_anchor` 纯函数 + `AnchorOrphaned/AnchorUnresolved`（~90 行，无 IO，不触 Timeline model） |
| `tests/p10/spike/test_anchor_resolver.py` | 新增 6 用例（T1/T2/T3 + orphan 反向 + absolute 拒绝 + 负偏移/fps 下限） |

禁止项遵守：无 Timeline model 新增（第 5 套 Timeline 未出现）；无 `hevi/creative/*`；无 refactor。

## 验证

- spike 测试 6/6 PASS；全 spike 套件 16/16 PASS（A 6 + B 4 + C 6）；ruff 干净
- T1 含真实值链：`1800ms(last word end) + 500ms = 2300ms -> frame 69@30fps`

## 已知局限（生产前必须解决）

1. 仅支持 `AFTER_DIALOGUE`；`BEFORE/AFTER_BEAT/AFTER_SHOT` 等类型是后续工作。
2. `confidence=1.0` 是确定性换算的占位；含模型推断（VAD/事件检测）时必须降置信度并走 M 类。
3. 接线缺口：`dialogue_end_ms` 字典尚未由 Timeline/assembly 自动供给（resolver 是纯函数，供给侧是 G0.3 工作）。

## Gate 影响

G0.2-C = PASS。G0.2 退出条件达成：

```text
A PASS + B PASS + C PASS => G0.2 PASS => P10-S allowed
```

G0 仍为 NOT PASSED，直到：A2 `cue_id` 合入 + ffmpeg 探测就绪 + G0.3 文件级成本评估完成。但 P10-S（30s 竖切 SPEC）已允许启动设计。
