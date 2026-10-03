# G0.2-A Spike Report — Script Stable Identity

```yaml
status: PASS
current_owner: director-pipeline (narrative layer)
date: 2026-10-02
spec: docs/p10/g0_2_spike_spec.md (G0.2-A)
```

## 结论

`unit_id survives revision` 成立：改写继承（revision+1）、插入不漂移、重排跟随、删除永不复用、orphan 可检测。`index based identity remains` 不成立——spike 证明 index 身份可被替代。

## 改动（minimal）

| 文件 | 动作 |
|------|------|
| `hevi/director/script_identity.py` | 新增：`ScriptUnit` + `assign_unit_ids` + `inherit_unit_ids` + `resolve_unit`（~120 行，纯函数，无 IO） |
| `hevi/director/pipeline_schemas.py` | `ScreenplayDialogueLine` 加 `unit_id: str = ""`（向后兼容，老数据空） |
| `tests/p10/spike/test_script_identity.py` | 新增 6 用例（T1/T2/T3/T4 + 改写继承 + Rule 3 反向） |

禁止项遵守：无 refactor、无 cleanup、无 architecture rewrite；screenplay 生成/解析未动。

## 验证

- spike 测试 6/6 PASS；ruff 干净
- 回归：`test_director_pipeline_schemas` + `test_director_pipeline_router` 45 passed

## migration_cost（生产化估计，工程判断）

```yaml
files: [screenplay.py 生成/解析填充 unit_id, _init_work/回退语义, SceneStage 视线派生改按 unit_id]
tests: [生成 prompt 含 ID 约束测试, 老 work 补 ID 迁移测试]
magnitude: M
breaking_changes: [无 — unit_id 默认为空，老行为不变]
```

## 已知局限（生产前必须解决）

1. 相似度匹配是 spike 级（difflib 0.5 阈值，同 scene 贪心）；大改写/跨 scene 移动会误判为删+增。生产需语义匹配或 LLM 辅助对齐。
2. 生成侧（LLM 产剧本）尚未输出 `unit_id`；`assign_unit_ids` 目前只覆盖读侧/补 ID。
3. `resolve_unit` 返回 None 即 orphan——Anchor 侧 `ANCHOR_ORPHANED` 接线是 Spike C 的工作。

## Gate 影响

G0.2-A = PASS。允许 PR-B（TTS alignment）启动，其 `ScriptUnit` 输入契约已就绪。
