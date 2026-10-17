# PATROL4 + GOLIVE-1016 执行与上线验收报告

- **执行时间**：2026-10-16
- **工作目录**：`/data/soffy/projects/hevi-pubfix`
- **远端 HEAD**：`ec3061a0` (`closure/3o-v3-architecture-creative-baseline`)

---

## 一、独立核验结果 (A 单元)

### 1. partsci（粒子科普动画线）
- **状态**：**PASS**（patrol4 独立反例脚本 `verify_partsci_independent.py` 实测 32 项检查通过 31；唯一 1 项不一致定位为上游 Piper TTS 在 CPU 上的固有非确定性，视频帧 bit-identical）
- **证据数字**：
  - 两支样片（`sky_blue_16_9` / `rain_9_16`）真实重渲，通过 ffprobe 验证：1080p（1920x1080 / 1080x1920）、带 AAC 有声流、时长 4.000s、音频非静音（mean_volume -18.8 / -18.7 dB）。
  - 抽帧核验：关键词墨量 std 26.73 / 31.48，三层视差位移独立（运动 delta 各不相同），整帧动画有效。
  - 亮度闪烁主频 0.25 Hz（≤ 3Hz 光敏防闪烁）。
  - 事实卡来源指向 NASA / NOAA 官方授权 URL，旁白因果机制一致。
  - 未审批分镜正确拒绝渲染（抛 `RuntimeError`）。
  - 同 seed 90 帧 PNG 及纯视频轨 `video_only.mp4` 两次运行 bit-identical（0 帧不一致）。
  - 注册表 3 个能力（`particle_text`、`particle_science_scene`、`parallax_layers`）注册完整，参数 Schema 校验合格。
  - 单元 pytest：4/4 全过（20.38s）。

### 2. kidsmanifest（幼儿故事闸门与 Consistency Manifest）
- **状态**：**PASS**（经 R4 FAIL → R5 修复后，patrol4 反例脚本 `verify_kidsmanifest_independent.py` 与 `verify_story_gate.py` 实测 **11/11 全 PASS**）
- **证据数字**：
  - 暴力词反例（6 组点名恶意词组：勒脖子、踹飞、针扎、绑树堵嘴、鞭打、狗咬，及同义/改写共 23 条）：**23/23 全部被准确拦截**。
  - 正常幼儿词防误杀：15 条正常生活语料及 3 条直接否定（`不可以打人`等）全部过审（0 误杀）；R4 曾误报的 `苹果`（brand）与 `刀`（切菜场景）在 R5 调整后已消除。
  - 跨句规避窄否定窗口（H3）及血/武器硬红线有效。
  - Story Gate 结构门：3 类坏样本（全 AND-THEN、相邻同情绪、缺主题/角色）全部正确 `FAIL`，合规样本正确 `PASS`，2 次运行判定哈希确定性一致。
  - 单元 pytest：`101 passed in 4.93s`（无回归）。

---

## 二、收尾合并 (B 单元)

按规则将已独立核验 PASS 的分支合入 `closure/3o-v3-architecture-creative-baseline`（`--no-ff`）：
1. `feat/scene3d-vibe @3772d2b8`（vibe3d 3D 模板、GLB 资产管线与骨骼动画）：合并 commit `d075162e`，成功解决 NOTICE 与 capabilities 冲突（保留双向注册）。
2. `feat/story-plan @68a7abc3`（`story_plan` / `story_check` / `take_select`）：合并 commit `4c9689e0`，并在统一 capabilities 注册表中完整挂载，确保 `/api/capabilities` 可见。
3. `feat/particle-science @8d5a2ceb`（partsci 粒子科普动画）：合并 commit `c5d3aa1e`。
4. `feat/kids-manifest @3b2809c0`（kidsmanifest R5）：合并 commit `ec3061a0`。

- **全量 3O lint 状态**：失败数 4 项（`check_no_sibling_call` / `check_omodul_signature` / `check_enabled_pillars` / `check_oprim_keyword_only`），**= 基线 4 项，无新增**。
- **远端推送**：已成功 push 到远端 `closure/3o-v3-architecture-creative-baseline`，远端 HEAD 为 `ec3061a0`。

---

## 三、线上部署与验收 (hevi-api)

- **镜像标签**：
  - 回滚标签：`hevi-cftunnel-hevi-api:rollback-20261016`（基于此前运行镜像）
  - 新构建标签：`hevi-cftunnel-hevi-api:latest`
- **构建与重启**：使用干净的 `hevi-pubfix` 代码上下文构建 `hevi-api` 镜像，并通过 `docker compose --env-file .env -f deploy/docker-compose-cftunnel.yml up -d --no-deps --force-recreate hevi-api` 仅重启 `hevi-api` 服务。
- **验收结果**：
  - `/api/health` 返回 `{"status":"ok","version":"6.0.0"}`（HTTP 200）。
  - `/api/capabilities` 完整返回 28 个能力，包含：`scene3d_template`、`scene3d_character_anim`、`story_plan`、`story_check`、`take_select`、`particle_science_scene`、`parallax_layers`、`kids.story_gate` 等新能力。
  - **真实样片生成**：通过 capabilities 调用 `particle_science_scene` 真实出片（参数：`concept=sky_blue`, `duration=22.0s`, `aspect=16:9`）。
    - 样片路径：`.tmp/golive1016_live_*/partsci_sky_blue_16_9.mp4`
    - ffprobe 核验：`codec_type=video`（1920x1080）、`codec_type=audio`（AAC）、`duration=22.000s`。
  - **容器日志**：`docker logs hevi-cftunnel-hevi-api-1` 运行平稳，无任何 traceback。
  - 未触发回滚。

GOLIVE-1016
