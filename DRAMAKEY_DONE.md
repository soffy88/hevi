# DRAMAKEY 交付报告 (DRAMAKEY_DONE)

## 1. 任务概述与完成情况

- **任务名称**: DRAMAKEY：CPU 关键帧引擎 + 小说/剧本 → 真关键帧 → 配音字幕成片（ViMax 思路，clean-room）
- **Worktree**: `/data/soffy/projects/hevi-dramakey`
- **分支**: `feat/dramakey-3o`
- **基线 Commit**: `98e216af`
- **完成状态**: **全部完成（真实推理出片，零 mock/占位）**

---

## 2. 完成工作详述

### A. 关键帧引擎 oprim (`hevi/layer4_legacy/keyframe/oprim_impl/`, shim `hevi/keyframe/oprim/`)
1. **抽象接口 `KeyframeEngine` & `KeyframeResult`**:
   - `contracts.py`: 定义 `KeyframeEngine(ABC)` 与 `KeyframeResult(path, seed, engine, model, sec, rss_mb, width, height, steps)`。
2. **核心引擎实现**:
   - `sdturbo_cpu`: 默认 CPU 关键帧引擎，单例懒加载，加载本地权重 `/data/soffy/models/ms/models/AI-ModelScope--sd-turbo` + TAESD 高速解码器 `/data/soffy/models/ms/models/madebyollin--taesd`。推理时自动获取全机文件锁 `/tmp/hevi_cpu_render.lock`（互斥保护 DRAMAKEY 与 COMICNARR 并发）。实测单图耗时 ~6-7s，峰值内存 ~6.9-7.4 GB（安全受控于 10GB unit 上限）。
   - `fake`: 仅供单元测试使用，生成合成 PIL 测试图，E2E 验收路径严格断言禁止。
   - `cloud_stub`: 云端插槽，默认 `available() == False`，严格遵循零成本原则不进行远程付费调用。
   - `sdxlturbo_cpu`: 高画质 CPU 插槽，带 `available()` 内存门禁（需系统可用内存 ≥18 GB，否则禁用）。
3. **注册表与解析逻辑**:
   - `registry.py`: `get_engine()`, `resolve_keyframe_engine()`, `register_engine()`。支持通过 dict/对象/环境变量 `HEVI_KEYFRAME_ENGINE` 解析。
   - 接口契约规范已完整记录于 `docs/KEYFRAME-ENGINE.md`。
4. **提示词翻译与改写 oskill**:
   - `prompt_translator.py`: `zh_shot_to_sd_prompt(shot, character_cards, style)`。结合本地/免费 omniroute 尝试及仙侠/古代题材确定性规则字典，原样注入角色卡锁定的固定外观描述（英文 tokens）。

### B. 真实择优 + 一致性 Gate (替换假 image_score)
5. **像素级综合质量打分 `image_score.py`**:
   - `compute_clip_similarity`: 使用本地 OpenCLIP ViT-B-32 (`/home/soffy/models/open_clip/open_clip_model.safetensors`) 计算文本与图像视觉语义相似度。
   - `compute_laplacian_sharpness`: 基于拉普拉斯算子方差计算边缘清晰度。
   - `compute_exposure_score`: 曝光平衡直方图打分。
   - `detect_bad_image`: 检测全黑、全白、纯单色坏图（空间各通道标准差校验）。
   - 双候选择优（ViMax 思路）：每镜头生成两个不同 seed 候选，择优胜出，未入选候选图保留落盘（命名含 `loser`）。
6. **人脸一致性门禁 `face_gate.py`**:
   - 基于 OpenCV DNN (YuNet 人脸检测 + SFace 人脸识别，模型位于 `/data/soffy/models/opencv/`)。
   - 角色定妆照生成：每个角色先用 3 个 seed 生成定妆候选，挑选检测到最优人脸者提取 128 维参考人脸特征向量并落盘。
   - 镜头人脸余弦相似度校验：低于阈值（实测设定 0.30-0.35）触发换 seed 重试（最多 2 次），耗尽标记 `identity_weak`，远景/无脸镜头自动跳过 gate。

