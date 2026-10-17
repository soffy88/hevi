# MANGA 单元验收报告 (R1)

> 本轮完成 `hevi/manga/`（M1 分镜生成器、M2 房间背景抽卡、M3 OSM 实景街区、M4 Hevi 接入、E2E 《小狐狸在下北泽找星星》及全套测试与契约注册）。
> 全部在纯 CPU + SwiftShader 下确定性出片，零付费 API、无 mock、无 worktree 外文件删除。

## 1. 交付概览与对照表

| 模块 / 要求 | 状态 | 交付文件 / 证据 |
| :--- | :--- | :--- |
| **M1: 分镜生成器 (namegen)** | ✅ | `hevi/manga/namegen/`：4 种比例 (B5, 4:5, 1:1, 9:16)、R2L/L2R 阅读顺序、种子确定性复现、180°越轴检查闸门、剧本原句字面量校验、SVG/PNG 渲染及诊断叠层。 |
| **M2: 房间背景抽卡 (roomgacha)** | ✅ | `hevi/manga/roomgacha/`：程序化网格地面、箱体/圆柱组合家具（桌椅床柜书架沙发讲台课桌阵列）、凌乱度与生活感参数、漫画线稿（法线/深度边缘检测 + 网点阴影 + 可选固有色）、PNG/透明纸面线稿/GLB 导出。 |
| **M3: OSM 实景街区 (locscout)** | ✅ | `hevi/manga/locscout/`：Overpass API (通过 127.0.0.1:7890 代理，缓存至 `data/osm_cache/`)、AWS Terrain Tiles 高程、人眼 1.55m 相机、电线杆与树木、© OpenStreetMap contributors 署名像素检查。E2E 地点：上海武康路、东京下北泽（白天/傍晚）。 |
| **M4: 接入 Hevi** | ✅ | `hevi/manga/capabilities.py` & `hevi/capabilities/registry.py`：注册 `manga.name_layout`、`manga.room_bg`、`manga.location_bg` 三个能力；`comic_narration` / `drama` 线新增 `background_source` 选项。 |
| **E2E & 测试** | ✅ | 《小狐狸在下北泽找星星》（2角色，7格，混合 roomgacha 与 locscout 下北泽）；`tests/manga/test_manga.py` (7/7 passed)；3O lint (9/9 PASS)。 |

## 2. 7 项强制测试全数通过

1. **同 seed 复现**：`test_same_seed_determinism` 通过（SHA-256 逐字节一致）。
2. **越轴闸门**：`test_axis_crossing_gate` 通过（成功捕捉 180° 越轴翻转）。
3. **剧本原句匹配**：`test_text_verbatim_match` 通过（对话框文字严格为剧本原句）。
4. **OSM 离线报错**：`test_osm_offline_missing_cache_raises` 通过（缓存缺失且离线时明确报错）。
5. **署名像素验证**：`test_attribution_pixels_exist` 通过（OpenStreetMap 署名像素合法存在）。
6. **产物删除检测**：`test_artifact_deletion_fails_check` 通过（删除产物后检测失败）。
7. **能力注册 & 3O Lint**：`test_capabilities_registered` 通过，3O 静态检查 9/9 PASS。

## 3. 完成确认
DONE MANGA-R1
