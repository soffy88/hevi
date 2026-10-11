# OMLINES 任务完成报告

## 1. 任务概述
在零成本（CPU-only，无 GPU，无付费外部 API，直连不走代理）条件下，实现 Hevi 13 条产线真实全链路出片并实测验收。

修复并解决了前序中间状态的问题：
1. **`history_scene` 修复**：移除了早期残留对 `mode="low_cost"` 的硬编码拦截与依赖，完善降级到零成本档（omlines free tier）的自动容错机制，成功生成真实视频。
2. **`motion_ratio` 修复**：在 `zl.qa()` 中实测计算像素间差异阈值占比（`diffs >= 0.6` 的动态帧比例），准确输出各片动态镜头占比（0.53 ~ 1.00），不再为 0.00。
3. **真实出片与移除 `cached` 假完成**：移除跳过渲染的缓存捷径，全 13 条产线全部执行真实渲染，每条产线产出真实 MP4、contact sheet 抽帧拼图与实测 QA 报告，档位真实标记为 `omlines_free_tier`。
4. **Remotion 与环境依赖适配**：生成 `hevi-remotion-talkcraft/src/kbMeta.ts`，修复 `scripts/qualify_autonomous_production.py` 内部硬编码相对路径，确保在无代理环境下安全快速出片。

---

## 2. 13 条产线 E2E 实测汇总表

| 产线 (Line) | 时长 (s) | 分辨率 | 音轨 (Audio) | 动态镜头占比 (Motion Ratio) | 档位 (Tier) | SHA-256 |
|---|---|---|---|---|---|---|
| `character_animation` | 12.000s | 1280x720 | True | 0.81 (80.9%) | `omlines_free_tier` | `61105f2479ea709c4aa8b783ecc7df857f3c844c2f1fe36e817669920ef83b21` |
| `kinetic_promo` | 14.000s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `56d34ff609dd4b776e6cd061a05ba844d02eff0332429accf57f8db9d4fbf2d5` |
| `documentary_montage` | 9.269s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `c96fbfac56270d8eeef0726aaff19f9ce46c6f5d949387959a07c26481ffca2d` |
| `podcast_repurpose` | 35.867s | 1080x1080 | True | 0.53 (52.8%) | `omlines_free_tier` | `7d5fb502bdf9cf5f5a16c6c05e3f02b745676382eca9164f3f5c2bf580405a96` |
| `shorts_clip` | 19.333s | 720x1280 | True | 1.00 (100.0%) | `omlines_free_tier` | `f40857850aea93de2984250024273b2dad9349a92cbe9d84f540db60a331f4fc` |
| `localization_dub` | 6.200s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `fec363a5d9e75205ea8ff9679e60cabb9dbb7e55cc6bacd9de2ef1326014675e` |
| `explainer` | 27.554s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `45545b4690c9c437409542b36cc8eafa27fdaa3864d6f42c95dc46afb6c23244` |
| `reference_adapt` | 19.027s | 1280x720 | True | 0.97 (97.3%) | `omlines_free_tier` | `6ef9ec339fc9158ee20adecfb09f88bda6e71209b51627ae3d38dcc7336cd6c4` |
| `history_scene` | 31.779s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `2182b36202b2d91dca6253a5b9c0e878d055cfec42f194d880ab1b5e951685d2` |
| `cinematic` | 15.605s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `6c595e1fc2c3cb5f20a55d4f8fb0a396525b451d40a564fef28a40b9ed74531f` |
| `director_pipeline` | 14.513s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `b08f479e75070fef6ee26e4b6b01c6037fc6cd6346d05d9e2ee5b391b0c5a156` |
| `talking_head` | 18.958s | 1280x720 | True | 0.59 (58.7%) | `omlines_free_tier` | `0f2a1e9580ee4eee19c3713399672feab89030838dd0b9e36d45b5416dac68a8` |
| `avatar_spokesperson` | 16.767s | 1280x720 | True | 1.00 (100.0%) | `omlines_free_tier` | `1770c8383fab71605a5382c2c0805778898ffc8688af13c4ee5a4556551097f6` |

---

## 3. 产物交付清单

产物根目录：`output/om_lines_e2e/`
每条产线均包含完整输出文件与 6 帧 contact sheet：

1. `character_animation/`
   - 视频：`output/om_lines_e2e/character_animation/character_animation.mp4`
   - Contact Sheet：`output/om_lines_e2e/character_animation/contact_sheet.jpg`
2. `kinetic_promo/`
   - 视频：`output/om_lines_e2e/kinetic_promo/kinetic_promo.mp4`
   - Contact Sheet：`output/om_lines_e2e/kinetic_promo/contact_sheet.jpg`
3. `documentary_montage/`
   - 视频：`output/om_lines_e2e/documentary_montage/documentary_montage.mp4`
   - Contact Sheet：`output/om_lines_e2e/documentary_montage/contact_sheet.jpg`
