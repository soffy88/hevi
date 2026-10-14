# SCENE3D 任务完成报告（r1 · 核验通过）

> 本轮实现 `hevi/layer4_legacy/scene3d/`：数据驱动的 Three.js 镜头线，
> 全部在 CPU + SwiftShader 下确定出片。三条样片均 ffprobe + sha256 + 抽
> 帧 contact sheet 核验；4 项任务强制测试 + 1 项 schema 测试 + 1 项 CLI
> 集成测试 + 9 项能力契约测试全部通过（16/16 PASS）；3O lint 与基线 9/9 PASS 一致；
> 按追加要求（2026-10-14 16:50）完成了 Hevi 统一能力契约注册与 HTTP API。

## 1. 本轮交付与任务要求对照

| 任务要求 | 状态 | 证据 |
| :--- | :--- | :--- |
| 1. `hevi/layer4_legacy/scene3d/`：JSON schema、渲染器、CLI；`line=scene3d` 入口 | ✅ | `schema.py` / `renderer.py` / `cli.py` / `stages.py` + `hevi/studio/lines/scene3d.yaml` |
| 2. 三条样片 (10–15s) + sha256 + 时长 + 每帧秒数 + contact sheet | ✅ | `output/scene3d_e2e/*/metrics.json` + `*_contact_sheet.png`（每条 12–13 s，30 fps，1080p） |
| 3. 1080p CPU ≤ 4s/frame | ✅ | orbit 1.551 s/frame · fox 0.776 s/frame · sea 1.191 s/frame（详见 §3、§5） |
| 4. 4 项 pytest（确定性 / 风力动 / 9:16 安全区 / 缺产物失败） | ✅ | `tests/test_scene3d.py` 7/7 passed，`tests/test_scene3d_capability.py` 9/9 passed |
| 5. 3O lint 不新增失败 | ✅ | `scripts/ci/run_3o_v3_lint.py` = 9/9 PASS，与基线相同 |
| 6. CC0 资产 + ASSETS.md 登记 | ✅ | `ASSETS.md`（全部程序化生成 + Three.js MIT 备注） |
| 7. 可选：CPU 图生 3D 调研（>10min 只写结论） | ✅（不接入） | `SCENE3D_EVAL.md` |
| 8. 能力契约注册（追加要求 2026-10-14） | ✅ | `hevi/capabilities/` 统一注册表 + `hevi/api/routers/capabilities.py` |

## 2. 模块布局

```
hevi/layer4_legacy/scene3d/
├── __init__.py          # 对外 API：load_scene / SceneRenderer / cli_main
├── schema.py            # SceneSpec dataclass + jsonschema 校验 + 序列化
├── template.py          # 浏览器内 Three.js 场景（程序化几何、风场与 shader）
├── renderer.py          # Playwright+SwiftShader 渲染器 + 本地 HTTP 静态服务
├── cli.py               # python -m hevi.layer4_legacy.scene3d.cli {render,validate,scenes}
├── stages.py            # 5 段流水线（load / render / encode / contact_sheet / report）
├── ASSETS.md            # 资产来源 + Three.js MIT 备注
├── NOTICE               # 第三方许可证正文
├── examples/
│   ├── little_planet_orbit.json   (16:9, 12 s)
│   ├── fox_in_wheat.json          (9:16, 12 s)
│   └── through_star_sea.json      (9:16, 13 s)
└── vendor/three/        # Three.js r169 (MIT)，11 个文件，1.4 MB
    ├── three.module.js
    ├── postprocessing/{EffectComposer,RenderPass,UnrealBloomPass,
    │                  OutputPass,MaskPass,Pass,ShaderPass}.js
    └── shaders/{CopyShader,LuminosityHighPassShader,OutputShader}.js

hevi/capabilities/       # 统一能力注册表（追加要求）
├── __init__.py          # 对外接口：register, get, list, resolve, Capability, CapabilityResult
├── registry.py          # 注册表全局单例与校验、查询
├── errors.py            # CapabilityError（严禁假成功）
├── result.py            # CapabilityResult 数据类（mp4, png, wav, duration_s, sha256, qa）
└── scene3d.py           # scene3d 镜头能力适配器（自动注册）

hevi/api/routers/
└── capabilities.py      # HTTP 入口：GET /api/capabilities, GET /{name}, POST /{name}/preview
```

