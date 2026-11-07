# 空间世界契约（world contract）

> 出处：hevi 内部立项（2026-10-23，Soffy 拍板）。方法借自"代码画世界"纪录片教程：
> 整个程序化世界先有一份总契约（米制平面图），所有分区施工只准读契约，
> 从而保证多方并行不打架。此前 scene3d / img2threejs / Blender 各线各写坐标，
> 本契约是空间世界级的唯一事实源。实现：`hevi/world_contract/`（纯 Python、无依赖）。

## 一句话规矩

**世界里每一个坐标都必须能溯源到契约。** 契约没有的坐标不许写；
要放新东西，先改契约（或用契约许可的偏移方式），再施工。

## 契约条文（规范）

契约是一份 JSON（格式见包内 `hevi/world_contract/schema.json`），
`contract_version: "1.0"`，与语言栈无关。必填块：

| 块 | 内容 |
|---|---|
| `world` | `name`、`units`（恒为 `"m"`）、`bounds`（`x_min/x_max/z_min/z_max`，地面 XZ 平面，Y 朝上）、`seed`（世界种子） |
| `ground` | 高度场唯一来源（`groundAt` 约定）：`kind` 三选一——`formula`（`h(x,z)=a*x+b*z+c`）、`grid`（规则网格文件＋`cell_size_m`）、`external`（外部高度场文件）。**不许有第二个高度来源。** |
| `zones` | 分区列表：`id`＋`bounds`（矩形）。分区可以重叠（如林地叠在草甸上）。 |
| `landmarks` | 大件：`id`、`position`（中心，`[x,y,z]`）、`size`（全尺寸 `[dx,dy,dz]`；足迹＝中心 ± size/2）。 |
| `rules` | 禁区规则：`region`（矩形或圆 `cx/cz/radius`）＋`kind`——`no_place`（`applies_to` 所列类别禁入）或 `max_height`（`max_height` 米，物件顶部 `y+height` 不得超）。`applies_to: ["*"]` 表示全部类别。 |
| `formulas` | **对接公式**：两个分区交界处共用的尺寸函数（见下节）。 |
| `anchors` | **锚点发布**：特写主体的命名坐标＋`facing_deg` 朝向（0＝+X 向东，自上而下逆时针）。镜头按名引用锚点，不写生坐标。锚点必须在世界边界内。 |
| `lighting` | **全局光照时间线**：关键帧 `t`（小时 0..24）、`sun_azimuth_deg`、`sun_elevation_deg`、`night_factor`（0..1）四字段缺一不可，至少 2 帧、`t` 不递减。全部效果共读这一条时间线，**不许各分区自写太阳**。 |
| `time` | `convention` 恒为 `"shot_local"`：**动作时间相对镜头**（每个镜头 t=0 是它自己的第一帧），不许用全片绝对时间排动作。 |

### 对接公式的表达形式（定死，不许临场发明）

一个公式＝`{id, variable, unit: "m", kind, tolerance, ...}`，两种可求值形式：

- `piecewise_linear`：`points: [[x, y], ...]`（x 严格递增），分段线性插值，
  区间外钳制到端点值。**首选**：每个点都可人工核对（如树干半径随高度）。
- `polynomial`：`coeffs` 为升幂系数（`coeffs[i]` 是 `x^i` 的系数），Horner 求值。
  用于光滑解析曲线（如桥面下垂随跨径比例）。

选一种写进契约即可；交界两侧的施工方都对**同一个公式对象**求值，
`formulas[].tolerance` 是允许的施工误差，超差即违规。

### 坐标溯源（校验判定规则）

世界清单（manifest）里每个物件必须带 `source`，且位置必须与所引来源对得上：

| `source.type` | 判定 |
|---|---|
| `anchor`（`ref`=锚点 id） | 锚点存在，且物件 XZ 与锚点一致（容差 0.05 m） |
| `landmark`（`ref`=大件 id） | 大件存在，且物件 XZ 落在大件足迹内 |
| `zone_offset`（`ref`=本物件所属分区 id，`offset=[dx,dz]`） | 物件 XZ 必须等于分区左下角＋offset（容差 0.05 m）。**这是放新物件的唯一合法方式：报偏移，不报生坐标。** |
| `formula`（`ref`=公式 id，物件另带 `formula_at`） | 公式存在、声明了求值点，且位置在世界边界内 |
| `contract_range` | 仅限契约明示可自由摆放的小道具：位置在世界边界内即可 |

缺 `source`、引用不存在、位置与来源对不上——一律判 `provenance` 违规。

## 施工规矩（给所有分区/管线）

1. **只读契约**：施工方只准读契约，不许回写、不许私存一份"本地版"坐标。
2. **坐标只来自契约**：按上表溯源；写死坐标＝校验不过＝不许渲染。
3. **种子 RNG**：随机性只从 `world.seed` 派生（分区种子＝`hash(seed, zone_id)` 一类确定性派生），同契约同种子必出同一世界。
4. **画面只由 t 决定**：任意时刻的画面是 `(契约, t)` 的纯函数，不依赖渲染顺序、机器或历史帧。
5. **光照共读全局状态**：太阳与 `night_factor` 只读 `lighting.timeline`，插值方式全线一致（相邻关键帧线性插值）。
6. **镜头内时间**：动作、台词、特效一律以镜头内 t 排程（`time.convention = shot_local`）。
7. **改世界先改契约**：新增大件/锚点/分区先走契约变更，再改施工；契约变更必须过校验器。

## 校验器用法

```bash
# 契约 + 清单一起验（退出码 0=通过，1=有违规，2=文件错误）
python -m hevi.world_contract validate contract.json manifest.json

# 只验契约本身（字段齐全、锚点在界内、光照完整、公式可求值）
python -m hevi.world_contract check-contract contract.json
```

输出为结构化 JSON：`{"pass": bool, "violations": [{"rule", "object", "reason"}], "checked": {...}}`。
规则名固定：`contract_fields` / `lighting_fields` / `anchor_in_bounds` /
`formula_wellformed` / `zone_exists` / `provenance` / `zone_rule_no_place` /
`zone_rule_max_height` / `formula_interface`。

能力入口（导入即自注册，沿用 brushpaint/genart 先例，未动
`hevi/capabilities/__init__.py`）：`world.contract_validate`，
参数 `contract_path`＋可选 `manifest_path`，产物为 out_dir 下的
`world_contract_report.json`，`qa["pass"]` 即结论。

## 示例（包内 `hevi/world_contract/examples/`）

原创精简世界 `river_vale`：一条河＋一棵大树＋一座小屋＋一座吊桥。

- `river_vale.contract.json` ＋ `river_vale.manifest.ok.json`：合规，校验通过；
- `river_vale.contract.bad_anchor.json`：锚点 `wide_river_view` 出界 → `anchor_in_bounds`；
- `river_vale.manifest.bad_zone.json`：河里建棚（`zone_rule_no_place`）＋东草甸 9 m 塔超限高（`zone_rule_max_height`）；
- `river_vale.manifest.bad_formula.json`：交界两侧树干半径与公式对不上 → `formula_interface`。

测试：`tests/test_world_contract.py`（含 CLI 退出码与能力注册）。