### C. 小说规划能力补强 (script2video)
7. **章节标题切分与长章切块**:
   - `novel_split.py`: 升级 `split_chapters`，正则识别 `第[0-9一二...]回/章/节/卷/幕` 及 Markdown 标题；超长章节自动按长度二次分块。
8. **角色合并与角色卡生成**:
   - `character_fuse.py`: 增加别名判定 `are_aliases`（如王生/王七/书生）、合并特征，生成符合规范的 `CharacterCard` 结构，落盘 `characters.json`。
9. **目标时长镜头预算**:
   - `shot_budget.py`: `shot_budget_for_duration(target_duration_s, min_shot_s=3.0, max_shot_s=5.0)`。

### D. 从“只出 JSON”到真实成片 (omodul)
10. **全流程视频渲染引擎 `video_render.py`**:
    - Ken Burns 镜头运动：推（push）、拉（pull）、左摇（pan_l）、右摇（pan_r）动态缩放裁剪，25fps 逐帧运动。
    - 配音（Piper TTS）：使用中文模型 `zh_CN-huayan-medium.onnx`，区分角色语速与对白，消除边缘静音，精确测算音轨时长。
    - 字幕生成与烧录：生成对齐的 `subtitles.srt`，采用文泉驿正黑（WenQuanYi Zen Hei）字体清晰硬字幕烧录。
    - MP4 拼接：1080×1920 竖屏输出，视频画面与音轨无缝合成。
11. **工作流入口接通**:
    - `hevi/production/novel2video_workflow.py`: 增加 `config.render` 开关（默认 False 保证旧测试 100% 兼容通过；True 则调用渲染流水线）。
    - `hevi/production/script2video_kernel_workflow.py`: 增加 `config.render` 开关。

---

## 3. 修改与新增文件清单

```
新增文件:
├── docs/KEYFRAME-ENGINE.md                                    # 引擎契约规范
├── hevi/keyframe/__init__.py                                 # Keyframe 顶层包
├── hevi/keyframe/oprim/__init__.py                           # Shim: keyframe oprim
├── hevi/keyframe/oskill/__init__.py                          # Shim: keyframe oskill
├── hevi/keyframe/omodul/__init__.py                          # Shim: keyframe omodul
├── hevi/layer4_legacy/keyframe/__init__.py                   # Layer4 keyframe 顶层
├── hevi/layer4_legacy/keyframe/oprim_impl/__init__.py        # oprim 导出
├── hevi/layer4_legacy/keyframe/oprim_impl/contracts.py       # KeyframeEngine 契约
├── hevi/layer4_legacy/keyframe/oprim_impl/lock.py            # cpu_render_lock 互斥锁
├── hevi/layer4_legacy/keyframe/oprim_impl/sdturbo_engine.py  # SD-Turbo + TAESD CPU 引擎
├── hevi/layer4_legacy/keyframe/oprim_impl/fake_engine.py     # 快速测试 Fake 引擎
├── hevi/layer4_legacy/keyframe/oprim_impl/cloud_stub_engine.py # 云端插槽
├── hevi/layer4_legacy/keyframe/oprim_impl/registry.py        # 引擎注册表
├── hevi/layer4_legacy/keyframe/oprim_impl/character_card.py  # CharacterCard 数据契约
├── hevi/layer4_legacy/keyframe/oprim_impl/image_score.py     # 像素级 CLIP/清晰度/坏图打分
├── hevi/layer4_legacy/keyframe/oprim_impl/face_gate.py       # YuNet + SFace 人脸一致性门禁
├── hevi/layer4_legacy/keyframe/oskill_impl/__init__.py       # oskill 导出
├── hevi/layer4_legacy/keyframe/oskill_impl/prompt_translator.py # 中译英提示词 + 规则字典
├── hevi/layer4_legacy/keyframe/omodul_impl/__init__.py       # omodul 导出
├── hevi/layer4_legacy/keyframe/omodul_impl/video_render.py   # 视频渲染、TTS、字幕、拼装流水线
├── hevi/layer4_legacy/script2video/oskill_impl/shot_budget.py # 时长转镜头预算
├── scripts/e2e/dramakey_e2e.py                               # E2E 真实验收脚本
└── tests/test_dramakey_pipeline.py                           # 快速单元测试 (<30s)

修改文件:
├── DRAMAKEY_PROGRESS.md                                      # 任务进度跟踪
├── hevi/director/planner.py                                  # 解除循环引用
├── hevi/layer4_legacy/script2video/omodul_impl/fuse.py       # 延迟导入，解除循环引用
├── hevi/layer4_legacy/script2video/oprim_impl/character_fuse.py # 增加角色别名合并与落盘
├── hevi/layer4_legacy/script2video/oprim_impl/image_score.py # 兼容保留旧函数，导出新像素打分
├── hevi/layer4_legacy/script2video/oprim_impl/novel_split.py # 增加第X章/回/节切分及长章切块
├── hevi/layer4_legacy/script2video/oskill_impl/__init__.py   # 导出 shot_budget_for_duration
├── hevi/production/novel2video_workflow.py                   # 接入 render=True 路径
└── hevi/production/script2video_kernel_workflow.py           # 接入 render=True 路径
```

