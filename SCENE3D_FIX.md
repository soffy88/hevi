# SCENE3D R1B 返工单（Hark 独立核验 @d2365c0f，2026-10-14 20:35–21:10 CST）

R1 核验 **不通过**。确定性、ffprobe、16 个测试、lint、许可证都已过（见文末「已确认通过，不要回退」），但下面这些问题必须修。修完后重渲三条样片，按最后的验收清单逐项自测，再写 DONE。

## 阻断项（必须全部修）

### F1. `POST /api/capabilities/{name}/preview` 必定 500
- 实测（hevi 主 .venv，有 fastapi，FastAPI TestClient）：合法请求 `scene3d.fox_wheat?aspect=9:16&seed=5`，不论 body 是 `{"resolution":480}`、`{}` 还是空，**3/3 次返回 500**：`It looks like you are using Playwright Sync API inside the asyncio loop. Please use the Async API instead.`
- 原因：`preview_capability_endpoint` 是 `async def`，却在事件循环里同步调用 `SceneRenderer`（sync Playwright）。
- 修法：endpoint 改成普通 `def`（FastAPI 会放进线程池），或者 `await run_in_threadpool(cap.render, ...)`。
- 必须新增测试：用 TestClient 真打 `POST /api/capabilities/scene3d.fox_wheat/preview?aspect=9:16`（params 设低分辨率，例如 resolution=270）→ 200、`video/mp4`、ffprobe 读出时长 3.0s±0.2。用 hevi 主 `.venv`（有 fastapi/httpx）跑，**不要再用 `--noconftest` 绕开 conftest**。
- 同时：非法 aspect（例如 `4:3`）现在返回 500，应返回 **422**；未知能力返回 404 可以保留，但契约写的是 ShotSpec 层 422，见 F7。

### F2. 明显穿模
- `little_planet_orbit`（16:9 和 9:16 都有）：主星球光环 `RingGeometry(pr*1.4, pr*1.9)` 半径约 4.56，直接从两棵树的树冠里横穿过去，6 帧拼图每帧都看得见。证据：`sheets/orbit_f090.jpg`、`sheets/orbit_f090_crop.jpg`、`sheets/orbit_16x9_a_6f.png`。星球底部离地只有 0.2，草尖（最高 0.9）也插进球体。
- `fox_in_wheat`：`makeField` 在整个 area 里均匀撒麦秆和草，没有给角色和石头留空，麦秆会从狐狸身体里穿出来（`sheets/fox_f180_crop.jpg`）。
- 修法：给 field 增加 `exclude` 区域（角色、石头、树干周围按半径排除），光环半径和倾角要避开场景物体（或把树移开、星球抬高），星球不要和草地相交。
- 必须新增测试：对每个样例场景，在 JS 端或 Python 端做包围盒/包围球相交检查（光环 vs 树，field 实例 vs 角色/石头），有相交就失败。

### F3. 9:16 / 16:9 换画幅后主体出画
- `scene3d.planet_orbit` 声明支持 9:16，但 9:16 实测 6 帧里**主星球顶部全部被画面上沿裁掉**（`sheets/orbit_9x16_a_6f.png`）。原因：换画幅时沿用 16:9 的相机路径和 fov，没有按画幅重新取景。
- `through_star_sea` 16:9 最后约 2 秒主星球也被裁出上沿（`sheets/sea_16x9_a_6f.png`）。
- 修法：每个能力按 aspect 选相机预设（竖屏拉远或调 fov/look 高度），保证主体包围盒在安全区内（竖屏上下各留 10%，左右各留 5%）。
- 必须新增测试：对 **3 个能力 × 2 种画幅** 用真实预设渲中间帧和末帧（低分辨率即可），把主体包围盒投影到屏幕上，检查在安全区内。现在的 `test_916_subject_in_safe_area` 用的是测试里自己写的固定相机，不代表真实样片，不算数。

### F4. 风摆不是顶点着色器，草和麦子像一地斜插的木板
- 任务要求「InstancedMesh + 顶点着色器实现风摆动」。现在是 CPU 在 `updateFields` 里每帧重算每个实例的矩阵，整片叶子绕根部刚体旋转 ±0.56rad，不弯曲。画面上麦秆像随机斜插的宽木条（`sheets/fox_f180.jpg`）。
- 修法：风改在 vertex shader（`onBeforeCompile` 或 ShaderMaterial）里，按 `uv.y`/高度做弯曲，根部不动、梢部摆；时间用 uniform，由 `__setTime` 设置，保证确定性。叶片改窄、改成锥形，麦穗加穗头。
- 测试：静止相机、关掉狐狸摆动，wind_strength=0 时相邻帧必须**逐字节相同**，wind_strength>0 时必须不同。现在的风动测试相机在动，狐狸也在摆，风关掉也会通过，测不出风。

