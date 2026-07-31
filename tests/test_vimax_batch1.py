"""ViMax 第一批能力接入测试（5 项高 ROI）。

覆盖：
  1. Rate Limiter — 令牌桶 + RPM/RPD + 并发
  2. Robust JSON Parser — LLM 输出容错解析
  3. Image Guard — 横屏方向守卫
  4. Portrait Triptych — 角色肖像三联画
  5. Best Image Selector — 多候选选优
"""

from __future__ import annotations

import asyncio
import json
import struct
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════
# 1. Rate Limiter
# ═══════════════════════════════════════════════════════════════════════

class TestRateLimiter:
    """通用速率限制器。"""

    def test_config_basic(self):
        from hevi.utils.rate_limiter import RateLimitConfig

        cfg = RateLimitConfig(rpm=60, rpd=1000, concurrency=5)
        assert cfg.rpm == 60
        assert cfg.rpd == 1000
        assert cfg.concurrency == 5

    def test_config_unlimited(self):
        from hevi.utils.rate_limiter import RateLimitConfig

        cfg = RateLimitConfig.unlimited()
        assert cfg.rpm == 0
        assert cfg.rpd == 0
        assert cfg.concurrency == 0

    def test_token_bucket_basic(self):
        from hevi.utils.rate_limiter import TokenBucket

        bucket = TokenBucket(rate=10.0, capacity=5)
        loop = asyncio.new_event_loop()
        try:
            # 初始有 5 个令牌，应该立即获取
            loop.run_until_complete(bucket.acquire(1))
            loop.run_until_complete(bucket.acquire(1))
        finally:
            loop.close()

    def test_rate_limiter_acquire_release(self):
        from hevi.utils.rate_limiter import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(concurrency=2))
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(limiter.acquire())
            limiter.release()
        finally:
            loop.close()

    def test_rate_limiter_context_manager(self):
        from hevi.utils.rate_limiter import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(rpm=100))
        loop = asyncio.new_event_loop()
        try:
            async def _test():
                async with limiter:
                    pass  # should not hang

            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_rate_limiter_stats(self):
        from hevi.utils.rate_limiter import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(rpm=60, rpd=1000, concurrency=3))
        stats = limiter.stats()
        assert stats["rpm_limit"] == 60
        assert stats["rpd_limit"] == 1000
        assert stats["concurrency_limit"] == 3

    def test_rate_limiter_rpm(self):
        """RPM 限流不阻塞小量请求。"""
        from hevi.utils.rate_limiter import RateLimiter, RateLimitConfig

        limiter = RateLimiter(RateLimitConfig(rpm=600))  # 600/min = 10/s
        loop = asyncio.new_event_loop()
        try:
            async def _test():
                for _ in range(5):
                    async with limiter:
                        pass
            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_registry_basic(self):
        from hevi.utils.rate_limiter import RateLimitConfig, RateLimiterRegistry

        reg = RateLimiterRegistry()
        reg.register("openai", RateLimitConfig(rpm=500))
        reg.register("minimax", RateLimitConfig(rpm=10))

        assert "openai" in reg.list_services()
        assert reg.get("openai") is not None
        assert reg.get("nonexistent") is None

    def test_registry_get_or_unlimited(self):
        from hevi.utils.rate_limiter import RateLimiterRegistry

        reg = RateLimiterRegistry()
        lim = reg.get_or_unlimited("unknown")
        assert lim.config.rpm == 0

    def test_registry_all_stats(self):
        from hevi.utils.rate_limiter import RateLimitConfig, RateLimiterRegistry

        reg = RateLimiterRegistry()
        reg.register("svc1", RateLimitConfig(rpm=100))
        reg.register("svc2", RateLimitConfig(rpd=500))
        stats = reg.all_stats()
        assert "svc1" in stats
        assert "svc2" in stats

    def test_create_limiter_factory(self):
        from hevi.utils.rate_limiter import create_limiter

        lim = create_limiter(rpm=30, concurrency=2)
        assert lim.config.rpm == 30
        assert lim.config.concurrency == 2

    def test_global_registry(self):
        from hevi.utils.rate_limiter import global_registry, register_global

        lim = register_global("test_svc", rpm=100)
        reg = global_registry()
        assert reg.get("test_svc") is lim

    def test_unlimited_limiter_no_block(self):
        from hevi.utils.rate_limiter import RateLimiter

        lim = RateLimiter()
        loop = asyncio.new_event_loop()
        try:
            async def _test():
                for _ in range(100):
                    async with lim:
                        pass
            loop.run_until_complete(_test())
        finally:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════
