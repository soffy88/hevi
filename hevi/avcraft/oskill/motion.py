"""Motion Prompt 词汇 → 检索 / 分镜词汇注入 / ffmpeg 滤镜（纯函数，无 IO）。

词条来自 showheyohtaki/motion-prompt（MIT License (c) 2026 Shohei Ohtaki，https://showheyohtaki.github.io/motion-prompt/）。
本文件不含上游 Canvas 代码：ffmpeg 表达式是 hevi 按各元素公开 spec（时长/缓动/弹簧公式）自写的近似实现，
每条映射注释里标注对应元素编号与上游版权，便于追溯。catalog 由 obase.motion_catalog.motion_catalog_load 传入。
"""

from __future__ import annotations

import copy
import re

_STOP = {"the", "and", "with", "from", "into", "onto", "that", "this", "shot", "camera", "slow", "slowly",
         "fast", "frame", "left", "right", "then", "over", "while", "very", "soft", "light", "behind"}
_WEAK_TAGS = {"camera move", "transition", "entrance", "lens", "texture", "energy", "clip", "edge", "reveal",
              "portrait lighting", "dramatic", "warm tone", "noise", "zoom", "sequence"}


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_/]+", " ", str(s).lower()).strip()


def _has_phrase(q: str, ph: str) -> bool:
    ph = _norm(ph)
    if not ph:
        return False
    if re.search(r"[\u3040-\u9fff]", ph):
        return ph in q
    return re.search(r"(?<![a-z0-9])" + re.escape(ph) + r"(?![a-z0-9])", q) is not None


def motion_search(catalog: dict, query: str, *, packs: list[str] | tuple | str | None = None, k: int = 5,
                  min_score: float = 2.0) -> list[dict]:
    """按中/英/日关键词给场景配元素。返回 [{id,slug,name,pack,score,hits}]（score 降序，同分按 id）。

    计分：中文别名/日文名/英文名/slug 短语命中 +5；tag 短语 +3（泛 tag +1）；英文实词出现在 meaning/use +0.5（≤2）。
    """
    q = _norm(query)
    if not q:
        return []
    if isinstance(packs, str):
        packs = [packs]
    words = {w for w in re.findall(r"[a-z][a-z0-9]{3,}", q) if w not in _STOP}
    out = []
    for e in catalog["elements"]:
        if packs and e["pack"] not in packs:
            continue
        sc, hits = 0.0, []
        names = [*e.get("zh", []), e["name"]["ja"], e["name"]["en"], e["slug"]]
        for nm in names:
            if len(_norm(nm)) >= 2 and _has_phrase(q, nm):
                sc += 5 + 0.05 * len(nm)
                hits.append(nm)
                break
        for tg in e.get("tags", []):
            if _has_phrase(q, tg):
                sc += 1 if tg in _WEAK_TAGS else 3
                hits.append(tg)
        txt = _norm(" ".join([e["meaning"]["en"], e.get("use", {}).get("en", ""), e["summary"]["en"]]))
        tw = set(re.findall(r"[a-z][a-z0-9]{3,}", txt))
        sc += min(2.0, 0.5 * len(words & tw))
        if sc >= min_score:
            out.append({"id": e["id"], "slug": e["slug"], "name": e["name"]["en"], "pack": e["pack"],
                        "score": round(sc, 2), "hits": hits})
    out.sort(key=lambda r: (-r["score"], r["id"]))
    return out[:k]


def _el(catalog: dict, key: str) -> dict:
    k = str(key).strip().lstrip("#")
    e = catalog["by_id"].get(k.zfill(3)) if k.isdigit() else catalog["by_slug"].get(k)
    if not e:
        raise KeyError(f"unknown motion element: {key}")
    return e


