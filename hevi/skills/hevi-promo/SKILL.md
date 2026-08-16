---
name: hevi-promo
version: "0.1.0"
description: Cinematic product promo from a product page or brief — shot recipe cards, brand→motion stylepack, BGM beat-sync, sound design, aesthetic canon final review. Produces a production plan (rendering via hevi-remotion).
argument-hint: "product_name=... [page_url=...]"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-promo

产品宣传片技能(内化自 video-shotcraft 八阶段流水线 + HyperFrames product-launch-video):
产品简报 → 品牌→动效参数 → 配方卡镜头映射 → 声音设计(BGM 先行+SFX 钉帧)→ 判例库终检。
核心引擎 `hevi/assembly/promo_video_workflow.py` + `hevi/motion/`。

## 前置

`HEVI_ROOT` 指向 hevi 仓库根。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python - <<'PY'
import asyncio
from pathlib import Path
from hevi.assembly.promo_video_workflow import PromoConfig, PromoInput, promo_video_workflow

res = asyncio.run(promo_video_workflow(
    PromoConfig(product_name="Acme", energy_axis=1.0, tone_axis=0.5, features=["a", "b", "c"]),
    PromoInput(page_url="https://..."),
    Path("out/promo"),
))
print(res)
PY
```

产物:制作计划 JSON(动效预设/镜头卡/声音设计/判例库终检报告)+ 可选采集
(`PromoInput.page_url` 走 hevi.motion.page_capture + design_token)。

## 可选增强

- BGM 给定 → 先 `hevi.motion.beat_sync` 网格分析,切点钉 beatF(n),渲后回测 ≤3f。
- 渲染:交 `hevi.assembly.remotion_render_workflow`(hevi-remotion,渲染契约)。
- 云渲染:`hevi.assembly.cloud_render_workflow`(@remotion/lambda)。
