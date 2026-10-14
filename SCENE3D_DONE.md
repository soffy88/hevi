# SCENE3D R1B 返工记录（未完成最终验收）

日期：2026-10-14；工作区：/data/soffy/projects/hevi-scene3d；分支：feat/scene3d-line。

结论：核心场景/API/风 shader/产物校验和两组测试有实测证据，但六条样片的确定性与儿童门禁、ShotSpec 装配接线尚未全部验收。磁盘使用率达到 99%（余量约 13G）后，按不清理磁盘的约束停止新增渲染。最后一条同 seed 复渲及另外三条样片的儿童门禁未获得结果。因此不写 DONE SCENE3D-R1B。

环境：使用 /data/soffy/projects/hevi/.venv/bin/python；JWT_SECRET=test-only；TMPDIR=/data/soffy/projects/hevi-scene3d/.tmp；PYTHONPATH=/data/soffy/projects/hevi-scene3d。仅在指定 worktree 工作，无付费 API、无磁盘清理。本机 /snap/bin/chromium 包装器在服务沙箱中无法启动，原生二进制 /snap/chromium/current/usr/lib/chromium-browser/chrome 可启动；调整了 chromium_available() 探测和渲染启动的原生浏览器回退，避免浏览器测试被全部 skip。

## SCENE3D_FIX.md 逐项结果

| 项目 | 修复/实现及实测 | 状态 |
|---|---|---|
| F1 同步 Playwright API 导致 preview 500 | preview 使用同步 handler；TestClient 实际返回 200 video/mp4，270p、3.0 s、90 帧；非法画幅 422，未知能力 404 | PASS |
| F2 轨道/行星/植物/狐狸穿模 | 场景几何有排除区域并调整轨道/星球布局；三个真实 preset 的碰撞探测测试通过 | PASS |
| F3 相机画幅安全区 | 三种能力分别按 16:9、9:16 使用相机路径；3 能力 × 2 画幅真实渲染的中段/末段安全区测试通过 | PASS |
| F4 shader 风场 | 顶点 shader 通过 UV 高度与确定性时间使根部固定、叶尖摆动；风关闭时帧字节一致，开启时帧变化 | PASS |
| F5 假成功与产物校验 | unsupported aspect、缺视频、ffprobe 异常转为 CapabilityError；文件存在检查、count_frames 校验、JSON Schema 严格失败、seed 优先级测试通过；末帧缺失测试检测到 59/60 | PASS |
| F6 幼儿风格/节奏门禁 | 狐狸脸部、层次大星体、柔和色彩与慢节奏有实现；三条样片的实测门禁通过，另外三条未完成测量 | PARTIAL |
| F7 lint 与 ShotSpec 接线 | 更正旧报告的 lint 9/9 PASS 错误；官方 lint 有 4 项已知基线失败；本轮不宣称 ShotSpec → assembly 已接线 | PARTIAL |

## 六条样片：ffprobe 与 SHA-256

所有主样片均由能力适配器实际渲染，seed=1234。时长、分辨率、帧数与逐帧时间来自渲染结果/ffprobe。每条均生成 6 帧 contact sheet。

| 样片目录 | 画幅 | 时长 | 分辨率 | 解码帧数 | 秒/帧 | SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| planet_orbit_16x9 | 16:9 | 12.0 s | 1920×1080 | 360/360 | 0.2529 | 856f38a27621441c0d425883e1084e6214ab748e6be1a252bdfeb095ff0776e0 |
| planet_orbit_9x16 | 9:16 | 12.0 s | 1080×1920 | 360/360 | 0.2243 | fcc856e2ca3a88d40c06b4b45432785e914e453f8066abff4971a12678fecf1b |
| fox_wheat_9x16 | 9:16 | 12.0 s | 1080×1920 | 360/360 | 0.2398 | 1c1f4e4abf2e18df27ad5026b68e5f73d196df942e3e9313e7dc4e1efb1337e5 |
| fox_wheat_16x9 | 16:9 | 12.0 s | 1920×1080 | 360/360 | 0.2289 | a8de1cfe375518fa4517a210d0cd5b16af167704845bcbdb6e2564c24938d3c9 |
| star_sea_9x16 | 9:16 | 13.0 s | 1080×1920 | 390/390 | 0.2538 | 0355e0cc7c3a4d62d563a54762e5efbf3b4174841da2a2cd31c404530790a28a |
| star_sea_16x9 | 16:9 | 13.0 s | 1920×1080 | 390/390 | 0.2534 | ee4a8eeef29e060a560e8f655b8e54d2c6f5992f43ef857d9f711d3e303fc2fb |

