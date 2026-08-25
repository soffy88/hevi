---
name: hevi-promo
version: "0.1.1"
description: Cinematic product promo from a product page or brief — shot recipe cards, brand→motion stylepack, BGM beat-sync, sound design, aesthetic canon final review. Produces a production plan (rendering via hevi-remotion).
argument-hint: "product_name=... [page_url=...]"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-promo

产品宣传片技能（内化自 video-shotcraft 八阶段流水线 + HyperFrames product-launch-video）：

产品简报 → 品牌/证据提取 → 品牌→动效参数 → 配方卡镜头映射 → 声音设计（BGM 先行 + SFX 钉帧）→ 判例库终检 → 产物校验。

核心引擎：`hevi/assembly/promo_video_workflow.py` 与 `hevi/motion/`。

## 前置

- `HEVI_ROOT` 必须指向 hevi 仓库根目录。
- 仅使用产品简报或页面中可核实的信息；缺失信息标记为假设，不要编造规格、客户、价格或品牌规范。
- 页面不可访问时仍可用 brief 生成计划，并在结果中记录采集失败原因。

## 调用

先确认仓库与 Python API 可用，再执行：

```bash
cd "$HEVI_ROOT" && uv run python - <<'PY'
import asyncio
from pathlib import Path
from hevi.assembly.promo_video_workflow import PromoConfig, PromoInput, promo_video_workflow

res = asyncio.run(promo_video_workflow(
    PromoConfig(
        product_name="Acme",
        energy_axis=1.0,
        tone_axis=0.5,
        features=["a", "b", "c"],
    ),
    PromoInput(page_url="https://..."),
    Path("out/promo"),
))
print(res)
PY
```

将真实产品名、已核实的 feature 列表和页面 URL 替换示例值。若 API 签名与示例不一致，先读取源码/签名，使用仓库当前版本的参数，不要猜测。

## 产物与验收

产物目录应包含制作计划 JSON（品牌/动效预设、镜头配方卡、声音设计、判例库终检报告）及可选页面采集资产。执行后检查：

1. 工作流无异常退出，输出路径存在且 JSON 可解析；
2. 每个 feature 至少映射到一个镜头或明确列为未使用；
3. 镜头包含目的、画面/动效、时长或节奏依据、转场和素材需求；
4. 终检报告记录可读性、层级、节奏、品牌一致性与未决风险；
5. 失败或降级必须在最终摘要中明确说明，不能把计划当作已渲染视频。

## 可选增强

- **BGM 给定**：先用 `hevi.motion.beat_sync` 分析节拍网格，在 beatF(n) 对齐切点；渲染后回测，偏差目标 ≤3 帧。若当前 API 不支持该参数，输出节拍网格与待接入说明。
- **渲染**：将已验收计划交给 `hevi.assembly.remotion_render_workflow`（遵守 hevi-remotion 渲染契约），并核对输出视频与日志。
- **云渲染**：使用 `hevi.assembly.cloud_render_workflow`（`@remotion/lambda`），仅在凭据、资源和渲染契约齐备时调用。

## 输出摘要

完成后用简短摘要报告：产物路径、采集/渲染状态、使用的证据来源、主要假设，以及需要人工确认的风险。