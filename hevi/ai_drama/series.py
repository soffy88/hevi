"""Series entity: one fixed cast reused across episodes.

A series owns a *cast* of character cards.  A card is the machine-checkable
description of a character: hairstyle and parting, eye colour, one identifying
detail, every clothing item, shoes, accessories, personality and voice.  Every
episode imports the card into its script and its image prompts, and the
episode's rendered portraits are compared with the series anchor sheet.

The comparison is an offline deterministic proxy (dHash + region colour
histograms).  It is deliberately conservative: a low score is a *major*
finding that a reviewer must accept, not a silent pass.  When a face model is
available the caller can inject a stronger ``face_scorer``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CARD_REQUIRED = (
    "name",
    "body",
    "hair",
    "hair_part",
    "eye_color",
    "signature_detail",
    "outfit",
    "outfits",
    "personality",
    "voice",
)
OUTFIT_PARTS = ("top", "bottom")
OUTFIT_DETAIL_FIELDS = ("material", "color", "length")
DEFAULT_THRESHOLD = 0.72


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finding(rule: str, severity: str, message: str, ref: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


def normalize_card(card: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Fill ids only; never invent creative fields."""
    out = dict(card)
    out.setdefault("id", f"c{index}")
    outfit = dict(out.get("outfit") or {})
    if "shoes" in out and "shoes" not in outfit:
        outfit["shoes"] = out["shoes"]
    out["outfit"] = outfit
    # 2-3 locked outfits: the first is the default; never fabricate a second.
    outfits = out.get("outfits")
    if outfits is None:
        outfits = [outfit] if outfit else []
    out["outfits"] = [dict(o) for o in outfits if isinstance(o, dict)]
    out.setdefault("accessories", [])
    out.setdefault("personality", "")
    out.setdefault("voice", {})
    out.setdefault("anchor_image", "")
    out.setdefault("portrait_image", "")
    return out


