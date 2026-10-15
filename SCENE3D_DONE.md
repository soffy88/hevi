# SCENE3D R1D 完工与独立核验记录

执行范围：仅 `/data/soffy/projects/hevi-scene3d` worktree；未改动主 checkout。环境使用 `JWT_SECRET=test-only`、`TMPDIR=/data/soffy/projects/hevi-scene3d/.tmp`、`PYTHONPATH=/data/soffy/projects/hevi-scene3d`。渲染脚本按单个进程顺序出片；没有调用付费 API。画面面向 2–6 岁幼儿，保持圆润、友好、颜色清晰，不引入惊吓或快速闪烁效果。

## R3 失败项逐条闭环

### C1 星海没有渲染出星星 — 已修复并用输出像素核验

`hevi/layer4_legacy/scene3d/template.py`：修复星点 shader 的 `gl_PointSize` GLSL 浮点字面量；采用 additive blending、明确的星点绘制顺序和不受背景层覆盖的深度设置；星场改为跟随相机路径的前方走廊，随镜头位移并带有限横向漂移，防止推进到后半段星场脱离视锥；提高前景星点尺寸/亮度。新测试 `tests/test_scene3d_r1d_visual.py` 对真实预设在 9:16 与 16:9、t=1.3/6.5/11.7s 抽帧，比较局部背景亮度并扣除行星投影区域，逐帧要求至少 40 个连通亮点；同时验证 540 档至少一颗半径 6 px 的星有对应亮像素、星点能从中心区域掠出画面，以及 `star_size` 增大后亮点数上升。以上 C1 像素测试全部通过。

生产 1080 档帧亦实测到大量高于局部背景的星点。以下为输出帧中以局部高光差 `ΔL >= 0.25` 检测、按 3–300 像素面积和包围框最大边不超过 40 px 过滤后的星状连通区域计数（这个快速计数未扣除行星投影，正式门槛由上述带行星投影遮罩的 pytest 执行）：

| 画幅 | 时间 | 实际帧路径 | 星状连通区域 | `max(ΔL)` |
|---|---:|---|---:|---:|
| 9:16 | 1.3s | `output/scene3d_r1d/star_sea_9x16/frames/frame_00040.png` | 591 | 0.516 |
| 9:16 | 6.5s | `output/scene3d_r1d/star_sea_9x16/frames/frame_00196.png` | 348 | 0.504 |
| 9:16 | 11.7s | `output/scene3d_r1d/star_sea_9x16/frames/frame_00352.png` | 160 | 0.513 |
| 16:9 | 1.3s | `output/scene3d_r1d/star_sea_16x9/frames/frame_00040.png` | 304 | 0.504 |
| 16:9 | 6.5s | `output/scene3d_r1d/star_sea_16x9/frames/frame_00196.png` | 256 | 0.513 |
| 16:9 | 11.7s | `output/scene3d_r1d/star_sea_16x9/frames/frame_00352.png` | 216 | 0.522 |

### C2 狐狸和麦田同色、天空灰白 — 已修复并实测颜色

`fox_in_wheat.json` 将天空顶部/底部和雾调整为蓝色；`template.py` 给狐狸橙色毛发使用不经色调映射、不过雾的专用材质，避免暖黄色被压成麦秆色。真实成片两画幅分别在 t=1.2/6.0/10.8s 抽样：狐狸橙色像素色相中位数 21.18°、平均饱和度 0.814–0.818；金黄色背景像素色相中位数 42.35°，和狐狸色相差约 21.17°；顶部 15% 天空平均饱和度在 0.257–0.317，天空色相中位数 203.29°–204.71°。三项均达到 R3 规定范围。

| 画幅 / 时间 | 抽帧 | 橙色像素数；色相中位数；平均饱和度 | 金黄色像素数；色相中位数 | 顶部天空平均饱和度；色相中位数 |
|---|---|---|---|---|
| 9:16 / 1.2s | `output/scene3d_r1d/fox_wheat_9x16/frames/frame_00037.png` | 62,320；21.18°；0.817 | 1,379,182；42.35° | 0.270；204.71° |
| 9:16 / 6.0s | `output/scene3d_r1d/fox_wheat_9x16/frames/frame_00181.png` | 67,062；21.18°；0.818 | 1,476,428；42.35° | 0.261；204.71° |
| 9:16 / 10.8s | `output/scene3d_r1d/fox_wheat_9x16/frames/frame_00325.png` | 62,528；21.18°；0.815 | 1,402,247；42.35° | 0.270；204.71° |
| 16:9 / 1.2s | `output/scene3d_r1d/fox_wheat_16x9/frames/frame_00037.png` | 35,612；21.18°；0.818 | 1,483,359；42.35° | 0.257；203.29° |
| 16:9 / 6.0s | `output/scene3d_r1d/fox_wheat_16x9/frames/frame_00181.png` | 39,974；21.18°；0.816 | 1,555,052；42.35° | 0.317；203.29° |
| 16:9 / 10.8s | `output/scene3d_r1d/fox_wheat_16x9/frames/frame_00325.png` | 36,259；21.18°；0.814 | 1,514,364；42.35° | 0.259；203.29° |

9:16 成片对应 R3 指定参考坐标的原始 RGB 样本（全分辨率坐标为 540 档坐标的两倍）：

