# Rough 式手绘线条（rough stroke）

hevi 的手绘描边可选项：让矢量线条看起来像手画的——线不直、带轻微弓弯，
而且像笔在纸上描了两遍。

## 原理（clean-room 自研，不含 rough.js 源码）

Python 实现在 `hevi/layer4_legacy/handdraw/rough_stroke.py`，只按通用原理
自研，与 rough.js 没有代码关系：

1. **顶点抖动（roughness）**：折线/曲线采样点的每个顶点，沿 x/y 各加
   `[−roughness, +roughness]` 内的随机偏移。
2. **弓弯（bowing）**：每条线段的中点沿线段法线方向加
   `[−bowing, +bowing]` 内的随机偏移，插回路径——直线因此带上手工的弧度。
3. **双描（double_stroke）**：同一路径用两个独立偏移各画一遍，得到
   “描了两遍”的速写感；关掉则只画一遍。
4. **确定性**：每次调用用独立的 `random.Random(f"...:{seed}:{pass}")`，
   不碰全局 RNG；同 seed 同输入必同输出。`roughness=0 且 bowing=0` 时
   每遍输出与原始路径逐点相等（即“关”的位置）。

参数都在与输入点相同的坐标单位里；`roughness`/`bowing` 取值范围
`[0, 50]`，非法值（负数、NaN/inf、非数字、点数 < 2、坐标非有限）一律
抛 `ValueError`（能力层转 `CapabilityError`），不假成功。

## 在 hevi 里怎么用

- **技法函数**：`roughen_polyline(points, roughness=…, bowing=…, seed=…,
  double_stroke=True, closed=False)` → `RoughStrokeResult`
  （`.passes` 点列列表、`.svg_paths` SVG path 字符串列表，两种都给）；
  多条线用 `roughen_polylines(...)`。
- **能力**：`image.rough_stroke`（kind=shot，line=handdraw）——传
  `polylines`（`[[[x,y],…],…]`）即出透明 PNG + `rough.svg` + sidecar JSON。
- **handdraw 线开关**：`handdraw.full` / `handdraw.storyboard` /
  `handdraw.illustration` 新增可选参数 `stroke_style`：
  `"legacy"`（默认，产物与此前逐字节一致）或 `"rough"`；另有
  `rough_roughness`（默认 2.0）、`rough_bowing`（默认 2.0，均为成图
  坐标单位）。底层入口是
  `build_scene_illustration(..., stroke_style="rough")` 与
  `render_handdraw_pipeline(..., stroke_style="rough")`。

## 网页渲染侧（可选，本次未落地）

网页/HyperFrames 侧不需要上面的 Python：可以直接引上游 rough.js 本体
（MIT 许可证）。锁版本 4.6.6：

```bash
npm install roughjs@4.6.6
```

或 CDN 直引：

```html
<script src="https://cdn.jsdelivr.net/npm/roughjs@4.6.6/bundled/rough.js"></script>
<script>
  const rc = rough.canvas(document.querySelector("canvas"));
  rc.rectangle(10, 10, 200, 120, { roughness: 1.2, bowing: 1.0, seed: 42 });
  // SVG 侧：rough.svg(svgEl).line(x1, y1, x2, y2, {...})
</script>
```

注意网页侧与 Python 侧是两套独立实现，参数语义相近但像素结果不会逐点
一致；需要跨端一致时以 Python 侧产物（PNG/SVG）为准。
