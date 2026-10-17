#!/usr/bin/env python3
"""Archify E2E 样片 —— 一个网页请求是怎么到达服务器的。

镜头序列(9:16 竖版, 720x1280):
  1. 钩子(标题卡, PIL 绘制) + 本地搜索素材 mars_camera_product.jpg
  2. 架构图(archify architecture)—— 用户/CDN/负载均衡/API/Redis/Postgres
  3. 时序图(archify sequence)—— 浏览器→API→Redis→Postgres 往返
  4. 生命周期(archify lifecycle, 基于真实 example)—— 发布状态机
  5. 数据流(archify dataflow)—— 生产者→中转→处理器→状态→消费者
  6. 工作流(archify workflow)—— 接入层/业务层请求处理流程
  7. 结尾(标题卡 + 本地搜索素材 astronaut_glove_product.jpg)

每个 archify 镜头都走完整路径:
  build_ir → render_archify (deliver CLI) → capture_png (chromium)
  → detect_overflow (browser-check)

配音: espeak 本地 TTS(离线, 无网络依赖)。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "output" / "archify_e2e"
SHOTS = OUT / "shots"
AUDIO = OUT / "audio"

sys.path.insert(0, str(REPO))

from hevi.visuals.archify_source import (
    ArchifyRenderError,
    build_ir,
    capture_png,
    detect_overflow,
    render_archify,
)
from hevi.visuals.router import route_visual
from hevi.visuals.search_source import ensure_local_copy, scan_local_images


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tts(text: str, out_wav: Path, *, voice: str = "zh", speed: int = 150) -> float:
    """espeak 本地 TTS。返回时长(秒)。"""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["espeak", "-v", voice, "-s", str(speed), "-w", str(out_wav), text]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not out_wav.exists():
        raise RuntimeError(f"espeak 失败: {proc.stderr}")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out_wav)],
        capture_output=True, text=True, timeout=30,
    )
    return float(probe.stdout.strip())


def make_title_card(
    png_path: Path,
    lines: list[str],
    *,
    width: int = 720,
    height: int = 1280,
    bg: tuple[int, int, int] = (18, 20, 28),
    fg: tuple[int, int, int] = (240, 242, 248),
    font_size: int = 52,
) -> dict[str, Any]:
    """PIL 画竖版标题卡。"""
    from PIL import Image, ImageDraw, ImageFont

    png_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    font = ImageFont.truetype(font_path, font_size)
    total_h = len(lines) * (font_size + 24)
    y = (height - total_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((width - w) / 2, y), line, fill=fg, font=font)
        y += font_size + 24
    img.save(png_path)
    data = png_path.read_bytes()
    return {
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def run() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "topic": "一个网页请求是怎么到达服务器的",
        "aspect": "9:16",
        "canvas": [720, 1280],
        "tts_engine": "espeak (offline)",
        "shots": [],
    }

    # ---- 镜头 1: 钩子 —— 标题卡 + 搜索素材 --------------------------
    shot1_text = "一个网页请求是怎么到达服务器的?"
    card1 = SHOTS / "shot1-hook-card.png"
    card1_info = make_title_card(card1, ["一个网页请求是", "怎么到达", "服务器的?"])
    hits = scan_local_images()
    mars = next(h for h in hits if "mars_camera" in h.path)
    mars_copy = ensure_local_copy(mars, SHOTS, stem="shot1-mars")
    shot1_audio = AUDIO / "shot1.wav"
    shot1_dur = tts(shot1_text, shot1_audio)
    record["shots"].append({
        "index": 1,
        "type": "hook",
        "narration": shot1_text,
        "visual_source": "search",
        "reason": "真实产品图做钩子(本地素材库 mars_camera_product.jpg)",
        "visual_card": str(card1),
        "card_info": card1_info,
        "search_hit": {
            "path": str(mars_copy),
            "sha256": sha256_file(mars_copy),
            "source": "local",
            "match": mars.to_dict(),
        },
        "audio": str(shot1_audio),
        "audio_duration_s": shot1_dur,
    })

    # ---- 镜头 2: 架构图 —— archify architecture ----------------------
    shot2_text = "请求先经过 CDN, 再到负载均衡和 API 服务器, 最后查询数据库"
    route2 = route_visual(shot2_text)
    ir2 = build_ir(
        "architecture",
        title="网页请求架构",
        aspect="9:16",
        nodes=[
            {"id": "user", "type": "external", "label": "用户浏览器",
             "sublabel": "发起请求", "pos": [310, 60], "size": [140, 64]},
            {"id": "cdn", "type": "cloud", "label": "CDN",
             "sublabel": "边缘缓存", "pos": [310, 260], "size": [140, 64]},
            {"id": "lb", "type": "cloud", "label": "负载均衡",
             "sublabel": "流量分发", "pos": [310, 460], "size": [140, 64]},
            {"id": "api", "type": "backend", "label": "API 服务器",
             "sublabel": "业务逻辑", "pos": [310, 660], "size": [140, 64]},
            {"id": "redis", "type": "database", "label": "Redis",
             "sublabel": "缓存层", "pos": [310, 860], "size": [140, 64]},
            {"id": "db", "type": "database", "label": "Postgres",
             "sublabel": "持久化", "pos": [310, 1060], "size": [140, 64]},
        ],
        edges=[
            {"from": "user", "to": "cdn", "label": "HTTPS", "labelDy": 24},
            {"from": "cdn", "to": "lb", "label": "forward", "labelDy": 24},
            {"from": "lb", "to": "api", "label": "HTTP/2", "labelDy": 24},
            {"from": "api", "to": "redis", "label": "cache", "labelDy": 24},
            {"from": "api", "to": "db", "label": "SQL", "labelDy": 24},
        ],
    )
    r2 = render_archify(ir2, SHOTS / "shot2-architecture.html")
    png2 = SHOTS / "shot2-architecture.png"
    # Content requires 1604px height for 720 width (no overflow)
    png2_info = capture_png(SHOTS / "shot2-architecture.html", png2,
                            width=720, height=1604)
    ov2 = detect_overflow(SHOTS / "shot2-architecture.html", out_dir=SHOTS,
                          width=720, height=1604)
    shot2_audio = AUDIO / "shot2.wav"
    shot2_dur = tts(shot2_text, shot2_audio)
    record["shots"].append({
        "index": 2,
        "type": "architecture",
        "narration": shot2_text,
        "visual_source": "archify",
        "reason": route2.reason,
        "keywords": list(route2.keywords),
        "archify_type": "architecture",
        "ir_path": str(SHOTS / "shot2-architecture.html"),
        "visual": str(png2),
        "visual_info": png2_info,
        "deliver_receipt": {
            "ok": r2["ok"],
            "checksPassed": r2["validation"]["checksPassed"],
            "artifact_sha256": r2["artifact"]["sha256"],
        },
        "overflow_check": {
            "overflow": ov2["overflow"],
            "portrait_overflow": ov2["portrait_overflow"],
            "containment": ov2["containment"],
            "readability": ov2["readability"],
            "portrait_viewport": ov2["portrait_viewport"],
        },
        "audio": str(shot2_audio),
        "audio_duration_s": shot2_dur,
    })

    # ---- 镜头 3: 时序图 —— archify sequence --------------------------
    shot3_text = "浏览器发送请求, API 先查缓存, 缓存未命中再查数据库, 最后返回结果"
    route3 = route_visual(shot3_text)
    ir3 = build_ir(
        "sequence",
        title="请求时序",
        aspect="9:16",
        participants=[
            {"id": "browser", "type": "external", "label": "浏览器"},
            {"id": "api", "type": "backend", "label": "API"},
            {"id": "redis", "type": "database", "label": "Redis"},
            {"id": "db", "type": "database", "label": "Postgres"},
        ],
        messages=[
            {"from": "browser", "to": "api", "label": "GET /data", "y": 160},
            {"from": "api", "to": "redis", "label": "read cache", "y": 200},
            {"from": "redis", "to": "api", "label": "miss", "y": 240,
             "variant": "return"},
            {"from": "api", "to": "db", "label": "SELECT", "y": 280},
            {"from": "db", "to": "api", "label": "rows", "y": 320,
             "variant": "return"},
            {"from": "api", "to": "redis", "label": "set cache", "y": 360},
            {"from": "api", "to": "browser", "label": "200 JSON", "y": 400,
             "variant": "return"},
        ],
    )
    r3 = render_archify(ir3, SHOTS / "shot3-sequence.html")
    png3 = SHOTS / "shot3-sequence.png"
    # Content requires 1604px height for 720 width (no overflow)
    png3_info = capture_png(SHOTS / "shot3-sequence.html", png3,
                            width=720, height=1604)
    ov3 = detect_overflow(SHOTS / "shot3-sequence.html", out_dir=SHOTS,
                          width=720, height=1604)
    shot3_audio = AUDIO / "shot3.wav"
    shot3_dur = tts(shot3_text, shot3_audio)
    record["shots"].append({
        "index": 3,
        "type": "sequence",
        "narration": shot3_text,
        "visual_source": "archify",
        "reason": route3.reason,
        "keywords": list(route3.keywords),
        "archify_type": "sequence",
        "ir_path": str(SHOTS / "shot3-sequence.html"),
        "visual": str(png3),
        "visual_info": png3_info,
        "deliver_receipt": {
            "ok": r3["ok"],
            "checksPassed": r3["validation"]["checksPassed"],
            "artifact_sha256": r3["artifact"]["sha256"],
        },
        "overflow_check": {
            "overflow": ov3["overflow"],
            "portrait_overflow": ov3["portrait_overflow"],
            "containment": ov3["containment"],
            "readability": ov3["readability"],
            "portrait_viewport": ov3["portrait_viewport"],
        },
        "audio": str(shot3_audio),
        "audio_duration_s": shot3_dur,
    })

    # ---- 镜头 4: 生命周期 —— archify lifecycle -----------------------
    shot4_text = "请求从排队开始, 经过构建和验证, 成功后上线, 失败则回滚"
    route4 = route_visual(shot4_text)
    ir4 = json.load(open(
        REPO / "third_party/archify/archify/examples/deployment-release.lifecycle.json"
    ))
    ir4["meta"]["output"] = "shot4-lifecycle.html"
    ir4["meta"]["title"] = "请求生命周期"
    ir4["meta"].pop("animation", None)
    ir4["meta"].pop("visual_preset", None)
    ir4["meta"]["quality_profile"] = "standard"
    # Don't override viewBox — the example uses intrinsic canvas
    for t in ir4["transitions"]:
        if t.get("from") == "verifying" and t.get("to") == "approval":
            t["labelDy"] = 25
    r4 = render_archify(ir4, SHOTS / "shot4-lifecycle.html")
    png4 = SHOTS / "shot4-lifecycle.png"
    # Lifecycle uses intrinsic canvas, 1080x1920 fits without overflow
    png4_info = capture_png(SHOTS / "shot4-lifecycle.html", png4,
                            width=1080, height=1920)
    ov4 = detect_overflow(SHOTS / "shot4-lifecycle.html", out_dir=SHOTS,
                          width=1080, height=1920)
    shot4_audio = AUDIO / "shot4.wav"
    shot4_dur = tts(shot4_text, shot4_audio)
    record["shots"].append({
        "index": 4,
        "type": "lifecycle",
        "narration": shot4_text,
        "visual_source": "archify",
        "reason": route4.reason,
        "keywords": list(route4.keywords),
        "archify_type": "lifecycle",
        "ir_path": str(SHOTS / "shot4-lifecycle.html"),
        "visual": str(png4),
        "visual_info": png4_info,
        "deliver_receipt": {
            "ok": r4["ok"],
            "checksPassed": r4["validation"]["checksPassed"],
            "artifact_sha256": r4["artifact"]["sha256"],
        },
        "overflow_check": {
            "overflow": ov4["overflow"],
            "portrait_overflow": ov4["portrait_overflow"],
            "containment": ov4["containment"],
            "readability": ov4["readability"],
            "portrait_viewport": ov4["portrait_viewport"],
        },
        "audio": str(shot4_audio),
        "audio_duration_s": shot4_dur,
    })

    # ---- 镜头 5: 数据流 —— archify dataflow --------------------------
    shot5_text = "数据从浏览器流向边缘, 再到处理层, 最后存储和消费"
    route5 = route_visual(shot5_text)
    ir5 = build_ir(
        "dataflow",
        title="数据流向",
        aspect="9:16",
        stages=[
            {"label": "Sources"},
            {"label": "Ingest"},
            {"label": "Process"},
            {"label": "Store"},
            {"label": "Consume"},
        ],
        nodes=[
            {"id": "web", "type": "frontend", "label": "浏览器",
             "sublabel": "事件源", "stage": 0, "row": 0},
            {"id": "edge", "type": "cloud", "label": "边缘 API",
             "sublabel": "接入", "stage": 1, "row": 0},
            {"id": "stream", "type": "messagebus", "label": "事件流",
             "sublabel": "消息总线", "stage": 2, "row": 0},
            {"id": "store", "type": "database", "label": "数据仓库",
             "sublabel": "存储", "stage": 3, "row": 0},
            {"id": "dash", "type": "backend", "label": "看板",
             "sublabel": "消费", "stage": 4, "row": 0},
        ],
        flows=[
            {"from": "web", "to": "edge", "label": "events"},
            {"from": "edge", "to": "stream", "label": "ingest"},
            {"from": "stream", "to": "store", "label": "process"},
            {"from": "store", "to": "dash", "label": "query"},
        ],
    )
    # Dataflow needs wider canvas for 5 stages
    ir5["meta"]["viewBox"] = [1080, 1920]
    r5 = render_archify(ir5, SHOTS / "shot5-dataflow.html")
    png5 = SHOTS / "shot5-dataflow.png"
    # Content requires 2137px height for 1080 width (no overflow)
    png5_info = capture_png(SHOTS / "shot5-dataflow.html", png5,
                            width=1080, height=2137)
    ov5 = detect_overflow(SHOTS / "shot5-dataflow.html", out_dir=SHOTS,
                          width=1080, height=2137)
    shot5_audio = AUDIO / "shot5.wav"
    shot5_dur = tts(shot5_text, shot5_audio)
    record["shots"].append({
        "index": 5,
        "type": "dataflow",
        "narration": shot5_text,
        "visual_source": "archify",
        "reason": route5.reason,
        "keywords": list(route5.keywords),
        "archify_type": "dataflow",
        "ir_path": str(SHOTS / "shot5-dataflow.html"),
        "visual": str(png5),
        "visual_info": png5_info,
        "deliver_receipt": {
            "ok": r5["ok"],
            "checksPassed": r5["validation"]["checksPassed"],
            "artifact_sha256": r5["artifact"]["sha256"],
        },
        "overflow_check": {
            "overflow": ov5["overflow"],
            "portrait_overflow": ov5["portrait_overflow"],
            "containment": ov5["containment"],
            "readability": ov5["readability"],
            "portrait_viewport": ov5["portrait_viewport"],
        },
        "audio": str(shot5_audio),
        "audio_duration_s": shot5_dur,
    })

    # ---- 镜头 6: 工作流 —— archify workflow ----------------------
    shot6_text = "请求处理流程: 接收, 鉴权, 执行业务, 返回响应"
    route6 = route_visual(shot6_text)
    ir6 = build_ir(
        "workflow",
        title="请求处理工作流",
        aspect="9:16",
        lanes=[
            {"id": "edge", "label": "接入层"},
            {"id": "core", "label": "业务层"},
        ],
        nodes=[
            {"id": "recv", "type": "frontend", "label": "接收",
             "sublabel": "入口", "lane": "edge", "col": 0},
            {"id": "auth", "type": "security", "label": "鉴权",
             "sublabel": "JWT 校验", "lane": "core", "col": 1},
            {"id": "biz", "type": "backend", "label": "业务处理",
             "sublabel": "核心逻辑", "lane": "core", "col": 3},
            {"id": "done", "type": "backend", "label": "返回响应",
             "sublabel": "200 OK", "lane": "core", "col": 5},
        ],
        edges=[
            {"from": "recv", "to": "auth", "label": "verify"},
            {"from": "auth", "to": "biz", "label": "execute"},
            {"from": "biz", "to": "done", "label": "return"},
        ],
    )
    ir6["meta"]["viewBox"] = [1080, 1920]
    r6 = render_archify(ir6, SHOTS / "shot6-workflow.html")
    png6 = SHOTS / "shot6-workflow.png"
    # Content requires 2137px height for 1080 width (no overflow)
    png6_info = capture_png(SHOTS / "shot6-workflow.html", png6,
                            width=1080, height=2137)
    ov6 = detect_overflow(SHOTS / "shot6-workflow.html", out_dir=SHOTS,
                          width=1080, height=2137)
    shot6_audio = AUDIO / "shot6.wav"
    shot6_dur = tts(shot6_text, shot6_audio)
    record["shots"].append({
        "index": 6,
        "type": "workflow",
        "narration": shot6_text,
        "visual_source": "archify",
        "reason": route6.reason,
        "keywords": list(route6.keywords),
        "archify_type": "workflow",
        "ir_path": str(SHOTS / "shot6-workflow.html"),
        "visual": str(png6),
        "visual_info": png6_info,
        "deliver_receipt": {
            "ok": r6["ok"],
            "checksPassed": r6["validation"]["checksPassed"],
            "artifact_sha256": r6["artifact"]["sha256"],
        },
        "overflow_check": {
            "overflow": ov6["overflow"],
            "portrait_overflow": ov6["portrait_overflow"],
            "containment": ov6["containment"],
            "readability": ov6["readability"],
            "portrait_viewport": ov6["portrait_viewport"],
        },
        "audio": str(shot6_audio),
        "audio_duration_s": shot6_dur,
    })

    # ---- 镜头 7: 结尾 —— 标题卡 + 搜索素材 --------------------
    shot7_text = "这就是网页请求到达服务器的完整路径"
    card7 = SHOTS / "shot7-end-card.png"
    card7_info = make_title_card(
        card7,
        ["请求到达服务器的", "完整路径", "你学会了吗?"],
        font_size=48,
    )
    astro = next(h for h in hits if "astronaut_glove" in h.path)
    astro_copy = ensure_local_copy(astro, SHOTS, stem="shot7-astronaut")
    shot7_audio = AUDIO / "shot7.wav"
    shot7_dur = tts(shot7_text, shot7_audio)
    record["shots"].append({
        "index": 7,
        "type": "end",
        "narration": shot7_text,
        "visual_source": "search",
        "reason": "真实产品图做结尾(本地素材库 astronaut_glove_product.jpg)",
        "visual_card": str(card7),
        "card_info": card7_info,
        "search_hit": {
            "path": str(astro_copy),
            "sha256": sha256_file(astro_copy),
            "source": "local",
            "match": astro.to_dict(),
        },
        "audio": str(shot7_audio),
        "audio_duration_s": shot7_dur,
    })

    # ---- 汇总 --------------------------------------------------
    total_dur = sum(s["audio_duration_s"] for s in record["shots"])
    record["total_duration_s"] = total_dur
    record["shot_count"] = len(record["shots"])
    record_path = OUT / "record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"E2E 样片完成: {len(record['shots'])} 镜头, "
          f"总时长 {total_dur:.1f}s")
    print(f"记录: {record_path}")
    for s in record["shots"]:
        print(f"  [{s['index']}] {s['type']}: "
              f"{s['visual_source']} ({s['audio_duration_s']:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
