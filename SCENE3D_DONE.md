# SCENE3D R1B 完成报告

日期：2026-10-14
工作区：/data/soffy/projects/hevi-scene3d
分支：feat/scene3d-line
运行环境：/data/soffy/projects/hevi/.venv/bin/python；JWT_SECRET=test-only；PYTHONPATH=/data/soffy/projects/hevi-scene3d；TMPDIR=.tmp。只在指定 worktree 内工作，CPU SwiftShader 渲染，无付费 API、无磁盘清理、未修改主 checkout。

## SCENE3D_FIX.md 项目验收

| 项目 | 修复及实测证据 | 结果 |
|---|---|---|
| F1 Preview 500 | Preview endpoint 改同步 handler，使同步 Playwright 在线程池执行。真实 TestClient 请求 aspect=9:16、resolution=270，HTTP 200 video/mp4；ffprobe 3.0 秒、90/90 帧。非法画幅 422，未知能力 404。 | PASS |
| F2 穿模 | 3 个真实预设碰撞探测 violations=[]；field 为狐狸与石块设置排除区，调整环轨及行星布局避开树冠/地面。穿模测试通过。 | PASS |
| F3 主体安全区 | 3 能力 × 2 画幅，使用实际相机预设，对中间帧和末帧投影包围盒，符合左右各 5%、上下各 10% 安全区，共 12 个点通过。 | PASS |
| F4 顶点 shader 风摆 | InstancedMesh 叶片按 UV 高度弯曲、根部固定、梢部摆动，时间由 __setTime 驱动。固定相机与狐狸摆动关闭时，风关闭帧逐字节一致、风开启帧有差异。 | PASS |
| F5 能力完整性 | 检查 supports_aspect；ffprobe count_frames 要求实际帧数等于 ceil(duration × fps)；检查文件存在后再 probe，失败转换为 CapabilityError；jsonschema 不可用时拒绝验证。params.seed 覆盖 seed= 的语义明确并通过测试；59/60 帧变异被拦截。 | PASS |
| F6 幼儿动画 | 狐狸补眼睛、鼻子、腮红；星海增大星体并增加远近层次，柔和配色。六条实片全部通过儿童门禁，时长 12–13 秒、平均饱和度 <0.85，测量频率/振幅远低于闪烁门禁。 | PASS |
| F7 ShotSpec 与 lint 报告 | ShotSpec capability bridge 按名字查询统一 registry 并调用能力；未知能力/非法画幅以 422 报告。新增三个测试覆盖名字 dispatch、未知能力 422、非法画幅 422。3O lint 正确记录四项既有基线失败，未声称全过。 | PASS（基线 lint 失败见下） |

## 六条正式样片

全部用 seed=1234 渲染，并独立同 seed 复渲；六条主片 SHA-256 均与复渲一致。均为 H.264、30 fps；实际解码帧数匹配期望；每个目录均含 contact_sheet_6f.png 及 PNG 帧序列。

| 样片目录 | 画幅 | 时长 | 分辨率 | 解码帧数 | SHA-256 | 复渲 |
|---|---|---:|---:|---:|---|---|
| planet_orbit_16x9 | 16:9 | 12.0 s | 1920×1080 | 360/360 | 856f38a27621441c0d425883e1084e6214ab748e6be1a252bdfeb095ff0776e0 | 一致 |
| planet_orbit_9x16 | 9:16 | 12.0 s | 1080×1920 | 360/360 | fcc856e2ca3a88d40c06b4b45432785e914e453f8066abff4971a12678fecf1b | 一致 |
| fox_wheat_9x16 | 9:16 | 12.0 s | 1080×1920 | 360/360 | 1c1f4e4abf2e18df27ad5026b68e5f73d196df942e3e9313e7dc4e1efb1337e5 | 一致 |
| fox_wheat_16x9 | 16:9 | 12.0 s | 1920×1080 | 360/360 | a8de1cfe375518fa4517a210d0cd5b16af167704845bcbdb6e2564c24938d3c9 | 一致 |
| star_sea_9x16 | 9:16 | 13.0 s | 1080×1920 | 390/390 | 0355e0cc7c3a4d62d563a54762e5efbf3b4174841da2a2cd31c404530790a28a | 一致 |
| star_sea_16x9 | 16:9 | 13.0 s | 1920×1080 | 390/390 | ee4a8eeef29e060a560e8f655b8e54d2c6f5992f43ef857d9f711d3e303fc2fb | 一致 |

拼图路径：output/scene3d_r1b/<sample>/contact_sheet_6f.png。

## 儿童门禁实测

从每条真实 PNG 每三帧取一帧（10 fps），先缩放到 64×64，再计算亮度、饱和度与平均亮度 FFT 主峰。六条门禁均 passed=true、failures=[]。

| 样片 | 结果 | 平均亮度 | 平均饱和度 | 主波动频率 | 振幅 |
|---|---|---:|---:|---:|---:|
| planet_orbit_16x9 | PASS | 0.57177 | 0.20447 | 0.08333 Hz | 0.001838 |
| planet_orbit_9x16 | PASS | 0.58229 | 0.21075 | 0.08333 Hz | 0.003752 |
| fox_wheat_9x16 | PASS | 0.78190 | 0.30523 | 0.08333 Hz | 0.001063 |
| fox_wheat_16x9 | PASS | 0.76923 | 0.31486 | 0.08333 Hz | 0.001712 |
| star_sea_9x16 | PASS | 0.64149 | 0.11894 | 0.15385 Hz | 0.000933 |
| star_sea_16x9 | PASS | 0.64865 | 0.09824 | 0.38462 Hz | 0.002541 |

## pytest 与 3O lint

验收命令：

    JWT_SECRET=test-only TMPDIR=.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scene3d.py tests/test_scene3d_capability.py tests/test_scene3d_r1b.py

实测：39 passed，0 failed，0 skipped，1 warning，194.72 秒。唯一 warning 是 Starlette 提醒未来的 TestClient/httpx 兼容性迁移，不影响结果。

官方 lint 命令：

    PYTHONPATH=/data/soffy/projects/hevi-scene3d /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py

实测退出码 1（FAIL），9 项中 5 PASS、4 FAIL。失败：check_no_sibling_call.py、check_omodul_signature.py、check_enabled_pillars.py、check_oprim_keyword_only.py；通过：check_flat_namespace.py、check_no_project_prefix.py、check_obase_no_reverse_dep.py、check_oservi_injection.py、check_async_contract.py。这四项失败与 SCENE3D_FIX.md 记录的主 .venv 基线一致；没有谎称 lint 全过，也没有为场景任务改动这些 3O 架构规则。

视频、拼图及帧序列位于 output/scene3d_r1b/；复渲与门禁 JSON 位于 .tmp/。未清理磁盘、未删除 worktree 外文件、未 push，未修改主 checkout。

DONE SCENE3D-R1B
