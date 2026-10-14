# SCENE3D R1B 修复与验收报告

日期：2026-10-14。工作区：/data/soffy/projects/hevi-scene3d，分支 feat/scene3d-line。验收项逐条对应 SCENE3D_FIX.md；产品方向参考 KIDS_ANIME_DIRECTION.md，能力接口参考 CAPABILITY_CONTRACT.md。

## 总结

- Scene3D 样片、API preview、碰撞检查、画幅安全区、顶点 shader 风摆、ffprobe 帧完整性及幼儿画面门禁有真实渲染/测试证据。
- 六种能力/画幅组合均生成 H.264、30 fps 完整视频及六帧联系表；同 seed 重渲 SHA-256 6/6 完全一致。
- 用户指定的完整 pytest 命令实测 36 passed、1 warning、0 failed、0 skipped。
- 官方 3O lint 实测 5 PASS / 4 FAIL。四项失败与返工单记载的既有基线一致，不声称 9/9 PASS。
- 按 SCENE3D_FIX.md F7 明确允许的替代方案，ShotSpec capability 到 assembly 的生产接线本单元未作为完成项；由 shotspec/webkit 单元负责。本报告不把该接线声称为已实现或已验收。

## F1 — Preview API 的 Playwright 事件循环冲突

修复：preview 路由使用同步 def handler，让 FastAPI 在线程池执行同步 Playwright。先校验能力参数与画幅，再生成预览；无视频产物会报错，成功时返回 video/mp4。非法画幅返回 422，未知能力返回 404。浏览器探测/启动添加原生 Chromium fallback：当 Playwright 浏览器包不存在时使用已安装的 /snap/chromium/current/usr/lib/chromium-browser/chrome，避免本服务沙箱中无法启动 /snap/bin/chromium 包装器；不下载或安装浏览器。

实测：TestClient 真实 POST 预览返回 HTTP 200、video/mp4；ffprobe 时长 3.0 秒、90 帧。非法 aspect 4:3 返回 422；未知 capability 返回 404。

## F2 — 场景几何穿模

修复：抬高主星球并收紧光环半径；植被采样排除狐狸、石头、树木与星球占据区域；麦秆变窄、渐尖，麦穗增加穗头。

实测：test_no_intersection_in_presets 使用三个能力的真实预设与 SceneRenderer.probe_collisions() 检查六种画幅组合，所有碰撞报告为零 violations，测试通过。

## F3 — 16:9 / 9:16 主体安全区

修复：三种能力按 aspect 选择相机路径，竖屏重新取景；星海横屏末段重新取景，避免主体被顶边裁掉。

实测：test_subject_in_safe_area_real_presets 对 3 个能力 × 2 种画幅进行真实低分辨率渲染，分别探测中间帧和末帧的主体包围盒。12 次投影检查全部通过，横向位于 5%–95%、纵向位于 10%–90% 的安全区。

## F4 — 顶点着色器风摆

修复：植被用 InstancedMesh，Material.onBeforeCompile 注入风摆顶点 shader；按叶片高度平方弯曲，根部固定、尖端摆动。时间由 __setTime(t) 驱动，实例有不同相位及摆幅，不再 CPU 每帧重算实例矩阵。

实测：静止相机、狐狸摆动关闭、wind_strength=0 时，不同时间点渲染帧 SHA-256 完全相同；wind_strength>0 时帧 SHA-256 不同。两项均在真实 Chromium/SwiftShader 上运行并通过。

## F5 — 能力结果完整性

修复：render 入口拒绝不支持的 aspect 和非正时长；视频先检查文件存在及非空，再执行 ffprobe 与 ffprobe -count_frames。解码帧数必须等于 ceil(duration × fps)，少帧、缺文件、探测失败均抛 CapabilityError。JSON Schema 验证器不可用时拒绝验证、不再静默放行。seed 优先级明确为 params["seed"] 优先，其次才是 seed= 参数。

实测：不支持画幅、缺失 MP4、截断视频与 seed 优先级测试全部通过。截掉最后一帧的变异样本实测 59/60 帧，能力校验拒绝该视频。

## F6 — 2–6 岁幼儿动画画面

修复：狐狸面部增加眼睛、瞳孔、高光、鼻子、腮红、耳内侧和浅色口鼻；强化橙色主体与麦田的色彩对比。星海加入远近分层、更大更亮的星点与柔和的天空渐变；镜头推进经过星场。风摆和星点亮度变化由确定性时间控制。