| 时间 | 狐狸约额头 `(540,879)` | 麦田 `(540,499)` | 天空 `(540,159)` |
|---|---|---|---|
| 1.2s | RGB(240,115,41)，H=21.2°，S=0.83 | RGB(210,182,108)，H=42.4°，S=0.48 | RGB(159,194,219)，H=204.7°，S=0.27 |
| 6.0s | RGB(240,115,41)，H=21.2°，S=0.83 | RGB(210,182,107)，H=42.4°，S=0.49 | RGB(162,195,219)，H=204.7°，S=0.26 |
| 10.8s | RGB(240,115,41)，H=21.2°，S=0.83 | RGB(210,182,108)，H=42.4°，S=0.48 | RGB(159,194,219)，H=204.7°，S=0.27 |

### C3 样片分辨率 — 已修复并用 ffprobe 实测

` scripts/scene3d_r1d_render.py ` 固定交付分辨率为 1080 档，依预设画幅输出 1920×1080 或 1080×1920；每条成片均做 ffprobe codec、帧率、时长、帧数检查。下表的帧数来自 ffprobe `nb_read_frames`，每条均为 H.264、30/1 fps；`r1d_render_results.json` 中 `complete=true`、失败数为 0。完整视频同 seed 重渲的 MP4 SHA-256 完全一致，6/6 `deterministic_match=true`。每个条目另有 `contact_sheet_6f.png` 六帧拼图。

| 成片 | 分辨率 | ffprobe 时长 | 帧数 / `nb_read_frames` | SHA-256（原片 = 重渲） | 六帧拼图 |
|---|---|---:|---:|---|---|
| `planet_orbit_16x9` | 1920×1080 | 12.000s | 360 / 360 | `5f4d2bb9170d30fe91c3acfa3353a47c52d83bfa1838dde88556f1a7c6183cf8` | `output/scene3d_r1d/planet_orbit_16x9/contact_sheet_6f.png` |
| `planet_orbit_9x16` | 1080×1920 | 12.000s | 360 / 360 | `5c99f41ee717cd7a23eb7279c63fe2df8e1ba76923c4e0787fad3c3f49426add` | `output/scene3d_r1d/planet_orbit_9x16/contact_sheet_6f.png` |
| `fox_wheat_9x16` | 1080×1920 | 12.000s | 360 / 360 | `a176be2664503de948dad2cdb8969e0dac4334ce2166c168d4e21ee96ecd6f56` | `output/scene3d_r1d/fox_wheat_9x16/contact_sheet_6f.png` |
| `fox_wheat_16x9` | 1920×1080 | 12.000s | 360 / 360 | `fef949be0954e51f367f3bd1a5f2011eafe495f32b5188375d5c73cecafcc8ca` | `output/scene3d_r1d/fox_wheat_16x9/contact_sheet_6f.png` |
| `star_sea_9x16` | 1080×1920 | 13.000s | 390 / 390 | `0d3ee86bb4bd97c9f4f1b8eb7b9fc3c1d62ab8973f68808498e507a89ae981b9` | `output/scene3d_r1d/star_sea_9x16/contact_sheet_6f.png` |
| `star_sea_16x9` | 1920×1080 | 13.000s | 390 / 390 | `3d6e7038e8a2336393b6d76ebca4fc0e9ec3767e31758dba9799695ed2ca2dd9` | `output/scene3d_r1d/star_sea_16x9/contact_sheet_6f.png` |

机器可读的逐片证据：`output/scene3d_r1d/r1d_render_results.json` 与每条视频旁的 `r1d_metrics.json`。

## 验证结果

- 规定的完整 pytest 命令：`JWT_SECRET=test-only TMPDIR=/data/soffy/projects/hevi-scene3d/.tmp PYTHONPATH=/data/soffy/projects/hevi-scene3d /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_scene3d*.py` — **49 passed, 1 warning, 435.98s**。警告是 Starlette `TestClient` 使用 httpx 的弃用警告；没有测试失败。
- R3 的 C1/C2 新增真实像素验收测试包含在上面的 49 项内，通过；原有 45 项回归保留并通过。
- `scripts/ci/run_3o_v3_lint.py`：实际结果为 `3O_V3_LINT=FAIL`，9 项检查中 5 项 PASS，4 项为原任务说明确认的基线失败：`check_no_sibling_call.py`、`check_omodul_signature.py`、`check_enabled_pillars.py`、`check_oprim_keyword_only.py`。这些报错来自 `/data/soffy/projects/hevi/.venv/lib/python3.14/site-packages/` 下的已安装包；本次没有修改或触碰它们。
- 语法检查与 `git diff --check` 通过。六条成片均完成渲染、ffprobe 检查、六帧拼图、全视频 SHA-256 重渲一致性检查。

## 本次代码变更

- `hevi/layer4_legacy/scene3d/template.py`：可见星点 shader / blending / 相机前方星场与掠过运动；清晰橙色狐狸材质。
- `hevi/layer4_legacy/scene3d/examples/fox_in_wheat.json`：更明确的蓝色天空与雾。
- `tests/test_scene3d_r1d_visual.py`：实际渲染像素阈值测试，覆盖两画幅、多个时间点、星点大小回归、近景大星与掠过效果、狐狸/麦田色相区分和天空颜色。
- `scripts/scene3d_r1d_render.py`：1080 档输出与严格的全视频同 seed SHA-256 判定；采样帧验证不会被误报为完整视频确定性通过。

DONE SCENE3D-R1D
