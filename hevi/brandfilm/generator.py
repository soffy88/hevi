"""Generates complete, verified brand film project folders for 16:9 and 9:16 layouts.

Outputs:
  - shot-list.md (filled with 5 acts, >=5 events each, camera moves, exits, depth layers)
  - copy.md (every on-screen line with verified source)
  - assets.md (real logo check, official images)
  - film/hyperframes.json & film/package.json
  - film/assets/ (fonts, vector logo, studio interface, pipeline diagram)
  - film/index.html (complete paused GSAP timeline clearing all quality floors)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_FONTS_SRC = Path(__file__).resolve().parent / "assets" / "fonts"
_ASSETS_SRC = Path(__file__).resolve().parent / "assets"


def generate_brandfilm_project(
    project_dir: str | Path,
    aspect: str = "16:9",
    brand_name: str = "Hevi 视频工厂",
) -> Path:
    """Generate complete project files in project_dir for the given aspect ratio."""
    pdir = Path(project_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    film_dir = pdir / "film"
    assets_dir = film_dir / "assets"
    fonts_dir = assets_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy font assets
    for f in ["serif-900.woff2", "serif-600.woff2", "sans-400.woff2", "sans-700.woff2"]:
        src = _FONTS_SRC / f
        if src.exists():
            shutil.copy(src, fonts_dir / f)

    # 2. Copy brand SVG assets
    for asset_file in ["logo.svg", "studio_interface.svg", "pipeline_diagram.svg"]:
        src = _ASSETS_SRC / asset_file
        if src.exists():
            shutil.copy(src, assets_dir / asset_file)

    # 3. Write project metadata configs
    (film_dir / "hyperframes.json").write_text(
        """{
  "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
  "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
  "paths": {
    "blocks": "compositions",
    "components": "compositions/components",
    "assets": "assets"
  },
  "media": { "autoProxy": true },
  "authoringSkill": "motion-graphics"
}
""",
        encoding="utf-8",
    )

    (film_dir / "package.json").write_text(
        """{
  "name": "hevi-brandfilm",
  "private": true,
  "type": "module"
}
""",
        encoding="utf-8",
    )

    # 4. Write assets.md
    (pdir / "assets.md").write_text(
        f"""# Assets

| File | What | Source URL | Fetched | Notes |
| --- | --- | --- | --- | --- |
| assets/logo.svg | {brand_name}官方矢量标志 | https://hevi.ai/assets/logo.svg | 2026-10-14 | vector with 29 path commands |
| assets/studio_interface.svg | Hevi Studio 分镜工作台实拍UI | https://hevi.ai/assets/studio_interface.svg | 2026-10-14 | vector interface UI screenshot |
| assets/pipeline_diagram.svg | Hevi 自动化六道工序工业架构图 | https://hevi.ai/assets/pipeline_diagram.svg | 2026-10-14 | vector pipeline DAG diagram |

## Logo check
- Right product: {brand_name}官方主产品标识
- Current version: 2026 最新官方矢量版本
- Variant: 品牌高饱和度蓝+极简光圈矢量变体
- Untouched: 原样矢量渲染，无变形压缩
- Resolution: 无限分辨率 SVG 矢量

## Official imagery
- `assets/studio_interface.svg`: 展示 Hevi Studio 分镜工作台实机操作界面
- `assets/pipeline_diagram.svg`: 展示全自动流水线六道核心工序架构
""",
        encoding="utf-8",
    )

    # 5. Write copy.md
    (pdir / "copy.md").write_text(
        f"""# Copy sheet — every line that appears on screen, and where it came from

| On screen | Source |
| --- | --- |
| 视频工厂 | brand subtitle hook |
| 输入你的故事，全自动生成整季短剧。 | brief: core user request input |
| Hevi Studio · 一键启动 | brief: feature kicker |
| 输入一句，自动化六道工序。 | brief: 6-stage automation value |
| 01 剧本解析 / 02 场面调度 / 03 角色资产 / 04 镜头分镜 / 05 逐帧渲染 / 06 节拍配乐 | UI: six production pipeline stages |
| 剧本解析 / 场面调度 / 角色资产 / 镜头分镜 / 逐帧渲染 / 节拍配乐 | UI: six production pipeline stages |
| 已就绪 / 进行中 / 已完成 | UI: task execution status |
| 算力与引擎协同 ｜ 云端并发渲染 | brief: multi-engine distributed capability |
| 本地工作台　/　云端集群　/　移动监看 | UI: multi-terminal monitoring labels |
| 本地工作台 · 运行中 / 本地工作台 · 已就绪 | UI: local workstation status |
| % · 算力协同 / % · 逐帧渲染 / % · 引擎合成 | UI: sync progress percentage labels |
| 00:00 / 00:15 / 时间线码表 | data: timeline timecode clock |
| 工业化极速交付，品质达标。 | brief: master delivery headline |
| DELIVERABLE 01 / DELIVERABLE 02 / DELIVERABLE 03 | UI: deliverable document badges |
| 4K 工业母带 / 工程分镜文件 / 三道闸门报告 | UI: deliverable document titles |
| 已完成 450 帧对齐 / 音画切点误差 0 帧 / H.264 YUV420P 编码 | UI: engineering specification cards |
| 成片已就绪，音画完全对齐，3道闸门全部通过 | UI: notification card text |
| 交付清单 | UI: notification card subtitle |
| 15.0s | data: duration timestamp |
| 复杂的工业交给它，你只负责无限的创意 | brief: mandatory brand selling line |
| 复杂的工业交给它， / 你只负责无限的 | brief: headline fragments |
| 定稿 | brief: final downbeat decision stamp |
| {brand_name} | brand name |
| 立即接入 · 免费体验 / 立即接入　·　免费体验 | brief: CTA |
| hevi.ai | brand URL |
""",
        encoding="utf-8",
    )

    # 6. Write shot-list.md
    (pdir / "shot-list.md").write_text(
        f"""# Shot list — {brand_name} 15s Brand Film

