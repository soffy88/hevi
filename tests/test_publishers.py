"""B2 跨平台一键发布 —— 发布器骨架/注册表/一体入口测试。

覆盖 hevi/publishers 的:
  - 默认 3 个 stub(TikTok/IG/YT): 恒不可用 + publish 返回 skipped
  - 注册表: 注册/覆盖/按平台列出
  - publish_to_platform: 未知平台/不可用/媒体缺失/异常 → 降级返回(不 raise)
  - 注入可用发布器 → published 路径
"""

from __future__ import annotations

from pathlib import Path

from hevi.publishers import (
    PLATFORM_INSTAGRAM,
    PLATFORM_TIKTOK,
    PLATFORM_YOUTUBE,
    Publisher,
    PublishResult,
    get_publisher,
    list_publishers,
    publish_to_platform,
    register_publisher,
)


class TestDefaults:
    def test_three_stub_publishers_registered(self) -> None:
        assert get_publisher(PLATFORM_TIKTOK) is not None
        assert get_publisher(PLATFORM_INSTAGRAM) is not None
        assert get_publisher(PLATFORM_YOUTUBE) is not None

    def test_stubs_all_unavailable(self) -> None:
        for name in (PLATFORM_TIKTOK, PLATFORM_INSTAGRAM, PLATFORM_YOUTUBE):
            pub = get_publisher(name)
            assert pub is not None and pub.available() is False

    def test_list_publishers_contains_platforms(self) -> None:
        items = list_publishers()
        platforms = {p for it in items for p in it["platforms"]}
        assert PLATFORM_TIKTOK in platforms
        stub_names = {PLATFORM_TIKTOK, PLATFORM_INSTAGRAM, PLATFORM_YOUTUBE}
        stubs = [it for it in items if it["name"] in stub_names]
        assert stubs and all(it["available"] is False for it in stubs)
        assert "douyin" in platforms


class TestPublishEntry:
    async def test_unknown_platform_failed(self) -> None:
        r = await publish_to_platform("nonexistent", Path("/tmp/x.mp4"))
        assert r.status == "failed"
        assert "unknown publisher" in r.reason

    async def test_stub_skipped_when_unavailable(self, tmp_path: Path) -> None:
        media = tmp_path / "out.mp4"
        media.write_bytes(b"fake")
        r = await publish_to_platform(PLATFORM_TIKTOK, media)
        assert r.status == "skipped"
        assert "credentials" in r.reason
        assert r.trail == [{"step": "detect_credentials", "ok": False}]

    async def test_missing_media_failed(self, tmp_path: Path) -> None:
        r = await publish_to_platform(PLATFORM_TIKTOK, tmp_path / "nope.mp4")
        assert r.status == "skipped"  # 先被凭据探测拦住(不可用), 不 reach 媒体检查
        # 用可用发布器验证媒体缺失分支
        reg = FakePublisher(available=True)
        register_publisher(reg)
        r2 = await publish_to_platform("fake_pub", tmp_path / "nope.mp4")
        assert r2.status == "failed"
        assert "media not found" in r2.reason

    async def test_published_path(self, tmp_path: Path) -> None:
        media = tmp_path / "out.mp4"
        media.write_bytes(b"fake")
        reg = FakePublisher(available=True)
        register_publisher(reg)
        r = await publish_to_platform(
            "fake_pub", media, title="T", description="D", tags=["a"]
        )
        assert r.status == "published"
        assert r.external_id == "ext-1"
        assert r.url == "https://fake.example/v/1"
        assert reg.last_call["title"] == "T"
        assert reg.last_call["tags"] == ["a"]

    async def test_exception_degrades_to_failed(self, tmp_path: Path) -> None:
        media = tmp_path / "out.mp4"
        media.write_bytes(b"fake")

        class BoomPublisher(FakePublisher):
            async def publish(self, media_path: Path, **meta: object) -> PublishResult:
                raise RuntimeError("boom")

        register_publisher(BoomPublisher(available=True))
        r = await publish_to_platform("fake_pub", media)
        assert r.status == "failed"
        assert "boom" in r.reason

    async def test_douyin_writes_handoff_ticket(self, tmp_path: Path) -> None:
        media = tmp_path / "out.mp4"
        media.write_bytes(b"fake")
        r = await publish_to_platform("douyin", media, title="盐税", tags=["史"])
        assert r.status == "handoff"
        ticket = Path(str(r.external_id))
        assert ticket.exists()
        assert "douyin" in ticket.name


class FakePublisher(Publisher):
    """可注入的假发布器: available 可控, 记录调用, 返回固定结果。"""

    name = "fake_pub"
    platforms = ("fake_pub",)

    def __init__(self, *, available: bool) -> None:
        self._available = available
        self.last_call: dict[str, object] = {}

    def available(self) -> bool:
        return self._available

    async def publish(
        self,
        media_path: Path,
        *,
        title: str = "",
        description: str = "",
        tags: list[str] | None = None,
        **meta: object,
    ) -> PublishResult:
        self.last_call = {
            "media_path": media_path,
            "title": title,
            "description": description,
            "tags": tags,
        }
        return PublishResult(
            status="published",
            platform=self.name,
            external_id="ext-1",
            url="https://fake.example/v/1",
        )


class TestRegister:
    def test_override_duplicate_name(self) -> None:
        reg = FakePublisher(available=True)
        register_publisher(reg)
        assert get_publisher("fake_pub") is reg
        # 再注册同 name → 覆盖
        reg2 = FakePublisher(available=False)
        register_publisher(reg2)
        assert get_publisher("fake_pub") is reg2

    def test_platform_alias_resolves_to_publisher(self) -> None:
        # 默认: platform 键直接指向 stub 发布器
        assert get_publisher(PLATFORM_TIKTOK).name == PLATFORM_TIKTOK
