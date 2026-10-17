# SCENE3D R3 返工单（Hark 独立核验 R1C @1f6e10e7，2026-10-15 08:00–08:25 CST）

R1C 核验 **不通过**。B1（狐狸正脸）已通过，回归项全部通过（见文末「已确认通过，不要回退」）。**B3 星海里一颗星星都没渲染出来，B2 狐狸和麦田几乎同色**，两项阻断。核验证据：`audit/scene3d/verify_r1c/`（REPORT.md、frames/、compare/、renders.json、probes.json）。

通用环境（所有命令都在 worktree 根目录执行）：
```
cd /data/soffy/projects/hevi-scene3d
export JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD
PY=/data/soffy/projects/hevi/.venv/bin/python
```

## 阻断项（必须全部修）

### C1. 「穿过星海」画面里没有任何星星（B3 未达成，比 R1B 退步）
- 复现：
  1. `SCENE3D_R1C_ONLY=star_sea_9x16 $PY scripts/scene3d_r1c_render.py`（或看现成的 `output/scene3d_r1c/star_sea_9x16/contact_sheet_6f.png`），抽 t=1.3/6.5/11.7s 帧。
  2. 诊断：`$PY audit/scene3d/verify_r1c/stardiag.py` —— 把 `weather.star_size` 从 0.85 改成 8.0 单帧渲 t=6.5s，输出 `audit/scene3d/verify_r1c/frames/stardiag_size{0.85,8.0}_t6.5.png`。
- 期望：画面主体是星空，星星有远近层次，推进时有星星从镜头两侧/身边掠过；少量柔和大星做前景。
- 实际：两画幅所有帧都只有紫蓝渐变 + 3 个行星球，零颗星；亮度 >170 的像素全部来自行星。star_size 放大约 10 倍后仍然零颗星——星星根本没画出来，不是尺寸问题。`probe_star_proximity` 报告 1438 可见/184 近星，是因为它只看几何坐标，不看像素。
- 证据：`frames/star_sea_9x16_t6.5.jpg`、`frames/star_sea_16x9_t1.3.jpg`、`frames/stardiag_size8.0_t6.5.png`、`compare/star_sea_9x16_t6.5_r1b_vs_r1c.jpg`。
- 排查方向（未验证的推测）：`starCorridor` 分支下 Points 是否真被绘制（背景渐变网格/天空球是否在星星之后绘制并覆盖了 depthWrite=false 的透明点；renderOrder；星星 z 区间 0.5–47 与相机路径/near 平面的关系）；片元着色器 `gl_FragColor=vec4(col*a,a)` 配 NormalBlending 会把预乘色再乘一次 alpha，星点偏暗，建议 AdditiveBlending 或 premultipliedAlpha 设置一致。先用单帧把一颗巨大的星放在相机正前方 3 个单位确认能看见，再调整体分布。
- 必须新增测试（基于渲染像素，不能只看几何）：
  - 真实预设两画幅、t=1.3/6.5/11.7 渲单帧，扣掉行星投影区域后，统计连通亮点（亮度比局部背景高 ≥0.25）个数，要求每帧 ≥40；
  - 至少一帧中有半径 ≥6px（540 档）或 ≥12px（1080 档）的近景大星；
  - 相邻两个采样时刻之间至少有一颗星从画面中心区域移动到画面边缘外（证明"穿过"），可用投影坐标 + 像素双重确认；
  - 回归测试：star_size 改大后亮点数必须增加（防止星星被整体隐藏）。

### C2. 狐狸与麦田几乎同色，狐狸不是橙色，天空是灰白（B2 未达成）
- 复现：
  `SCENE3D_R1C_ONLY=fox_wheat_9x16 $PY scripts/scene3d_r1c_render.py`，抽 t=6.0s 帧，取像素：狐狸额头 (270,440)、麦田 (270,250)、天空 (270,80)（540×960 帧坐标）。