---

## 4. 如何调用 (API & CLI)

### Python API 示例 1: 小说/文本直接成片 (`novel2video_workflow`)
```python
import asyncio
from pathlib import Path
from hevi.production.novel2video_workflow import Novel2VideoConfig, Novel2VideoInput, novel2video_workflow

async def main():
    text = "第一回 崂山问道\n王生少慕仙术，负笈往游崂山。见一道士坐蒲团上，白发垂领，神光爽迈..."
    config = Novel2VideoConfig(
        render=True,             # 开启真视频渲染
        engine="sdturbo_cpu",    # CPU 关键帧引擎
        target_duration_s=60.0,  # 目标时长 60 秒
        target_width=1080,
        target_height=1920,      # 竖屏 9:16
    )
    result = await novel2video_workflow(
        config=config,
        input_data=Novel2VideoInput(novel_text=text),
        output_dir=Path("output/my_novel_video"),
    )
    print("成片路径:", result["final_mp4"])
    print("QA报告:", result["qa_path"])

asyncio.run(main())
```

### Python API 示例 2: 分镜列表直接渲染 (`render_dramakey_pipeline`)
```python
from pathlib import Path
from hevi.layer4_legacy.keyframe.omodul_impl.video_render import RenderConfig, render_dramakey_pipeline

shots = [
    {
        "idx": 0,
        "text": "王生至崂山，见一观宇甚幽。",
        "visual_desc": "青年书生站在道观门前，云雾缭绕",
        "visible_chars": ["王生"],
        "camera_move": "push",
    },
]
result = render_dramakey_pipeline(
    shots=shots,
    output_dir=Path("output/shots_run"),
    config=RenderConfig(engine="sdturbo_cpu"),
)
```

### CLI 执行验收脚本
```bash
.venv/bin/python scripts/e2e/dramakey_e2e.py
```

---

## 5. E2E 真实验收产物与 QA 指标摘要

验收脚本 `scripts/e2e/dramakey_e2e.py` 执行并产出：

### 产物 A: 崂山道士全流程成片 (Novel2Video 路径)
- **目录**: `output/dramakey_e2e/novel_20261011_113753/`
- **成片文件**: `output/dramakey_e2e/novel_20261011_113753/final.mp4`
- **QA 判定 (`qa.json`)**: `passed: true`
- **实测规格 (ffprobe)**:
  - 时长: `73.76 秒`（完全落入目标 60-90 秒范围）
  - 分辨率: `1080 x 1920`（标准竖屏）
  - 帧率: `25.0 fps`
  - 编码: `h264`
  - 音频: `aac, 48000 Hz, stereo`
  - MP4 SHA256: `d3bdacb9f63ae385003a18e2388df7d2aa5342b71e7b973aeb612071aa185586`
- **音频响度 (volumedetect)**:
  - `mean_volume`: `-20.20 dB`（远优于 > -45 dB 门槛要求）
  - `max_volume`: `-2.70 dB`（无静音、无爆音）