实测：六条视频的全部 360/390 帧均以 30 fps 解码到 96×96 分析图，逐帧通过 kids_gate。六条时长为 12–13 秒，平均亮度为 0.319–0.436，平均饱和度为 0.058–0.178（上限 0.85），测得亮度主频最高 0.385 Hz（限制 3 Hz）。六条均无黑帧、无白帧、无相邻重复静帧。这里交付的是无音轨视觉镜头；未生成或测量音频 LUFS，也不声称完成旁白/字幕验收。

## 六条样片：实测 ffprobe、SHA-256 和逐帧耗时

时长、分辨率、解码帧数、SHA 来自本轮渲染文件与 ffprobe。秒/帧为渲染器记录的逐帧输出耗时；六条均低于 4 s/frame。

| 样片目录 | 画幅 | 时长 | 分辨率 | 解码帧数 | 秒/帧 | SHA-256 |
|---|---|---:|---:|---:|---:|---|
| planet_orbit_16x9 | 16:9 | 12.0 s | 1920×1080 | 360 | 0.2529 | 856f38a27621441c0d425883e1084e6214ab748e6be1a252bdfeb095ff0776e0 |
| planet_orbit_9x16 | 9:16 | 12.0 s | 1080×1920 | 360 | 0.2243 | fcc856e2ca3a88d40c06b4b45432785e914e453f8066abff4971a12678fecf1b |
| fox_wheat_9x16 | 9:16 | 12.0 s | 1080×1920 | 360 | 0.2398 | 1c1f4e4abf2e18df27ad5026b68e5f73d196df942e3e9313e7dc4e1efb1337e5 |
| fox_wheat_16x9 | 16:9 | 12.0 s | 1920×1080 | 360 | 0.2289 | a8de1cfe375518fa4517a210d0cd5b16af167704845bcbdb6e2564c24938d3c9 |
| star_sea_9x16 | 9:16 | 13.0 s | 1080×1920 | 390 | 0.2538 | 0355e0cc7c3a4d62d563a54762e5efbf3b4174841da2a2cd31c404530790a28a |
| star_sea_16x9 | 16:9 | 13.0 s | 1920×1080 | 390 | 0.2534 | ee4a8eeef29e060a560e8f655b8e54d2c6f5992f43ef857d9f711d3e303fc2fb |

六条编码均为 H.264、30 fps。六帧联系表（起始、20%、40%、60%、80%、末帧）：
- output/scene3d_r1b/planet_orbit_16x9/contact_sheet_6f.png
- output/scene3d_r1b/planet_orbit_9x16/contact_sheet_6f.png
- output/scene3d_r1b/fox_wheat_9x16/contact_sheet_6f.png
- output/scene3d_r1b/fox_wheat_16x9/contact_sheet_6f.png
- output/scene3d_r1b/star_sea_9x16/contact_sheet_6f.png
- output/scene3d_r1b/star_sea_16x9/contact_sheet_6f.png

六条同 seed 复渲保存于 .tmp/scene3d_r1b_repeat/，与首渲逐字节 SHA-256 比较均一致，6/6 equal=true。完整 ffprobe、kids_gate、帧质量和确定性数据见 .tmp/scene3d_r1b_qa/summary.json。

## 测试与 lint 实测结果

指定测试命令（主 Hevi .venv，正常加载 conftest，没有 --noconftest）：

PYTHONPATH=/data/soffy/projects/hevi-scene3d JWT_SECRET=test-only TMPDIR=.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scene3d.py tests/test_scene3d_capability.py tests/test_scene3d_r1b.py

实测：36 passed, 1 warning in 187.54s；0 failed、0 skipped。唯一警告是 Starlette 提示 starlette.testclient 使用 httpx 已弃用，后续建议迁移 httpx2；不影响测试结果。分组实测：test_scene3d_r1b.py 为 22 passed，test_scene3d.py + test_scene3d_capability.py 为 14 passed。

官方 lint 命令：

PYTHONPATH=/data/soffy/projects/hevi-scene3d /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py

实测 5 PASS / 4 FAIL。四个既有基线失败为 check_no_sibling_call、check_omodul_signature、check_enabled_pillars、check_oprim_keyword_only，与 SCENE3D_FIX.md 记录的基线一致；check_obase_no_reverse_dep、check_oservi_injection、check_async_contract、check_flat_namespace、check_no_project_prefix 通过。没有把 lint 失败误报为 PASS。

能力注册名：scene3d.planet_orbit、scene3d.fox_wheat、scene3d.star_sea。Three.js r169 的 MIT 许可证与 NOTICE 保留；场景程序化生成，不调用付费 API，不下载外部模型或贴图。未清理磁盘、未 push、未修改主 checkout。最终磁盘检查通过，未触发剩余空间低于 5 GiB 的停止线。

DONE SCENE3D-R1B