def shot_vocab_inject(shot: dict, ids: list[str], catalog: dict, *, lang: str = "en",
                      with_ask: bool = False) -> dict:
    """返回 shot 副本，附 shot["vocab"]=[{id,term,meaning,pack[,ask]}]（按 ids 去重保序）。

    compile_shot_prompt 遇到 shot["vocab"] 会追加一行 "Terms: ..."（可选、向后兼容）。
    """
    s = copy.deepcopy(shot)
    seen, voc = set(), list(s.get("vocab") or [])
    seen.update(v["id"] for v in voc)
    for i in ids:
        e = _el(catalog, i)
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        v = {"id": e["id"], "term": e["name"][lang], "meaning": e["meaning"][lang], "pack": e["pack"]}
        if with_ask:
            v["ask"] = e["ask"][lang]
        voc.append(v)
    s["vocab"] = voc
    return s


def vocab_line(vocab: list[dict]) -> str:
    """'Terms: Dolly-in (Move the camera toward the subject); Film grain (...).'"""
    if not vocab:
        return ""
    return "Terms: " + "; ".join(f"{v['term']} ({v['meaning'].rstrip('.')})" for v in vocab) + "."


# ---------------------------------------------------------------- ffmpeg

def _p(st: float, d: float) -> str:
    return f"clip((t-{st:g})/{max(d, 1e-3):g},0,1)"


def _ease_out(st, d):  # easeOutCubic
    return f"(1-pow(1-{_p(st, d)},3))"


def _smooth(st, d):  # smoothstep
    p = _p(st, d)
    return f"({p}*{p}*(3-2*{p}))"


def _step_expr(times: list[float], xs: list[int], var: str = "T") -> str:
    expr = str(xs[-1])
    for i in range(len(times) - 1, -1, -1):
        prev = xs[i - 1] if i > 0 else 0
        expr = f"if(lt({var},{times[i]:g}),{prev},{expr})"
    return expr


_CENTER = "x='(W-w)/2':y='(H-h)*{yf:g}'"

# 键：上游元素 id → (kind, 说明)。kind: title=标题动效(双输入 [0:v]背景 [1:v]透明文字层→[v])，
# vf=单流滤镜链，xfade=两段转场。
SUPPORTED = {
    # Motion Prompt #001 · MIT License (c) 2026 Shohei Ohtaki —— Pop-in：弹簧 1−e^(−6.5t)·cos(15t)
    "001": ("title", "pop-in 弹出（弹簧缩放）"),
    # Motion Prompt #005 · MIT License (c) 2026 Shohei Ohtaki —— Mask reveal：文字从不可见边缘下方升起
    "005": ("title", "mask-reveal 遮罩上浮出字"),
    # Motion Prompt #006 · MIT License (c) 2026 Shohei Ohtaki —— Typewriter：逐字出现
    "006": ("title", "typewriter 打字机逐字"),
    # Motion Prompt #074 · MIT License (c) 2026 Shohei Ohtaki —— Fade-in on scroll：淡入+轻微上移
    "074": ("title", "fade-in 淡入上移"),
    # Motion Prompt #027 · MIT License (c) 2026 Shohei Ohtaki —— Dolly-in（近似：数字推近 + smoothstep）
    "027": ("vf", "dolly-in 慢推"),
    # Motion Prompt #028 · MIT License (c) 2026 Shohei Ohtaki —— Zoom-in（镜头放大，线性）
    "028": ("vf", "zoom-in 变焦推近"),
    # Motion Prompt #025 · MIT License (c) 2026 Shohei Ohtaki —— Pan（近似：放大后横移裁切）
    "025": ("vf", "pan 横摇"),
    # Motion Prompt #034 · MIT License (c) 2026 Shohei Ohtaki —— Handheld（确定性正弦抖动，无随机）
    "034": ("vf", "handheld 手持"),
    # Motion Prompt #024 · MIT License (c) 2026 Shohei Ohtaki —— Impact shake（衰减震动）
    "024": ("vf", "impact-shake 震屏"),
    # Motion Prompt #112 · MIT License (c) 2026 Shohei Ohtaki —— Vignette
    "112": ("vf", "vignette 暗角"),
    # Motion Prompt #115 · MIT License (c) 2026 Shohei Ohtaki —— Black and white
    "115": ("vf", "black-and-white 黑白"),
    # Motion Prompt #118 · MIT License (c) 2026 Shohei Ohtaki —— Film grain（固定种子）
    "118": ("vf", "film-grain 胶片颗粒"),
    # Motion Prompt #037 · MIT License (c) 2026 Shohei Ohtaki —— Slow motion（setpts，帧复制）
    "037": ("vf", "slow-motion 慢动作"),
    # Motion Prompt #044/#045/#137/#043/#141/#017/#020/#138 · MIT License (c) 2026 Shohei Ohtaki —— 转场 → xfade
    "044": ("xfade", "cross-dissolve 叠化"),
    "045": ("xfade", "wipe 划像"),
    "137": ("xfade", "push 推移"),
    "043": ("xfade", "whip-pan 甩镜（hblur 近似）"),
    "141": ("xfade", "pixelate 像素化"),
    "017": ("xfade", "mask-transition 圆形展开"),
    "020": ("xfade", "zoom-through 推进穿越"),
    "138": ("xfade", "blinds 百叶窗（切片近似）"),
}
_XFADE = {"044": "fade", "045": "wipeleft", "137": "slideleft", "043": "hblur", "141": "pixelize",
          "017": "circleopen", "020": "zoomin", "138": "hlslice"}
