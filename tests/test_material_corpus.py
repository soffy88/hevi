"""material_corpus 测试 —— 素材语料库纯函数 + 多源检索降级(差距 A4/B9)。

纯函数部分(画幅/时长/关键词/挑选/去重)零网络; IO 部分用 mock httpx 模拟
Pexels/Pixabay/Coverr/Archive 响应与失败降级。
"""

from __future__ import annotations

from pathlib import Path

import httpx

from hevi.video.material_corpus import (
    MaterialInfo,
    aspect_fit,
    dedupe,
    ensure_cached,
    filter_by_aspect,
    filter_by_duration,
    pick_best,
    rank_by_keywords,
    search_all,
    search_archive_videos,
    search_coverr_videos,
    search_pexels_videos,
    search_pixabay_videos,
)


def _m(**kw) -> MaterialInfo:
    base = {"source": "pexels", "id": "1", "url": "https://x/1.mp4", "width": 720, "height": 1280, "duration_s": 5.0, "title": "sunset", "keywords": ("sunset", "sky")}
    base.update(kw)
    return MaterialInfo(**base)


def test_aspect_fit_known_and_unknown():
    assert aspect_fit("9:16", "9:16") == 1.0
    assert aspect_fit("9:16", "16:9") == 0.2
    assert aspect_fit("9:16", "") == 0.0
    assert aspect_fit("16:9", "16:9") == 1.0


def test_aspect_detection():
    assert _m().aspect == "9:16"  # 720x1280
    assert _m(width=1280, height=720).aspect == "16:9"
    assert _m(width=800, height=800).aspect == "1:1"


def test_filter_by_aspect():
    items = [_m(), _m(width=1280, height=720), _m(width=800, height=800)]
    out = filter_by_aspect(items, "9:16")
    assert [m.aspect for m in out] == ["9:16", "1:1"]
    out_strict = filter_by_aspect(items, "9:16", min_fit=0.9)
    assert [m.aspect for m in out_strict] == ["9:16"]


def test_filter_by_duration():
    items = [_m(duration_s=5.0), _m(id="2", duration_s=0.0), _m(id="3", duration_s=30.0)]
    out = filter_by_duration(items, min_s=4.0, max_s=20.0)
    assert {m.id for m in out} == {"1", "2"}  # 未知时长保留


def test_rank_by_keywords():
    items = [
        _m(id="a", title="beach sunset", keywords=("ocean",)),
        _m(id="b", title="city night", keywords=("sunset",)),
        _m(id="c", title="plain", keywords=()),
    ]
    ranked = rank_by_keywords(items, "sunset")
    assert ranked[0].id == "a"
    assert ranked[1].id == "b"


def test_pick_best_pipeline():
    items = [
        _m(id="a", title="beach sunset", width=1280, height=720, duration_s=30.0),
        _m(id="b", title="sunset timelapse", width=720, height=1280, duration_s=6.0),
        _m(id="c", title="sunset slow", width=720, height=1280, duration_s=60.0),
    ]
    best = pick_best(items, "sunset", target_aspect="9:16", min_s=4.0, max_s=10.0)
    assert best is not None and best.id == "b"


def test_pick_best_no_match():
    assert pick_best([], "x") is None
    assert pick_best([_m(width=1280, height=720)], "x", target_aspect="9:16") is None


def test_dedupe():
    items = [_m(), _m(), _m(id="2")]
    assert len(dedupe(items)) == 2


def test_ensure_cached_downloads(tmp_path: Path):
    item = _m(url="https://cdn.example.com/clip.mp4")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://cdn.example.com/clip.mp4"
        return httpx.Response(200, content=b"\x00\x01video")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    got = ensure_cached(item, tmp_path, client=client)
    assert got.cached_path
    assert Path(got.cached_path).exists()
    assert Path(got.cached_path).read_bytes() == b"\x00\x01video"
    # 二次命中不重复下载
    got2 = ensure_cached(got, tmp_path, client=httpx.Client())
    assert got2.cached_path == got.cached_path


def test_ensure_cached_failure_returns_original(tmp_path: Path):
    item = _m(url="https://cdn.example.com/missing.mp4")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    got = ensure_cached(item, tmp_path, client=client)
    assert got.cached_path == ""
    assert not list(tmp_path.iterdir())


def test_search_pexels_requires_key():
    assert search_pexels_videos("x", "") == []


def test_search_pexels_success():
    payload = {
        "videos": [
            {
                "id": 111,
                "duration": 8,
                "url": "https://www.pexels.com/video/111/",
                "user": {"name": "pho"},
                "video_files": [
                    {"width": 640, "height": 1136, "link": "https://d/111_sd.mp4"},
                    {"width": 1280, "height": 2272, "link": "https://d/111_hd.mp4"},
                ],
                "tags": ["sunset", "ocean"],
            }
        ]
    }
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "KEY123"
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = search_pexels_videos("sunset", "KEY123", client=client)
    assert len(items) == 1
    m = items[0]
    assert m.source == "pexels"
    assert m.url == "https://d/111_hd.mp4"  # 取最大分辨率
    assert m.duration_s == 8.0


def test_search_pexels_failure_degrades():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert search_pexels_videos("x", "KEY", client=client) == []


def test_search_pixabay_success():
    payload = {
        "hits": [
            {
                "id": 222,
                "width": 720,
                "height": 1280,
                "duration": 6,
                "pageURL": "https://pixabay.com/videos/222/",
                "tags": "sunset, sky",
                "videos": {"large": {"url": "https://v/222_large.mp4"}},
            }
        ]
    }
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = search_pixabay_videos("sunset", "KEY", client=client)
    assert len(items) == 1
    assert items[0].source == "pixabay"
    assert items[0].keywords == ("sunset", " sky")


def test_search_coverr_and_archive_success():
    coverr_payload = {
        "hits": [{"id": "c1", "title": "beach", "duration": 10, "mp4": "https://c/1.mp4", "tags": ["beach"]}]
    }
    archive_payload = {
        "response": {"docs": [{"identifier": "id-1", "title": "old film", "length": 60.0}]}
    }
    def handler(request: httpx.Request) -> httpx.Response:
        if "coverr" in str(request.url):
            return httpx.Response(200, json=coverr_payload)
        return httpx.Response(200, json=archive_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    coverr = search_coverr_videos("beach", "", client=client)
    arch = search_archive_videos("film", client=client)
    assert coverr[0].source == "coverr"
    assert arch[0].source == "archive"
    assert arch[0].url.startswith("https://archive.org/download/")


def test_search_all_merges_and_dedupes():
    def pexels_ok(**kw):
        return httpx.Response(
            200,
            json={"videos": [{"id": 1, "duration": 5, "url": "u", "video_files": [{"width": 720, "height": 1280, "link": "https://d/1.mp4"}]}]},
        )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "pexels" in url:
            return pexels_ok()
        return httpx.Response(200, json={"hits": []} if "pixabay" in url or "coverr" in url else {"response": {"docs": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items = search_all(
        "sunset",
        pexels_key="K1",
        pixabay_key="K2",
        client=client,
    )
    assert len(items) == 1
    assert items[0].source == "pexels"