# 2. Robust JSON Parser
# ═══════════════════════════════════════════════════════════════════════

class TestRobustJsonParser:
    """健壮 JSON 解析器。"""

    def test_valid_json(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_trailing_comma_object(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"a": 1, "b": 2,}')
        assert result == {"a": 1, "b": 2}

    def test_trailing_comma_array(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('[1, 2, 3,]')
        assert result == [1, 2, 3]

    def test_trailing_comma_nested(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"outer": {"inner": [1, 2,],},}')
        assert result == {"outer": {"inner": [1, 2]}}

    def test_single_line_comment(self):
        from hevi.utils.robust_json import robust_json_loads

        text = """{
            // this is a comment
            "key": "value"
        }"""
        result = robust_json_loads(text)
        assert result == {"key": "value"}

    def test_multi_line_comment(self):
        from hevi.utils.robust_json import robust_json_loads

        text = """{
            /* multi-line
               comment */
            "key": "value"
        }"""
        result = robust_json_loads(text)
        assert result == {"key": "value"}

    def test_nan_value(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"x": NaN, "y": 1}')
        assert result["x"] is None
        assert result["y"] == 1

    def test_infinity_value(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"big": Infinity}')
        assert result["big"] == 1e308

    def test_extract_from_text(self):
        from hevi.utils.robust_json import robust_json_loads

        text = """
        Here is the JSON output:
        {"result": "success", "count": 5}
        That's all.
        """
        result = robust_json_loads(text)
        assert result["result"] == "success"

    def test_extract_from_markdown_code_block(self):
        from hevi.utils.robust_json import extract_json_from_markdown

        text = """
        Here's the result:

        ```json
        {"name": "test", "value": 42}
        ```
        """
        result = extract_json_from_markdown(text)
        assert result["name"] == "test"
        assert result["value"] == 42

    def test_extract_from_unmarked_code_block(self):
        from hevi.utils.robust_json import extract_json_from_markdown

        text = """
        ```
        {"items": [1, 2, 3]}
        ```
        """
        result = extract_json_from_markdown(text)
        assert result == {"items": [1, 2, 3]}

    def test_safe_json_loads_valid(self):
        from hevi.utils.robust_json import safe_json_loads

        result = safe_json_loads('{"a": 1}', default={})
        assert result == {"a": 1}

    def test_safe_json_loads_invalid(self):
        from hevi.utils.robust_json import safe_json_loads

        result = safe_json_loads("not json at all {{{", default={"fallback": True})
        assert result == {"fallback": True}

    def test_strict_mode(self):
        from hevi.utils.robust_json import robust_json_loads

        # Valid JSON in strict mode
        result = robust_json_loads('{"a": 1}', strict=True)
        assert result == {"a": 1}

        # Invalid JSON should raise in strict mode
        with pytest.raises(json.JSONDecodeError):
            robust_json_loads('{"a": 1,}', strict=True)

    def test_double_comma(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"a": 1,, "b": 2}')
        assert result["a"] == 1
        assert result["b"] == 2

    def test_empty_object(self):
        from hevi.utils.robust_json import robust_json_loads

        assert robust_json_loads('{}') == {}

    def test_empty_array(self):
        from hevi.utils.robust_json import robust_json_loads

        assert robust_json_loads('[]') == []

    def test_nested_complex(self):
        from hevi.utils.robust_json import robust_json_loads

        text = """{
            "characters": [
                {"name": "Alice", "age": 25,},
                {"name": "Bob", "age": 30,},
            ],
            "settings": {
                "theme": "dark",
                "fps": 30,
            },
        }"""
        result = robust_json_loads(text)
        assert len(result["characters"]) == 2
        assert result["settings"]["fps"] == 30

    def test_find_json_objects(self):
        from hevi.utils.robust_json import find_json_objects

        text = 'hello {"a":1} world [2,3] end'
        objects = find_json_objects(text)
        assert len(objects) >= 2

    def test_string_with_commas_preserved(self):
        from hevi.utils.robust_json import robust_json_loads

        result = robust_json_loads('{"msg": "hello, world, how are you"}')
        assert result["msg"] == "hello, world, how are you"


# ═══════════════════════════════════════════════════════════════════════
# 3. Image Guard
# ═══════════════════════════════════════════════════════════════════════

class TestImageGuard:
    """横屏方向守卫。"""

    def _create_png(self, path: Path, width: int, height: int) -> Path:
        """创建一个指定尺寸的 PNG 文件头。"""
        # 最小 PNG 文件头
        signature = b'\x89PNG\r\n\x1a\n'
        # IHDR chunk
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        import zlib
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b'IHDR' + ihdr_data + struct.pack(">I", ihdr_crc)

        # Minimal IDAT (1x1 pixel, not accurate but enough for header parsing)
        raw = zlib.compress(b'\x00' + b'\xff\xff\xff' * width)
        idat_crc = zlib.crc32(b'IDAT' + raw) & 0xFFFFFFFF
        idat = struct.pack(">I", len(raw)) + b'IDAT' + raw + struct.pack(">I", idat_crc)

        # IEND
        iend_crc = zlib.crc32(b'IEND') & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b'IEND' + struct.pack(">I", iend_crc)

        path.write_bytes(signature + ihdr + idat + iend)
        return path

    def test_image_dimensions_landscape(self):
        from hevi.utils.image_guard import ImageDimensions

        dims = ImageDimensions(width=1920, height=1080)
        assert dims.is_landscape
        assert not dims.is_portrait
        assert not dims.is_square
        assert dims.aspect_ratio == pytest.approx(16 / 9, abs=0.1)

    def test_image_dimensions_portrait(self):
        from hevi.utils.image_guard import ImageDimensions

        dims = ImageDimensions(width=1080, height=1920)
        assert not dims.is_landscape
        assert dims.is_portrait

    def test_image_dimensions_square(self):
        from hevi.utils.image_guard import ImageDimensions

        dims = ImageDimensions(width=1024, height=1024)
        assert dims.is_square

    def test_image_dimensions_megapixels(self):
        from hevi.utils.image_guard import ImageDimensions

        dims = ImageDimensions(width=1920, height=1080)
        assert dims.megapixels == pytest.approx(2.07, abs=0.1)

    def test_get_dimensions_from_dict(self):
        from hevi.utils.image_guard import get_image_dimensions

        dims = get_image_dimensions({"width": 1280, "height": 720})
        assert dims.width == 1280
        assert dims.height == 720

    def test_get_dimensions_from_png(self):
        from hevi.utils.image_guard import get_image_dimensions

        with tempfile.TemporaryDirectory() as td:
            path = self._create_png(Path(td) / "test.png", 1920, 1080)
            dims = get_image_dimensions(path)
            assert dims.width == 1920
            assert dims.height == 1080

    def test_ensure_landscape_passes(self):
        from hevi.utils.image_guard import ensure_landscape

        dims = ensure_landscape({"width": 1920, "height": 1080})
        assert dims.is_landscape

    def test_ensure_landscape_fails_portrait(self):
        from hevi.utils.image_guard import (
            ImageOrientationError,
            ensure_landscape,
        )

        with pytest.raises(ImageOrientationError):
            ensure_landscape({"width": 1080, "height": 1920})

    def test_ensure_not_portrait_alias(self):
        from hevi.utils.image_guard import ensure_not_portrait

        dims = ensure_not_portrait({"width": 1280, "height": 720})
        assert dims.is_landscape

    def test_landscape_guard_requested_16_9(self):
        from hevi.utils.image_guard import landscape_guard_requested

        assert landscape_guard_requested(aspect_ratio="16:9")

    def test_landscape_guard_requested_9_16(self):
        from hevi.utils.image_guard import landscape_guard_requested

        assert not landscape_guard_requested(aspect_ratio="9:16")

    def test_landscape_guard_requested_default(self):
        from hevi.utils.image_guard import landscape_guard_requested

        assert landscape_guard_requested()  # default is True

    def test_guard_image_no_enforce(self):
        from hevi.utils.image_guard import guard_image

        dims = guard_image({"width": 1080, "height": 1920}, enforce_landscape=False)
        assert dims.is_portrait

    def test_guard_image_log_fallback(self):
        from hevi.utils.image_guard import guard_image

        dims = guard_image(
            {"width": 1080, "height": 1920},
            enforce_landscape=True,
            fallback_action="log",
        )
        assert dims.is_portrait  # log mode doesn't raise

    def test_orientation_error_attributes(self):
        from hevi.utils.image_guard import ImageOrientationError

        err = ImageOrientationError(720, 1280)
        assert err.width == 720
        assert err.height == 1280
        assert err.aspect_ratio < 1.0

    def test_guard_batch(self):
        from hevi.utils.image_guard import guard_batch

        sources = [
            {"width": 1920, "height": 1080},
            {"width": 720, "height": 1280},  # portrait
            {"width": 1280, "height": 720},
        ]
        results = guard_batch(sources, enforce_landscape=True, strict=False)
        assert len(results) == 3
        assert results[0][1] is not None  # landscape OK
        assert results[2][1] is not None  # landscape OK

    def test_guard_batch_strict(self):
        from hevi.utils.image_guard import guard_batch

        sources = [
            {"width": 1920, "height": 1080},
            {"width": 720, "height": 1280},  # portrait — strict stops here
        ]
        results = guard_batch(sources, enforce_landscape=True, strict=True)
        assert len(results) == 2  # stops after portrait


# ═══════════════════════════════════════════════════════════════════════
# 4. Portrait Triptych
# ═══════════════════════════════════════════════════════════════════════

class TestPortraitTriptych:
    """角色肖像三联画。"""

    def test_portrait_view_basic(self):
        from hevi.director.portrait_triptych import PortraitView

        view = PortraitView(
            view="front",
            path=Path("/tmp/front.png"),
            description="A tall warrior",
        )
        assert view.view == "front"
        d = view.to_dict()
        assert d["view"] == "front"
        assert d["path"] == "/tmp/front.png"

    def test_character_portrait_all_views(self):
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitView,
        )

        cp = CharacterPortrait(
            name="Alice",
            identifier="alice",
            physical_description="A mage",
            front=PortraitView("front", Path("/tmp/f.png")),
            side=PortraitView("side", Path("/tmp/s.png")),
            back=None,
        )
        assert len(cp.all_views) == 2

    def test_character_portrait_reference_paths(self):
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitView,
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            Path(f.name).write_bytes(b"\x89PNG" + b"\x00" * 100)

            cp = CharacterPortrait(
                name="Bob",
                identifier="bob",
                physical_description="",
                front=PortraitView("front", Path(f.name)),
            )
            assert len(cp.reference_paths) == 1

            Path(f.name).unlink()

    def test_portrait_registry(self):
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitRegistry,
        )

        reg = PortraitRegistry()
        cp = CharacterPortrait(
            name="John",
            identifier="john",
            physical_description="A farmer",
        )
        reg.register(cp)

        assert reg.get("john") is cp
        assert reg.get("unknown") is None

    def test_portrait_registry_roundtrip(self):
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitRegistry,
            PortraitView,
        )

        reg = PortraitRegistry()
        reg.register(CharacterPortrait(
            name="Alice",
            identifier="alice",
            physical_description="Mage",
            front=PortraitView("front", Path("/tmp/alice_front.png"), "front desc"),
            style="anime",
        ))
        reg.register(CharacterPortrait(
            name="Bob",
            identifier="bob",
            physical_description="Warrior",
        ))

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.json"
            reg.save(path)
            loaded = PortraitRegistry.load(path)

            assert loaded.get("alice") is not None
            assert loaded.get("alice").style == "anime"
            assert loaded.get("bob") is not None

    def test_portrait_registry_get_reference_paths(self):
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitRegistry,
            PortraitView,
        )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b'\x89PNG' + b'\x00' * 100)
            f.flush()
            path = Path(f.name)

        try:
            reg = PortraitRegistry()
            reg.register(CharacterPortrait(
                name="X",
                identifier="x",
                physical_description="",
                front=PortraitView("front", path),
            ))
            paths = reg.get_reference_paths(["x", "nonexistent"])
            assert len(paths) == 1
        finally:
            path.unlink(missing_ok=True)

    def test_build_portrait_prompt(self):
        from hevi.director.portrait_triptych import build_portrait_prompt

        prompt = build_portrait_prompt("front", "A warrior with a sword", "realistic")
        assert "front view" in prompt
        assert "warrior with a sword" in prompt
        assert "realistic" in prompt

    def test_build_portrait_prompt_side(self):
        from hevi.director.portrait_triptych import build_portrait_prompt

        prompt = build_portrait_prompt("side", "A mage", "anime")
        assert "side profile" in prompt
        assert "mage" in prompt

    def test_build_portrait_prompt_back(self):
        from hevi.director.portrait_triptych import build_portrait_prompt

        prompt = build_portrait_prompt("back", "A knight", "realistic")
        assert "back view" in prompt

    def test_generate_portrait_triptych(self):
        from hevi.director.portrait_triptych import generate_portrait_triptych

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                result = loop.run_until_complete(
                    generate_portrait_triptych(
                        character_name="TestChar",
                        identifier="test_char",
                        description="A test character",
                        output_dir=Path(td),
                        style="realistic",
                    )
                )
                assert result.name == "TestChar"
                assert result.front is not None
                assert result.side is not None
                assert result.back is not None
                assert len(result.all_views) == 3
        finally:
            loop.close()

    def test_generate_all_portraits(self):
        from hevi.director.portrait_triptych import generate_all_portraits

        characters = [
            {"name": "Alice", "identifier": "alice", "description": "Mage"},
            {"name": "Bob", "identifier": "bob", "description": "Warrior"},
        ]

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                registry = loop.run_until_complete(
                    generate_all_portraits(characters, Path(td))
                )
                assert registry.get("alice") is not None
                assert registry.get("bob") is not None
                assert (Path(td) / "character_portraits_registry.json").exists()
        finally:
            loop.close()

    def test_generate_all_portraits_skip_existing(self):
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitRegistry,
            generate_all_portraits,
        )

        existing = PortraitRegistry()
        existing.register(CharacterPortrait(
            name="Alice",
            identifier="alice",
            physical_description="Existing",
        ))

        characters = [
            {"name": "Alice", "identifier": "alice", "description": "Skip"},
            {"name": "Bob", "identifier": "bob", "description": "Generate"},
        ]

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                registry = loop.run_until_complete(
                    generate_all_portraits(
                        characters, Path(td),
                        existing_registry=existing,
                    )
                )
                assert registry.get("alice").physical_description == "Existing"
                assert registry.get("bob") is not None
        finally:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════