**渲染管线**（`renderer.py::SceneRenderer.render`）：

1. 把 SceneSpec 写进 `scene.html`（场景描述通过 `window.__SCENE3D_SPEC` 注入，import map 指向 vendored three）。
2. 起一个 `http.server` 在 127.0.0.1 随机端口服务 workdir（ES module 不能走 `file://`）。
3. `playwright.sync_api.chromium.launch(args=['--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox',...]` 启动 SwiftShader（CPU WebGL）。
4. 逐帧 `window.__setTime(t)` → 场景按 `t` 推进 → 读 `canvas.toBlob` 拿 PNG → 写 `frame_NNNNN.png`（避免 screenshot stability race）。
5. ffmpeg `image2` demuxer → `libx264 -pix_fmt yuv420p -preset veryfast -crf 20`。
6. ffmpeg `image2` + `tile=COLSxROWS` 做 contact sheet。

**确定性**：mulberry32 PRNG，seed 取自 `SceneSpec.seed`；`updateFields` 和 `buildBase` 在第一次 `__setTime` 之后的所有帧都从同一份 PRNG 状态开始；帧 PNG 与最终 MP4 用 SHA-256 校验。

## 3. 三条样片实测（全量物理出片核验）

> 渲染指标落盘在 `output/scene3d_e2e/<name>/metrics.json`；下方
> 表格数字直接提取自落盘产物（ffprobe + sha256 + 物理实测耗时）。

| 样片 | 画幅 | 时长 | 帧数 | 分辨率 | 总渲染秒 | 每帧秒 | 编码秒 | SHA-256 |
| :--- | :--- | ---: | ---: | :---: | ---: | ---: | ---: | :--- |
| `little_planet_orbit` | 16:9 | 12.0 s | 360 | 1920×1080 | 558.29 | **1.551** | 7.28 | `611f66db523b4de0e61774af975be89df054fd48c909f79f2e9db463c60f472c` |
| `fox_in_wheat` | 9:16 | 12.0 s | 360 | 1080×1920 | 279.40 | **0.776** | 12.50 | `060e026bc99e6b44c0ae6fa4ef021b8deca9c2275988b320a575efc6513594ca` |
| `through_star_sea` | 9:16 | 13.0 s | 390 | 1080×1920 | 464.32 | **1.191** | 20.13 | `3968294f05fa860f6fdc5d535459769fbf787b51b04fea5ddeafbcfab5310039` |

**Contact sheet** 路径（全部已实测生成）：
- `output/scene3d_e2e/little_planet_orbit/little_planet_orbit_contact_sheet.png`
- `output/scene3d_e2e/fox_in_wheat/fox_in_wheat_contact_sheet.png`
- `output/scene3d_e2e/through_star_sea/through_star_sea_contact_sheet.png`

## 4. 视觉要素

| 要求 | 实现 |
| :--- | :--- |
| 球面小星球，toon/lambert 渐变 | `makePlanet`：IcosahedronGeometry(4 级细分) + per-vertex 正弦扰动 + `MeshToonMaterial`；可选光环 |
| 麦田和草，InstancedMesh + 顶点风动 | `makeField`：每实例 `PlaneGeometry` quad + per-vertex dark→light 渐变 `MeshLambertMaterial`；`updateFields` 用 `sin(t·ws·sp + ph)` 驱动 Z 旋转弯曲 |
| 星空粒子 + 闪烁 | `THREE.Points` 2600 颗 on a large shell + 自定义 fragment shader `0.6+0.4*sin(t*2+phase)` 闪烁 |
| 雾 / 大气渐变 | `THREE.FogExp2(fog_color, 0.011)` + 自定义 `ShaderMaterial` 天空球 (top→bottom 渐变) |
| UnrealBloom | `EffectComposer(RenderPass + UnrealBloomPass + OutputPass)`；阈值 0.85、强度 0.55（避免麦尖过曝） |
| 柔和阴影 | `THREE.PCFSoftShadowMap` + 512×512 方向光阴影 + 4096-vertex 阴影相机 |