_SLUG2ID = {"pop-in": "001", "mask-reveal": "005", "typewriter": "006", "fade-in-on-scroll": "074", "fade-in": "074",
            "dolly-in": "027", "zoom-in": "028", "pan": "025", "handheld": "034", "impact-shake": "024",
            "vignette": "112", "black-and-white": "115", "film-grain": "118", "slow-motion": "037",
            "cross-dissolve": "044", "wipe": "045", "push-transition": "137", "whip-pan": "043",
            "pixelate": "141", "mask-transition": "017", "zoom-through": "020", "blinds-transition": "138"}


def motion_spec_to_ffmpeg(key: str, *, duration: float = 3.0, w: int = 1080, h: int = 1920, fps: int = 30,
                          start: float = 0.0, strength: float = 1.0, y_frac: float = 0.5,
                          char_x: list[int] | None = None, n_chars: int | None = None,
                          a_duration: float | None = None, catalog: dict | None = None) -> dict:
    """把常用动效翻成 ffmpeg 滤镜（纯函数）。key=元素 id 或 slug。

    返回 {id, slug, kind, filter, inputs, credit, note}：
      title → filter_complex，输入 [0:v]=WxH 背景、[1:v]=透明文字层（loop），输出 [v]；
              typewriter 用 char_x（各字右边界像素，来自 obase.text_layer.render_text_png）逐字揭示；
      vf    → 单流滤镜链（-vf 直接用）；duration 为片长（推/摇用于归一化）；
      xfade → "[0:v][1:v]xfade=...[v]"，offset = a_duration − duration（a_duration=前段时长）或 start。
    """
    k = str(key).strip().lstrip("#")
    mid = k.zfill(3) if k.isdigit() else _SLUG2ID.get(k)
    if mid not in SUPPORTED:
        raise KeyError(f"no ffmpeg mapping for {key}; supported: {sorted(SUPPORTED)}")
    kind, note = SUPPORTED[mid]
    slug = next((s for s, i in _SLUG2ID.items() if i == mid), mid)
    if catalog:
        slug = catalog["by_id"][mid]["slug"]
    st, d, s = float(start), float(duration), float(strength)
    pos = _CENTER.format(yf=y_frac)
    if mid == "001":
        x = f"max(t-{st:g},0)"
        sc = f"if(lt(t,{st:g}),0.02,max(0.02,1-exp(-6.5*{x})*cos(15*{x})))"
        f = (f"[1:v]format=rgba,scale=w='max(2,trunc(iw*{sc}/2)*2)':h='max(2,trunc(ih*{sc}/2)*2)':eval=frame[t];"
             f"[0:v][t]overlay={pos}:eval=frame:shortest=1[v]")
    elif mid == "005":
        dd = min(0.6, d) * (1 / max(s, 0.2))
        f = (f"[1:v]format=rgba,pad=iw:ih*2:0:ih:color=black@0,"
             f"crop=w=iw:h=ih/2:x=0:y='(in_h/2)*{_ease_out(st, dd)}'[t];"
             f"[0:v][t]overlay={pos}:shortest=1[v]")
    elif mid == "006":
        cps = 0.09 / max(s, 0.2)
        if char_x:
            times = [st + i * cps for i in range(len(char_x))]
            rexpr = _step_expr(times, char_x)
        else:
            n = max(1, int(n_chars or 10))
            rexpr = f"W*floor({n}*clip((T-{st:g})/{n * cps:g},0,1)+1e-6)/{n}"
        f = (f"[1:v]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(X,{rexpr}),alpha(X,Y),0)'[t];"
             f"[0:v][t]overlay={pos}:shortest=1[v]")
    elif mid == "074":
        dd = min(0.8, d)
        f = (f"[1:v]format=rgba,fade=t=in:st={st:g}:d={dd:g}:alpha=1[t];"
             f"[0:v][t]overlay=x='(W-w)/2':y='(H-h)*{y_frac:g}+{40 * s:g}*(1-{_ease_out(st, dd)})'"
             f":eval=frame:shortest=1[v]")
    elif mid in ("027", "028"):
        z = (0.12 if mid == "027" else 0.25) * s
        n = max(1, int(round(d * fps)))
        p = f"min(1,on/{n})"
        zz = f"1+{z:g}*{p}*{p}*(3-2*{p})" if mid == "027" else f"1+{z:g}*{p}"
        f = (f"scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
             f"zoompan=z='{zz}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}")
    elif mid == "025":
        m = 1 + 0.25 * s
        f = (f"scale={int(w * m) // 2 * 2}:{int(h * m) // 2 * 2}:force_original_aspect_ratio=increase,"
             f"crop={w}:{h}:x='(iw-{w})*{_smooth(st, d)}':y='(ih-{h})/2'")
    elif mid == "034":
        m = 1 + 0.06 * s
        f = (f"scale={int(w * m) // 2 * 2}:{int(h * m) // 2 * 2},"
             f"crop={w}:{h}:x='(iw-{w})/2*(1+0.7*sin(2*PI*1.1*t)*cos(2*PI*0.37*t))'"
             f":y='(ih-{h})/2*(1+0.7*sin(2*PI*0.83*t+1.3))'")
    elif mid == "024":
        m = 1 + 0.06 * s
        dec = f"if(gte(t,{st:g}),exp(-7*(t-{st:g}))*sin(2*PI*13*(t-{st:g})),0)"
        f = (f"scale={int(w * m) // 2 * 2}:{int(h * m) // 2 * 2},"
             f"crop={w}:{h}:x='(iw-{w})/2*(1+{dec})':y='(ih-{h})/2*(1-0.6*{dec})'")
    elif mid == "112":
        f = f"vignette=angle={0.6 * min(max(s, 0.3), 1.5):.3f}"
    elif mid == "115":
        f = "hue=s=0"
    elif mid == "118":
        f = f"noise=alls={int(round(10 * s))}:allf=t+u:all_seed=7"
    elif mid == "037":
        f = f"setpts={2.0 * s:g}*PTS,fps={fps}"
    else:
        off = (a_duration - d) if a_duration is not None else st
        f = f"[0:v][1:v]xfade=transition={_XFADE[mid]}:duration={d:g}:offset={max(0.0, off):g}[v]"
    return {"id": mid, "slug": slug, "kind": kind, "filter": f,
            "inputs": {"title": 2, "xfade": 2}.get(kind, 1),
            "credit": f"Motion Prompt #{mid} · MIT License (c) 2026 Shohei Ohtaki", "note": note}