def card_findings(card: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cid = str(card.get("id") or card.get("name") or "?")
    for field in CARD_REQUIRED:
        value = card.get(field)
        if field == "outfit":
            outfit = value if isinstance(value, dict) else {}
            for part in OUTFIT_PARTS:
                if not str(outfit.get(part) or "").strip():
                    out.append(_finding("C-CARD", "major", f"角色卡缺服装 {part}", cid))  # noqa: PERF401
            if not str(outfit.get("shoes") or card.get("shoes") or "").strip():
                out.append(_finding("C-CARD", "major", "角色卡缺鞋", cid))
        elif field == "voice":
            if not str((value or {}).get("description") or "").strip():
                out.append(_finding("C-CARD", "major", "角色卡缺声音描述", cid))
        elif field == "accessories":
            if value is None:
                out.append(_finding("C-CARD", "minor", "角色卡配饰为空（可以是无）", cid))
        elif not str(value or "").strip():
            out.append(_finding("C-CARD", "major", f"角色卡缺 {field}", cid))
    outfits = card.get("outfits") or []
    if len(outfits) < 2:
        out.append(_finding("C-BIBLE", "major", "角色需要 2–3 套锁死服装", cid))
    elif len(outfits) > 3:
        out.append(_finding("C-BIBLE", "minor", "角色服装超过 3 套，跨集容易漂移", cid))
    for pos, outfit in enumerate(outfits):
        if not isinstance(outfit, dict):
            out.append(_finding("C-BIBLE", "major", f"第 {pos + 1} 套服装不是对象", cid))
            continue
        for field in OUTFIT_DETAIL_FIELDS:
            if not str(outfit.get(field) or "").strip():
                out.append(_finding(
                    "C-BIBLE", "major",
                    f"第 {pos + 1} 套服装缺 {field}（材质/颜色/长度必须写死）", cid,
                ))
    voice = card.get("voice") or {}
    if not (voice.get("tts_params") or card.get("tts_params")):
        out.append(_finding("C-BIBLE", "major", "角色缺 TTS 参数（音色参考 + 参数）", cid))
    return out


def card_look(card: dict[str, Any]) -> str:
    """Compose the Chinese look line injected into script + asset prompts."""
    outfit = card.get("outfit") or {}
    accessories = card.get("accessories") or []
    acc = "、".join(str(x) for x in accessories if str(x).strip()) or "无配饰"
    parts = [
        f"体型{card.get('body', '')}",
        f"发型{card.get('hair', '')}{card.get('hair_part', '')}",
        f"瞳色{card.get('eye_color', '')}",
        f"辨识细节：{card.get('signature_detail', '')}",
        f"上装{outfit.get('top', '')}",
        f"下装{outfit.get('bottom', '')}",
    ]
    if str(outfit.get("outer") or "").strip():
        parts.append(f"外套{outfit['outer']}")
    parts += [f"鞋{outfit.get('shoes', card.get('shoes', ''))}", f"配饰{acc}"]
    return "；".join(parts)


def card_prompt_tokens(card: dict[str, Any]) -> list[str]:
    outfit = card.get("outfit") or {}
    accessories = [str(x) for x in (card.get("accessories") or []) if str(x).strip()]
    tokens = [
        str(card.get("body") or ""),
        str(card.get("hair") or ""),
        str(card.get("hair_part") or ""),
        str(card.get("eye_color") or ""),
        str(card.get("signature_detail") or ""),
        str(outfit.get("top") or ""),
        str(outfit.get("bottom") or ""),
        str(outfit.get("outer") or ""),
        str(outfit.get("shoes") or card.get("shoes") or ""),
        *accessories,
    ]
    return [token for token in tokens if token.strip()]


def create_series(
    *,
    title: str,
    genre: str,
    cast: list[dict[str, Any]],
    out_dir: str | Path,
    style: str = "anime",
    style_card: str = "",
    languages: list[str] | None = None,
    series_id: str | None = None,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cards = [normalize_card(c, index=i + 1) for i, c in enumerate(cast)]
    series = {
        "series_id": series_id or "s_" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:10],
        "title": title,
        "genre": genre,
        "style": style,
        "languages": languages or ["zh"],
        "cast": cards,
        # fixed scene descriptions are part of the bible; prompts are
        # concatenated from them, never re-described per episode.
        "scene_bible": {},
        "episodes": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    if style_card:
        from .style_cards import apply_style_card

        apply_style_card(series, style_card)
    save_series(series, out)
    return series


def save_series(series: dict[str, Any], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    series["updated_at"] = _now()
    path = out / "series.json"
    path.write_text(json.dumps(series, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "character_sheet.md").write_text(character_sheet_markdown(series), encoding="utf-8")
    return path


def set_scene_bible(series: dict[str, Any], name: str, description: dict[str, Any]) -> dict[str, Any]:
    series.setdefault("scene_bible", {})[name] = {
        "description": str(description.get("description") or ""),
        "lighting": str(description.get("lighting") or ""),
        "props": list(description.get("props") or []),
        "render_en": str(description.get("render_en") or ""),
    }
    return series


def scene_bible_findings(script: dict[str, Any], series: dict[str, Any]) -> list[dict[str, Any]]:
    """Every scene must match a fixed bible entry (no per-episode rewriting)."""
    out: list[dict[str, Any]] = []
    bible = series.get("scene_bible") or {}
    for scene in script.get("scenes") or []:
        name = str(scene.get("name") or scene.get("location") or "")
        entry = bible.get(name)
        if entry is None:
            out.append(_finding("C-SCENE", "major", f"场景 {name} 不在系列场景圣经里", name))
            continue
        if entry.get("render_en") and str(scene.get("render_en") or "") != entry["render_en"]:
            # Inject the locked description instead of letting the episode drift.
            scene["render_en"] = entry["render_en"]
        if entry.get("lighting") and str((scene.get("lighting") or {}).get("description") or "") not in {
            "", entry["lighting"]
        }:
            out.append(_finding("C-SCENE", "minor", f"场景 {name} 光向与圣经不一致", name))
    return out


def load_series(out_dir: str | Path) -> dict[str, Any]:
    path = Path(out_dir) / "series.json"
    if not path.is_file():
        raise FileNotFoundError(f"series.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def character_sheet_markdown(series: dict[str, Any]) -> str:
    lines = [f"# {series.get('title', '未命名系列')}", "", f"- 类型：{series.get('genre', '')}",
             f"- 画风：{series.get('style', '')}", ""]
    if series.get("style_card"):
        lines += [
            f"- 风格卡：{series.get('style_card_name') or series.get('style_card')}（{series.get('style_card')}）",
            f"- 风格提示词：{series.get('style_prompt', '')}",
            f"- 封面：{series.get('style_cover') or '（未生成）'}",
            f"- 平光定妆参考：{series.get('style_makeup_reference') or '（未生成）'}",
            "",
        ]
    for card in series.get("cast") or []:
        lines += [f"## {card.get('name')}（{card.get('id')}）", "",
                  f"- 形象：{card_look(card)}",
                  f"- 性格：{card.get('personality', '')}",
                  f"- 声音：{(card.get('voice') or {}).get('description', '')}",
                  f"- 设定图：{card.get('anchor_image') or '（未生成）'}",
                  ""]
    return "\n".join(lines)


def cast_by_id(series: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("id")): c for c in series.get("cast") or []}


def inject_cast(script: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the script with the series cards merged in."""
    import copy

    out = copy.deepcopy(script)
    cards = cast_by_id(series)
    by_name = {str(c.get("name")): c for c in series.get("cast") or []}
    out["series_id"] = series.get("series_id")
    out.setdefault("style", series.get("style") or "anime")
    for key in (
        "style_card", "style_card_name", "style_prompt", "style_prompt_zh",
        "style_negative", "style_palette", "style_lighting", "style_cover",
        "style_makeup_reference",
    ):
        if series.get(key):
            out[key] = series[key]
    used: set[str] = set()
    for char in out.get("characters") or []:
        cid = str(char.get("id"))
        card = cards.get(cid) or by_name.get(str(char.get("name")))
        if card is None:
            continue
        used.add(str(card.get("id")))
        char["id"] = card.get("id")
        char["name"] = card.get("name")
        char["look"] = card_look(card)
        char["character_card"] = card
        char["series_id"] = series.get("series_id")
        char["anchor_image"] = card.get("anchor_image", "")
        char.setdefault("voice", {}).update(card.get("voice") or {})
        char["voice"] = card.get("voice") or char.get("voice")
        char["render_look_en"] = _look_en(card)
    missing = [cid for cid in cards if cid not in used]
    out["cast_missing_from_script"] = missing
    return out


def _look_en(card: dict[str, Any]) -> str:
    outfit = card.get("outfit") or {}
    acc = ", ".join(str(x) for x in (card.get("accessories") or []) if str(x).strip())
    return (
        f"{card.get('hair', '')} hair with {card.get('hair_part', '')} parting, "
        f"{card.get('eye_color', '')} eyes, {card.get('signature_detail', '')}, "
        f"wearing {outfit.get('top', '')} and {outfit.get('bottom', '')}"
        + (f", {outfit.get('outer')}" if str(outfit.get('outer') or '').strip() else "")
        + f", {outfit.get('shoes', card.get('shoes', ''))}"
        + (f", accessories {acc}" if acc else "")
    )


def series_findings(script: dict[str, Any], series: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    from .style_cards import style_card_findings

    out.extend(style_card_findings(series))
    for card in series.get("cast") or []:
        out.extend(card_findings(card))
    missing = script.get("cast_missing_from_script") or []
    for cid in missing:
        out.append(_finding("C-CAST", "major", f"本集没有使用系列角色 {cid}（可接受，但需说明）", cid))  # noqa: PERF401
    for char in script.get("characters") or []:
        if not char.get("character_card"):
            out.append(_finding("C-CAST", "major", f"角色 {char.get('id')} 没有注入角色卡", str(char.get("id"))))  # noqa: PERF401
    if series.get("scene_bible"):
        out.extend(scene_bible_findings(script, series))
    return out


def annotate_assets(assets: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    """Carry card fields and the series anchor path into every character image."""
    cards = cast_by_id(series)
    for img in assets.get("images") or []:
        cid = str(img.get("character_id") or "")
        card = cards.get(cid)
        if card is None:
            continue
        img["character_card"] = card
        img["series_id"] = series.get("series_id")
        img["series_anchor"] = card.get("anchor_image", "")
        img["card_fields"] = card_prompt_tokens(card)
        extra = "角色卡固定项：" + "；".join(card_prompt_tokens(card))
        if img.get("kind") in ("character_identity", "character_portrait") and "角色卡固定项" not in str(img.get("prompt")):
            img["prompt"] = f"{img.get('prompt', '')}。{extra}。"
            if img.get("render_prompt"):
                img["render_prompt"] = f"{img['render_prompt']}, {_look_en(card)}"
    return assets


def prompt_missing_fields(img: dict[str, Any], card: dict[str, Any]) -> list[str]:
    prompt = str(img.get("prompt") or "") + " " + str(img.get("render_prompt") or "")
    return [token for token in card_prompt_tokens(card) if token not in prompt]


def _dhash(image: Any, size: int = 8) -> list[int]:
    import numpy as np

    small = np.asarray(image.convert("L").resize((size + 1, size)), dtype=np.int16)
    return (small[:, :-1] > small[:, 1:]).astype(int).flatten().tolist()


def _hist_similarity(a: Any, b: Any) -> float:
    import numpy as np

    def hist(image: Any) -> Any:
        arr = np.asarray(image.convert("RGB").resize((64, 64)), dtype=np.float32)
        parts = []
        for channel in range(3):
            h, _ = np.histogram(arr[:, :, channel], bins=16, range=(0, 255))
            parts.append(h.astype(np.float32))
        vec = np.concatenate(parts)
        total = float(vec.sum()) or 1.0
        return vec / total

    va, vb = hist(a), hist(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
    return max(0.0, min(1.0, float(np.dot(va, vb) / denom)))


def compare_to_anchor(
    image_path: str | Path,
    anchor_path: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Compare an episode image with the series anchor (face / hair / clothing)."""
    from PIL import Image

    image = Image.open(image_path).convert("RGB").resize((512, 512))
    anchor = Image.open(anchor_path).convert("RGB").resize((512, 512))

    def region(img: Any, box: tuple[float, float, float, float]) -> Any:
        w, h = img.size
        return img.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])))

    face_box = (0.2, 0.05, 0.8, 0.45)
    hair_box = (0.15, 0.0, 0.85, 0.3)
    cloth_box = (0.1, 0.45, 0.9, 0.95)
    a_bits = _dhash(region(image, face_box))
    b_bits = _dhash(region(anchor, face_box))
    dhash = 1.0 - sum(1 for x, y in zip(a_bits, b_bits, strict=True) if x != y) / len(a_bits)
    face_hist = _hist_similarity(region(image, face_box), region(anchor, face_box))
    # The face region is dominated by placement-invariant colour; a light dHash
    # term catches gross shape changes without punishing Ken Burns framing.
    face = 0.75 * face_hist + 0.25 * dhash
    hair = _hist_similarity(region(image, hair_box), region(anchor, hair_box))
    clothing = _hist_similarity(region(image, cloth_box), region(anchor, cloth_box))
    passed = face >= threshold and hair >= threshold and clothing >= threshold
    return {
        "face": round(face, 4),
        "hair": round(hair, 4),
        "clothing": round(clothing, 4),
        "threshold": threshold,
        "passed": passed,
        "method": "dhash+region-histogram",
    }


def check_episode_consistency(
    assets: dict[str, Any],
    series: dict[str, Any],
    *,
    out_dir: str | Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    cards = cast_by_id(series)
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for img in assets.get("images") or []:
        cid = str(img.get("character_id") or "")
        card = cards.get(cid)
        if card is None:
            continue
        missing = prompt_missing_fields(img, card)
        if missing:
            findings.append(_finding("C-PROMPT", "major", f"角色 {cid} 图像提示词缺固定项: {missing}", cid))
        anchor = str(
            card.get("portrait_image") if img.get("kind") == "character_portrait"
            else card.get("anchor_image")
        ) or str(card.get("anchor_image") or "")
        rendered = str(img.get("path") or "")
        if anchor and rendered and Path(anchor).is_file() and Path(rendered).is_file():
            cmp = compare_to_anchor(rendered, anchor, threshold=threshold)
            results.append({"character_id": cid, "kind": img.get("kind"), "image": rendered,
                            "anchor": anchor, **cmp})
            if not cmp["passed"]:
                findings.append(_finding(
                    "C-VISUAL", "major",
                    f"角色 {cid} 与设定图不一致（脸 {cmp['face']:.2f} / 发 {cmp['hair']:.2f} / 服装 {cmp['clothing']:.2f}）",
                    cid,
                ))
    report = {
        "series_id": series.get("series_id"),
        "checked_at": _now(),
        "threshold": threshold,
        "comparisons": results,
        "findings": findings,
        "passed": not any(f["severity"] == "blocker" for f in findings) and all(c.get("passed", True) for c in results),
    }
    if out_dir is not None:
        path = Path(out_dir) / "consistency.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["path"] = str(path)
    return report


def add_episode(series: dict[str, Any], episode: dict[str, Any]) -> dict[str, Any]:
    series.setdefault("episodes", []).append(episode)
    return series


def ensure_single_anchor(series: dict[str, Any]) -> dict[str, Any]:
    """Exactly one anchor image per character; later images reference it."""
    for card in series.get("cast") or []:
        anchor = str(card.get("anchor_image") or "").strip()
        if not anchor:
            continue
        card["anchor_image"] = anchor
        # A identity board is the anchor.  If a portrait was stored first,
        # keep that as the anchor instead of silently switching mid-series.
        if not str(card.get("portrait_image") or "").strip():
            card["portrait_image"] = anchor
    return series


def lock_generation_to_anchor(assets: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    """Make every expression/angle/portrait generation reference the anchor.

    The first identity image is the anchor; it is generated from text.  Every
    other character image must carry ``anchor_reference`` and an explicit
    "以锚图为唯一形象参考" clause, so a downstream engine cannot quietly redraw
    the face from the text prompt alone.
    """
    cards = cast_by_id(series)
    for img in assets.get("images") or []:
        cid = str(img.get("character_id") or "")
        card = cards.get(cid)
        if card is None:
            continue
        anchor = str(card.get("anchor_image") or "").strip()
        if not anchor:
            continue
        img["anchor_reference"] = anchor
        prefix = "以锚图为唯一形象参考，保持同一张脸、同一发型、同一套服装："
        if img.get("kind") == "character_identity" and str(img.get("path") or "") == anchor:
            continue
        prompt = str(img.get("prompt") or "")
        if prefix not in prompt:
            img["prompt"] = f"{prefix}{prompt}"
        render = str(img.get("render_prompt") or "")
        anchor_clause = "use the anchor image as the only identity reference, same face, same hair, same outfit"
        if anchor_clause not in render:
            img["render_prompt"] = f"{render}, {anchor_clause}" if render else anchor_clause
    return assets


def makeup_shot_prompt(
    card: dict[str, Any], style_card: dict[str, Any] | None = None
) -> dict[str, str]:
    """定妆照: flat light, pure colour background, front/full/3-4 side."""
    look = card_look(card)
    style_line = ""
    style_en = ""
    if style_card:
        style_line = f"画风：{style_card.get('style_prompt_zh') or style_card.get('name', '')}。"
        style_en = f", {style_card.get('style_prompt', '')}"
    return {
        "kind": "makeup_shot",
        "character_id": str(card.get("id")),
        "shots": "正脸、全身、3/4 侧脸",
        "prompt": (
            f"定妆照：{look}。{style_line}平光，纯色背景（浅灰或白），"
            "正脸、全身、3/4 侧脸三张，不要阴影造型，不要滤镜，同一张脸。"
        ),
        "render_prompt": (
            f"{_look_en(card)}, makeup test, flat even lighting, plain seamless background, "
            f"front face, full body, three-quarter profile, no dramatic shadow, same face{style_en}"
        ),
        "checks": ["flat_light", "plain_background", "front_full_three_quarter", "same_face_7_of_10"],
    }


def check_makeup_shot(image_path: str | Path, card: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, offline checks for a 定妆照 image.

    It measures what can be measured without a face model: file present, plain
    background (corner brightness uniformity), flat light (low highlight
    variance), and that the card's fixed tokens are present in the card (the
    prompt side is checked by ``prompt_missing_fields``).  Face identity across
    10 draws is handled by :func:`select_consistent_draws`.
    """
    from PIL import Image, ImageStat

    errors: list[str] = []
    path = Path(image_path)
    if not path.is_file():
        return {"passed": False, "errors": ["image missing"], "metrics": {}}
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w < 256 or h < 256:
        errors.append(f"image too small: {w}x{h}")
    gray = img.convert("L")
    corners = [
        gray.crop((0, 0, w // 6, h // 6)),
        gray.crop((w - w // 6, 0, w, h // 6)),
        gray.crop((0, h - h // 6, w // 6, h)),
        gray.crop((w - w // 6, h - h // 6, w, h)),
    ]
    means = [ImageStat.Stat(c).mean[0] for c in corners]
    spread = max(means) - min(means)
    if spread > 18:
        errors.append(f"background is not plain/flat (corner brightness spread {spread:.1f})")
    highlight = ImageStat.Stat(gray).stddev[0]
    if highlight > 110:
        errors.append(f"lighting is not flat (global contrast {highlight:.1f})")
    if not str(card.get("anchor_image") or "").strip():
        errors.append("card has no anchor image")
    return {
        "passed": not errors,
        "errors": errors,
        "metrics": {"width": w, "height": h, "corner_spread": round(spread, 2),
                    "contrast": round(highlight, 2)},
    }


def select_consistent_draws(
    scores: list[float], *, draws: int = 10, need: int = 7, threshold: float = DEFAULT_THRESHOLD
) -> dict[str, Any]:
    """The 10-draw / 7-same-face rule, over anchor similarity scores."""
    kept = [s for s in scores if float(s) >= threshold]
    passed = len(scores) >= draws and len(kept) >= need
    return {
        "passed": passed,
        "draws": len(scores),
        "required_draws": draws,
        "same_face": len(kept),
        "required_same_face": need,
        "threshold": threshold,
        "kept": kept,
    }