Contact sheet 在 output/scene3d_r1b/<sample>/contact_sheet_6f.png；视频与 PNG 帧序列在对应目录。六条视频均为 H.264、30fps，实际解码帧数匹配 ceil(duration × fps)。

### 同 seed 复渲

| 样片 | 首渲与复渲 SHA-256 |
|---|---|
| planet_orbit_16x9 | 一致：856f38a27621441c0d425883e1084e6214ab748e6be1a252bdfeb095ff0776e0 |
| planet_orbit_9x16 | 一致：fcc856e2ca3a88d40c06b4b45432785e914e453f8066abff4971a12678fecf1b |
| fox_wheat_9x16 | 一致：1c1f4e4abf2e18df27ad5026b68e5f73d196df942e3e9313e7dc4e1efb1337e5 |
| fox_wheat_16x9 | 一致：a8de1cfe375518fa4517a210d0cd5b16af167704845bcbdb6e2564c24938d3c9 |
| star_sea_9x16 | 一致：0355e0cc7c3a4d62d563a54762e5efbf3b4174841da2a2cd31c404530790a28a |
| star_sea_16x9 | 未运行。磁盘剩余约 13G、使用率 99% 后停止新增渲染以避免写满；没有把缺失实测伪记为通过。 |

### 幼儿门禁实测（真实 PNG 每三帧取一帧，10fps）

| 样片 | 结果 | 平均亮度 | 平均饱和度 | 主亮度波动频率 | 振幅 |
|---|---|---:|---:|---:|---:|
| planet_orbit_16x9 | PASS | 0.5718 | 0.2085 | 0.0833 Hz | 0.00184 |
| planet_orbit_9x16 | PASS | 0.5823 | 0.2138 | 0.0833 Hz | 0.00375 |
| fox_wheat_9x16 | PASS | 0.7819 | 0.3092 | 0.0833 Hz | 0.00106 |
| fox_wheat_16x9 | 未运行 | — | — | — | — |
| star_sea_9x16 | 未运行 | — | — | — | — |
| star_sea_16x9 | 未运行 | — | — | — | — |

已测三条时长均为 12 秒，超过 2.5 秒下限；平均饱和度低于 0.85 上限，亮度主频与振幅低，无门禁失败。另三条没有有效结果，不能宣称全部通过。

## 测试与 lint 实际结果

使用指定主 .venv，未使用 --noconftest；Chromium 修复后浏览器用例实际执行：

- pytest tests/test_scene3d_r1b.py -q：22 passed、0 skipped（42.30 s；1 条 Starlette/httpx 弃用警告）。
- pytest tests/test_scene3d.py tests/test_scene3d_capability.py -q：14 passed、0 skipped（72.63 s）。
- 两组分别执行合计 36 passed、0 skipped。合并执行的尝试未返回有效测试结果，因此没有计入。
- 官方 lint 命令：PYTHONPATH=/data/soffy/projects/hevi-scene3d /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py。实际退出码 1 / FAIL；四项既有基线失败是 check_no_sibling_call.py、check_omodul_signature.py、check_enabled_pillars.py、check_oprim_keyword_only.py，其余多项检查通过。不能表述成 9/9 PASS；本轮未修改这些架构规则涉及的文件。

## 尚未完成的验收项

1. star_sea_16x9 同 seed 复渲 SHA-256 未实测；fox_wheat_16x9、star_sea_9x16、star_sea_16x9 的幼儿门禁没有有效测量结果。
2. ShotSpec capability → assembly 的生产接线和装配层未知能力返回 422 测试未纳入本次完成范围。工作区预先存在的 hevi/creative/shotspec_capability.py、hevi/creative/director_contract.py 保持原样，未被本轮暂存。
3. 磁盘余量已降至约 13G / 99%。按不清理磁盘的限制，没有删除、移动中间帧或继续启动可能消耗数 GB 的渲染。

因此 R1B 核心场景/API/风 shader/产物校验和两组测试有实测证据，但完整六条样片的确定性与儿童门禁、ShotSpec 装配接线尚未全部验收。本报告保留未完成状态。
