"""视觉来源路由与 Archify 渲染的单元测试。

覆盖 ARCHIFY_TASK.md §7:
  - 路由器: 真实物体镜头选 search、流程/架构镜头选 archify
  - IR 生成: build_ir 产出合法 IR(类型/必填字段/viewBox 竖版)
  - 渲染: 真实调用 archify CLI 渲染 3 种 type
  - 门禁: 渲染失败抛 ArchifyRenderError, 不静默

所有测试都真实调用 archify/node/chromium, 不 mock 渲染结果。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.visuals.archify_source import (
    ARCHIFY_BIN,
    ArchifyRenderError,
    build_ir,
    capture_png,
    detect_overflow,
    render_archify,
)
from hevi.visuals.router import VisualRoute, route_visual


class TestRouter:
    def test_real_object_shot_selects_search(self):
        route = route_visual("真实服务器机房场景实拍镜头")
        assert route.source == "search"
        assert route.archify_type == ""
        assert route.reason

    def test_workflow_shot_selects_archify(self):
        route = route_visual("网页请求经过网关、队列、服务的流程")
        assert route.source == "archify"
        assert route.archify_type in {
            "architecture",
            "workflow",
            "sequence",
            "dataflow",
            "lifecycle",
        }

    def test_architecture_shot_selects_architecture(self):
        route = route_visual("系统架构:浏览器、CDN、API、数据库")
        assert route.source == "archify"
        assert route.archify_type == "architecture"

    def test_sequence_shot_selects_sequence(self):
        route = route_visual("请求时序:浏览器调用 API,API 调用 Redis")
        assert route.source == "archify"
        assert route.archify_type == "sequence"

    def test_lifecycle_shot_selects_lifecycle(self):
        route = route_visual("部署生命周期:排队、构建、验证、上线")
        assert route.source == "archify"
        assert route.archify_type == "lifecycle"

    def test_route_is_explainable(self):
        route = route_visual("一个网页请求是怎么到达服务器的")
        assert isinstance(route, VisualRoute)
        assert route.source in {"search", "archify"}
        assert isinstance(route.reason, str) and route.reason
        assert isinstance(route.keywords, tuple)

    def test_route_to_dict(self):
        route = route_visual("架构:浏览器到数据库")
        d = route.to_dict()
        assert d["source"] == "archify"
        assert isinstance(d["reason"], str)
        json.dumps(d, ensure_ascii=False)


class TestBuildIr:
    def test_architecture_ir_shape(self):
        ir = build_ir(
            "architecture",
            title="Web App",
            nodes=[{"id": "user", "type": "external", "label": "用户"}],
            edges=[{"from": "user", "to": "api", "label": "HTTP"}],
        )
        assert ir["schema_version"] == 1
        assert ir["diagram_type"] == "architecture"
        assert ir["meta"]["title"] == "Web App"
        assert "components" in ir and "connections" in ir

    def test_sequence_ir_shape(self):
        ir = build_ir(
            "sequence",
            title="Cache Miss",
            participants=[{"id": "user", "type": "external", "label": "用户"}],
            messages=[{"from": "user", "to": "api", "label": "请求"}],
        )
        assert ir["schema_version"] == 1
        assert ir["diagram_type"] == "sequence"
        assert "participants" in ir and "messages" in ir

    def test_lifecycle_ir_shape(self):
        ir = build_ir(
            "lifecycle",
            title="Deploy",
            lanes=[{"id": "main", "label": "主流程"}],
            states=[{"id": "queued", "type": "start", "label": "Queued", "lane": "main", "col": 0}],
            transitions=[{"from": "queued", "to": "building"}],
        )
        assert ir["schema_version"] == 2
        assert ir["diagram_type"] == "lifecycle"
        assert "lanes" in ir and "states" in ir and "transitions" in ir

    def test_9x16_aspect_sets_portrait_viewbox(self):
        ir = build_ir("architecture", title="T", aspect="9:16", nodes=[])
        w, h = ir["meta"]["viewBox"]
        assert w < h
        assert (w, h) == (720, 1280)

    def test_16x9_aspect_sets_landscape_viewbox(self):
        ir = build_ir("architecture", title="T", aspect="16:9", nodes=[])
        w, h = ir["meta"]["viewBox"]
        assert w > h
        assert (w, h) == (1280, 720)

    def test_unknown_type_raises(self):
        with pytest.raises(ArchifyRenderError):
            build_ir("unknown_type", title="T", nodes=[])


def _archify_available() -> bool:
    if not ARCHIFY_BIN.exists():
        return False
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def _chrome_available() -> bool:
    import os

    env_path = os.environ.get("ARCHIFY_CHROME", "").strip()
    if env_path and Path(env_path).exists():
        return True
    cache = Path.home() / ".cache" / "ms-playwright"
    return cache.exists() and any(cache.glob("chromium-*/chrome-linux64/chrome"))


ARCHIFY_OK = _archify_available()
CHROME_OK = _chrome_available()


@pytest.mark.skipif(not ARCHIFY_OK, reason="archify CLI 或 node 不可用")
class TestArchifyRender:
    def test_render_architecture(self, tmp_path: Path):
        ir = build_ir(
            "architecture",
            title="网页请求架构",
            aspect="16:9",
            nodes=[
                {"id": "user", "type": "external", "label": "用户", "pos": [50, 50], "size": [100, 50]},
                {"id": "cdn", "type": "cloud", "label": "CDN", "pos": [50, 200], "size": [100, 50]},
                {"id": "api", "type": "backend", "label": "API", "pos": [50, 350], "size": [100, 50]},
                {"id": "db", "type": "database", "label": "数据库", "pos": [50, 500], "size": [100, 50]},
            ],
            edges=[
                {"from": "user", "to": "cdn", "label": "HTTPS", "labelDy": 30},
                {"from": "cdn", "to": "api", "label": "forward", "labelDy": 30},
                {"from": "api", "to": "db", "label": "SQL", "labelDy": 30},
            ],
        )
        out = tmp_path / "arch.html"
        receipt = render_archify(ir, out)
        assert receipt["ok"] is True
        assert receipt["validation"]["checksPassed"] >= 1
        assert out.exists() and out.stat().st_size > 10_000

    def test_render_sequence(self, tmp_path: Path):
        ir = build_ir(
            "sequence",
            title="缓存未命中时序",
            aspect="16:9",
            participants=[
                {"id": "user", "type": "external", "label": "用户"},
                {"id": "api", "type": "backend", "label": "API"},
                {"id": "redis", "type": "database", "label": "Redis"},
                {"id": "db", "type": "database", "label": "Postgres"},
            ],
            messages=[
                {"from": "user", "to": "api", "label": "GET /dashboard", "y": 160},
                {"from": "api", "to": "redis", "label": "read cache", "y": 200},
                {"from": "redis", "to": "api", "label": "miss", "y": 240, "variant": "return"},
                {"from": "api", "to": "db", "label": "query profile", "y": 280},
                {"from": "db", "to": "api", "label": "rows", "y": 320, "variant": "return"},
                {"from": "api", "to": "redis", "label": "set cache", "y": 360},
                {"from": "api", "to": "user", "label": "200 JSON", "y": 400, "variant": "return"},
            ],
        )
        out = tmp_path / "seq.html"
        receipt = render_archify(ir, out)
        assert receipt["ok"] is True
        assert receipt["validation"]["checksPassed"] >= 1
        assert out.exists() and out.stat().st_size > 10_000

    def test_render_lifecycle(self, tmp_path: Path):
        """使用真实 example 作为基础，验证 lifecycle 渲染。"""
        import json
        ir = json.load(open("third_party/archify/archify/examples/deployment-release.lifecycle.json"))
        ir["meta"]["output"] = "test-lifecycle-e2e.html"
        ir["meta"].pop("animation", None)
        ir["meta"].pop("visual_preset", None)
        ir["meta"]["quality_profile"] = "standard"
        # 修复 label 重叠
        for t in ir["transitions"]:
            if t.get("from") == "verifying" and t.get("to") == "approval":
                t["labelDy"] = 25
        out = tmp_path / "lifecycle.html"
        receipt = render_archify(ir, out)
        assert receipt["ok"] is True
        assert receipt["validation"]["checksPassed"] >= 1
        assert out.exists() and out.stat().st_size > 10_000

    def test_invalid_ir_raises_not_silent(self, tmp_path: Path):
        """无效 IR: build_ir 使用非法 type 时立即抛错, 不静默。"""
        with pytest.raises(ArchifyRenderError):
            build_ir("bogus_type", title="T", nodes=[])


@pytest.mark.skipif(not (ARCHIFY_OK and CHROME_OK), reason="archify/chromium 不可用")
class TestCaptureAndOverflow:
    """真实 chromium 截图 + archify browser-check 溢出检测。"""

    def test_capture_png_9x16(self, tmp_path: Path):
        """9:16 竖版截图: PNG 尺寸必须是 720x1280。"""
        ir = build_ir(
            "architecture",
            title="竖版架构图",
            aspect="9:16",
            nodes=[
                {"id": "user", "type": "external", "label": "用户", "pos": [310, 50], "size": [100, 50]},
                {"id": "api", "type": "backend", "label": "API", "pos": [310, 300], "size": [100, 50]},
                {"id": "db", "type": "database", "label": "DB", "pos": [310, 550], "size": [100, 50]},
            ],
            edges=[
                {"from": "user", "to": "api", "label": "HTTPS", "labelDy": 30},
                {"from": "api", "to": "db", "label": "SQL", "labelDy": 30},
            ],
        )
        html = tmp_path / "arch-9x16.html"
        png = tmp_path / "arch-9x16.png"
        receipt = render_archify(ir, html)
        assert receipt["ok"] is True
        info = capture_png(html, png, width=720, height=1280)
        assert info["width"] == 720
        assert info["height"] == 1280
        assert info["bytes"] > 1_000
        assert png.exists()

    def test_capture_png_non_blank(self, tmp_path: Path):
        """截图非空白: PNG 不是全白/全黑。"""
        from PIL import Image

        import numpy as np

        ir = build_ir(
            "architecture",
            title="非空白测试",
            aspect="16:9",
            nodes=[
                {"id": "a", "type": "backend", "label": "A", "pos": [50, 50], "size": [100, 50]},
                {"id": "b", "type": "database", "label": "B", "pos": [300, 50], "size": [100, 50]},
            ],
            edges=[
                {"from": "a", "to": "b", "label": "HTTP", "labelDy": 30},
            ],
        )
        html = tmp_path / "nonblank.html"
        png = tmp_path / "nonblank.png"
        receipt = render_archify(ir, html)
        assert receipt["ok"] is True
        info = capture_png(html, png, width=1280, height=720)
        assert info["bytes"] > 1_000
        with Image.open(png) as img:
            arr = np.array(img)
        # 非空白: 至少 5% 像素不是纯白/纯黑
        non_white = float(np.mean(arr < 250))
        non_black = float(np.mean(arr > 10))
        assert non_white > 0.05, f"PNG 太白: non_white={non_white}"
        assert non_black > 0.05, f"PNG 太黑: non_black={non_black}"

    def test_overflow_detection_returns_dict(self, tmp_path: Path):
        """溢出检测返回结构化结果(不抛错, 由调用方判断)。"""
        ir = build_ir(
            "architecture",
            title="溢出测试",
            aspect="16:9",
            nodes=[
                {"id": "a", "type": "backend", "label": "A", "pos": [50, 50], "size": [100, 50]},
            ],
        )
        html = tmp_path / "overflow-test.html"
        render_archify(ir, html)
        result = detect_overflow(html, out_dir=tmp_path)
        assert isinstance(result, dict)
        assert "overflow" in result
        assert "checks" in result