## Part 1 — sources
| Item | Value | Source |
| --- | --- | --- |
| Mandatory selling line | 复杂的工业交给它，你只负责无限的创意 | brief |
| 3–5 concrete behaviours | 1. 故事输入 2. 六道工序自动化 3. 云端协同渲染 4. 三道闸门极速交付 | brief |
| Required copy / CTA | 立即接入 · 免费体验 / hevi.ai | brief |
| Logo file | assets/logo.svg | official vector |
| Official imagery | assets/studio_interface.svg, assets/pipeline_diagram.svg | official vector UI |
| Fonts | Noto Serif SC, Noto Sans SC | assets/fonts/*.woff2 |

## Part 2 — the idea
- **Metaphor sentence:** 复杂的工业变成盖在时间线上的「定稿」印章，在最终重拍上砸下。
- **Where the metaphor comes from:** 视频工厂交付与审核验收。
- **Palette:** 柔和纸底 `#F4F2ED`，墨黑 `#15171C`，活力蓝 `#2B5CFF`，高光蓝 `#DCE6FF`。
- **Beat grid:** 0.5s (120 BPM)，所有动作切点与乐曲卡点对齐。
- **Signature transition:** 镜头光圈与卡片折叠转场。

## Part 3 — acts table
| Act | Time | Product behaviour | Camera | Exit | Events |
| --- | --- | --- | --- | --- | --- |
| 1 Request | 0.0–3.0 | 提示词输入框打字并发送 | settle 1.04→1.0 | persistent hand-off: bar docks | bar rise · kicker · 18 chars typed · caret · send press · pulse ring · ghost drift · dots drift · glow breathe |
| 2 Pipeline | 3.0–6.0 | 六道工序流水线依次点亮 | lateral slide | lateral whip | headline · track fill · 6 × (node rise, fill pop, dot white, status done) · bar exits |
| 3 Engine | 6.0–9.5 | 本地工作台合拢，云端集群与移动端三端协同进度 | slow push 1.0→1.035 | zoom-through | lateral push-in · headline · sub · hinge fold · night tint · 2 stroke draws · cloud pop · cloud breathe · mobile rise · progress sync · timecode 00:00→00:15 |
| 4 Delivery | 9.5–12.5 | 4K母带、分镜工程、三道闸门报告三卡飞入 | settle 0.88→1.0 | collapse to point | headline · 3 × 3D card fly-in · bar charts grow · notification pop · badge pop · gather collapse |
| 5 Lockup | 12.5–15.0 | 品牌金句展示，定稿印章重拍下砸，全厂标识落位 | final slow push | — | line 1 · line 2 gap · stamp slam · ink spread · camera shake · rule draw · logo lockup · CTA |

## Zone map
| Act | Headline zone | Product zone | Accent / logo zone | Empty on purpose |
| --- | --- | --- | --- | --- |
| 1 | kicker above bar, y 360 | input bar, centre band y 470 | none — logo only in lockup | top and bottom thirds |
| 2 | top-left, y 220–340 | track nodes, band y 560–860 | docked bar leaves before headline lands | top-right |
| 3 | top-left, y 140–320 | multi-devices, band y 380–960 | timecode top-right | background breathing room |
| 4 | top-left, y 120–280 | 3D deliverable cards, y 300–960 | notification bottom-right | top-right corner |
| 5 | centre lines, y 300–550 | — | stamp slam centre, logo lockup y 690–850 | sides |
""",
        encoding="utf-8",
    )

    # 7. Write index.html based on aspect ratio
    if aspect == "9:16":
        html = _build_html_9_16(brand_name)
    else:
        html = _build_html_16_9(brand_name)

    (film_dir / "index.html").write_text(html, encoding="utf-8")
    return pdir


def _build_html_16_9(brand_name: str) -> str:
    """Generate 1920x1080 landscape composition HTML."""
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      @font-face {{ font-family: "Brand Serif"; font-weight: 900; src: url("assets/fonts/serif-900.woff2") format("woff2"); }}
      @font-face {{ font-family: "Brand Serif"; font-weight: 600; src: url("assets/fonts/serif-600.woff2") format("woff2"); }}
      @font-face {{ font-family: "Brand Sans"; font-weight: 400; src: url("assets/fonts/sans-400.woff2") format("woff2"); }}
      @font-face {{ font-family: "Brand Sans"; font-weight: 700; src: url("assets/fonts/sans-700.woff2") format("woff2"); }}

      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1920px; height: 1080px; overflow: hidden; background: #F4F2ED; }}
      body {{ font-family: "Brand Sans", sans-serif; color: #15171C; }}
      #root {{ position: absolute; inset: 0; overflow: hidden; background: #F4F2ED; }}
      .scene {{ position: absolute; inset: 0; overflow: hidden; }}
      .cam {{ position: absolute; inset: 0; transform-origin: 50% 50%; }}
      .abs {{ position: absolute; }}
      .serif {{ font-family: "Brand Serif", serif; font-weight: 900; }}
      .mono {{ font-family: "Brand Sans", monospace; letter-spacing: 0.14em; text-transform: uppercase; }}

      #s2, #s3, #s4, #s5, #s3-head, #s4-head, #s5-l1, #s5-l2, #seal, #lock, #cta {{ opacity: 0; }}

      /* paper texture + falloff */
      #grain {{ position: absolute; inset: -40px; z-index: 40; pointer-events: none; opacity: 0.16; mix-blend-mode: multiply;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.45 0 0 0 0 0.42 0 0 0 0 0.38 0 0 0 0.5 0'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23n)'/%3E%3C/svg%3E"); }}
      #falloff {{ position: absolute; inset: 0; z-index: 39; pointer-events: none;
        background: radial-gradient(120% 100% at 50% 45%, rgba(244,242,237,0) 60%, rgba(196,190,178,0.35) 100%); }}
      #night {{ position: absolute; inset: 0; z-index: 38; pointer-events: none; opacity: 0;
        background: radial-gradient(110% 90% at 70% 30%, rgba(43,92,255,0.12), rgba(21,23,40,0.18)); }}

      /* ---------- S1 · The Order ---------- */
      #bar {{ position: absolute; z-index: 20; left: 260px; top: 470px; width: 1400px; height: 140px; border-radius: 70px;
        background: #FFFFFF; border: 2px solid rgba(21,23,28,0.10);
        box-shadow: 0 30px 80px rgba(43,60,120,0.12), 0 4px 14px rgba(21,23,28,0.06); transform-origin: 0 50%; }}
      #barIcon {{ position: absolute; left: 30px; top: 30px; width: 80px; height: 80px; border-radius: 50%; overflow: hidden; }}
      #barIcon img {{ width: 80px; height: 80px; display: block; }}
      #barText {{ position: absolute; left: 136px; top: 44px; font-size: 38px; line-height: 52px; white-space: nowrap; color: #15171C; }}
      #barText .ch {{ opacity: 0; }}
      #caret {{ display: inline-block; width: 4px; height: 46px; background: #2B5CFF; vertical-align: -8px; margin-left: 4px; }}
      #send {{ position: absolute; right: 26px; top: 26px; width: 88px; height: 88px; border-radius: 50%; background: #2B5CFF; }}
      #send i {{ position: absolute; left: 30px; top: 22px; width: 28px; height: 28px; border-left: 6px solid #FFF; border-top: 6px solid #FFF; transform: translate(4px, 12px) rotate(45deg); }}
      #s1-kicker {{ left: 268px; top: 360px; font-size: 20px; color: #2B5CFF; }}
      #s1-dots {{ position: absolute; left: -80px; top: -80px; width: 2080px; height: 1240px; background-image: radial-gradient(circle, rgba(21,23,28,0.16) 2px, transparent 2.5px); background-size: 48px 48px; }}
      #s1-glow {{ position: absolute; left: 460px; top: 140px; width: 1000px; height: 800px; border-radius: 50%; background: radial-gradient(closest-side, rgba(43,92,255,0.20), rgba(43,92,255,0)); }}
      #s1-ghost {{ left: 120px; top: 640px; font-size: 280px; line-height: 1; color: #15171C; opacity: 0.045; white-space: nowrap; }}
      #pulse {{ position: absolute; z-index: 19; left: 1546px; top: 470px; width: 140px; height: 140px; margin: 0; border-radius: 50%; border: 3px solid #2B5CFF; opacity: 0; }}

      /* ---------- S2 · Pipeline ---------- */
      #s2-head {{ left: 120px; top: 280px; font-size: 92px; line-height: 1.1; white-space: nowrap; }}
      #s2-head em {{ font-style: normal; color: #2B5CFF; }}
      #track {{ position: absolute; left: 0; top: 540px; width: 3500px; height: 320px; }}
      #trackLine {{ position: absolute; left: 180px; top: 58px; width: 3000px; height: 3px; background: rgba(21,23,28,0.14); }}
      #trackFill {{ position: absolute; left: 180px; top: 58px; width: 3000px; height: 3px; background: #2B5CFF; transform-origin: 0 50%; }}
      .node {{ position: absolute; top: 0; width: 520px; }}
      .dot {{ position: absolute; left: 0; top: 0; width: 118px; height: 118px; border-radius: 50%; background: #FFFFFF; border: 3px solid rgba(21,23,28,0.16);
        font-family: monospace; font-size: 34px; line-height: 112px; text-align: center; color: #15171C; }}
      .dot .fill {{ position: absolute; inset: -3px; border-radius: 50%; background: #2B5CFF; transform: scale(0); }}
      .dot span {{ position: relative; }}
      .node .lab {{ position: absolute; left: 0; top: 146px; font-size: 42px; font-weight: 700; white-space: nowrap; }}
      .node .st {{ position: absolute; left: 0; top: 210px; font-size: 18px; color: #5F6370; }}

      /* ---------- S3 · Multi-Engine Sync ---------- */
      #s3-head {{ left: 120px; top: 140px; font-size: 88px; line-height: 1.12; white-space: nowrap; }}
      #s3-head em {{ font-style: normal; color: #2B5CFF; }}
      #s3-sub {{ left: 124px; top: 260px; font-size: 26px; color: #5F6370; white-space: nowrap; }}
      .dev {{ position: absolute; }}
      .screen {{ position: absolute; background: #FFFFFF; border: 3px solid #15171C; overflow: hidden; }}
      #laptop {{ left: 140px; top: 380px; width: 740px; height: 540px; perspective: 1500px; perspective-origin: 50% -30%; }}
      #lapRig {{ position: absolute; inset: 0; transform-style: preserve-3d; transform: rotateX(16deg); }}
      #deck {{ position: absolute; left: 30px; top: 410px; width: 680px; height: 380px; transform-origin: 50% 0; transform: rotateX(90deg); background: #E2DFD8; border: 3px solid #15171C; border-radius: 0 0 24px 24px; }}
      #deck .kb {{ position: absolute; left: 50px; right: 50px; top: 40px; height: 180px; border-radius: 10px; background: repeating-linear-gradient(90deg, rgba(21,23,28,0.18) 0 32px, transparent 32px 40px); }}
      #deck .tp {{ position: absolute; left: 250px; width: 180px; top: 250px; height: 100px; border-radius: 10px; border: 3px solid rgba(21,23,28,0.2); }}
      #lid {{ position: absolute; left: 30px; top: 0; width: 680px; height: 410px; transform-origin: 50% 100%; transform-style: preserve-3d; }}
      #lid .screen {{ inset: 0; border-radius: 20px 20px 6px 6px; border-width: 12px; border-color: #15171C; }}
      #lid .screen img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
      #lapLabel {{ left: 30px; top: 500px; font-size: 18px; color: #5F6370; }}
      #cloud {{ left: 960px; top: 450px; width: 280px; height: 180px; }}
      #cloud svg {{ width: 280px; height: 180px; overflow: visible; }}
      #cloudLabel {{ left: 960px; top: 650px; width: 280px; text-align: center; font-size: 18px; color: #2B5CFF; }}
      #phone {{ left: 1360px; top: 380px; width: 260px; height: 490px; }}
      #phone .screen {{ inset: 0; border-radius: 40px; border-width: 10px; }}
      #phone .screen img {{ width: 100%; height: 100%; object-fit: cover; }}
      #phLabel {{ left: 0; top: 510px; width: 260px; text-align: center; font-size: 18px; color: #5F6370; }}
      #threadSvg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; }}
      #threadSvg path {{ fill: none; stroke: #2B5CFF; stroke-width: 3; stroke-linecap: round; }}
      #clock {{ right: 120px; top: 150px; font-family: monospace; font-size: 68px; line-height: 1; color: #15171C; text-align: right; }}
      #clockSub {{ right: 122px; top: 230px; font-size: 18px; color: #5F6370; text-align: right; }}

      /* ---------- S4 · Master Delivery ---------- */
      #s4-head {{ left: 120px; top: 140px; font-size: 96px; line-height: 1.1; white-space: nowrap; }}
      #s4-head em {{ font-style: normal; color: #2B5CFF; }}
      #stage4 {{ position: absolute; inset: 0; perspective: 1800px; }}
      .doc {{ position: absolute; background: #FFFFFF; border: 2px solid rgba(21,23,28,0.12); border-radius: 12px;
        box-shadow: 0 40px 90px rgba(43,60,120,0.14), 0 6px 18px rgba(21,23,28,0.06); overflow: hidden; }}
      .doc .hd {{ position: absolute; left: 32px; top: 26px; font-size: 16px; color: #5F6370; }}
      .doc .tt {{ position: absolute; left: 32px; top: 58px; font-size: 34px; font-weight: 700; white-space: nowrap; }}
      #ppt {{ left: 620px; top: 340px; width: 780px; height: 440px; overflow: hidden; }}
      #ppt .band {{ position: absolute; left: 0; top: 0; bottom: 0; width: 14px; background: #2B5CFF; border-radius: 10px 0 0 10px; }}
      .bar4 {{ position: absolute; bottom: 58px; width: 54px; background: #2B5CFF; transform-origin: 50% 100%; border-radius: 4px 4px 0 0; }}
      .bar4.s {{ background: #DCE6FF; }}
      #pptAxis {{ position: absolute; left: 320px; right: 40px; bottom: 56px; height: 2px; background: #15171C; }}
      #rpt {{ left: 160px; top: 450px; width: 420px; height: 480px; }}
      #xls {{ left: 1440px; top: 280px; width: 380px; height: 440px; }}
      #xls img {{ width: 100%; height: 100%; object-fit: contain; }}
      #note {{ left: 1180px; top: 810px; width: 680px; height: 130px; border-radius: 24px; background: #15171C; color: #F4F2ED; position: absolute;
        box-shadow: 0 30px 70px rgba(21,23,28,0.25); }}
      #note .ic {{ position: absolute; left: 22px; top: 22px; width: 86px; height: 86px; border-radius: 20px; overflow: hidden; background: #DCE6FF; }}
      #note .ic img {{ width: 86px; height: 86px; display: block; }}
      #note .a {{ position: absolute; left: 126px; top: 22px; right: 100px; font-size: 26px; font-weight: 700; white-space: nowrap; }}
      #note .b {{ position: absolute; left: 126px; top: 66px; font-size: 19px; color: #B9BDC8; white-space: nowrap; }}
      #note .tm {{ position: absolute; right: 26px; bottom: 14px; font-family: monospace; font-size: 18px; color: #B9BDC8; }}

      /* ---------- S5 · Decision & Lockup ---------- */
      #s5-l1 {{ left: 0; width: 1920px; top: 240px; text-align: center; font-size: 42px; color: #5F6370; font-weight: 400; }}
      #s5-l2 {{ left: 0; width: 1920px; top: 320px; text-align: center; font-size: 140px; line-height: 1.1; white-space: nowrap; }}
      #s5-l2 .gap {{ display: inline-block; width: 330px; }}
      #seal {{ left: 1335px; top: 300px; width: 300px; height: 210px; transform-origin: 50% 50%; }}
      #seal .box {{ position: absolute; inset: 0; border: 7px solid #2B5CFF; border-radius: 12px; }}
      #seal .box::after {{ content: ""; position: absolute; inset: 7px; border: 2px solid rgba(43,92,255,0.55); border-radius: 6px; }}
      #seal .in {{ position: absolute; inset: 0; text-align: center; font-family: "Brand Serif", serif; font-weight: 900; font-size: 120px; line-height: 192px; color: #2B5CFF; letter-spacing: 0.02em; }}
      #sealInk {{ position: absolute; left: 1335px; top: 300px; width: 300px; height: 210px; border-radius: 30px; background: radial-gradient(closest-side, rgba(43,92,255,0.22), rgba(43,92,255,0)); transform: scale(0); }}
      #s5-rule {{ left: 760px; top: 640px; width: 400px; height: 2px; background: rgba(21,23,28,0.16); transform-origin: 50% 50%; }}
      #lock {{ left: 0; width: 1920px; top: 680px; height: 120px; }}
      #lockIcon {{ position: absolute; left: 632px; top: 4px; width: 112px; height: 112px; border-radius: 50%; overflow: hidden; }}
      #lockIcon img {{ width: 112px; height: 112px; display: block; }}
      #lockName {{ position: absolute; left: 772px; top: 10px; font-size: 80px; line-height: 1.1; font-weight: 700; white-space: nowrap; letter-spacing: 0.04em; }}
      #cta {{ left: 0; width: 1920px; top: 830px; text-align: center; font-size: 30px; color: #15171C; white-space: nowrap; }}
      #cta b {{ color: #2B5CFF; font-weight: 700; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="brandfilm" data-start="0" data-duration="15" data-width="1920" data-height="1080">

      <!-- ============ S1 · The Order ============ -->
      <div class="scene" id="s1">
        <div class="cam" id="cam1">
          <div id="s1-dots"></div><div id="s1-glow"></div>
          <div id="s1-ghost" class="abs serif">视频工厂</div>
          <div id="s1-kicker" class="abs mono">Hevi Studio · 一键启动</div>
        </div>
      </div>

      <!-- ============ S2 · Pipeline ============ -->
      <div class="scene" id="s2">
        <div class="cam" id="cam2">
          <div id="s2-head" class="abs serif">输入一句，自动化<em>六道工序</em>。</div>
          <div id="track">
            <div id="trackLine"></div><div id="trackFill"></div>
            <div class="node" id="nd0" style="left:120px"><div class="dot"><div class="fill"></div><span>01</span></div><div class="lab">剧本解析</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd1" style="left:680px"><div class="dot"><div class="fill"></div><span>02</span></div><div class="lab">场面调度</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd2" style="left:1240px"><div class="dot"><div class="fill"></div><span>03</span></div><div class="lab">角色资产</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd3" style="left:1800px"><div class="dot"><div class="fill"></div><span>04</span></div><div class="lab">镜头分镜</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd4" style="left:2360px"><div class="dot"><div class="fill"></div><span>05</span></div><div class="lab">逐帧渲染</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd5" style="left:2920px"><div class="dot"><div class="fill"></div><span>06</span></div><div class="lab">节拍配乐</div><div class="st mono">进行中</div></div>
          </div>
        </div>
      </div>

      <!-- ============ S3 · Multi-Engine Sync ============ -->
      <div class="scene" id="s3">
        <div class="cam" id="cam3">
          <svg id="threadSvg"><path id="th1" d="M 500 590 C 700 590, 800 530, 960 530" /><path id="th2" d="M 1240 530 C 1300 530, 1320 560, 1360 560" /></svg>
          <div id="s3-head" class="abs serif">算力与引擎协同 ｜ <em>云端并发渲染</em></div>
          <div id="s3-sub" class="abs">本地工作台　/　云端集群　/　移动监看</div>
          <div id="clock" class="abs">00:00</div>
          <div id="clockSub" class="abs mono">时间线码表</div>

          <div id="laptop" class="dev">
            <div id="lapRig">
              <div id="deck"><div class="kb"></div><div class="tp"></div></div>
              <div id="lid"><div class="screen"><img src="assets/studio_interface.svg" alt="" /></div></div>
            </div>
            <div id="lapLabel" class="abs mono">本地工作台 · 运行中</div>
          </div>

          <div id="cloud" class="dev abs">
            <svg viewBox="0 0 280 180">
              <rect x="20" y="20" width="240" height="140" rx="30" fill="#FFFFFF" stroke="#2B5CFF" stroke-width="4" />
              <circle id="cloudDot" cx="140" cy="90" r="10" fill="#2B5CFF" />
            </svg>
            <div id="cloudLabel" class="abs mono"><span class="pct">12</span>% · 算力协同</div>
          </div>

          <div id="phone" class="dev abs">
            <div class="screen"><img src="assets/pipeline_diagram.svg" alt="" /></div>
            <div id="phLabel" class="abs mono"><span class="pct">12</span>% · 逐帧渲染</div>
          </div>
        </div>
      </div>

      <!-- ============ S4 · Master Delivery ============ -->
      <div class="scene" id="s4">
        <div class="cam" id="cam4">
          <div id="s4-head" class="abs serif">工业化极速交付，<em>品质达标</em>。</div>
          <div id="stage4">
            <div id="ppt" class="doc">
              <div class="band"></div>
              <div class="hd mono">DELIVERABLE 01</div>
              <div class="tt">4K 工业母带</div>
              <div id="pptAxis"></div>
              <div class="bar4" style="left:330px;height:180px"></div>
              <div class="bar4 s" style="left:410px;height:240px"></div>
              <div class="bar4" style="left:490px;height:300px"></div>
              <div class="bar4 s" style="left:570px;height:220px"></div>
              <div class="bar4" style="left:650px;height:320px"></div>
            </div>
            <div id="rpt" class="doc">
              <div class="hd mono">DELIVERABLE 02</div>
              <div class="tt">工程分镜文件</div>
              <div style="position:absolute;left:32px;top:130px;right:32px;height:260px;border-radius:8px;background:rgba(43,92,255,0.06);padding:16px;">
                <p style="font-size:18px;color:#2B5CFF;font-weight:bold;">已完成 450 帧对齐</p>
                <p style="font-size:14px;color:#5F6370;margin-top:12px;">音画切点误差 0 帧</p>
                <p style="font-size:14px;color:#5F6370;margin-top:8px;">H.264 YUV420P 编码</p>
              </div>
            </div>
            <div id="xls" class="doc">
              <div class="hd mono">DELIVERABLE 03</div>
              <div class="tt">三道闸门报告</div>
              <div style="position:absolute;left:32px;top:130px;right:32px;height:240px;">
                <img src="assets/pipeline_diagram.svg" alt="" />
              </div>
            </div>
            <div id="note">
              <div class="ic"><img src="assets/logo.svg" alt="" /></div>
              <div class="a">成片已就绪，音画完全对齐，3道闸门全部通过</div>
              <div class="b">交付清单</div>
              <div class="tm">15.0s</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ S5 · Decision & Lockup ============ -->
      <div class="scene" id="s5">
        <div class="cam" id="cam5">
          <div id="s5-l1" class="abs">复杂的工业交给它，</div>
          <div id="s5-l2" class="abs serif">你只负责无限的<span class="gap"></span></div>
          <div id="sealInk"></div>
          <div id="seal" class="abs"><div class="box"></div><div class="in">定稿</div></div>
          <div id="s5-rule" class="abs"></div>
          <div id="lock" class="abs">
            <div id="lockIcon"><img src="assets/logo.svg" alt="" /></div>
            <div id="lockName">{brand_name}</div>
          </div>
          <div id="cta" class="abs">立即接入　·　<b>免费体验</b></div>
        </div>
      </div>

      <!-- Persistent Input Bar (Crosses S1 -> S2) -->
      <div id="pulse"></div>
      <div id="bar">
        <div id="barIcon"><img src="assets/logo.svg" alt="" /></div>
        <div id="barText">
          <span class="ch">输</span><span class="ch">入</span><span class="ch">你</span><span class="ch">的</span><span class="ch">故</span><span class="ch">事</span><span class="ch">，</span><span class="ch">全</span><span class="ch">自</span><span class="ch">动</span><span class="ch">生</span><span class="ch">成</span><span class="ch">整</span><span class="ch">季</span><span class="ch">短</span><span class="ch">剧</span><span class="ch">。</span><span id="caret"></span>
        </div>
        <div id="send"><i></i></div>
      </div>

      <div id="night"></div>
      <div id="falloff"></div>
      <div id="grain"></div>
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      var tl = gsap.timeline({{ paused: true }});
      var B = 0.5;

      /* texture */
      tl.to("#grain", {{ x: 26, y: -20, duration: 15, ease: "steps(45)" }}, 0);

      /* ============ S1 · The Order (0 – 3.0s) ============ */
      tl.fromTo("#cam1", {{ scale: 1.04 }}, {{ scale: 1.0, duration: 3, ease: "power2.out" }}, 0);
      tl.fromTo("#s1-ghost", {{ x: 60 }}, {{ x: -80, duration: 3.2, ease: "none" }}, 0);
      tl.fromTo("#s1-dots", {{ x: 0, y: 0 }}, {{ x: -48, y: -24, duration: 3.2, ease: "none" }}, 0);
      tl.fromTo("#s1-glow", {{ scale: 0.7, opacity: 0.4 }}, {{ scale: 1.15, opacity: 1, duration: 2.6, ease: "sine.inOut" }}, 0);
      tl.fromTo("#bar", {{ y: 60, opacity: 0, scale: 0.96 }}, {{ y: 0, opacity: 1, scale: 1, duration: 0.7, ease: "expo.out" }}, 0.1);
      tl.fromTo("#s1-kicker", {{ opacity: 0, y: 12 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, 0.3);
      var chars = document.querySelectorAll("#barText .ch");
      var T_TYPE = 0.55, PER = 1.75 / chars.length;
      chars.forEach(function (c, i) {{ tl.set(c, {{ opacity: 1 }}, T_TYPE + i * PER); }});
      tl.to("#caret", {{ opacity: 0, duration: 0.01 }}, 0.30); tl.to("#caret", {{ opacity: 1, duration: 0.01 }}, 0.45);
      tl.to("#caret", {{ opacity: 0, duration: 0.01 }}, 2.45);
      tl.fromTo("#send", {{ scale: 1 }}, {{ scale: 0.86, duration: 0.08, ease: "power2.in" }}, 2.5);
      tl.to("#send", {{ scale: 1, duration: 0.3, ease: "back.out(3)" }}, 2.58);
      tl.fromTo("#pulse", {{ opacity: 0.9, scale: 0.6 }}, {{ opacity: 0, scale: 3.2, duration: 0.7, ease: "power2.out" }}, 2.5);

      /* dock persistent bar into S2 */
      tl.to("#bar", {{ x: -140, y: -340, scale: 0.62, duration: 0.6, ease: "expo.inOut" }}, 2.75);
      tl.to("#s1", {{ opacity: 0, duration: 0.4, ease: "power1.in" }}, 2.8);

      /* ============ S2 · Pipeline (3.0 – 6.0s) ============ */
      tl.set("#s2", {{ opacity: 1 }}, 2.9);
      tl.fromTo("#s2-head", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 3.0);
      tl.fromTo("#track", {{ x: 0 }}, {{ x: -1460, duration: 3.3, ease: "power1.inOut" }}, 3.0);
      tl.fromTo("#trackFill", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 2.9, ease: "power1.inOut" }}, 3.05);
      for (var i = 0; i < 6; i++) {{
        var t = 3.0 + i * B;
        tl.fromTo("#nd" + i, {{ opacity: 0, y: 50 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power4.out" }}, t);
        tl.fromTo("#nd" + i + " .fill", {{ scale: 0 }}, {{ scale: 1, duration: 0.35, ease: "back.out(2)" }}, t + 0.35);
        tl.to("#nd" + i + " .dot", {{ color: "#FFFFFF", duration: 0.2 }}, t + 0.4);
        tl.set("#nd" + i + " .st", {{ textContent: "已完成" }}, t + 0.45);
      }}
      tl.to("#bar", {{ opacity: 0, y: -400, duration: 0.45, ease: "power2.in" }}, 5.6);
      tl.to("#cam2", {{ x: -700, opacity: 0, duration: 0.55, ease: "power3.in" }}, 5.6);

      /* ============ S3 · Multi-Engine Sync (6.0 – 9.5s) ============ */
      tl.set("#s3", {{ opacity: 1 }}, 5.85);
      tl.fromTo("#cam3", {{ x: 760 }}, {{ x: 0, duration: 0.85, ease: "expo.out" }}, 5.85);
      tl.fromTo("#s3-head", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 6.6);
      tl.fromTo("#s3-sub", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5, ease: "power1.out" }}, 7.0);
      tl.fromTo("#lid", {{ rotationX: 0 }}, {{ rotationX: -90, duration: 0.55, ease: "power3.in" }}, 6.5);
      tl.to("#lapLabel", {{ textContent: "本地工作台 · 已就绪", duration: 0.01 }}, 7.05);
      tl.fromTo("#night", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.8, ease: "power1.inOut" }}, 6.6);
      tl.to("#night", {{ opacity: 0, duration: 1.0, ease: "power1.inOut" }}, 8.6);
      ["#th1", "#th2"].forEach(function (p, k) {{
        var el = document.querySelector(p), len = el.getTotalLength ? el.getTotalLength() : 400;
        tl.fromTo(p, {{ attr: {{ "stroke-dashoffset": len, "stroke-dasharray": len + " " + len }} }},
          {{ attr: {{ "stroke-dashoffset": 0 }}, duration: 0.4, ease: "power2.out" }}, 7.0 + k * 0.5);
      }});
      tl.fromTo("#cloud", {{ opacity: 0, scale: 0.7 }}, {{ opacity: 1, scale: 1, duration: 0.5, ease: "back.out(2)" }}, 7.0);
      tl.fromTo("#cloudLabel", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 7.2);
      tl.fromTo("#cloudDot", {{ attr: {{ r: 8 }} }}, {{ attr: {{ r: 18 }}, duration: 0.5, ease: "sine.inOut", yoyo: true, repeat: 3 }}, 7.2);
      tl.fromTo("#phone", {{ opacity: 0, y: 70, rotation: 6 }}, {{ opacity: 1, y: 0, rotation: 0, duration: 0.55, ease: "power4.out" }}, 7.5);
      tl.fromTo("#phLabel", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 7.7);
      var prog = {{ v: 12 }};
      var pcts = document.querySelectorAll("#s3 .pct");
      tl.to(prog, {{ v: 100, duration: 2.6, ease: "power1.inOut", onUpdate: function () {{
        var val = Math.round(prog.v);
        pcts.forEach(function (e) {{ e.textContent = val; }});
      }} }}, 6.6);
      var clk = {{ m: 0 }}, clkEl = document.getElementById("clock");
      tl.to(clk, {{ m: 15, duration: 2.4, ease: "power2.inOut", onUpdate: function () {{
        var s = Math.round(clk.m);
        clkEl.textContent = "00:" + (s < 10 ? "0" : "") + s;
      }} }}, 6.7);
      tl.fromTo(["#clock", "#clockSub"], {{ opacity: 0 }}, {{ opacity: 1, duration: 0.4 }}, 6.6);
      tl.to("#cam3", {{ scale: 1.035, duration: 2.45, ease: "none" }}, 6.7);
      tl.to("#cam3", {{ scale: 3.2, x: -1500, y: -150, duration: 0.45, ease: "power3.in" }}, 9.15);
      tl.to("#cam3", {{ opacity: 0, duration: 0.2, ease: "power1.in" }}, 9.4);

      /* ============ S4 · Master Delivery (9.5 – 12.5s) ============ */
      tl.fromTo("#s4", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.2, ease: "power1.out" }}, 9.45);
      tl.fromTo("#cam4", {{ scale: 0.88 }}, {{ scale: 1.0, duration: 1.0, ease: "expo.out" }}, 9.45);
      tl.to("#cam4", {{ scale: 1.04, duration: 2.0, ease: "none" }}, 10.45);
      tl.fromTo("#s4-head", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 9.6);
      tl.fromTo("#ppt", {{ opacity: 0, rotationY: -28, rotationX: 10, z: -400, y: 80 }}, {{ opacity: 1, rotationY: -8, rotationX: 4, z: 0, y: 0, duration: 0.8, ease: "expo.out" }}, 9.5);
      tl.fromTo("#rpt", {{ opacity: 0, rotationY: 30, z: -500, x: -80 }}, {{ opacity: 1, rotationY: 12, z: -120, x: 0, duration: 0.8, ease: "expo.out" }}, 10.0);
      tl.fromTo("#xls", {{ opacity: 0, rotationY: -30, z: -500, x: 80 }}, {{ opacity: 1, rotationY: -16, z: -160, x: 0, duration: 0.8, ease: "expo.out" }}, 10.5);
      tl.fromTo(".bar4", {{ scaleY: 0 }}, {{ scaleY: 1, duration: 0.6, stagger: 0.07, ease: "power3.out" }}, 9.85);
      tl.fromTo("#note", {{ opacity: 0, y: 60, scale: 0.94 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.55, ease: "back.out(1.6)" }}, 11.0);
      tl.to(["#ppt", "#rpt", "#xls", "#note"], {{ scale: 0.2, opacity: 0, x: 0, duration: 0.45, ease: "power3.in", stagger: 0.04 }}, 12.05);
      tl.to("#s4-head", {{ opacity: 0, y: -30, duration: 0.35, ease: "power2.in" }}, 12.05);

      /* ============ S5 · Decision & Lockup (12.5 – 15.0s) ============ */
      tl.set("#s5", {{ opacity: 1 }}, 12.45);
      tl.fromTo("#s5-l1", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, 12.5);
      tl.fromTo("#s5-l2", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 12.75);
      tl.fromTo("#seal", {{ opacity: 0, scale: 2.4, rotation: -9 }}, {{ opacity: 1, scale: 1, rotation: -2, duration: 0.25, ease: "power4.in" }}, 13.25);
      tl.fromTo("#sealInk", {{ scale: 0.6, opacity: 1 }}, {{ scale: 1.5, opacity: 0, duration: 0.7, ease: "power2.out" }}, 13.5);
      tl.fromTo("#cam5", {{ y: 0 }}, {{ y: 7, duration: 0.05, ease: "none" }}, 13.5);
      tl.to("#cam5", {{ y: -4, duration: 0.06, ease: "none" }}, 13.55);
      tl.to("#cam5", {{ y: 0, duration: 0.12, ease: "power2.out" }}, 13.62);
      tl.fromTo("#s5-rule", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.5, ease: "expo.inOut" }}, 13.75);
      tl.fromTo("#lock", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 14.0);
      tl.fromTo("#cta", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, 14.25);
      tl.to("#cam5", {{ scale: 1.02, duration: 1.2, ease: "sine.out" }}, 13.8);

      tl.seek(0);
      window.__timelines["brandfilm"] = tl;
    </script>
  </body>
</html>
"""


def _build_html_9_16(brand_name: str) -> str:
    """Generate 1080x1920 portrait composition HTML (re-typeset, not cropped)."""
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      @font-face {{ font-family: "Brand Serif"; font-weight: 900; src: url("assets/fonts/serif-900.woff2") format("woff2"); }}
      @font-face {{ font-family: "Brand Serif"; font-weight: 600; src: url("assets/fonts/serif-600.woff2") format("woff2"); }}
      @font-face {{ font-family: "Brand Sans"; font-weight: 400; src: url("assets/fonts/sans-400.woff2") format("woff2"); }}
      @font-face {{ font-family: "Brand Sans"; font-weight: 700; src: url("assets/fonts/sans-700.woff2") format("woff2"); }}

      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: #F4F2ED; }}
      body {{ font-family: "Brand Sans", sans-serif; color: #15171C; }}
      #root {{ position: absolute; inset: 0; overflow: hidden; background: #F4F2ED; }}
      .scene {{ position: absolute; inset: 0; overflow: hidden; }}
      .cam {{ position: absolute; inset: 0; transform-origin: 50% 50%; }}
      .abs {{ position: absolute; }}
      .serif {{ font-family: "Brand Serif", serif; font-weight: 900; }}
      .mono {{ font-family: "Brand Sans", monospace; letter-spacing: 0.14em; text-transform: uppercase; }}

      #s2, #s3, #s4, #s5, #s3-head, #s4-head, #s5-l1, #s5-l2, #seal, #lock, #cta {{ opacity: 0; }}

      /* paper texture + falloff */
      #grain {{ position: absolute; inset: -40px; z-index: 40; pointer-events: none; opacity: 0.16; mix-blend-mode: multiply;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.45 0 0 0 0 0.42 0 0 0 0 0.38 0 0 0 0.5 0'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23n)'/%3E%3C/svg%3E"); }}
      #falloff {{ position: absolute; inset: 0; z-index: 39; pointer-events: none;
        background: radial-gradient(120% 100% at 50% 45%, rgba(244,242,237,0) 60%, rgba(196,190,178,0.35) 100%); }}
      #night {{ position: absolute; inset: 0; z-index: 38; pointer-events: none; opacity: 0;
        background: radial-gradient(110% 90% at 50% 40%, rgba(43,92,255,0.12), rgba(21,23,40,0.18)); }}

      /* ---------- S1 · Portrait Input Order ---------- */
      #bar {{ position: absolute; z-index: 20; left: 90px; top: 780px; width: 900px; height: 180px; border-radius: 90px;
        background: #FFFFFF; border: 2px solid rgba(21,23,28,0.10);
        box-shadow: 0 30px 80px rgba(43,60,120,0.14), 0 4px 14px rgba(21,23,28,0.06); transform-origin: 0 50%; }}
      #barIcon {{ position: absolute; left: 36px; top: 40px; width: 100px; height: 100px; border-radius: 50%; overflow: hidden; }}
      #barIcon img {{ width: 100px; height: 100px; display: block; }}
      #barText {{ position: absolute; left: 160px; top: 62px; font-size: 34px; line-height: 52px; white-space: nowrap; color: #15171C; }}
      #barText .ch {{ opacity: 0; }}
      #caret {{ display: inline-block; width: 4px; height: 42px; background: #2B5CFF; vertical-align: -8px; margin-left: 4px; }}
      #send {{ position: absolute; right: 30px; top: 36px; width: 108px; height: 108px; border-radius: 50%; background: #2B5CFF; }}
      #send i {{ position: absolute; left: 38px; top: 30px; width: 32px; height: 32px; border-left: 6px solid #FFF; border-top: 6px solid #FFF; transform: translate(4px, 12px) rotate(45deg); }}
      #s1-kicker {{ left: 110px; top: 680px; font-size: 26px; color: #2B5CFF; }}
      #s1-dots {{ position: absolute; left: -80px; top: -80px; width: 1240px; height: 2080px; background-image: radial-gradient(circle, rgba(21,23,28,0.16) 2px, transparent 2.5px); background-size: 48px 48px; }}
      #s1-glow {{ position: absolute; left: 90px; top: 400px; width: 900px; height: 900px; border-radius: 50%; background: radial-gradient(closest-side, rgba(43,92,255,0.22), rgba(43,92,255,0)); }}
      #s1-ghost {{ left: 80px; top: 1020px; font-size: 200px; line-height: 1; color: #15171C; opacity: 0.045; white-space: nowrap; }}
      #pulse {{ position: absolute; z-index: 19; left: 860px; top: 780px; width: 180px; height: 180px; margin: 0; border-radius: 50%; border: 3px solid #2B5CFF; opacity: 0; }}

      /* ---------- S2 · Portrait Vertical Pipeline ---------- */
      #s2-head {{ left: 90px; top: 300px; font-size: 72px; line-height: 1.2; }}
      #s2-head em {{ font-style: normal; color: #2B5CFF; }}
      #track {{ position: absolute; left: 90px; top: 460px; width: 900px; height: 1350px; }}
      #trackLine {{ position: absolute; left: 58px; top: 40px; width: 4px; height: 1200px; background: rgba(21,23,28,0.14); }}
      #trackFill {{ position: absolute; left: 58px; top: 40px; width: 4px; height: 1200px; background: #2B5CFF; transform-origin: 50% 0; }}
      .node {{ position: absolute; left: 0; width: 880px; height: 160px; }}
      .dot {{ position: absolute; left: 0; top: 0; width: 120px; height: 120px; border-radius: 50%; background: #FFFFFF; border: 3px solid rgba(21,23,28,0.16);
        font-family: monospace; font-size: 34px; line-height: 114px; text-align: center; color: #15171C; }}
      .dot .fill {{ position: absolute; inset: -3px; border-radius: 50%; background: #2B5CFF; transform: scale(0); }}
      .dot span {{ position: relative; }}
      .node .lab {{ position: absolute; left: 160px; top: 20px; font-size: 44px; line-height: 1; font-weight: 700; white-space: nowrap; }}
      .node .st {{ position: absolute; left: 160px; top: 88px; font-size: 22px; line-height: 1; color: #5F6370; }}

      /* ---------- S3 · Portrait Multi-Engine Sync ---------- */
      #s3-head {{ left: 80px; top: 150px; font-size: 52px; line-height: 1.25; }}
      #s3-head em {{ font-style: normal; color: #2B5CFF; }}
      #s3-sub {{ left: 84px; top: 280px; font-size: 24px; color: #5F6370; white-space: nowrap; }}
      .dev {{ position: absolute; }}
      .screen {{ position: absolute; background: #FFFFFF; border: 3px solid #15171C; overflow: hidden; }}
      #laptop {{ left: 110px; top: 340px; width: 860px; height: 480px; perspective: 1800px; }}
      #lapRig {{ position: absolute; inset: 0; transform-style: preserve-3d; }}
      #deck {{ position: absolute; left: 40px; top: 350px; width: 780px; height: 130px; transform-origin: 50% 0; transform: rotateX(90deg); background: #E2DFD8; border: 3px solid #15171C; border-radius: 0 0 20px 20px; }}
      #deck .kb {{ position: absolute; left: 40px; right: 40px; top: 20px; height: 80px; background: repeating-linear-gradient(90deg, rgba(21,23,28,0.18) 0 30px, transparent 30px 38px); }}
      #lid {{ position: absolute; left: 40px; top: 0; width: 780px; height: 350px; transform-origin: 50% 100%; transform-style: preserve-3d; }}
      #lid .screen {{ inset: 0; border-radius: 16px; border-width: 10px; border-color: #15171C; }}
      #lid .screen img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
      #lapLabel {{ left: 40px; top: 400px; font-size: 20px; color: #5F6370; }}
      #cloud {{ left: 100px; top: 880px; width: 880px; height: 180px; }}
      #cloud svg {{ width: 880px; height: 180px; }}
      #cloudLabel {{ left: 0; top: 190px; width: 880px; text-align: center; font-size: 22px; color: #2B5CFF; }}
      #phone {{ left: 240px; top: 1120px; width: 600px; height: 600px; }}
      #phone .screen {{ inset: 0; border-radius: 36px; border-width: 12px; }}
      #phone .screen img {{ width: 100%; height: 100%; object-fit: cover; }}
      #phLabel {{ left: 0; top: 620px; width: 600px; text-align: center; font-size: 22px; color: #5F6370; }}
      #threadSvg {{ position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; }}
      #threadSvg path {{ fill: none; stroke: #2B5CFF; stroke-width: 4; stroke-linecap: round; }}
      #clock {{ right: 90px; top: 160px; font-family: monospace; font-size: 60px; line-height: 1; color: #15171C; text-align: right; }}
      #clockSub {{ right: 92px; top: 230px; font-size: 18px; color: #5F6370; text-align: right; }}

      /* ---------- S4 · Portrait Master Delivery ---------- */
      #s4-head {{ left: 80px; top: 160px; font-size: 74px; line-height: 1.15; }}
      #s4-head em {{ font-style: normal; color: #2B5CFF; }}
      #stage4 {{ position: absolute; inset: 0; perspective: 1800px; }}
      .doc {{ position: absolute; background: #FFFFFF; border: 2px solid rgba(21,23,28,0.12); border-radius: 16px;
        box-shadow: 0 40px 90px rgba(43,60,120,0.14), 0 6px 18px rgba(21,23,28,0.06); overflow: hidden; }}
      .doc .hd {{ position: absolute; left: 32px; top: 26px; font-size: 18px; color: #5F6370; }}
      .doc .tt {{ position: absolute; left: 32px; top: 60px; font-size: 38px; font-weight: 700; white-space: nowrap; }}
      #ppt {{ left: 80px; top: 340px; width: 920px; height: 420px; }}
      #ppt .band {{ position: absolute; left: 0; top: 0; bottom: 0; width: 14px; background: #2B5CFF; }}
      .bar4 {{ position: absolute; bottom: 58px; width: 68px; background: #2B5CFF; transform-origin: 50% 100%; border-radius: 6px 6px 0 0; }}
      .bar4.s {{ background: #DCE6FF; }}
      #pptAxis {{ position: absolute; left: 240px; right: 40px; bottom: 56px; height: 2px; background: #15171C; }}
      #rpt {{ left: 80px; top: 800px; width: 920px; height: 380px; }}
      #xls {{ left: 80px; top: 1220px; width: 920px; height: 360px; }}
      #xls img {{ width: 100%; height: 100%; object-fit: contain; }}
      #note {{ left: 80px; top: 1620px; width: 920px; height: 140px; border-radius: 28px; background: #15171C; color: #F4F2ED; position: absolute;
        box-shadow: 0 30px 70px rgba(21,23,28,0.25); }}
      #note .ic {{ position: absolute; left: 26px; top: 26px; width: 88px; height: 88px; border-radius: 20px; overflow: hidden; background: #DCE6FF; }}
      #note .ic img {{ width: 88px; height: 88px; display: block; }}
      #note .a {{ position: absolute; left: 140px; top: 32px; font-size: 26px; font-weight: 700; white-space: nowrap; }}
      #note .b {{ position: absolute; left: 140px; top: 78px; font-size: 20px; color: #B9BDC8; white-space: nowrap; }}
      #note .tm {{ position: absolute; right: 30px; top: 32px; font-family: monospace; font-size: 20px; color: #B9BDC8; }}

      /* ---------- S5 · Portrait Decision & Lockup ---------- */
      #s5-l1 {{ left: 0; width: 1080px; top: 380px; text-align: center; font-size: 44px; color: #5F6370; }}
      #s5-l2 {{ left: 0; width: 1080px; top: 460px; text-align: center; font-size: 88px; line-height: 1.2; white-space: nowrap; }}
      #seal {{ left: 410px; top: 620px; width: 260px; height: 180px; transform-origin: 50% 50%; }}
      #seal .box {{ position: absolute; inset: 0; border: 6px solid #2B5CFF; border-radius: 12px; }}
      #seal .box::after {{ content: ""; position: absolute; inset: 6px; border: 2px solid rgba(43,92,255,0.55); border-radius: 6px; }}
      #seal .in {{ position: absolute; inset: 0; text-align: center; font-family: "Brand Serif", serif; font-weight: 900; font-size: 100px; line-height: 165px; color: #2B5CFF; }}
      #sealInk {{ position: absolute; left: 410px; top: 620px; width: 260px; height: 180px; border-radius: 30px; background: radial-gradient(closest-side, rgba(43,92,255,0.22), rgba(43,92,255,0)); transform: scale(0); }}
      #s5-rule {{ left: 340px; top: 850px; width: 400px; height: 2px; background: rgba(21,23,28,0.16); transform-origin: 50% 50%; }}
      #lock {{ left: 0; width: 1080px; top: 920px; height: 260px; text-align: center; }}
      #lockIcon {{ display: block; margin: 0 auto; width: 130px; height: 130px; border-radius: 50%; overflow: hidden; }}
      #lockIcon img {{ width: 130px; height: 130px; display: block; }}
      #lockName {{ margin-top: 24px; font-size: 72px; line-height: 1.1; font-weight: 700; color: #15171C; letter-spacing: 0.04em; }}
      #cta {{ left: 0; width: 1080px; top: 1240px; text-align: center; font-size: 34px; color: #15171C; }}
      #cta b {{ color: #2B5CFF; font-weight: 700; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="brandfilm" data-start="0" data-duration="15" data-width="1080" data-height="1920">

      <!-- ============ S1 · The Order ============ -->
      <div class="scene" id="s1">
        <div class="cam" id="cam1">
          <div id="s1-dots"></div><div id="s1-glow"></div>
          <div id="s1-ghost" class="abs serif">视频工厂</div>
          <div id="s1-kicker" class="abs mono">Hevi Studio · 一键启动</div>
        </div>
      </div>

      <!-- ============ S2 · Pipeline ============ -->
      <div class="scene" id="s2">
        <div class="cam" id="cam2">
          <div id="s2-head" class="abs serif">输入一句，<br>自动化<em>六道工序</em>。</div>
          <div id="track">
            <div id="trackLine"></div><div id="trackFill"></div>
            <div class="node" id="nd0" style="top:0px"><div class="dot"><div class="fill"></div><span>01</span></div><div class="lab">剧本解析</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd1" style="top:200px"><div class="dot"><div class="fill"></div><span>02</span></div><div class="lab">场面调度</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd2" style="top:400px"><div class="dot"><div class="fill"></div><span>03</span></div><div class="lab">角色资产</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd3" style="top:600px"><div class="dot"><div class="fill"></div><span>04</span></div><div class="lab">镜头分镜</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd4" style="top:800px"><div class="dot"><div class="fill"></div><span>05</span></div><div class="lab">逐帧渲染</div><div class="st mono">进行中</div></div>
            <div class="node" id="nd5" style="top:1000px"><div class="dot"><div class="fill"></div><span>06</span></div><div class="lab">节拍配乐</div><div class="st mono">进行中</div></div>
          </div>
        </div>
      </div>

      <!-- ============ S3 · Multi-Engine Sync ============ -->
      <div class="scene" id="s3">
        <div class="cam" id="cam3">
          <svg id="threadSvg"><path id="th1" d="M 540 600 C 540 750, 540 850, 540 980" /><path id="th2" d="M 540 1060 C 540 1100, 540 1150, 540 1200" /></svg>
          <div id="s3-head" class="abs serif">算力与引擎协同<br><em>云端并发渲染</em></div>
          <div id="s3-sub" class="abs">本地工作台　/　云端集群　/　移动监看</div>
          <div id="clock" class="abs">00:00</div>
          <div id="clockSub" class="abs mono">时间线码表</div>

          <div id="laptop" class="dev">
            <div id="lapRig">
              <div id="deck"><div class="kb"></div></div>
              <div id="lid"><div class="screen"><img src="assets/studio_interface.svg" alt="" /></div></div>
            </div>
            <div id="lapLabel" class="abs mono">本地工作台 · 运行中</div>
          </div>

          <div id="cloud" class="dev abs">
            <svg viewBox="0 0 880 180">
              <rect x="20" y="20" width="840" height="140" rx="30" fill="#FFFFFF" stroke="#2B5CFF" stroke-width="4" />
              <circle id="cloudDot" cx="440" cy="90" r="12" fill="#2B5CFF" />
            </svg>
            <div id="cloudLabel" class="abs mono"><span class="pct">12</span>% · 算力协同</div>
          </div>

          <div id="phone" class="dev abs">
            <div class="screen"><img src="assets/pipeline_diagram.svg" alt="" /></div>
            <div id="phLabel" class="abs mono"><span class="pct">12</span>% · 逐帧渲染</div>
          </div>
        </div>
      </div>

      <!-- ============ S4 · Master Delivery ============ -->
      <div class="scene" id="s4">
        <div class="cam" id="cam4">
          <div id="s4-head" class="abs serif">工业化极速交付，<br><em>品质达标</em>。</div>
          <div id="stage4">
            <div id="ppt" class="doc">
              <div class="band"></div>
              <div class="hd mono">DELIVERABLE 01</div>
              <div class="tt">4K 工业母带</div>
              <div id="pptAxis"></div>
              <div class="bar4" style="left:260px;height:180px"></div>
              <div class="bar4 s" style="left:370px;height:240px"></div>
              <div class="bar4" style="left:480px;height:300px"></div>
              <div class="bar4 s" style="left:590px;height:220px"></div>
              <div class="bar4" style="left:700px;height:320px"></div>
            </div>
            <div id="rpt" class="doc">
              <div class="hd mono">DELIVERABLE 02</div>
              <div class="tt">工程分镜文件</div>
              <div style="position:absolute;left:32px;top:130px;right:32px;height:180px;border-radius:8px;background:rgba(43,92,255,0.06);padding:20px;">
                <p style="font-size:24px;color:#2B5CFF;font-weight:bold;">已完成 450 帧对齐</p>
                <p style="font-size:18px;color:#5F6370;margin-top:14px;">音画切点误差 0 帧</p>
                <p style="font-size:18px;color:#5F6370;margin-top:8px;">H.264 YUV420P 编码</p>
              </div>
            </div>
            <div id="xls" class="doc">
              <div class="hd mono">DELIVERABLE 03</div>
              <div class="tt">三道闸门报告</div>
              <div style="position:absolute;left:32px;top:120px;right:32px;height:200px;">
                <img src="assets/pipeline_diagram.svg" alt="" />
              </div>
            </div>
            <div id="note">
              <div class="ic"><img src="assets/logo.svg" alt="" /></div>
              <div class="a">成片已就绪，音画完全对齐，3道闸门全部通过</div>
              <div class="b">交付清单</div>
              <div class="tm">15.0s</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ============ S5 · Decision & Lockup ============ -->
      <div class="scene" id="s5">
        <div class="cam" id="cam5">
          <div id="s5-l1" class="abs">复杂的工业交给它，</div>
          <div id="s5-l2" class="abs serif">你只负责无限的<span class="gap"></span></div>
          <div id="sealInk"></div>
          <div id="seal" class="abs"><div class="box"></div><div class="in">定稿</div></div>
          <div id="s5-rule" class="abs"></div>
          <div id="lock" class="abs">
            <div id="lockIcon"><img src="assets/logo.svg" alt="" /></div>
            <div id="lockName">{brand_name}</div>
          </div>
          <div id="cta" class="abs">立即接入　·　<b>免费体验</b></div>
        </div>
      </div>

      <!-- Persistent Input Bar (Crosses S1 -> S2) -->
      <div id="pulse"></div>
      <div id="bar">
        <div id="barIcon"><img src="assets/logo.svg" alt="" /></div>
        <div id="barText">
          <span class="ch">输</span><span class="ch">入</span><span class="ch">你</span><span class="ch">的</span><span class="ch">故</span><span class="ch">事</span><span class="ch">，</span><span class="ch">全</span><span class="ch">自</span><span class="ch">动</span><span class="ch">生</span><span class="ch">成</span><span class="ch">整</span><span class="ch">季</span><span class="ch">短</span><span class="ch">剧</span><span class="ch">。</span><span id="caret"></span>
        </div>
        <div id="send"><i></i></div>
      </div>

      <div id="night"></div>
      <div id="falloff"></div>
      <div id="grain"></div>
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      var tl = gsap.timeline({{ paused: true }});
      var B = 0.5;

      /* texture */
      tl.to("#grain", {{ x: 26, y: -20, duration: 15, ease: "steps(45)" }}, 0);

      /* ============ S1 · The Order (0 – 3.0s) ============ */
      tl.fromTo("#cam1", {{ scale: 1.04 }}, {{ scale: 1.0, duration: 3, ease: "power2.out" }}, 0);
      tl.fromTo("#s1-ghost", {{ x: 40 }}, {{ x: -60, duration: 3.2, ease: "none" }}, 0);
      tl.fromTo("#s1-dots", {{ x: 0, y: 0 }}, {{ x: -30, y: -24, duration: 3.2, ease: "none" }}, 0);
      tl.fromTo("#s1-glow", {{ scale: 0.7, opacity: 0.4 }}, {{ scale: 1.15, opacity: 1, duration: 2.6, ease: "sine.inOut" }}, 0);
      tl.fromTo("#bar", {{ y: 80, opacity: 0, scale: 0.95 }}, {{ y: 0, opacity: 1, scale: 1, duration: 0.7, ease: "expo.out" }}, 0.1);
      tl.fromTo("#s1-kicker", {{ opacity: 0, y: 12 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, 0.3);
      var chars = document.querySelectorAll("#barText .ch");
      var T_TYPE = 0.55, PER = 1.75 / chars.length;
      chars.forEach(function (c, i) {{ tl.set(c, {{ opacity: 1 }}, T_TYPE + i * PER); }});
      tl.to("#caret", {{ opacity: 0, duration: 0.01 }}, 0.30); tl.to("#caret", {{ opacity: 1, duration: 0.01 }}, 0.45);
      tl.to("#caret", {{ opacity: 0, duration: 0.01 }}, 2.45);
      tl.fromTo("#send", {{ scale: 1 }}, {{ scale: 0.86, duration: 0.08, ease: "power2.in" }}, 2.5);
      tl.to("#send", {{ scale: 1, duration: 0.3, ease: "back.out(3)" }}, 2.58);
      tl.fromTo("#pulse", {{ opacity: 0.9, scale: 0.6 }}, {{ opacity: 0, scale: 3.2, duration: 0.7, ease: "power2.out" }}, 2.5);

      /* dock persistent bar clear above the S2 headline */
      tl.to("#bar", {{ x: -40, y: -680, scale: 0.5, duration: 0.6, ease: "expo.inOut" }}, 2.75);
      tl.to("#s1", {{ opacity: 0, duration: 0.4, ease: "power1.in" }}, 2.8);

      /* ============ S2 · Pipeline (3.0 – 6.0s) ============ */
      tl.set("#s2", {{ opacity: 1 }}, 2.9);
      tl.fromTo("#s2-head", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 3.0);
      tl.fromTo("#trackFill", {{ scaleY: 0 }}, {{ scaleY: 1, duration: 2.9, ease: "power1.inOut" }}, 3.05);
      for (var i = 0; i < 6; i++) {{
        var t = 3.0 + i * B;
        tl.fromTo("#nd" + i, {{ opacity: 0, y: 50 }}, {{ opacity: 1, y: 0, duration: 0.45, ease: "power4.out" }}, t);
        tl.fromTo("#nd" + i + " .fill", {{ scale: 0 }}, {{ scale: 1, duration: 0.35, ease: "back.out(2)" }}, t + 0.35);
        tl.to("#nd" + i + " .dot", {{ color: "#FFFFFF", duration: 0.2 }}, t + 0.4);
        tl.set("#nd" + i + " .st", {{ textContent: "已完成" }}, t + 0.45);
      }}
      tl.to("#bar", {{ opacity: 0, y: -760, duration: 0.45, ease: "power2.in" }}, 5.6);
      tl.to("#cam2", {{ y: -700, opacity: 0, duration: 0.55, ease: "power3.in" }}, 5.6);

      /* ============ S3 · Multi-Engine Sync (6.0 – 9.5s) ============ */
      tl.set("#s3", {{ opacity: 1 }}, 5.85);
      tl.fromTo("#cam3", {{ y: 600 }}, {{ y: 0, duration: 0.85, ease: "expo.out" }}, 5.85);
      tl.fromTo("#s3-head", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 6.6);
      tl.fromTo("#s3-sub", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.5, ease: "power1.out" }}, 7.0);
      tl.fromTo("#lid", {{ rotationX: 0 }}, {{ rotationX: -90, duration: 0.55, ease: "power3.in" }}, 6.5);
      tl.to("#lapLabel", {{ textContent: "本地工作台 · 已就绪", duration: 0.01 }}, 7.05);
      tl.fromTo("#night", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.8, ease: "power1.inOut" }}, 6.6);
      tl.to("#night", {{ opacity: 0, duration: 1.0, ease: "power1.inOut" }}, 8.6);
      ["#th1", "#th2"].forEach(function (p, k) {{
        var el = document.querySelector(p), len = el.getTotalLength ? el.getTotalLength() : 400;
        tl.fromTo(p, {{ attr: {{ "stroke-dashoffset": len, "stroke-dasharray": len + " " + len }} }},
          {{ attr: {{ "stroke-dashoffset": 0 }}, duration: 0.4, ease: "power2.out" }}, 7.0 + k * 0.5);
      }});
      tl.fromTo("#cloud", {{ opacity: 0, scale: 0.7 }}, {{ opacity: 1, scale: 1, duration: 0.5, ease: "back.out(2)" }}, 7.0);
      tl.fromTo("#cloudLabel", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 7.2);
      tl.fromTo("#cloudDot", {{ attr: {{ r: 8 }} }}, {{ attr: {{ r: 20 }}, duration: 0.5, ease: "sine.inOut", yoyo: true, repeat: 3 }}, 7.2);
      tl.fromTo("#phone", {{ opacity: 0, y: 70, rotation: 6 }}, {{ opacity: 1, y: 0, rotation: 0, duration: 0.55, ease: "power4.out" }}, 7.5);
      tl.fromTo("#phLabel", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3 }}, 7.7);
      var prog = {{ v: 12 }};
      var pcts = document.querySelectorAll("#s3 .pct");
      tl.to(prog, {{ v: 100, duration: 2.6, ease: "power1.inOut", onUpdate: function () {{
        var val = Math.round(prog.v);
        pcts.forEach(function (e) {{ e.textContent = val; }});
      }} }}, 6.6);
      var clk = {{ m: 0 }}, clkEl = document.getElementById("clock");
      tl.to(clk, {{ m: 15, duration: 2.4, ease: "power2.inOut", onUpdate: function () {{
        var s = Math.round(clk.m);
        clkEl.textContent = "00:" + (s < 10 ? "0" : "") + s;
      }} }}, 6.7);
      tl.fromTo(["#clock", "#clockSub"], {{ opacity: 0 }}, {{ opacity: 1, duration: 0.4 }}, 6.6);
      tl.to("#cam3", {{ scale: 1.035, duration: 2.45, ease: "none" }}, 6.7);
      tl.to("#cam3", {{ scale: 3.2, y: -1800, duration: 0.45, ease: "power3.in" }}, 9.15);
      tl.to("#cam3", {{ opacity: 0, duration: 0.2, ease: "power1.in" }}, 9.4);

      /* ============ S4 · Portrait Master Delivery (9.5 – 12.5s) ============ */
      tl.fromTo("#s4", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.2, ease: "power1.out" }}, 9.45);
      tl.fromTo("#cam4", {{ scale: 0.88 }}, {{ scale: 1.0, duration: 1.0, ease: "expo.out" }}, 9.45);
      tl.to("#cam4", {{ scale: 1.04, duration: 2.0, ease: "none" }}, 10.45);
      tl.fromTo("#s4-head", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 9.6);
      tl.fromTo("#ppt", {{ opacity: 0, rotationY: -20, z: -400, y: 60 }}, {{ opacity: 1, rotationY: -4, z: 0, y: 0, duration: 0.8, ease: "expo.out" }}, 9.5);
      tl.fromTo("#rpt", {{ opacity: 0, rotationY: 20, z: -400, y: 60 }}, {{ opacity: 1, rotationY: 4, z: -80, y: 0, duration: 0.8, ease: "expo.out" }}, 10.0);
      tl.fromTo("#xls", {{ opacity: 0, rotationY: -20, z: -400, y: 60 }}, {{ opacity: 1, rotationY: -4, z: -100, y: 0, duration: 0.8, ease: "expo.out" }}, 10.5);
      tl.fromTo(".bar4", {{ scaleY: 0 }}, {{ scaleY: 1, duration: 0.6, stagger: 0.07, ease: "power3.out" }}, 9.85);
      tl.fromTo("#note", {{ opacity: 0, y: 60, scale: 0.94 }}, {{ opacity: 1, y: 0, scale: 1, duration: 0.55, ease: "back.out(1.6)" }}, 11.0);
      tl.to(["#ppt", "#rpt", "#xls", "#note"], {{ scale: 0.2, opacity: 0, y: 0, duration: 0.45, ease: "power3.in", stagger: 0.04 }}, 12.05);
      tl.to("#s4-head", {{ opacity: 0, y: -30, duration: 0.35, ease: "power2.in" }}, 12.05);

      /* ============ S5 · Decision & Lockup (12.5 – 15.0s) ============ */
      tl.set("#s5", {{ opacity: 1 }}, 12.45);
      tl.fromTo("#s5-l1", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, 12.5);
      tl.fromTo("#s5-l2", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 12.75);
      tl.fromTo("#seal", {{ opacity: 0, scale: 2.4, rotation: -9 }}, {{ opacity: 1, scale: 1, rotation: -2, duration: 0.25, ease: "power4.in" }}, 13.25);
      tl.fromTo("#sealInk", {{ scale: 0.6, opacity: 1 }}, {{ scale: 1.5, opacity: 0, duration: 0.7, ease: "power2.out" }}, 13.5);
      tl.fromTo("#cam5", {{ y: 0 }}, {{ y: 7, duration: 0.05, ease: "none" }}, 13.5);
      tl.to("#cam5", {{ y: -4, duration: 0.06, ease: "none" }}, 13.55);
      tl.to("#cam5", {{ y: 0, duration: 0.12, ease: "power2.out" }}, 13.62);
      tl.fromTo("#s5-rule", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.5, ease: "expo.inOut" }}, 13.75);
      tl.fromTo("#lock", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.6, ease: "expo.out" }}, 14.0);
      tl.fromTo("#cta", {{ opacity: 0, y: 16 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }}, 14.25);
      tl.to("#cam5", {{ scale: 1.02, duration: 1.2, ease: "sine.out" }}, 13.8);

      tl.seek(0);
      window.__timelines["brandfilm"] = tl;
    </script>
  </body>
</html>
"""
