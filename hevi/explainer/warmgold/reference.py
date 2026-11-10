"""拆对标节点（知识讲解 / 历史现场可用）。

只处理用户上传或声明有权的参考视频；不批量抓取、不读 cookie、不接下载器。
互动数据由用户填写或上传截图，统一标「用户提供」。每个数字都带证据级别：
``实测`` / ``估计`` / ``用户提供`` / ``未覆盖``（绝不把估算写成实测）。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFont

from hevi.explainer.warmgold import beats as beats_mod

TEXT_CACHE: dict[tuple[str, str], str] = {}
CTA_WORDS = ["关注", "点赞", "评论", "转发", "收藏", "订阅", "下期", "下集", "留言"]
PROMISE_WORDS = ["保证", "包你", "一定能", "必然", "100%", "稳赚", "必火", "必爆", "轻松成功"]
SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


def _evidence(value: Any, level: str) -> dict[str, Any]:
    return {"value": value, "evidence": level}


def _num(value: Any) -> float:
    try:
        return float(value)
    except TypeError, ValueError:
        return 0.0


def _font(size: int) -> Any:
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _frame_at(video: Path, t: float, dest: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, t):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-1",
            str(dest),
        ],
        capture_output=True,
        check=False,
    )


def _ocr(image_path: Path) -> str:
    key = (str(image_path), str(image_path.stat().st_mtime) if image_path.exists() else "")
    if key in TEXT_CACHE:
        return TEXT_CACHE[key]
    text = ""
    try:
        proc = subprocess.run(
            ["tesseract", str(image_path), "stdout", "-l", "chi_sim+eng"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        text = proc.stdout
        if not text.strip():
            proc = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "eng"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            text = proc.stdout
    except FileNotFoundError, subprocess.TimeoutExpired:
        text = ""
    text = " ".join(text.split())
    TEXT_CACHE[key] = text
    return text


def _contact_sheet(frames: list[Path], dest: Path, cols: int = 6) -> Path:
    thumbs: list[Image.Image] = []
    for frame in frames:
        try:
            thumbs.append(Image.open(frame).convert("RGB"))
        except OSError:
            continue
    if not thumbs:
        Image.new("RGB", (480, 270), (18, 14, 11)).save(dest)
        return dest
    w, h = thumbs[0].size
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * h), (18, 14, 11))
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % cols) * w, (i // cols) * h))
    sheet.save(dest, quality=88)
    return dest


def _frame_diff(a: Path, b: Path) -> float:
    try:
        ia = Image.open(a).convert("L").resize((64, 36))
        ib = Image.open(b).convert("L").resize((64, 36))
    except OSError:
        return 0.0
    diff = ImageChops.difference(ia, ib)
    hist = diff.histogram()
    total = sum(value * count for value, count in enumerate(hist[:256]))
    return round(total / (64 * 36 * 255), 4)


def _keywords(text: str) -> set[str]:
    words = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for i in range(len(run) - 1):
            words.add(run[i : i + 2])
    return words


def _verdict(ratios: dict[str, float]) -> dict[str, Any]:
    share = ratios.get("share_per_like", 0.0)
    save = ratios.get("save_per_like", 0.0)
    comment = ratios.get("comment_per_like", 0.0)
    if share >= 0.35:
        return {
            "use": "share",
            "label": "转发高",
            "action": "结尾替他说出那句话，让他直接转给某个人。",
            "evidence": "用户提供",
        }
    if save >= 0.40:
        return {
            "use": "save",
            "label": "收藏高",
            "action": "把结论做成一屏可截图的清单，结尾只提醒收藏。",
            "evidence": "用户提供",
        }
    if comment >= 0.08:
        return {
            "use": "comment",
            "label": "评论高",
            "action": "结尾留一个具体问题，不要泛泛求评论。",
            "evidence": "用户提供",
        }
    return {
        "use": "watch",
        "label": "互动均衡",
        "action": "先把反直觉结果讲清楚，结尾再选一种最轻的互动。",
        "evidence": "用户提供",
    }


def _transcript_text(transcript: Any) -> str:
    if isinstance(transcript, str):
        return transcript
    if isinstance(transcript, list):
        parts = []
        for item in transcript:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return ""


def _transcript_with_time(transcript: Any) -> list[dict[str, Any]]:
    if isinstance(transcript, list):
        rows = [
            {"t": _num(item.get("t") or item.get("start") or 0.0), "text": str(item["text"])}
            for item in transcript
            if isinstance(item, dict) and (item.get("text") or "")
        ]
        return sorted(rows, key=lambda r: r["t"])
    if isinstance(transcript, str) and transcript.strip():
        return [
            {"t": 0.0, "text": line.strip()} for line in transcript.splitlines() if line.strip()
        ]
    return []


def decompose(payload: dict[str, Any], workdir: str | Path) -> dict[str, Any]:
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    coverage: dict[str, bool] = {}

    interactions = dict(payload.get("interactions") or {})
    likes = _num(interactions.get("likes"))
    ratios = {
        "share_per_like": round(_num(interactions.get("shares")) / likes, 4) if likes else 0.0,
        "save_per_like": round(_num(interactions.get("saves")) / likes, 4) if likes else 0.0,
        "comment_per_like": round(_num(interactions.get("comments")) / likes, 4) if likes else 0.0,
    }
    coverage["interactions"] = bool(likes)
    if not likes:
        warnings.append("没有互动数据：用途判断跳过，不猜。")
    usage = _verdict(ratios)
    usage["evidence"] = "用户提供" if likes else "未覆盖"

    video_path = str(payload.get("video_path") or "").strip()
    video = Path(video_path) if video_path else None
    if video and not video.is_file():
        warnings.append(f"参考视频不存在：{video_path}")
        video = None
    coverage["video"] = bool(video)

    duration = beats_mod.ffprobe_duration(video) if video else 0.0
    music = beats_mod.analyze_music(video) if video and duration > 1.0 else None
    if video:
        coverage["music"] = bool(music and music.get("source") == "measured")
    else:
        coverage["music"] = False

    transcript_rows = _transcript_with_time(payload.get("transcript"))
    transcript = _transcript_text(payload.get("transcript"))
    coverage["transcript"] = bool(transcript_rows)

    screen_texts: list[dict[str, Any]] = []
    frames: list[Path] = []
    burst_cards: list[dict[str, Any]] = []
    sheet_path = work / "reference_contact_sheet.jpg"
    if video:
        step = 1.0
        count = max(1, int(duration))
        for i in range(count):
            dest = work / f"frame_{i:04d}.jpg"
            _frame_at(video, i * step, dest)
            if dest.is_file():
                frames.append(dest)
                text = _ocr(dest)
                if text:
                    screen_texts.append(
                        {
                            "t": round(i * step, 3),
                            "text": text,
                            "evidence": "实测",
                        }
                    )
        _contact_sheet(frames, sheet_path)
        # 爆点卡：字变多、画面变化、音乐能量三者取前 3 秒。
        diffs = [(i, _frame_diff(frames[i - 1], frames[i])) for i in range(1, len(frames))]
        text_change: dict[float, int] = {}
        for item in screen_texts:
            text_change[float(item["t"])] = len(str(item["text"]))
        scored = []
        for i, _t in enumerate(range(len(frames))):
            t = float(i)
            d = next((v for idx, v in diffs if idx == i), 0.0)
            words = text_change.get(t, 0)
            energy = 0.0
            if music:
                bar = int(t / max(0.4, 4 * float(music.get("beat_s") or 0.5)))
                bars = music.get("energy_per_bar") or []
                if bars and bar < len(bars):
                    energy = float(bars[bar])
            score = d * 2 + min(1.0, words / 24) + min(1.0, energy / 6)
            scored.append((score, i, d, words, energy))
        for score, i, d, words, energy in sorted(scored, reverse=True)[:3]:
            burst_cards.append(
                {
                    "t": float(i),
                    "score": round(score, 3),
                    "evidence": {
                        "read_speed_chars_per_s": {
                            "value": words,
                            "evidence": "实测" if words else "未覆盖",
                        },
                        "frame_change": {"value": d, "evidence": "实测"},
                        "music_energy": {
                            "value": round(energy, 3),
                            "evidence": "实测" if music else "未覆盖",
                        },
                    },
                }
            )
        coverage["screen_text"] = bool(screen_texts)
    else:
        Image.new("RGB", (480, 270), (18, 14, 11)).save(sheet_path)
        coverage["screen_text"] = False

    anchor = str(payload.get("anchor") or "").strip()
    contrast = str(payload.get("contrast") or "").strip()
    if not anchor:
        warnings.append("信息差缺「锚」：观众以为的是什么？不补不写脚本。")
    if not contrast:
        warnings.append("信息差缺「反差」：实际是什么？不补不写脚本。")
    anchor_daily = bool(payload.get("anchor_daily"))
    if anchor and not anchor_daily:
        warnings.append(f"锚「{anchor}」不是日常可见物，观众可能没有体感。")

    psych = list(payload.get("psych_chain") or [])
    if len(psych) < 4:
        warnings.append("心理链不足 4 环：被说中→想起谁→卸下什么→想做什么。")

    top_comments = [str(c) for c in (payload.get("top_comments") or []) if str(c).strip()]
    direction = str(payload.get("our_direction") or "").strip()
    comment_vs_direction: dict[str, Any] = {
        "top_comment_count": {"value": len(top_comments), "evidence": "用户提供"},
        "our_direction": direction,
        "overlap": None,
        "aligned": None,
    }
    if top_comments and direction:
        kw_comment = _keywords(" ".join(top_comments))
        kw_direction = _keywords(direction)
        overlap = len(kw_comment & kw_direction) / max(1, len(kw_comment | kw_direction))
        comment_vs_direction["overlap"] = round(overlap, 3)
        comment_vs_direction["aligned"] = overlap >= 0.06
        if overlap < 0.06:
            warnings.append("高赞评论主旨与我们的方向不一致：先确认观众到底在讨论什么。")
    else:
        warnings.append("缺高赞评论或我们的方向：无法比对。")

    flaws: list[dict[str, str]] = []
    lower = (transcript + " " + " ".join(str(s["text"]) for s in screen_texts)).strip()
    if not lower:
        warnings.append("没有逐字稿/屏幕字：原片漏洞只能标未覆盖。")
    if any(w in transcript for w in PROMISE_WORDS):
        flaws.append(
            {"type": "话太满", "evidence": "实测", "fix": "删掉成功承诺，只讲条件与结果。"}
        )
    numbers = re.findall(r"\d+(?:\.\d+)?%?", transcript)
    if numbers and not re.search(r"来源|出处|据|数据来自", transcript):
        flaws.append(
            {"type": "数据错配风险", "evidence": "估计", "fix": "为每个数字补出处，或标「示意」。"}
        )
    if re.search(r"(概念|原理|机制|理论)", transcript) and not screen_texts:
        flaws.append(
            {"type": "概念没画出", "evidence": "估计", "fix": "给抽象概念配一个可看的零件。"}
        )
    for item in screen_texts:
        text = str(item["text"])
        if len(text) > 22:
            flaws.append(
                {
                    "type": "字太快",
                    "evidence": "实测",
                    "at": item["t"],
                    "fix": "一屏字太多，按 6 字/秒 重排。",
                }
            )
            break
    tail = transcript[-max(1, len(transcript) // 5) :] if transcript else ""
    if tail and not any(w in tail for w in CTA_WORDS):
        flaws.append(
            {"type": "结尾无动作", "evidence": "估计", "fix": "结尾加一个具体、单一的互动。"}
        )

    sentences = [s.strip() for s in SENTENCE_SPLIT.split(transcript) if 6 <= len(s.strip()) <= 60]
    banned = list(dict.fromkeys(sentences))[:40]
    if not banned:
        warnings.append("没有可用的原句：禁用清单为空，脚本查重将无事可做。")

    return {
        "schema": "hevi.warmgold.reference_breakdown/1",
        "source": {
            "video": video_path or "",
            "rights_declared": bool(payload.get("rights_declared")),
            "duration_s": _evidence(round(duration, 3), "实测" if video else "未覆盖"),
            "contact_sheet": str(sheet_path),
        },
        "coverage": coverage,
        "warnings": warnings,
        "interactions": {
            "counts": {
                k: _evidence(interactions.get(k), "用户提供")
                for k in ("likes", "shares", "saves", "comments")
            },
            "ratios": {
                k: _evidence(v, "用户提供" if likes else "未覆盖") for k, v in ratios.items()
            },
            "audience_use": usage,
        },
        "burst_cards": burst_cards,
        "screen_text": screen_texts,
        "music": music,
        "information_gap": {
            "anchor": _evidence(anchor, "用户提供" if anchor else "未覆盖"),
            "contrast": _evidence(contrast, "用户提供" if contrast else "未覆盖"),
            "anchor_daily": _evidence(anchor_daily, "用户提供"),
        },
        "psych_chain": psych
        or [
            {"stage": s, "value": "", "evidence": "未覆盖"}
            for s in ("被说中", "想起谁", "卸下什么", "想做什么")
        ],
        "top_comment_vs_direction": comment_vs_direction,
        "original_flaws": flaws,
        "banned_sentences": banned,
        "requires_confirmation": True,
    }


def write_report(payload: dict[str, Any], workdir: str | Path) -> tuple[Path, Path]:
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    json_path = work / "reference_breakdown.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path = work / "reference_breakdown.html"
    html_path.write_text(render_html(payload), encoding="utf-8")
    return json_path, html_path


def render_html(payload: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    rows = []
    for key, value in (payload.get("coverage") or {}).items():
        rows.append(f"<tr><td>{esc(key)}</td><td>{'有' if value else '未覆盖'}</td></tr>")
    cards = "".join(
        f"<li><b>{c['t']:.0f}s</b> 分数 {c['score']}（读速 {c['evidence']['read_speed_chars_per_s']['value']} 字/秒，"
        f"画面变化 {c['evidence']['frame_change']['value']}）</li>"
        for c in payload.get("burst_cards") or []
    )
    flaws = "".join(
        f"<li><b>{esc(f['type'])}</b> · {esc(f['evidence'])} · {esc(f['fix'])}</li>"
        for f in payload.get("original_flaws") or []
    )
    warns = "".join(f"<li>{esc(w)}</li>" for w in payload.get("warnings") or [])
    banned = "".join(f"<li>{esc(s)}</li>" for s in payload.get("banned_sentences") or [])
    sheet = payload.get("source", {}).get("contact_sheet", "")
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>拆解总览</title><style>
body{{background:#120E0B;color:#F2E8D5;font:16px/1.7 "Noto Sans CJK SC",sans-serif;margin:0;padding:48px}}
h1,h2{{font-family:"Noto Serif CJK SC",serif;color:#E4CB92}} main{{max-width:980px;margin:auto}}
table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #3a2c20;padding:8px;text-align:left}}
code{{color:#C8A96A}} img{{max-width:100%;border:1px solid #3a2c20}} .warn{{color:#C97A6A}}
section{{margin:36px 0}}</style></head><body><main>
<h1>拆解总览</h1>
<p>每个数字都带证据级别：实测 / 估计 / 用户提供 / 未覆盖。此页需用户确认后才写脚本。</p>
<section><h2>覆盖</h2><table>{rows}</table></section>
<section><h2>互动比例 → 用途</h2><pre>{esc(json.dumps(payload.get("interactions"), ensure_ascii=False, indent=2))}</pre></section>
<section><h2>爆点卡</h2><ul>{cards}</ul><img src="{esc(Path(sheet).name)}" alt="联系表"></section>
<section><h2>信息差 / 心理链</h2><pre>{esc(json.dumps({"gap": payload.get("information_gap"), "psych": payload.get("psych_chain"), "comment": payload.get("top_comment_vs_direction")}, ensure_ascii=False, indent=2))}</pre></section>
<section><h2>原片漏洞（超越点）</h2><ul>{flaws}</ul></section>
<section><h2 class="warn">警告</h2><ul>{warns}</ul></section>
<section><h2>原句禁用清单</h2><ol>{banned}</ol></section>
</main></body></html>"""


def require_confirmation(payload: dict[str, Any], confirmed: bool) -> None:
    if payload.get("requires_confirmation") and not confirmed:
        raise PermissionError("拆解总览未确认：用户确认后才写脚本。")