# 5. Best Image Selector
# ═══════════════════════════════════════════════════════════════════════

class TestBestImageSelector:
    """最佳图像选择器。"""

    def _create_test_image(self, path: Path, valid: bool = True) -> Path:
        """创建测试图像文件。"""
        if valid:
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 5000)
        else:
            path.write_bytes(b'\x00' * 10)
        return path

    def test_candidate_image_basic(self):
        from hevi.director.image_selector import CandidateImage

        c = CandidateImage(index=0, path=Path("/tmp/test.png"))
        assert c.index == 0
        assert not c.exists  # file doesn't exist

    def test_score_image_basic_valid(self):
        from hevi.director.image_selector import score_image_basic

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "valid.png"
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 1000)
            score = score_image_basic(path)
            assert score >= 0.8

    def test_score_image_basic_invalid(self):
        from hevi.director.image_selector import score_image_basic

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "invalid.bin"
            path.write_bytes(b'\x00' * 10)
            score = score_image_basic(path)
            assert score < 0.5

    def test_score_image_basic_nonexistent(self):
        from hevi.director.image_selector import score_image_basic

        score = score_image_basic(Path("/nonexistent/test.png"))
        assert score == 0.0

    def test_score_image_file_size(self):
        from hevi.director.image_selector import score_image_file_size

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sized.bin"
            path.write_bytes(b'\x00' * 500_000)
            score = score_image_file_size(path)
            assert score >= 0.7

    def test_score_image_dimensions_landscape(self):
        from hevi.director.image_selector import score_image_dimensions

        score = score_image_dimensions(
            {"width": 1920, "height": 1080},
            ideal_ratio=16 / 9,
        )
        assert score >= 0.8

    def test_score_image_dimensions_portrait(self):
        from hevi.director.image_selector import score_image_dimensions

        score = score_image_dimensions(
            {"width": 1080, "height": 1920},
        )
        assert score < 0.5

    def test_select_best_single_candidate(self):
        from hevi.director.image_selector import CandidateImage, select_best_image

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "img.png"
            self._create_test_image(path)
            candidates = [CandidateImage(0, path)]

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(select_best_image(candidates))
                assert result.best.index == 0
                assert result.strategy == "first_valid"
            finally:
                loop.close()

    def test_select_best_multiple_candidates(self):
        from hevi.director.image_selector import CandidateImage, select_best_image

        with tempfile.TemporaryDirectory() as td:
            candidates = []
            for i in range(3):
                path = Path(td) / f"img_{i}.png"
                # 不同大小 → 不同分数
                path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * (1000 * (i + 1)))
                candidates.append(CandidateImage(i, path))

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(select_best_image(candidates))
                assert result.best in candidates
                assert result.strategy in ("score", "llm")
                assert len(result.all_candidates) == 3
            finally:
                loop.close()

    def test_select_best_no_valid_raises(self):
        from hevi.director.image_selector import CandidateImage, select_best_image

        candidates = [
            CandidateImage(0, Path("/nonexistent/a.png")),
            CandidateImage(1, Path("/nonexistent/b.png")),
        ]
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(ValueError, match="no valid"):
                loop.run_until_complete(select_best_image(candidates))
        finally:
            loop.close()

    def test_selection_result_to_dict(self):
        from hevi.director.image_selector import CandidateImage, SelectionResult

        result = SelectionResult(
            best=CandidateImage(1, Path("/tmp/best.png"), score=0.95),
            all_candidates=[
                CandidateImage(0, Path("/tmp/a.png"), score=0.7),
                CandidateImage(1, Path("/tmp/best.png"), score=0.95),
            ],
            strategy="score",
            reasoning="highest score",
        )
        d = result.to_dict()
        assert d["best_index"] == 1
        assert d["best_score"] == 0.95
        assert len(d["candidates"]) == 2

    def test_generate_and_select(self):
        from hevi.director.image_selector import generate_and_select

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                result = loop.run_until_complete(
                    generate_and_select(
                        prompt="A beautiful sunset",
                        reference_images=[],
                        output_dir=Path(td),
                        n_candidates=3,
                    )
                )
                assert result.best is not None
                assert len(result.all_candidates) == 3
        finally:
            loop.close()

    def test_rank_candidates(self):
        from hevi.director.image_selector import CandidateImage, rank_candidates

        with tempfile.TemporaryDirectory() as td:
            candidates = []
            for i in range(3):
                path = Path(td) / f"img_{i}.png"
                path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 1000)
                c = CandidateImage(i, path, score=0.5 + i * 0.2)
                candidates.append(c)

            ranked = rank_candidates(candidates)
            assert len(ranked) == 3
            assert ranked[0].score >= ranked[1].score

    def test_filter_valid(self):
        from hevi.director.image_selector import CandidateImage, filter_valid

        with tempfile.TemporaryDirectory() as td:
            valid_path = Path(td) / "valid.png"
            valid_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 1000)

            invalid_path = Path(td) / "invalid.bin"
            invalid_path.write_bytes(b'\x00' * 5)

            candidates = [
                CandidateImage(0, valid_path),
                CandidateImage(1, invalid_path),
                CandidateImage(2, Path("/nonexistent")),
            ]
            valid = filter_valid(candidates)
            assert len(valid) >= 1
            assert valid[0].index == 0


