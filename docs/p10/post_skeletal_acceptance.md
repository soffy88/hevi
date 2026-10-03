# P10 Post-Skeletal Production Acceptance (A3/A4/A5/A8/A9/A13 + guards)

```yaml
status: PASS
date: 2026-10-03
scope: G0 遗留项生产化 + per-shot 缓存 + 相似度护栏 + Q4 attestation
verification: tests/p10 87 passed · adjacent 143 passed · ruff clean · mypy clean (17 files)
```

## What landed

| ID | 落点 | 状态 |
|----|------|------|
| A3 | `director/screenplay.py::_assign_scene_unit_ids` — 生成侧确定性分配 `scene{n}.line{NNN}`，已带 ID 不覆盖(供 revision 继承) | PASS |
| A4 | `audio/edge_tts_custom.py` 保留词级边界 → `audio/tts_alignment.py::write_alignment_sidecar` 落 `<audio>.alignment.json`；**返回契约不变(Path)**，8 个调用方零改动 | PASS |
| A5 | `studio/anchor_resolver.py::compose_film_anchor` + `dialogue_end_map` — R-P10-01 由约定变为结构 | PASS |
| A8 | `tongjian/assemble.py` 在 `P10_EXPORT_STEMS=1` 时写 `audio_artifact.json`(登记已有中间混音产物，不新增混音步骤)；缺 stem → 相关检查 `NOT_EVALUABLE` | PASS |
| A9 | `direction_plan/shot_cache.py` — 内容哈希为键的 per-shot 缓存 + 产物消失即失效(不返回悬空引用) | PASS |
| A13 | `direction_plan/authority_pin.py` — `id@version` 强制 pin，未 pin → `AUTHORITY_REF_UNPINNED`，解析不到 → `AUTHORITY_REF_STALE` | PASS |
| 护栏 | `direction_verify/guard.py::check_similarity` — **默认关闭**(`P10_SIMILARITY_GUARD=1` 启用)，may 级信号 | PASS |
| Q4 | `guard.py::AttestationLog` — 人工 attestation 记录 + 可选双人复核(`require_second`) | PASS |

## Evidence highlights

- A4 真跑：两行 TTS → sidecar `phrases=[(scene1.line001,0,2496),(scene1.line002,2496,4728)]`，词时间单调，跨行偏移为 film 级。
- A5：`dialogue_end_map` 返回**末词**结束(1800/3800)，非音频段尾(2496/4728)；`compose_film_anchor` = local + segment offset，换 TTS 后 film 锚点随之前移(R-P10-01 可测)。
- A9：同内容同键、生成参数变即变键；缓存条目指向的产物被删 → 视为 MISS。
- 护栏：默认 `NOT_EVALUABLE`；开启后同图 FAIL、不同非周期图 PASS(R-P10-03：fixture 用非周期纹理)。
- Q4：非法 verdict / 缺 actor / 缺 artifact_hash 均拒绝；`require_second=True` 且未复核 → `INCONCLUSIVE`。

## Non-goals respected

未改 ShotPlanner / Timeline / Video Intelligence / Asset & Provider authority；
未新增存储后端；A8 为 opt-in，A4 返回契约不变。