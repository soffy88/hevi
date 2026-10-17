# multi_take — 多 take 选优

**用途**:对 QC 综合分 borderline 的段落,额外生成 N 个 take 并竞选最优,提升出片一致性。

---

## 何时启用

| 场景 | 建议 |
|---|---|
| 角色一致性要求高(特写、情绪戏) | `multi_take=3` |
| 批量生产、容错宽(背景镜头) | `multi_take=1`(默认,关闭) |
| 身份漂移频发(换脸/换角) | `multi_take=2–3` |
| 预算紧张 | `multi_take=1` |

每个额外 take = 1× 该段生成成本(`duration_s * $0.14`)。只在 borderline 段触发,非每段都跑。

---

## 工作原理

```
generate_take_0 → QC → score_0
                           ↓
         score < 0.75?  ──Yes──→ generate_take_1 → QC → score_1
                           │                            ↓
                           │                   generate_take_2 → QC → score_2
                           │                                            ↓
                           └──No───→ keep take_0     pick argmax(score)
```

### 触发条件

```python
_MULTI_TAKE_BORDERLINE_QC = 0.75  # QC 综合分 < 此值 = borderline

if multi_take > 1 and final_clip and qc and _qc_score(qc) < 0.75:
    # 额外生成 multi_take - 1 个 take
```

### QC 综合分计算

```python
_qc_score(qc) = (
    identity_score  * 0.4
  + lip_sync_score  * 0.2
  + expression_score * 0.2
  + motion_score    * 0.1
  + aesthetic_score * 0.1
)
```

缺属性用 0.5 保守填充,`qc=None` 返回 0.0。

### 选优策略

- **argmax(score)**:纯粹按综合分选最高,不引入额外偏好
- **seed 错开**:每个 take 用 `30000 + hash(seg_id) + take_idx`,确保生成多样性
- **成本累加**:每个 take 的 `duration_s * 0.14` 都计入 `total_cost_usd`

---

## 调用方式

```python
await run_v2_produce(
    # ... 其它参数
    multi_take=3,       # 最多 3 个 take(1 初始 + 2 额外)
)
```

结果记录在 `config_json.multi_take`:

```json
{
  "multi_take": 3,
  "actual_usd": 2.38,
  ...
}
```

---

## 调参

| 参数 | 默认 | 说明 |
|---|---|---|
| `multi_take` | `1` | 最大 take 数(1=关闭) |
| `_MULTI_TAKE_BORDERLINE_QC` | `0.75` | 触发阈值(内部常量) |

调高阈值 → 更多段触发多 take → 质量提升但成本上升。

---

## 与 edit_craft 的关系

- **multi_take**:生成阶段选优,提升单段质量
- **edit_craft**:后处理阶段剪辑,优化全片节奏

两者独立,可同时启用:

```python
await run_v2_produce(
    multi_take=3,
    edit_craft=True,
    # ...
)
```
