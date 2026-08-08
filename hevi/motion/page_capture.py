"""页面采集 —— headless 浏览器截真实页面(纹理+元素抠图+坐标表)(3O 内化 Phase B)。

来源: video-shotcraft 的页面采集管线:"复刻既有页面必须用真实截图;手搓 UI 限
非复刻场景"。采集 = 起本地 dev server → 无头浏览器全页 2x 纹理 + 元素级抠图 +
layout.json 坐标表。数据按风险口径处理(客户/个人/内部/密钥必须虚构或脱敏)。

本模块为 hevi 暂驻(待上游 `oprim.page_capture`):playwright 可选依赖,缺浏览器
时抛 PageCaptureError;layout.json 写入逻辑纯文件 IO,可测。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class PageCaptureError(Exception):
    """页面采集失败。"""


@dataclass
class PageAsset:
    """一次采集的产物:全页纹理 + 元素抠图列表 + layout 坐标表。"""

    url: str
    fullpage_path: Path
    elements: list[dict[str, object]] = field(default_factory=list)  # [{name,path,box}]
    layout_path: Path | None = None
    device_scale_factor: float = 2.0
    viewport: tuple[int, int] = (1440, 900)

    def to_layout(self) -> dict[str, object]:
        """layout.json 内容(坐标表 + 产物索引)。"""
        return {
            "url": self.url,
            "device_scale_factor": self.device_scale_factor,
            "viewport": list(self.viewport),
            "fullpage": str(self.fullpage_path),
            "elements": self.elements,
        }

    def save_layout(self, out_path: str | Path) -> Path:
        """落盘 layout.json,返回路径。"""
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_layout(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.layout_path = p
        return p


def capture_page_assets(
    url: str,
    out_dir: str | Path,
    *,
    viewport: tuple[int, int] = (1440, 900),
    device_scale_factor: float = 2.0,
    element_selectors: list[str] | None = None,
    fullpage: bool = True,
    timeout_ms: int = 30_000,
) -> PageAsset:
    """无头浏览器采集:全页 2x 纹理 + 元素级抠图 + layout.json。

    Args:
        url: 目标页面(本地 dev server 或公网)。
        out_dir: 采集产物目录。
        viewport: 视口。
        device_scale_factor: 2 = 全页 2x 纹理(文字清晰度最低要求)。
        element_selectors: 需要元素级抠图的 CSS 选择器列表。
        fullpage: 是否截整页滚动长图。
        timeout_ms: 页面加载超时。

    Returns:
        PageAsset(产物路径 + 坐标表)。

    Raises:
        PageCaptureError: playwright/浏览器不可用或采集失败。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - env guard
        raise PageCaptureError(f"playwright 未安装: {e}") from e

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(
                viewport={"width": viewport[0], "height": viewport[1]},
                device_scale_factor=device_scale_factor,
            )
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            fullpage_path = out / "fullpage.png"
            if fullpage:
                page.screenshot(path=str(fullpage_path), full_page=True)
            else:
                page.screenshot(path=str(fullpage_path))

            elements: list[dict[str, object]] = []
            for idx, selector in enumerate(element_selectors or []):
                try:
                    handles = page.query_selector_all(selector)
                except Exception as e:  # pragma: no cover - invalid selector
                    logger.warning("capture: selector %r failed: %s", selector, e)
                    continue
                for j, handle in enumerate(handles):
                    box = handle.bounding_box()
                    if box is None:
                        continue
                    name = f"el_{idx:02d}_{j:02d}"
                    path = out / f"{name}.png"
                    handle.screenshot(path=str(path))
                    elements.append(
                        {
                            "name": name,
                            "selector": selector,
                            "path": str(path),
                            "box": [box["x"], box["y"], box["width"], box["height"]],
                        }
                    )
            browser.close()

            asset = PageAsset(
                url=url,
                fullpage_path=fullpage_path,
                elements=elements,
                device_scale_factor=device_scale_factor,
                viewport=viewport,
            )
            asset.save_layout(out / "layout.json")
            return asset
    except PageCaptureError:
        raise
    except Exception as e:
        raise PageCaptureError(f"capture failed for {url}: {e}") from e
