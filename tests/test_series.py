"""Series 资产化测试(§3 L2)—— 继承逻辑(无 DB,mock)。"""

from __future__ import annotations

import uuid

import pytest

from hevi.series.series_service import SeriesService

_SID = str(uuid.uuid4())


class _FakeSeriesRepo:
    def __init__(self, series):
        self._series = series
        self.updated = []

    async def get(self, sid):
        return self._series

    async def update(self, sid, updates):
        self.updated.append(updates)
        self._series = {**self._series, **updates}
        return self._series


class _FakeTaskRepo:
    def __init__(self):
        self.updates = []

    async def update_task(self, tid, data):
        self.updates.append((tid, data))
        return True


class _FakeTaskSvc:
    def __init__(self):
        self.repository = _FakeTaskRepo()
        self.create_calls = []

    async def create_task(
        self, *, topic, duration_archetype, video_provider, audio_provider, user_id=None, **kw
    ):
        self.create_calls.append(
            {
                "topic": topic,
                "duration_archetype": duration_archetype,
                "video_provider": video_provider,
                "audio_provider": audio_provider,
                **kw,
            }
        )
        return {"id": "t1", "topic": topic, "config_json": kw}


@pytest.mark.asyncio
async def test_create_episode_inherits_all_but_topic():
    series = {
        "id": _SID,
        "user_id": "u1",
        "subject_ids": ["hero"],
        "style_preset": "赛博朋克",
        "episode_count": 3,
        "spec_json": {
            "duration_archetype": "short",
            "video_provider": "wan_local",
            "audio_provider": "vibevoice",
            "num_characters": 2,
            "quality_profile": "high",
        },
    }
    repo = _FakeSeriesRepo(series)
    tsvc = _FakeTaskSvc()
    ep = await SeriesService(repo, tsvc).create_episode(_SID, topic="第4集")

    call = tsvc.create_calls[0]
    assert call["topic"] == "第4集"  # 只有 topic 是新的
    assert call["duration_archetype"] == "short" and call["video_provider"] == "wan_local"
    assert call["style_preset"] == "赛博朋克" and call["subject_id"] == "hero"
    assert call["num_characters"] == 2 and call["quality_profile"] == "high"  # spec 全继承
    assert ep["episode_index"] == 3  # 继承 episode_count
    assert tsvc.repository.updates[0][1]["episode_index"] == 3  # FK 绑定
    assert repo.updated[-1]["episode_count"] == 4  # 集数递增


@pytest.mark.asyncio
async def test_create_episode_inherits_intro_outro_clips():
    """片头/片尾:此前只存不消费,现在 create_episode 把它们透传进 create_task。"""
    series = {
        "id": _SID,
        "subject_ids": [],
        "episode_count": 0,
        "spec_json": {"video_provider": "wan_local"},
        "intro_template_id": "/assets/intro.mp4",
        "outro_template_id": "/assets/outro.mp4",
    }
    tsvc = _FakeTaskSvc()
    await SeriesService(_FakeSeriesRepo(series), tsvc).create_episode(_SID, topic="ep1")
    call = tsvc.create_calls[0]
    assert call["intro_clip"] == "/assets/intro.mp4"
    assert call["outro_clip"] == "/assets/outro.mp4"


@pytest.mark.asyncio
async def test_create_series_empty_name_raises():
    with pytest.raises(ValueError):
        await SeriesService(_FakeSeriesRepo({}), None).create_series(name="   ")


@pytest.mark.asyncio
async def test_create_episode_unknown_series_raises():
    class _NoneRepo:
        async def get(self, sid):
            return None

    with pytest.raises(ValueError):
        await SeriesService(_NoneRepo(), _FakeTaskSvc()).create_episode(_SID, topic="t")


@pytest.mark.asyncio
async def test_create_episode_without_task_service_raises():
    with pytest.raises(ValueError):
        await SeriesService(_FakeSeriesRepo({"id": _SID, "spec_json": {}}), None).create_episode(
            _SID, topic="t"
        )


class _FakeStyleSvc:
    async def resolve(self, pid):
        return {
            "style": "cinematic noir",
            "lighting": "soft",
            "camera": "dolly",
            "color_grade": "teal orange",
            "negative": "text",
        }


@pytest.mark.asyncio
async def test_create_episode_expands_stylepack_to_prompts():
    """Series 引用 StylePack → create_episode resolve 展开成 prompt_*(覆盖 preset)。"""
    series = {
        "id": _SID,
        "style_pack_id": _SID,
        "style_preset": "电影感",
        "subject_ids": [],
        "episode_count": 0,
        "spec_json": {"video_provider": "wan_local"},
    }
    tsvc = _FakeTaskSvc()
    svc = SeriesService(_FakeSeriesRepo(series), tsvc, _FakeStyleSvc())
    await svc.create_episode(_SID, topic="ep1")
    call = tsvc.create_calls[0]
    assert call["prompt_style"] == "cinematic noir"
    assert call["prompt_color_grade"] == "teal orange"
    assert call["prompt_camera"] == "dolly"