## 5. 性能与 4 s/frame 预算

| 场景 | 分辨率 | 每帧秒 | 4s 预算裕量 | 场景要素 |
| :--- | :---: | ---: | :---: | :--- |
| orbit (16:9) | 1920×1080 | 1.551 s | 裕量 61.2% | 3 planet + 2 tree + 2 rock + 900 grass + 350 wheat + 1500 star |
| fox (9:16) | 1080×1920 | 0.776 s | 裕量 80.6% | 主体 fox + 900 wheat + 300 grass + 2 rock + 2 tree |
| sea (9:16) | 1080×1920 | 1.191 s | 裕量 70.2% | 3 planet + 2600 star + 500 grass |

**所有场景均大幅低于 4 s/frame 上限，直接交付 1080p 全高清，无需先 720p 降质放大。**

## 6. 追加要求：能力契约（CAPABILITY_CONTRACT.md）

按追加要求，已在 `hevi/capabilities/registry.py` 实现了统一的能力注册中心，所有产品线（zero、talkcraft、短剧、artmotion、explainer、ShotSpec 工作台）均可按名字调用。

### 6.1 本线注册的全部能力名清单

| 注册能力名 | kind | 支持画幅 | CPU 耗时估算 (s/s) | 说明 |
| :--- | :--- | :--- | :---: | :--- |
| `scene3d.planet_orbit` | shot | 16:9, 9:16 | 1.6 | 漂浮 toon 小星球环绕镜头（小王子风格，CPU/SwiftShader 出片） |
| `scene3d.fox_wheat` | shot | 9:16, 16:9 | 0.8 | 麦田里的小狐狸竖屏镜头，风吹草动 + 暖色 bloom |
| `scene3d.star_sea` | shot | 9:16, 16:9 | 1.2 | 穿过星海推进镜头，星空粒子 + 大气雾 + bloom |

### 6.2 契约接口与实现
- **注册与查找**：
  - `hevi.capabilities.register(Capability(...))`
  - `hevi.capabilities.get(name)` / `hevi.capabilities.resolve(name)`
  - `hevi.capabilities.list(kind=..., aspect=...)`
- **渲染入口**：
  `cap.render(params, out_dir, *, duration, aspect, seed) -> CapabilityResult`
- **严禁假成功**：
  任何参数非法、资产缺失或渲染中断直接抛 `CapabilityError`。
- **HTTP API**（在 `hevi/api/routers/capabilities.py` 实现并挂载至 `/api`，已同步更新 `docs/API-CAPABILITIES.md`）：
  - `GET /api/capabilities` — 列出全部能力
  - `GET /api/capabilities/{name}` — 查看单项能力详情
  - `POST /api/capabilities/{name}/preview` — 生成 3 秒真实预览

## 7. 测试与 Lint 验证

```
$ PYTHONPATH=/data/soffy/projects/hevi-scene3d JWT_SECRET=test-only-dummy \
  .venv-scene3d/bin/python -m pytest tests/test_scene3d.py tests/test_scene3d_capability.py --noconftest

collected 16 items
tests/test_scene3d.py .......                                            [ 43%]
tests/test_scene3d_capability.py .........                               [100%]
=================== 16 passed, 1 warning in 69.21s (0:01:09) ===================
```

覆盖全部要求：
1. **确定性**：`test_same_seed_determinism` + `test_capability_render_deterministic` — 同 seed 渲染两次，逐字节相同。
2. **风力动**：`test_wind_produces_frame_motion` — 相邻帧哈希相异，确实为动态麦浪而非静帧。
3. **9:16 安全区**：`test_916_subject_in_safe_area` — 暖色 toon 星球质心严格在画面纵向中央 50% 安全区内。
4. **缺产物失败**：`test_missing_artefact_fails_check` + `test_capability_missing_artefact_fails` — 任意产物删除后，校验必定报错。
5. **契约测试**：`test_capability_registered_and_listable`、`test_capability_rejects_bad_params`、`test_capability_render_passes_ffprobe`（2秒渲染并通过 ffprobe 核验）。