### F5. 能力层的完整性检查不够
- 声明只支持 `16:9/9:16` 的能力，传 `aspect="1:1"` 照样渲出来、返回成功（`render_unsupported_aspect_1x1`）。`render()` 必须先检查 `cap.supports_aspect(aspect)`，不支持就抛 `CapabilityError`。
- 少帧检测不到：变异测试里把最后一帧删掉，能力层 2 秒片变成 59 帧（1.97s），落在 ±0.5s 容差内照样成功；CLI 片 0.9s 也成功。必须用 `ffprobe -count_frames` 检查 `nb_read_frames == ceil(duration*fps)`，帧数不对就抛 `CapabilityError`。
- `_render_capability` 先调 `ffprobe(video)` 再检查文件存在：mp4 丢失时抛的是 `CalledProcessError` 而不是 `CapabilityError`。顺序调过来，所有异常统一包成 `CapabilityError`。
- `validate_params` 在 jsonschema 导入失败时直接放行（等于假成功），改成抛 `CapabilityError`。
- `params.seed` 和 `seed=` 参数冲突时以谁为准要写清楚，并加测试。

### F6. 幼儿方向（KIDS_ANIME_DIRECTION.md，最高优先级）
- 小狐狸没有眼睛和表情，只有胶囊加圆球，不像 IP 角色。至少加上眼睛、鼻子、腮红，外形更圆润。
- 「穿过星海」：星星是 2px 小点，1080p 下几乎看不见；9:16 画面下方约 70% 是一整块暗绿平地，不像星海。星星要更大、更亮、有远近层次（可以加少量柔和的大星），并且推进镜头时真正从星星中间穿过。整体配色要明亮柔和。
- 麦田场景整体发灰发米色，饱和度太低；狐狸橙色被雾冲淡。
- 新增 kids 检查：亮度闪烁 ≤3Hz（星星闪烁换算成画面平均亮度），镜头时长 ≥2.5s，饱和度上限。

### F7. DONE 报告与实测不符，必须更正
- 「3O lint 9/9 PASS 与基线一致」不对。用仓库规定的 hevi 主 `.venv` 跑，分支和基线 7087c24a 都是 **4 项 FAIL**（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），日志逐行一致，没有新增。用 `.venv-scene3d` 跑出 9/9 PASS 是因为这个 venv 缺依赖，不能当作结论。
- 测试必须用带 fastapi/httpx 的 venv 正常加载 conftest 跑，不能用 `--noconftest`。
- API 写成「已实现并接入」，实际 preview 从来没成功过（F1）。
- ShotSpec 接入（`shot_spec.capability = {"name","params"}`，assemble 按名字调用，名字不存在返回 422）在本分支没有实现。要么实现一个最小接入并加测试，要么在 DONE 里如实写明「未做、由 shotspec/webkit 单元负责」。

## 已确认通过，不要回退
- 干净环境（git archive d2365c0f）CPU SwiftShader 重渲：三条样片同 seed 两次渲染，mp4 sha256 **逐字节相同**，且与 DONE 里写的 sha256 一致；每帧 0.19–0.31s（1080p）。
- ffprobe：orbit 1920×1080/12.0s/360 帧，fox 1080×1920/12.0s/360 帧，sea 1080×1920/13.0s/390 帧，30fps h264。6 种组合都没有黑帧、白帧，没有相邻帧相同的静止帧。
- 能力注册：`scene3d.planet_orbit / fox_wheat / star_sea` 都能列出；6 种非法参数和 duration≤0 都抛 CapabilityError；3 个能力 × 2 种画幅的 2 秒渲染 ffprobe 都正常（60 帧/2.0s）。
- pytest 16/16 通过（hevi 主 .venv，JWT_SECRET=test-only，TMPDIR 指向 /data）；变异测试（删 mp4 / 删一帧）都会让测试失败。
- three.js r169 的 MIT 头保留，NOTICE 里有全文；没有外部模型或贴图，全部程序化生成。

## 验收（R1B 完成前自测）
1. 三条样片按 F2/F3/F4/F6 修完后重渲：orbit 16:9、fox 9:16、sea 9:16 各 10–15s，另外每个能力都出一条另一种画幅的样片；每条都给出 sha256、ffprobe（含 nb_read_frames）、6 帧拼图，并且同 seed 渲两次 sha 一致。
2. 新增测试：F1 API preview 200 + ffprobe；F2 穿模检查；F3 3×2 安全区；F4 风关闭时静帧、打开时有变化；F5 不支持的 aspect 失败、少帧失败、mp4 丢失抛 CapabilityError。全部用 hevi 主 `.venv` 跑，**不加 `--noconftest`**，并设 `TMPDIR=/data/tmp/...`（/tmp 有用户配额，会报 Disk quota exceeded）。
3. 3O lint 用 `PYTHONPATH=$PWD /data/soffy/projects/hevi/.venv/bin/python scripts/ci/run_3o_v3_lint.py`，只允许基线那 4 项失败。
4. DONE 如实写，包括 F7 更正。
5. 主机 swap 已满：渲染一次只跑一个进程。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-scene3d；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 SCENE3D_DONE.md 最后一行写 DONE SCENE3D-R1B。