- **动态帧差 (6 帧抽检)**:
  - 抽样帧间平均绝对差异: `121.29`（远高于静态判定阈值，证明非静帧）
  - Contact sheet 产物: `output/dramakey_e2e/novel_20261011_113753/contact_sheet.jpg`
- **分镜与关键帧**:
  - 镜头数: `14 镜`
  - 关键帧总数: `76 张`（含 14 张胜出定稿、未选中的第二候选图 `loser`、以及人脸 gate 重试候选）
- **角色一致性 Gate 实测结果**:
  - “老道长” SFace 余弦相似度分布：0.3323, 0.4406, 0.4819, 0.5828，均通过阈值；
  - “王生” 初选相似度较低时自动触发 2 次换 seed 重生，择优录取，耗尽后标记 `identity_weak` 继续推进成片。
- **性能与开销 (`record.json`)**:
  - 模型: `sd-turbo` (fp16以fp32加载) + `madebyollin--taesd`
  - 关键帧总出图耗时: `474.32 秒`（76 张图）
  - 进程峰值内存: `6898.0 MB` (6.9 GB，严格受控在 10GB 上限内)

### 产物 B: 30 秒剧本小样 (Script2Video 路径)
- **目录**: `output/script2video_e2e/script_20261011_113753/`
- **成片文件**: `output/script2video_e2e/script_20261011_113753/final.mp4`
- **QA 判定 (`qa.json`)**: `passed: true`
- **实测规格**:
  - 时长: `31.96 秒`
  - 分辨率: `1080 x 1920`
  - MP4 SHA256: `46947c71ba487e82e30de48c1a03a2972c1ed14865f066e2a85147addd2f469b`
  - 响度: `mean_volume: -19.8 dB`
  - 抽样帧差: `121.23`

---

## 6. 测试与架构规范检验

### 单元测试
- 命令: `.venv/bin/pytest tests/test_dramakey_pipeline.py -q`
- 结果: **10 passed in 11.09s**（使用 `fake` 引擎，满足 <30s 快速跑完要求）。

### 回归测试
- 命令: `.venv/bin/pytest tests/test_script2video_kernel.py tests/test_storygraph.py -q`
- 结果: **22 passed in 0.88s**。

### 3O 架构 Lint
- 命令: `.venv/bin/python scripts/ci/run_3o_v3_lint.py`
- 对比结果:
  - 开工基线: 4 个由外部 `.venv/site-packages` 引起的预设检查失败（`check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py`）；
  - 完工复核: **新代码在 `hevi/` 内 0 违规，失败项目数量与基线完全一致，未引入任何新违规**。

---

## 7. Clean-room 声明与合规性

1. **Clean-room 声明**:
   本项目实现（包括小说分块、角色档案、双候选择优、人脸门禁、Ken Burns 运动及合成管线）系独立 clean-room 自行编写。未复制、引入或集成来自火宝（Huobao）、waoowaoo、ViMax、Toonflow、Pixelle-Video、Jellyfish 等参考项目的任何代码行或受版权保护文本。
2. **开源模型许可声明**:
   - `SD-Turbo`：采用 Stability AI Community License（非商用研究免费，年收入 <$1M 可商用）。已留有可插拔引擎接口，便于后续替换为 Apache-2.0 基础模型。
   - `YuNet` & `SFace`：基于 Apache-2.0 许可（OpenCV Zoo）。
   - `OpenCLIP`：基于 MIT 许可。
   - `Piper TTS`：基于 MIT / GPL 许可。
3. **零成本与硬件合规**:
   - 未调用任何外部付费 API。
   - 全流程严格在 CPU 上运行，遵循 `torch.set_num_threads(8)` 限制与进程互斥锁 `/tmp/hevi_cpu_render.lock`。
   - 未执行任何针对故障 GPU 的异常操作。

---

## 8. 新增依赖说明

- **未新增任何 pip 包**：环境已有依赖满足全部需求（`torch`, `diffusers`, `open_clip`, `opencv-python`, `piper`, `ffmpeg`）。

---

## 9. 结论

DRAMAKEY 任务要求的所有 A、B、C、D 各阶段目标、测试覆盖、E2E 双入口真实出片、及自动化 QA 检测已全部达标通过。
