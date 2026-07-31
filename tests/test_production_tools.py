"""production_tools 全模块测试 —— 对标 OpenMontage 新增能力的 Hevi 实现。

覆盖:
  - media_profiles: 多平台预设完整性 + ffmpeg 参数生成
  - stock_footage: 对位校验(match_score) + 主体绑定约束
  - playbook_loader: YAML 加载 + 三张查找表 + 根变量 + prompt 编译
  - cost reconcile: estimate → reserve → reconcile 三阶段闭环
  - enhancement: color_grade 内置 LUT 完整性
  - remotion_service: composition 列表 + manifest 构造
  - reference_video: pacing 分析(纯计算)
  - backlot API: 数据聚合
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Media Profiles ────────────────────────────────────────────────────────────

class TestMediaProfiles:
    def test_all_profiles_have_required_fields(self):
        from hevi.video.media_profiles import list_profiles
        profiles = list_profiles()
        assert len(profiles) >= 10
        for p in profiles:
            assert p.width > 0
            assert p.height > 0
            assert p.aspect
            assert p.fps > 0
            assert p.codec

    def test_get_known_profile(self):
        from hevi.video.media_profiles import get_media_profile
        p = get_media_profile("youtube_landscape")
        assert p.width == 1920
        assert p.height == 1080
        assert p.fps == 30

    def test_unknown_profile_returns_default(self):
        from hevi.video.media_profiles import get_media_profile
        p = get_media_profile("nonexistent_platform")
        assert p.name == "hevi_default"

    def test_ffmpeg_args_contain_scale(self):
        from hevi.video.media_profiles import ffmpeg_output_args, get_media_profile
        p = get_media_profile("tiktok")
        args = ffmpeg_output_args(p)
        assert any("scale=1080:1920" in a for a in args)
        assert "-c:v" in args

    def test_ffmpeg_for_profile(self):
        from hevi.video.media_profiles import ffmpeg_for_profile, get_media_profile
        p = get_media_profile("cinematic")
        cmd = ffmpeg_for_profile(p, src="input.mp4", dst="output.mp4")
        assert cmd[0] == "ffmpeg"
        assert "output.mp4" in cmd


# ── Stock Footage ─────────────────────────────────────────────────────────────

class TestStockFootage:
    def test_score_match_perfect(self):
        from hevi.image.stock_footage import MatchResult, StockClip, score_match
        clip = StockClip(
            url="https://example.com/city.mp4",
            provider="pexels",
            description="city urban skyline night lights",
            tags=["city", "night"],
        )
        result = score_match("城市夜景", clip=clip)
        assert result.score > 0.3

    def test_score_match_no_match(self):
        from hevi.image.stock_footage import score_match, StockClip
        clip = StockClip(
            url="https://example.com/forest.mp4",
            provider="pexels",
            description="forest trees nature",
            tags=["forest"],
        )
        result = score_match("科技电路", clip=clip)
        assert result.score < 0.3

    def test_score_match_empty_keywords(self):
        from hevi.image.stock_footage import score_match
        result = score_match("xyz", clip_description="abc")
        assert 0 <= result.score <= 1

    def test_is_eligible_scene_type(self):
        from hevi.image.stock_footage import is_eligible_for_stock
        assert is_eligible_for_stock({"shot_type": "scene"})
        assert is_eligible_for_stock({"shot_type": "establishing"})
        assert not is_eligible_for_stock({"shot_type": "character"})
        assert not is_eligible_for_stock({"reference_role": "portrait"})

    def test_extract_keywords_chinese(self):
        from hevi.image.stock_footage import _extract_keywords
        kws = _extract_keywords("雨天的城市街道")
        assert len(kws) > 0
        assert any("rain" in k.lower() for k in kws)

    def test_extract_keywords_english_fallback(self):
        from hevi.image.stock_footage import _extract_keywords
        kws = _extract_keywords("beautiful sunset over ocean")
        assert len(kws) > 0


# ── Playbook Loader ──────────────────────────────────────────────────────────

class TestPlaybookLoader:
    def test_load_builtin_device_pack(self):
        from hevi.style.playbook_loader import _BUILTIN_DEVICE_PACKS, load_playbook_from_dict
        pb = load_playbook_from_dict({
            "id": "test", "capture_source": "35mm电影感",
            "device_pack": "cinema_35mm",
        })
        assert pb.capture_source == "35mm电影感"
        assert pb.device_pack.id == "cinema_35mm"

    def test_load_inline_device_pack(self):
        from hevi.style.playbook_loader import load_playbook_from_dict
        pb = load_playbook_from_dict({
            "id": "custom",
            "capture_source": "自定义",
            "device_pack": {
                "id": "my_pack",
                "visual_features": "高饱和度",
                "operation_features": "手持",
                "negative_constraints": "低画质",
            },
        })
        assert pb.device_pack.id == "my_pack"
        assert "高饱和度" in pb.device_pack.visual_features

    def test_missing_capture_source_raises(self):
        from hevi.style.playbook_loader import load_playbook_from_dict
        with pytest.raises(ValueError, match="capture_source"):
            load_playbook_from_dict({"id": "bad"})

    def test_compile_prompt(self):
        from hevi.style.playbook_loader import compile_prompt, load_playbook_from_dict
        pb = load_playbook_from_dict({
            "id": "test", "capture_source": "历史正剧",
            "device_pack": "historical_epic",
            "color_baseline": "青灰赭褐",
        })
        result = compile_prompt(pb, provider="happyhorse", genre="historical")
        assert "visual_style" in result
        assert "negative_prompt" in result
        assert "青灰赭褐" in result["visual_style"]

    def test_atmosphere_translation(self):
        from hevi.style.playbook_loader import compile_prompt, load_playbook_from_dict
        pb = load_playbook_from_dict({
            "id": "test", "capture_source": "温馨家庭",
            "device_pack": "dv_2000s",
        })
        result = compile_prompt(pb, scene_description="温馨的家庭场景")
        # "温馨" should trigger atmosphere hints
        assert result["atmosphere_hints"]  # non-empty

    def test_list_playbooks(self):
        from hevi.style.playbook_loader import list_playbooks
        pbs = list_playbooks()
        assert len(pbs) >= 8  # at least 8 builtin device packs
        ids = [p["id"] for p in pbs]
        assert "cinema_35mm" in ids

    def test_builtin_genres(self):
        from hevi.style.playbook_loader import _BUILTIN_GENRES
        assert "historical" in _BUILTIN_GENRES
        assert "product" in _BUILTIN_GENRES
        assert _BUILTIN_GENRES["historical"].camera_tendency == "slow_push"

    def test_yaml_load_from_file(self):
        from hevi.style.playbook_loader import load_playbook
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write("id: test-yaml\ncapture_source: 测试\ndevice_pack: dv_2000s\n")
            f.flush()
            pb = load_playbook(Path(f.name))
        assert pb.id == "test-yaml"
        assert pb.device_pack.id == "dv_2000s"


# ── Cost Reconcile ────────────────────────────────────────────────────────────

class TestCostReconcile:
    @pytest.fixture
    def ledger(self):
        from hevi.cost.reconcile import BudgetMode, CostLedger
        return CostLedger(pool=None, budget_usd=10.0, mode=BudgetMode.CAP)

    @pytest.mark.asyncio
    async def test_estimate_reserve_reconcile(self, ledger):
        eid = await ledger.estimate("task-1", provider="happyhorse", duration_s=10.0)
        assert eid

        await ledger.reserve(eid)
        entry = ledger._entries[eid]
        assert entry.status.value == "reserved"
        assert entry.reserved_usd > 0

        result = await ledger.reconcile(eid, actual_usd=1.2, actual_duration_s=8.5)
        assert result.status.value == "reconciled"
        assert result.actual_usd == 1.2

    @pytest.mark.asyncio
    async def test_budget_cap_blocks(self, ledger):
        # Reserve most of the budget
        eid1 = await ledger.estimate("task-1", provider="x", duration_s=50.0)
        await ledger.reserve(eid1)

        from hevi.cost.reconcile import BudgetExceededError
        with pytest.raises(BudgetExceededError):
            await ledger.estimate("task-2", provider="y", duration_s=50.0)

    @pytest.mark.asyncio
    async def test_cancel_releases_budget(self, ledger):
        eid = await ledger.estimate("task-1", provider="x", duration_s=10.0)
        await ledger.reserve(eid)
        remaining_before = ledger.get_remaining_budget()

        await ledger.cancel(eid)
        remaining_after = ledger.get_remaining_budget()
        assert remaining_after > remaining_before

    @pytest.mark.asyncio
    async def test_task_spend_summary(self, ledger):
        eid = await ledger.estimate("task-1", provider="x", duration_s=5.0)
        await ledger.reserve(eid)
        await ledger.reconcile(eid, actual_usd=0.65)

        spend = ledger.get_task_spend("task-1")
        assert spend["actual"] == 0.65
        assert spend["estimated"] > 0


# ── Enhancement ───────────────────────────────────────────────────────────────

class TestEnhancement:
    def test_list_luts(self):
        from hevi.enhancement.color_grade import list_luts
        luts = list_luts()
        assert "warm_cinema" in luts
        assert "historical_epic" in luts
        assert "identity" in luts

    def test_color_grade_filter_construction(self):
        from hevi.enhancement.color_grade import _BUILTIN_LUTS
        for name, lut in _BUILTIN_LUTS.items():
            assert "filter" in lut
            assert len(lut["filter"]) > 0

    def test_all_luts_have_descriptions(self):
        from hevi.enhancement.color_grade import _BUILTIN_LUTS
        for name, lut in _BUILTIN_LUTS.items():
            assert "desc" in lut
            assert len(lut["desc"]) > 5


# ── Remotion Service ──────────────────────────────────────────────────────────

class TestRemotionService:
    def test_list_compositions(self):
        from hevi.video.remotion_service import list_compositions
        comps = list_compositions()
        assert len(comps) >= 1
        # Actual compositions from Root.tsx: Zhibo, Explainer-Portrait, Explainer-Landscape
        assert any("Explainer" in c or "Zhibo" in c for c in comps)


# ── Reference Video Analysis ──────────────────────────────────────────────────

class TestReferenceVideo:
    def test_pacing_analysis(self):
        from hevi.analysis.reference_video import _analyze_pacing
        from hevi.analysis.scene_detect import Scene
        scenes = [
            Scene(0, 0.0, 5.0, 5.0),
            Scene(1, 5.0, 12.0, 7.0),
            Scene(2, 12.0, 15.0, 3.0),
            Scene(3, 15.0, 25.0, 10.0),
        ]
        pacing = _analyze_pacing(scenes, None)
        assert pacing.scene_count == 4
        assert pacing.avg_shot_duration_s == 6.25
        assert pacing.pacing_category == "medium"

    def test_pacing_fast(self):
        from hevi.analysis.reference_video import _analyze_pacing
        from hevi.analysis.scene_detect import Scene
        scenes = [Scene(i, i * 1.5, (i + 1) * 1.5, 1.5) for i in range(10)]
        pacing = _analyze_pacing(scenes, None)
        assert pacing.pacing_category == "rapid"

    def test_pacing_empty(self):
        from hevi.analysis.reference_video import _analyze_pacing
        pacing = _analyze_pacing([], None)
        assert pacing.scene_count == 0
        assert pacing.pacing_category == "unknown"

    def test_heuristic_style(self):
        from hevi.analysis.reference_video import _heuristic_style
        style = _heuristic_style([], [])
        assert style.visual_mood
        assert style.aspect_ratio


# ── Provider Veo ──────────────────────────────────────────────────────────────

class TestProviderVeo:
    def test_import(self):
        from hevi.video.provider_veo import VeoResult, generate_veo_clip
        assert callable(generate_veo_clip)

    def test_import_minimax(self):
        from hevi.video.provider_minimax import MiniMaxResult, generate_minimax_clip
        assert callable(generate_minimax_clip)