3O Lint 检查：
```
$ PYTHONPATH=/data/soffy/projects/hevi-scene3d .venv-scene3d/bin/python scripts/ci/run_3o_v3_lint.py
[PASS] check_no_sibling_call.py
[PASS] check_omodul_signature.py
[PASS] check_enabled_pillars.py
[PASS] check_flat_namespace.py
[PASS] check_no_project_prefix.py
[PASS] check_oprim_keyword_only.py
[PASS] check_obase_no_reverse_dep.py
[PASS] check_oservi_injection.py
[PASS] check_async_contract.py
3O_V3_LINT=PASS
```
**与基线完全一致（9/9 PASS，0 新增失败）。**

## 8. 调用方式

### 8.1 产品线 Python 代码直接调用（按契约推荐）
```python
import hevi.capabilities

# 获取能力并调用
cap = hevi.capabilities.get("scene3d.planet_orbit")
result = cap.render(
    params={"seed": 1234, "bloom_strength": 0.55},
    out_dir="output/shot_001",
    duration=5.0,
    aspect="16:9",
    seed=1234,
)
print("产物 MP4:", result.mp4)
print("SHA256:", result.sha256)
```

### 8.2 CLI 直接渲染
```bash
PYTHONPATH=. JWT_SECRET=test-only-dummy \
  .venv-scene3d/bin/python -m hevi.layer4_legacy.scene3d.cli render \
  hevi/layer4_legacy/scene3d/examples/little_planet_orbit.json \
  --out output/my_orbit
```

### 8.3 HTTP API 调用
```bash
# 查询可用能力
curl http://127.0.0.1:8000/api/capabilities

# 请求 3 秒预览
curl -X POST "http://127.0.0.1:8000/api/capabilities/scene3d.fox_wheat/preview?aspect=9:16&seed=42" \
  -o preview.mp4
```

## 9. 文件清单（仅本 worktree 新增与变更）

```
M  .gitignore
M  docs/API-CAPABILITIES.md
M  docs/generated/line_catalog.md
M  hevi/api/main.py
A  CAPABILITY_CONTRACT.md
A  SCENE3D_EVAL.md
A  SCENE3D_TASK.md
A  SCENE3D_DONE.md
A  hevi/api/routers/capabilities.py
A  hevi/capabilities/{__init__,registry,scene3d,errors,result}.py
A  hevi/layer4_legacy/scene3d/{__init__,schema,template,renderer,cli,stages}.py
A  hevi/layer4_legacy/scene3d/ASSETS.md
A  hevi/layer4_legacy/scene3d/NOTICE
A  hevi/layer4_legacy/scene3d/examples/{little_planet_orbit,fox_in_wheat,through_star_sea}.json
A  hevi/layer4_legacy/scene3d/vendor/three/{three.module.js, postprocessing/*, shaders/*}
A  hevi/studio/lines/scene3d.yaml
A  scripts/scene3d_e2e.{py,sh}
A  tests/test_scene3d.py
A  tests/test_scene3d_capability.py
```

## 10. 结论

SCENE3D-R1 验收全部通过：
1. 3 条 1080p 样片（12–13 s，30 fps，1080p）全部真实出片并 ffprobe + sha256 + contact sheet 严谨核验；
2. CPU SwiftShader 每帧渲染耗时 0.78s ~ 1.55s，远低于 4.0s/frame 预算；
3. 16 项自动化测试全部通过（4 项硬性指标测试 + schema 测试 + CLI 集成 + 契约全套测试）；
4. 3O lint 9/9 PASS 零新增错误；
5. 严格遵守安全准则：CPU-only，无任何付费 API，无 mock，未动 worktree 外文件，无磁盘清理；
6. 严格落实能力契约，完成 `scene3d.planet_orbit`、`scene3d.fox_wheat`、`scene3d.star_sea` 统一注册与 HTTP 接入。

DONE SCENE3D-R1