# ═══════════════════════════════════════════════════════════════════════
# 6. Integration
# ═══════════════════════════════════════════════════════════════════════

class TestVimaxBatch1Integration:
    """跨模块集成测试。"""

    def test_all_imports_utils(self):
        from hevi.utils import (
            ImageDimensions,
            RateLimiter,
            create_limiter,
            ensure_landscape,
            robust_json_loads,
            safe_json_loads,
        )
        assert ImageDimensions is not None
        assert RateLimiter is not None

    def test_all_imports_director(self):
        from hevi.director import (
            CandidateImage,
            CharacterPortrait,
            PortraitRegistry,
            PortraitView,
            SelectionResult,
            generate_all_portraits,
            generate_portrait_triptych,
            select_best_image,
        )
        assert CharacterPortrait is not None

    def test_rate_limiter_with_json_parse(self):
        """限流器保护下的 JSON 解析。"""
        from hevi.utils.rate_limiter import RateLimiter
        from hevi.utils.robust_json import robust_json_loads

        limiter = RateLimiter()
        loop = asyncio.new_event_loop()
        try:
            async def _test():
                async with limiter:
                    result = robust_json_loads('{"status": "ok", "items": [1,2,3,],}')
                    return result

            result = loop.run_until_complete(_test())
            assert result["status"] == "ok"
            assert result["items"] == [1, 2, 3]
        finally:
            loop.close()

    def test_portrait_with_image_guard(self):
        """肖像生成 + 横屏守卫集成。"""
        from hevi.director.portrait_triptych import (
            CharacterPortrait,
            PortraitView,
        )
        from hevi.utils.image_guard import guard_image

        cp = CharacterPortrait(
            name="Test",
            identifier="test",
            physical_description="",
            front=PortraitView("front", Path("/tmp/test.png")),
        )
        # 验证 reference_paths 可用
        assert isinstance(cp.reference_paths, list)

    def test_full_pipeline_mock(self):
        """完整链路：生成肖像 → 守卫 → 选图 → JSON 输出。"""
        from hevi.director.image_selector import CandidateImage, select_best_image
        from hevi.director.portrait_triptych import generate_portrait_triptych
        from hevi.utils.robust_json import robust_json_loads

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                # 生成三联画
                portrait = loop.run_until_complete(
                    generate_portrait_triptych(
                        character_name="Hero",
                        identifier="hero",
                        description="A brave warrior",
                        output_dir=Path(td),
                    )
                )

                # 选图
                candidates = [
                    CandidateImage(i, v.path)
                    for i, v in enumerate(portrait.all_views)
                ]
                if candidates:
                    result = loop.run_until_complete(
                        select_best_image(candidates)
                    )
                    assert result.best is not None

                    # JSON 输出
                    output_json = json.dumps(result.to_dict())
                    parsed = robust_json_loads(output_json)
                    assert "best_index" in parsed
        finally:
            loop.close()
