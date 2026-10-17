# SCENE3D R2 返工单（Hark 独立核验 R1B @f054ddce，2026-10-15 05:20–06:10 CST）

R1B 核验 **不通过**。F1–F5、F7 的工程项已经实测通过（见文末「已确认通过，不要回退」），但 **F6 幼儿方向** 在亲自重渲的样片里仍然不达标。核验证据：`audit/scene3d/verify_r1b/`（REPORT.md、frames/*.jpg、renders.tsv、api_probe.json）。

## 阻断项（必须全部修）

### B1. 小狐狸在两条 fox_wheat 样片里始终背对镜头，五官看不见（F6 未达成）
- 复现：
  `cd /data/soffy/projects/hevi-scene3d && JWT_SECRET=test-only TMPDIR=$PWD/.tmp PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python -m hevi.layer4_legacy.scene3d.cli render output/scene3d_r1b/fox_wheat_9x16/scene.json --out .tmp/r2_fox9`
  然后抽 t=1.2/6.0/10.8s 帧看。
- 期望：IP 角色小狐狸正脸或 3/4 正脸朝向镜头，眼睛、鼻子、腮红清楚可见（至少占镜头时长的大部分），外形圆润可爱。
- 实际：fox_wheat_9x16 和 fox_wheat_16x9 每一帧都是从背后/侧后方拍，只露出后脑勺、尾巴和屁股，脸只在画面边缘露出一只眼睛的侧影；腮红、鼻子完全看不到。四条腿是棕色方柱，像木桩，不像幼儿动画角色。
- 证据：`audit/scene3d/verify_r1b/frames/fox_wheat_9x16_t1.2.jpg`、`fox_wheat_9x16_t6.0.jpg`、`fox_wheat_16x9_t6.0.jpg`、`fox_wheat_9x16_6f.jpg`。
- 修法：调整狐狸 rotY 或相机路径，让镜头从狐狸前方/前侧方环绕（确认 makeFox 的"正面"方向与相机路径一致）；腿改成短圆柱/胶囊并与身体同色系（深橙或棕橙渐变），整体更圆。
- 必须新增测试：真实预设下，在开头、中间、结尾三帧，把狐狸脸部朝向向量（头部前方）与"狐狸→相机"向量做点积，要求 >0.3（脸朝镜头）；并把眼睛的包围盒投影到屏幕，要求在画面内且未被遮挡（可用射线检测或 depth 比较）。

### B2. 麦田配色仍然发灰发米色，狐狸不是橙色（F6 未达成，R1 原问题仍在）
- 复现：同 B1，看任意帧。
- 期望：配色明亮柔和、饱和适中（幼儿动画常见的暖金色麦田 + 蓝天 + 明亮橙色狐狸），狐狸与背景有清楚的色相/明度对比。
- 实际：天空、地面、麦秆几乎是同一种米黄色（天空也是米色），狐狸是淡黄色而不是橙色，被背景吞掉；kids_gate 测得平均饱和度只有 0.30（只设了上限，没设下限）。
- 证据：同 B1 的帧。
- 修法：天空改成柔和蓝色渐变，减弱或改色雾（雾色不能和麦田同色），狐狸恢复 R1 规定的橙色 [1.0,0.55,0.16] 并确认渲染后仍是橙色（不被雾/曝光冲淡），麦秆加明显的穗头。
- 必须新增测试：kids_gate 增加饱和度下限（建议平均饱和度 ≥0.35）；对狐狸所在屏幕区域取样，色相在橙色范围（约 15°–40°）且饱和度 ≥0.5。

### B3. 「穿过星海」仍然不是星海，镜头没有从星星中间穿过（F6 未达成）
- 复现：
  `... cli render output/scene3d_r1b/star_sea_9x16/scene.json --out .tmp/r2_sea9`（16:9 同理），抽 t=1.3/6.5/11.7s 帧。
- 期望：星星有远近层次，推进镜头时星星从镜头两侧/身边掠过（真正"穿过"）；画面主体是星空，而不是一大块平地；整体明亮柔和。
- 实际：星星变大了，但全部是地平线后面的一面"散景墙"，镜头始终在地面上方朝一颗淡蓝球推进，没有任何星星从镜头旁经过；9:16 画面下方约 45–50% 仍是一整块灰绿色平地；整体平均饱和度只有 0.10–0.12（kids_gate.json），偏灰。
- 证据：`audit/scene3d/verify_r1b/frames/star_sea_9x16_6f.jpg`、`star_sea_9x16_t1.3.jpg`、`star_sea_16x9_t6.5.jpg`。
- 修法：去掉或大幅缩小地面（星海场景不需要草地），星星分布在相机路径周围的体积里（包括近处），镜头沿路径真正穿过星群；加少量柔和大星做前景掠过；背景用更明亮柔和的紫蓝渐变。
- 必须新增测试：真实预设下，统计相机路径前进过程中进入相机近处（例如距离 < 若干单位且在视锥内）的星星数，要求 >0；9:16 画面中地面像素占比 ≤20%；平均饱和度 ≥0.25。

## 非阻断观察（顺手处理）
- 能力层 `cap.render(..., duration=1.0)` 和 ShotSpec 桥接都能渲出 1 秒片，没有拒绝；API preview 因为固定 3 秒、额外字段返回 422，所以 API 层没问题。若幼儿线要求单镜头 ≥2.5s，建议在能力层或 ShotSpec 层也加最小时长校验（<2s 抛 CapabilityError/422），并加测试。

## 已确认通过，不要回退
- F1：TestClient 真打 `POST /api/capabilities/scene3d.fox_wheat/preview?aspect=9:16`，resolution=270 → 200 video/mp4，ffprobe 270×480、3.0s、90/90 帧；4:3、1:1、abc → 422；多余字段 duration/duration_s → 422；类型错误 → 422；未知能力 → 404。
- F2：光环与树冠无相交（几何复核：主星光环外径 3.79，树距中心 ≥8.3），抽帧未见麦秆穿入狐狸。
- F3：9:16 / 16:9 两种画幅的主星球、狐狸都完整在画内。
- F4：风摆在 InstancedMesh 材质的 onBeforeCompile 顶点着色器里实现（按高度 hf² 弯曲，uTime 由 __setTime 驱动）。
- F5：截掉 1 帧（89/90）→ CapabilityError；mp4 丢失 → CapabilityError。
- F7：DONE 里 lint 描述与实测一致（主 .venv：5 PASS / 4 FAIL，正是基线 4 项）；pytest 39 passed。
- 6 条样片重渲 sha256 与 DONE 一致，h264 30fps，帧数 360/360/390 正确。three.js r169 MIT 头与 NOTICE 保留。

## 验收（R1C 完成前自测）
1. 按 B1–B3 修完后重渲 6 条样片（3 能力 × 2 画幅），给 sha256、ffprobe（含 nb_read_frames）、6 帧拼图；同 seed 渲两次 sha 一致。
2. 新增 B1–B3 测试并全部通过；原 39 个测试不回退：`JWT_SECRET=test-only TMPDIR=.tmp /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scene3d.py tests/test_scene3d_capability.py tests/test_scene3d_r1b.py`（加上新测试文件），不加 `--noconftest`。
3. 3O lint 只允许基线 4 项失败。
4. DONE 如实写，附抽帧路径，最后一行单独写 `DONE SCENE3D-R1C`。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-scene3d；不 push；不调付费 API；渲染一次只跑一个进程；不要把日志提交进仓库。
