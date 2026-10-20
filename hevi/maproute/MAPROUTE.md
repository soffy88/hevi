# 地图路线片产品线（maproute）

口播时间戳驱动的真实地图路线动画：给一份镜头表（地点序列 + 每站旁白），
出一条路线在真实底图上逐步描绘、镜头俯冲/跟随的 MP4。

- 能力名：`video.map_route`（注册：`hevi/capabilities/maproute.py`）
- 实现：`hevi/maproute/`（`schema.py` 镜头表校验、`geo.py` 地理编码/路线、
  `timeline.py` 时间戳驱动、`render.py` 瓦片拼接 + Chromium 逐帧渲染 + ffmpeg）
- 测试：`tests/test_maproute.py`（离线契约测试，HTTP 与帧捕获均可注入 mock）

## 与 explainer 线的关系

explainer 是**通用**词级排镜：`explainer.visual_plan` 拿词级时间戳决定
每张配图/图层何时出现，画面是程序化信息图。maproute 是**地图专用线**：
同样消费词级时间戳，但时间戳驱动的不是"换图"，而是**路线描绘进度与
地图镜头**——每站旁白段的结束时刻 = 路线画到该站的时刻。两者互补：
一条旅行口播片可以 explainer 排讲解段落、maproute 出路线段落，
最后按 ShotSpec 拼装。

## 镜头表 schema

```json
{
  "title": "京津冀南下之旅",
  "provider": "osm",
  "profile": "driving",
  "fps": 15,
  "total_duration_s": 14,
  "stops": [
    {"name": "北京", "lat": 39.9087, "lon": 116.3974,
     "dwell_s": 3.0, "camera": "dive", "narration": "我们从北京出发"},
    {"name": "天津", "dwell_s": 4.0, "camera": "follow",
     "narration": "第一站来到天津"},
    {"name": "济南", "dwell_s": 4.0, "camera": "follow",
     "narration": "最后抵达济南"}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `stops[].name` | 地名（必填）；无坐标时按名字地理编码 |
| `stops[].lat/lon` | 可选，必须成对；WGS-84（amap 源为 GCJ-02，见下） |
| `stops[].dwell_s` | 无时间戳模式下，该站的时间预算（到站+停留），0.5–30 s |
| `stops[].camera` | `dive` 俯冲（拉远→推近）/ `follow` 跟随路线头 / `static` 全景固定；描述"抵达该站这一段"的镜头，第一站描述开场 |
| `stops[].narration` | 该站旁白文本段；有 alignment 时按此在对齐流中定位 |
| `provider` | `osm`（默认）或 `amap`，见下 |
| `profile` | `driving` / `walking` / `cycling` |
| `route_polyline` | 可选，自带路线几何 `[[lon, lat], ...]`，跳过路线引擎（离线/GPX 转入） |
| `total_duration_s` | 可选，把整条时间线等比拉伸到该总时长 |

能力参数：把镜头表放在 `shot_table` 里，或把字段平铺在顶层参数；
另有 `alignment`（对齐对象）/ `alignment_path`（对齐 JSON 路径）二选一。

## 时间戳驱动

alignment 接受 hevi 现有对齐产物原格式（`hevi/audio/whisper_alignment.py`
的 whisper_local 产物、ElevenLabs forced alignment 产物同构，
如 `output/storyfilm/*/alignment.json`）：

```json
{"alignment_source": "whisper_asr_local", "is_estimated": false,
 "duration_ms": 44039,
 "words": [{"text": "小", "start_ms": 140, "end_ms": 200}, ...]}
```

匹配规则：按站顺序，在对齐字符流（去标点）中顺序查找每站 `narration`，
命中段最后一个词的 `end_ms` 即到站时刻；中间站找不到时按相邻已知时刻
插值并在 sidecar 注明；第一站找不到直接报错（不假装对齐成功）。
无 alignment 时退回 dwell 模式：按各站 `dwell_s` 均匀推进。

## 地图源切换（可插拔）

默认 `osm`，全部免费无 key：

| 环节 | 服务 | 说明 |
|---|---|---|
| 地理编码 | 内置地名表 → Photon (photon.komoot.io) → Nominatim | Photon/Nominatim 均为 OSM 数据、无 key |
| 路线 | OSRM 公开 demo (router.project-osrm.org) | 真实道路几何；profile: driving/foot/bike |
| 底图 | Esri World Street Map 瓦片 (server.arcgisonline.com) | 免费无 key，画面内标注 Esri / (c) OpenStreetMap contributors |

**2026-10-20 在 ubuntu26 实测连通性**（决定了上表顺序）：
OSRM 200 ✓、Photon 200 ✓、Esri 瓦片 200（真实 JPEG）✓；
Nominatim 与 tile.openstreetmap.org、OpenTopoMap 均超时（curl 000）；
CARTO basemaps 虽返回 200，但瓦片是 "API KEY REQUIRED" 水印占位图
（第一版小样抽帧时发现，已弃用）——代码仍保留 Nominatim 为地理编码
第二顺位（可达环境自动生效），瓦片改走 Esri World Street Map；
瓦片全失败时底图退回 PIL 矢量经纬网格纸面，sidecar 如实标注
`basemap.source = "vector-fallback"`，路线本身仍来自真实路线引擎。

高德 `amap` 适配器：把 `provider` 改为 `"amap"` 并由**用户**提供 key：

```sh
export HEVI_AMAP_KEY=<高德开放平台 Web服务 key>
```

地理编码走 `/v3/geocode/geo`、路线走 `/v3/direction/{driving,walking,bicycling}`。
无 key 时能力明确 `CapabilityError`（提示默认 OSM 可用），不静默降级。
注意：高德坐标系为 GCJ-02、OSM 为 WGS-84，provider 是整表级开关，
不要在同一张镜头表里混用两种坐标来源。

## 出处与许可

镜头表（地点序列 + 镜头动作 + 逐站文案）的产品形态参考了
SpaceZephyr/map-motion（GitHub，**MIT License**，2026-10-20 经 GitHub API
与 LICENSE 原文核实）；本实现为 hevi 独立编写（clean-room，未复制其代码），
schema 按 hevi 能力契约与 alignment 格式自研。高德用法、真实路线与
海拔剖面等形态是其 README 描述的功能方向，本线当前只做路线描绘。

## 成本

零付费调用：地理编码/路线/瓦片均为免费公开服务；本地成本只有
Chromium 逐帧截图 + ffmpeg 编码（`cpu_cost_hint = 2.0`）。