- 期望：明亮橙色狐狸（R1 规定 [1.0,0.55,0.16]，渲染后色相约 20°–32°、饱和度 ≥0.6），与金色麦田有清楚的色相差；天空是柔和蓝色（饱和度 ≥0.25）。
- 实际：狐狸额头 RGB(224,189,108)，色相 42°、饱和度 0.52；麦田 RGB(209,183,109)，色相 44°、饱和度 0.48，两者几乎相同，狐狸被麦田吞掉；天空 RGB(198,211,220)，饱和度 0.10，灰白。单元测试的头部橙色检查实测色相中位数 39.53°，卡在 15–40° 上限边上才过，且不比较狐狸与背景。
- 证据：`frames/fox_wheat_9x16_t6.0.jpg`、`frames/fox_wheat_16x9_t6.0.jpg`、`compare/fox_wheat_9x16_t6.0_r1b_vs_r1c.jpg`。
- 修法：检查狐狸材质颜色是否被雾、曝光、tone mapping、色彩空间（sRGB/Linear）或 bloom 冲淡成浅黄；狐狸身体改回 [1.0,0.55,0.16] 并确认渲染后仍是橙色；麦田可以偏金黄但要与狐狸拉开色相或明度；天空换成明显的浅蓝渐变，雾色不要发灰。
- 必须新增测试（真实预设，两画幅，t=1.2/6.0/10.8）：
  - 狐狸头部/身体投影区域的饱和像素色相中位数在 18°–32°，平均饱和度 ≥0.6；
  - 狐狸区域与狐狸包围盒外一圈背景（麦田）的色相中位数差 ≥10°，或 CIELAB ΔE ≥20；
  - 画面顶部 15% 天空区域平均饱和度 ≥0.25、色相在 190°–230°。

### C3. 交付样片按预设分辨率出片
- R1C 样片是 960×540 / 540×960（scripts/scene3d_r1c_render.py RESOLUTION=540），R1B 是 1080。R1D 的 6 条交付样片用预设默认 1080（1920×1080 / 1080×1920）渲染；测试可以继续用低分辨率。

## 已确认通过，不要回退
- B1：两画幅 0–12s 每 0.5s 采样，狐狸脸朝镜头 dot ≥0.91，双眼在画内（16:9 t=11s 一只眼被麦秆挡，可接受）；腿已是圆胶囊。
- <2s 拦截：cap.render(duration=1.0/1.99) → CapabilityError。
- API：preview 200（270×480、3.0s、90 帧），4:3/1:1/abc/多余字段/类型错误 → 422，未知能力 → 404，无 500。
- 无穿模；两画幅主体在画内；风摆在 InstancedMesh onBeforeCompile 顶点着色器；同 seed 重渲 6/6 sha256 一致；pytest `tests/test_scene3d*.py` 45 passed；3O lint 只有基线 4 项失败；three.js MIT 头与 NOTICE 保留。

## 验收（R1D 完成前自测）
1. 修完 C1–C3，按 1080 重渲 6 条样片（3 能力 × 2 画幅），给 sha256、ffprobe（含 nb_read_frames）、6 帧拼图；同 seed 渲两次 sha 一致；渲染一次一个进程。
2. 新增 C1、C2 测试全部通过；`$PY -m pytest -q -p no:cacheprovider tests/test_scene3d*.py` 全过（不加 --noconftest），原 45 项不回退。
3. 3O lint 只允许基线 4 项失败：`$PY scripts/ci/run_3o_v3_lint.py`。
4. DONE 如实写，附 t=1.3/6.5/11.7（星海）、t=1.2/6.0/10.8（狐狸）抽帧路径和像素取样数值，最后一行单独写 `DONE SCENE3D-R1D`。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-scene3d；不 push；不调付费 API；渲染一次只跑一个进程（机器可用内存约 6G，另有任务在跑）；不要把日志、.tmp/、.veya-project/、pi_r1*.jsonl、*.err 提交进仓库。
