# VIBE3D-R1 完工与独立核验报告

## 做了什么

1. **方法内化 (§A)**：通读花叔《3D Vibe Coding 手册》（v260914c），提炼成 `docs/SCENE3D_VIBE_RULES.md`（含 §03 验收/朝向、§04 减面下限表、§05 语义分件、§06 绑骨/动画/朝向惯例、§17 批量流水线、附录B 踩坑索引），只留对 Hevi CPU (SwiftShader) 渲染有实际操作意义的条目，每条注明章节。
2. **GLB 资产管线与管线验证 (§B)**：实现 `hevi.scene3d.assets_pipeline`（纯 Python GLB 解析与校验 + gltf-transform 减面/降贴图到 512 + 内容寻址缓存 + 资产清单 JSON `assets/scene3d/manifest.json` + 署名 `ATTRIBUTION.md` 与 NOTICE）。对 8 件源资产（包 03 / 包 05，全数 ≤2MB）实测减面与降档。
3. **角色动画驱动 (§C)**：接入包 05 带 41 关节骨骼与行走动画的 GLB，通过 `SkeletonUtils.clone()` 与 `AnimationMixer` 按确定性时间步（`window.__setTime(t)`）步进，支持相位错开、切位移轨只留旋转，并使用 measured glTF POSITION bbox 规避 SkinnedMesh 的 Box3 缓存陷阱。实测肢体位移与地面贴合。
4. **场景模板与相机路径预设 (§D)**：实现 `little_planet`（小星球）、`town_street`（小镇街道，含巴黎 512 建筑、树木、街具与步行角色）、`playground`（游乐园一角）3 个幼儿向、非写实、暖色模板；支持 `orbit`、`push_in`、`follow` 相机路径预设。
5. **能力层与导演层接入 (§E)**：在统一注册表注册 `scene3d_asset_import`、`scene3d_template`、`scene3d_character_anim` 三大能力（`GET /api/capabilities` 可见，非法参数返回 422），串联 `kids_gate` 质量闸门与布局安全区门。ShotSpec 可通过能力绑定直接组装镜头。
6. **样片与对照 (§F)**：使用 `scripts/vibe3d_samples.py` 产出 2 支幼儿 3D 小短片（1080p，16:9 与 9:16 各一，配 CosyVoice 中文旁白与 SRT 字幕、单进程 CPU 渲染），并产出 6 帧对比拼图 `audit/vibe3d/sample_comparison.png` 与 `audit/vibe3d/samples_metrics.json`。
7. **真实测试与 lint (§G)**：运行 pytest 真实测试（无 mock 渲染），全部 38 个 vibe3d / template / pipeline 测试通过。3O lint 失败数为 4，未超过基线。

---

## 测试命令与实测数据

- **测试命令**：
  `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vibe3d_pipeline.py tests/test_vibe3d_templates.py tests/test_scene3d_r2.py`
  - 结果：**38 passed**（约 40s）。
- **资产减面前后面数与哈希（部分代表）**：
  - `building-03-boulangerie`：16,696 → 7,504 三角面（ratio 0.45），贴图 1024² → 512²，体积 568 KiB → 388 KiB。
  - `car-01-taxi`：18,083 → 4,451 三角面（ratio 0.25），贴图 1024² → 512²，体积 488 KiB → 246 KiB。
  - `pedestrian-01-walk-anim`：19,594 → 19,594 三角面（绑骨网格不减面），贴图 1024² → 512²，体积 1,353 KiB → 876 KiB。
- **样片实测（1080p 30fps，CPU SwiftShader）**：
  - `planet_walk_16x9`（14.0s，420 帧）：单帧渲染耗时 0.188s/frame，SHA-256 `b33d453962dc6f52`。
  - `town_walk_9x16`（14.0s，420 帧）：单帧渲染耗时 0.192s/frame，SHA-256 记录于 metrics.json。
- **3O Lint 检查**：
  - 失败数为 4（精确等于基线 4：`check_no_sibling_call`, `check_omodul_signature`, `check_enabled_pillars`, `check_oprim_keyword_only`）。

---

## 样片路径

- 16:9 小星球短片：`audit/vibe3d/samples/planet_walk_16x9/planet_walk_16x9.mp4`
- 9:16 小镇短片：`audit/vibe3d/samples/town_walk_9x16/town_walk_9x16.mp4`
- 对比拼图：`audit/vibe3d/sample_comparison.png`
- 样片指标：`audit/vibe3d/samples_metrics.json`

---

## 已知限制

1. SwiftShader 下离线渲染单帧约需 0.18–0.20 秒（1080p），渲染长片需预留计算时间。
2. 动画轨道仅提取基础行走步态（`preset:biped:walk`），未接入情绪/对话动作混合树。

DONE VIBE3D-R1
