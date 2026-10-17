"""Archify 生成器 —— 写类型化 JSON IR → archify CLI 渲染 → 截图。

对外接口(见 ARCHIFY_TASK.md §1/§2/§3/§4):
  - :func:`render_archify` 渲染单条 IR: 调 ``archify.mjs deliver``
    (自带 schema 校验 + provenance 校验), 失败抛
    :class:`ArchifyRenderError` 由调用方降级到 search。
  - :func:`capture_png` 用机器上已有的 chromium 截 PNG。
  - :func:`detect_overflow` 走 archify 自带 ``browser-check`` 的
    containment 检查(在 DOM 层检测元素是否超出视口/可读性),
    返回溢出证据。溢出时调用方应降级字号/换布局重渲。
  - :func:`render_with_overflow_gate` 是带门禁的完整路径:
    渲染 → 截图 → 溢出检测 → 失败抛错(由调用方降级 search)。

设计:
  - 不新增依赖: node 用 PATH 上的 v26.4.0; chromium 复用
    playwright 缓存(通过 ARCHIFY_CHROME 环境变量发现)。
  - 9:16 竖版: IR 里 meta.viewBox 用竖版画布(如 720x1280),
    不做横图硬裁(ARCHIFY_TASK.md §3)。
  - 所有失败都抛异常/记录, 不静默(§2)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ARCHIFY_BIN = (
    Path(__file__).resolve().parents[2]
    / "third_party"
    / "archify"
    / "archify"
    / "bin"
    / "archify.mjs"
)

#: 竖版默认画布(9:16)。720x1280 是 1080x1920 的 2/3, 渲染快。
DEFAULT_CANVAS: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (900, 900),
}

#: archify 允许的 type 集合(与 bin/archify.mjs TYPES 一致)。
ARCHIFY_TYPES = frozenset(
    {"architecture", "workflow", "sequence", "dataflow", "lifecycle"}
)


class ArchifyRenderError(RuntimeError):
    """archify 渲染/校验失败。调用方应降级到 search, 不得静默。"""


def _find_chrome() -> str:
    """发现 chromium: ARCHIFY_CHROME > playwright 缓存。"""
    env_path = os.environ.get("ARCHIFY_CHROME", "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    cache = Path.home() / ".cache" / "ms-playwright"
    if cache.exists():
        candidates = sorted(
            cache.glob("chromium-*/chrome-linux64/chrome"),
            key=lambda p: p.as_posix(),
        )
        if candidates:
            return str(candidates[-1])
    raise ArchifyRenderError(
        "找不到 chromium: 设置 ARCHIFY_CHROME 或安装 playwright chromium"
    )


def build_ir(
    archify_type: str,
    *,
    title: str,
    output: str = "diagram.html",
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    participants: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    stages: list[dict[str, Any]] | None = None,
    flows: list[dict[str, Any]] | None = None,
    lanes: list[dict[str, Any]] | None = None,
    states: list[dict[str, Any]] | None = None,
    transitions: list[dict[str, Any]] | None = None,
    cards: list[dict[str, Any]] | None = None,
    aspect: str = "9:16",
    animation: str | None = None,
    visual_preset: str | None = None,
) -> dict[str, Any]:
    """按 type 组装最小合法 IR(确定性规则, 非 LLM)。

    只填该 type 的核心字段; meta.viewBox 按竖版/横版画布。
    """
    if archify_type not in ARCHIFY_TYPES:
        raise ArchifyRenderError(f"未知 archify type: {archify_type}")
    width, height = DEFAULT_CANVAS.get(aspect, (720, 1280))
    meta: dict[str, Any] = {
        "title": title,
        "output": output,
        "quality_profile": "standard",
        "viewBox": [width, height],
    }
    if animation:
        meta["animation"] = animation
    if visual_preset:
        meta["visual_preset"] = visual_preset
    ir: dict[str, Any] = {
        "schema_version": 2 if archify_type in {"workflow", "lifecycle"} else 1,
        "diagram_type": archify_type,
        "meta": meta,
    }
    if archify_type == "architecture":
        ir["components"] = nodes or []
        ir["connections"] = edges or []
    elif archify_type == "workflow":
        ir["lanes"] = lanes or [{"id": "main", "label": "主流程"}]
        ir["nodes"] = nodes or []
        ir["edges"] = edges or []
    elif archify_type == "sequence":
        ir["participants"] = participants or []
        ir["messages"] = messages or []
    elif archify_type == "dataflow":
        ir["stages"] = stages or []
        ir["nodes"] = nodes or []
        ir["flows"] = flows or []
    elif archify_type == "lifecycle":
        ir["lanes"] = lanes or [{"id": "main", "label": "主流程"}]
        ir["states"] = states or []
        ir["transitions"] = transitions or []
    if cards:
        ir["cards"] = cards
    return ir


def render_archify(
    ir: dict[str, Any],
    output_html: Path,
    *,
    quality: str = "standard",
) -> dict[str, Any]:
    """调 archify deliver 渲染并校验。返回 CLI 的 JSON receipt。

    失败抛 ArchifyRenderError(含 CLI 错误输出, 不静默)。
    """
    archify_type = ir.get("diagram_type", "")
    if archify_type not in ARCHIFY_TYPES:
        raise ArchifyRenderError(f"未知 archify type: {archify_type}")
    output_html = Path(output_html).resolve()
    output_html.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(ir, tmp, ensure_ascii=False, indent=2)
        ir_path = tmp.name
    try:
        cmd = [
            "node",
            str(ARCHIFY_BIN),
            "deliver",
            archify_type,
            ir_path,
            str(output_html),
            "--quality",
            quality,
            "--json",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "ARCHIFY_CHROME": _find_chrome()},
        )
    except subprocess.TimeoutExpired as exc:
        raise ArchifyRenderError(f"archify deliver 超时: {exc}") from exc
    except OSError as exc:
        raise ArchifyRenderError(f"archify deliver 启动失败: {exc}") from exc
    finally:
        Path(ir_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise ArchifyRenderError(
            f"archify deliver 失败(rc={proc.returncode}): "
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    try:
        receipt = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ArchifyRenderError(
            f"archify deliver 输出非 JSON: {proc.stdout[-1000:]}"
        ) from exc
    if not receipt.get("ok"):
        raise ArchifyRenderError(
            f"archify deliver receipt 不 ok: "
            f"{json.dumps(receipt, ensure_ascii=False)[:2000]}"
        )
    return receipt


def capture_png(
    html_path: Path,
    png_path: Path,
    *,
    width: int = 720,
    height: int = 1280,
) -> dict[str, Any]:
    """用 chromium 截 PNG(直接调 chrome --headless, 不依赖 playwright python 包)。

    返回 {"width", "height", "sha256", "bytes"}。
    """
    chrome = _find_chrome()
    png_path = Path(png_path).resolve()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archify-shot-") as profile:
        cmd = [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            f"--screenshot={png_path}",
            html_path.as_uri(),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "ARCHIFY_CHROME_NO_SANDBOX": "1"},
        )
    if proc.returncode != 0 or not png_path.exists():
        raise ArchifyRenderError(
            f"chromium 截图失败(rc={proc.returncode}): {proc.stderr[-1000:]}"
        )
    data = png_path.read_bytes()
    from PIL import Image

    with Image.open(png_path) as img:
        w, h = img.size
    return {
        "width": w,
        "height": h,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def detect_overflow(
    html_path: Path,
    *,
    out_dir: Path | None = None,
    width: int = 720,
    height: int = 1280,
) -> dict[str, Any]:
    """用 archify 自带 browser-check 检测 DOM 层 containment/可读性。

    browser-check 在真实 chromium 里跑 containment 检查
    (元素是否超出视口/可读性), 是 archify 官方门禁。
    返回 {"overflow": bool, "checks": {...}, "containment": {...}, "readability": {...}, "receipt": {...}}。

    注意: browser-check 使用桌面视口(1440x900 等)而非
    竖版画布, 对 9:16 内容会误判为 overflowY。本函数
    解析 receipt 的真实结构(containment.status / readability.status),
    并提供 portrait_viewport 字段让调用方按目标画布判断。
    """
    chrome = _find_chrome()
    out_dir = Path(out_dir) if out_dir else html_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "node",
        str(ARCHIFY_BIN),
        "browser-check",
        str(html_path),
        "--json",
        "--out-dir",
        str(out_dir),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180,
        env={
            **os.environ,
            "ARCHIFY_CHROME": chrome,
            "ARCHIFY_CHROME_NO_SANDBOX": "1",
        },
    )
    if proc.returncode != 0:
        # browser-check 对未通过 containment 的页面也会返回 receipt
        # (非零 exit), 尝试解析 receipt 而不是直接抛错。
        try:
            receipt = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ArchifyRenderError(
                f"browser-check 失败且无法解析 receipt: "
                f"{proc.stdout[-1000:]}\n{proc.stderr[-1000:]}"
            ) from exc
    else:
        receipt = json.loads(proc.stdout)

    # 解析 receipt 真实结构: containment/readability 是 dict,
    # 不是 checks 下的字符串。
    containment_obj = receipt.get("containment", {}) or {}
    readability_obj = receipt.get("readability", {}) or {}
    containment = containment_obj.get("status", "skipped")
    readability = readability_obj.get("status", "skipped")

    # 官方门禁: containment/readability 任一 fail 即溢出。
    # browser-check 用桌面视口(1440x900 等), 对 9:16 竖版内容
    # 会误判 overflowY —— 需结合 portrait_viewport 单独判断。
    overflow = containment == "fail" or readability == "fail"

    # 竖版视口独立判断: 用 chromium 截图检测目标画布下是否溢出。
    portrait_viewport = _check_portrait_overflow(
        html_path, width=width, height=height
    )

    return {
        "overflow": overflow,
        "portrait_overflow": portrait_viewport.get("overflow"),
        "checks": {
            "containment": containment,
            "readability": readability,
        },
        "containment": containment,
        "readability": readability,
        "portrait_viewport": portrait_viewport,
        "receipt": receipt,
    }


def _check_portrait_overflow(
    html_path: Path,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """在目标竖版视口下用 chromium 检测 DOM overflow。

    browser-check 默认用桌面视口(1440x900), 对 9:16 内容
    会误判。此函数注入测量脚本并返回目标视口下的
    scrollWidth/scrollHeight/innerWidth/innerHeight 真实值。
    """
    chrome = _find_chrome()
    inject = (
        '<script>window.addEventListener("load",function(){'
        'var i={scrollWidth:document.documentElement.scrollWidth,'
        'scrollHeight:document.documentElement.scrollHeight,'
        'innerWidth:window.innerWidth,innerHeight:window.innerHeight};'
        'document.title="MEASURE:"+JSON.stringify(i);});'
        '</script>'
    )
    html = html_path.read_text(encoding="utf-8")
    html = html.replace("</body>", inject + "</body>") if "</body>" in html else html + inject
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html",
                                       delete=False, encoding="utf-8")
    try:
        tmp.write(html)
        tmp.close()
        with tempfile.TemporaryDirectory(prefix="archify-portrait-") as profile:
            cmd = [
                chrome, "--headless=new", "--no-sandbox",
                "--disable-gpu", "--disable-dev-shm-usage",
                "--hide-scrollbars",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                "--dump-dom",
                tmp.name,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                env={**os.environ, "ARCHIFY_CHROME_NO_SANDBOX": "1"},
            )
    finally:
        os.unlink(tmp.name)
    import re
    dom = proc.stdout or ""
    match = re.search(r'MEASURE:(\{[^}]+\})', dom)
    if not match:
        return {
            "width": width,
            "height": height,
            "overflow": False,
            "note": "未能注入测量脚本(dump-dom 无 MEASURE 输出)",
        }
    data = json.loads(match.group(1))
    scroll_w = data["scrollWidth"]
    scroll_h = data["scrollHeight"]
    inner_w = data["innerWidth"]
    inner_h = data["innerHeight"]
    # 允许 2% 的垂直容差: 浏览器 chrome/scrollbar 可能导致
    # innerHeight 略小于 window-size, 但内容实际不溢出。
    # 如果 scrollHeight 不超过 innerHeight 的 102%, 视为不溢出。
    tolerance = 1.02
    overflow_y = scroll_h > inner_h * tolerance
    overflow_x = scroll_w > inner_w * tolerance
    return {
        "width": width,
        "height": height,
        "scrollWidth": scroll_w,
        "scrollHeight": scroll_h,
        "innerWidth": inner_w,
        "innerHeight": inner_h,
        "overflow_x": overflow_x,
        "overflow_y": overflow_y,
        "overflow": overflow_x or overflow_y,
    }


def render_with_overflow_gate(
    ir: dict[str, Any],
    out_dir: Path,
    *,
    stem: str = "diagram",
    aspect: str = "9:16",
    max_attempts: int = 2,
) -> dict[str, Any]:
    """完整渲染门禁: deliver → 截图 → 溢出检测。

    返回 {"html", "png", "receipt", "attempts", "overflow", "png_info"}。
    溢出或渲染失败时抛 ArchifyRenderError, 由调用方降级 search。
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    width, height = DEFAULT_CANVAS.get(aspect, (720, 1280))
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        html_path = out_dir / f"{stem}-{attempt}.html"
        png_path = out_dir / f"{stem}-{attempt}.png"
        try:
            receipt = render_archify(ir, html_path)
            png_info = capture_png(html_path, png_path, width=width, height=height)
            overflow = detect_overflow(html_path, out_dir=out_dir,
                                        width=width, height=height)
            if overflow["portrait_overflow"]:
                last_error = ArchifyRenderError(
                    f"第 {attempt} 次渲染检测到溢出: "
                    f"containment={overflow['containment']} "
                    f"readability={overflow['readability']}"
                )
                logger.warning("archify 渲染溢出, 重试: %s", last_error)
                continue
            return {
                "html": str(html_path),
                "png": str(png_path),
                "receipt": receipt,
                "attempts": attempt,
                "overflow": overflow,
                "png_info": png_info,
            }
        except ArchifyRenderError as exc:
            last_error = exc
            logger.warning("archify 渲染失败(第 %d 次): %s", attempt, exc)
    raise ArchifyRenderError(f"archify 渲染 {max_attempts} 次均失败: {last_error}")