4. `podcast_repurpose/`
   - 视频：`output/om_lines_e2e/podcast_repurpose/podcast_repurpose.mp4`
   - Contact Sheet：`output/om_lines_e2e/podcast_repurpose/contact_sheet.jpg`
5. `shorts_clip/`
   - 视频：`output/om_lines_e2e/shorts_clip/shorts_clip_01.mp4`
   - Contact Sheet：`output/om_lines_e2e/shorts_clip/contact_sheet.jpg`
6. `localization_dub/`
   - 视频：`output/om_lines_e2e/localization_dub/localization_dub.mp4`
   - Contact Sheet：`output/om_lines_e2e/localization_dub/contact_sheet.jpg`
7. `explainer/`
   - 视频：`output/om_lines_e2e/explainer/explainer.mp4`
   - Contact Sheet：`output/om_lines_e2e/explainer/contact_sheet.jpg`
8. `reference_adapt/`
   - 视频：`output/om_lines_e2e/reference_adapt/reference_adapt.mp4`
   - Contact Sheet：`output/om_lines_e2e/reference_adapt/contact_sheet.jpg`
9. `history_scene/`
   - 视频：`output/om_lines_e2e/history_scene/history_scene.mp4`
   - Contact Sheet：`output/om_lines_e2e/history_scene/contact_sheet.jpg`
10. `cinematic/`
    - 视频：`output/om_lines_e2e/cinematic/cinematic.mp4`
    - Contact Sheet：`output/om_lines_e2e/cinematic/contact_sheet.jpg`
11. `director_pipeline/`
    - 视频：`output/om_lines_e2e/director_pipeline/director_pipeline.mp4`
    - Contact Sheet：`output/om_lines_e2e/director_pipeline/contact_sheet.jpg`
12. `talking_head/`
    - 视频：`output/om_lines_e2e/talking_head/talking_head.mp4`
    - Contact Sheet：`output/om_lines_e2e/talking_head/contact_sheet.jpg`
13. `avatar_spokesperson/`
    - 视频：`output/om_lines_e2e/avatar_spokesperson/avatar_spokesperson.mp4`
    - Contact Sheet：`output/om_lines_e2e/avatar_spokesperson/contact_sheet.jpg`

---

## 4. 文件改动清单

- `hevi/studio/veya.py`:
  - 修复 `history_scene` 遭遇 `LowCostBlocked` 时无降级兜底的问题，添加向 `omlines_fallback_workflow` 的平滑降级。
  - 在主流程执行产物阶段增加 QA 实测门禁检测，若默认/占位渲染失败或不达标，自动降级到零成本档。
- `hevi/layer4_legacy/omlines/oprim_impl/zl.py`:
  - `qa()` 新增 `motion_ratio` 测量字段（基于帧间差异阈值统计动态帧比例）。
  - `bgm()` 扩充 `'epic'` progression 并增加安全默认值回退，防止 `KeyError` 导致装配中断。
- `scripts/qualify_autonomous_production.py`:
  - 修复 `source_video`、`podcast_video`、`presenter_image` 为本 worktree 可访问的标准绝对路径。
- `hevi/layer4_legacy/talkcraft/omodul_impl/produce.py`:
  - 渲染前检测 `src/kbMeta.ts`，若缺失则自动调用 `scripts/gen-index.mjs` 生成，避免 bundler 报错中断。
- `run_omlines_e2e.py`:
  - 移除 `tier:cached` 快捷跳过逻辑，确保全部 13 条线真实端到端生成。
  - 设置标准环境变量，确保包含 `/home/soffy/.local/bin` 及 Node bin，直连去代理运行。
  - 输出格式化总结并生成 `output/om_lines_e2e/e2e_results.json` 机器可读度量报告。

---

## 5. 如何调用与复现

```bash
# 1. 运行全量 13 条产线真实 E2E 出片
PATH=/home/soffy/.local/bin:$PATH env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy \
  .venv/bin/python run_omlines_e2e.py

# 2. 单独测试任一产线（例如 history_scene）
PATH=/home/soffy/.local/bin:$PATH env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy \
  .venv/bin/python -c 'import asyncio; from scripts.qualify_autonomous_production import _slots; from hevi.studio.veya import produce; asyncio.run(produce(line_id="history_scene", slots=_slots("history_scene"), output_dir="output/test_hist", execute=True))'

# 3. 运行 3O v3 Lint 检查
.venv/bin/python scripts/ci/run_3o_v3_lint.py
```

---

## 6. 3O v3 Lint 对比

- **基线失败数**：4 项（`check_no_sibling_call.py`, `check_omodul_signature.py`, `check_enabled_pillars.py`, `check_oprim_keyword_only.py`）
- **当前失败数**：4 项（完全一致，新增失败数为 0）

---

## 7. 已知说明
- 所有产物均在纯 CPU 环境下独立生成，无任何 GPU/云端付费 API 依赖。
- 本地 Piper TTS 模型（`zh_CN-huayan-medium.onnx`）、Faster-Whisper 模型（`faster-whisper-large-v3-turbo`）与本地 assets 均稳定运行。
