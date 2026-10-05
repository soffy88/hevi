"""S2 验收:media probe → 兼容性 → 归一化 → canonical 候选/证据。

真媒体文件(ffmpeg 现场生成),不 mock 探测链。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hevi.creative.autonomous.acquire import LocalAssetAcquirer, normalize_local_asset
from hevi.creative.autonomous.resolver import AssetResolver
from hevi.production.p7.asset_contract import AssetSemanticRole, AssetStatus, MediaType
from hevi.production.p7.asset_requirement import AssetRequirement
from hevi.production.p7.constraint_check import check_compatibility


def _video(path: Path, *, seconds: float = 4.0, w: int = 1080, h: int = 1920) -> Path:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size={w}x{h}:rate=25:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, text=True, timeout=180)
    assert path.exists() and path.stat().st_size > 0, proc.stderr[-300:]
    return path


def _req(**constraints: str) -> AssetRequirement:
    return AssetRequirement(media_type=MediaType.VIDEO, semantic_role=AssetSemanticRole.SCENE,
                            constraints=tuple(constraints.items()))


# ── constraint_check:类型换算 + 不可判定不等于通过 ──
def test_constraint_translation_handles_string_vs_typed():
    """constraint 值是字符串,probe 产出 float/tuple —— 直连 EQ 永不匹配。"""
    req = _req(duration="3", resolution="1080", aspect="9:16", license="CC0")
    report = check_compatibility(req, {"duration": 5.0, "resolution": (1080, 1920),
                                       "license": "CC0"})
    assert report.blocked_keys == () and report.undecidable_keys == ()
    assert report.compatible is True


def test_aspect_derived_from_resolution_when_not_reported():
    req = _req(aspect="9:16")
    assert check_compatibility(req, {"resolution": (1080, 1920)}).compatible is True
    assert check_compatibility(req, {"resolution": (1920, 1080)}).blocked_keys == ("aspect",)


def test_duration_is_a_floor_not_equality():
    req = _req(duration="3")
    assert check_compatibility(req, {"duration": 10.0}).compatible is True
    assert check_compatibility(req, {"duration": 1.0}).blocked_keys == ("duration",)


def test_resolution_is_min_height():
    req = _req(resolution="1080")
    assert check_compatibility(req, {"resolution": (3840, 2160)}).compatible is True
    assert check_compatibility(req, {"resolution": (640, 480)}).blocked_keys == ("resolution",)


def test_unobserved_constraint_is_undecidable_not_pass():
    report = check_compatibility(_req(license="CC0"), {})
    assert report.undecidable_keys == ("license",) and report.compatible is False


def test_query_is_not_a_judgeable_constraint():
    report = check_compatibility(_req(query="black hole"), {})
    assert report.outcomes == ()  # query 交给检索,不判


# ── 归一化:真媒体 ──
def test_normalize_real_media_produces_canonical_shapes(tmp_path):
    media = _video(tmp_path / "shot.mp4")
    req = _req(duration="2", resolution="1080", aspect="9:16")
    normalized = normalize_local_asset(req, media, license_name="CC0")
    assert normalized.usable is True
    assert normalized.evidence.status is AssetStatus.AVAILABLE
    assert normalized.evidence.license == "CC0"
    assert normalized.evidence.content_hash  # 真 checksum
    assert normalized.candidate.asset_ref == str(media)
    assert normalized.candidate.verified is True
    # S2 不评分:confidence/scored_by 必须留空交给 S3
    assert normalized.candidate.confidence == 0.0 and normalized.candidate.scored_by == ""


def test_normalize_rejects_incompatible_media(tmp_path):
    small = _video(tmp_path / "small.mp4", seconds=1.0, w=320, h=240)
    normalized = normalize_local_asset(_req(duration="5", resolution="1080", aspect="9:16"),
                                       small, license_name="CC0")
    assert normalized.usable is False
    assert set(normalized.compatibility.blocked_keys) == {"duration", "resolution", "aspect"}
    assert normalized.evidence.status is not AssetStatus.AVAILABLE
    assert normalized.candidate.verified is False
    assert normalized.candidate.reason


def test_normalize_without_license_cannot_be_available(tmp_path):
    """p7 硬规则:AVAILABLE 必须声明 license(授权可审计)。"""
    media = _video(tmp_path / "shot.mp4")
    normalized = normalize_local_asset(_req(duration="1"), media, license_name="")
    assert normalized.evidence.status is not AssetStatus.AVAILABLE
    assert normalized.usable is False


def test_normalize_broken_file_is_rejected_not_available(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    normalized = normalize_local_asset(_req(), broken, license_name="CC0")
    assert normalized.usable is False
    assert normalized.evidence.status is AssetStatus.REJECTED
    assert normalized.candidate.verified is False


# ── LocalAcquirer ──
def test_acquirer_requires_declared_license(tmp_path):
    with pytest.raises(ValueError, match="LOCAL_ACQUIRER_REQUIRES_LICENSE"):
        LocalAssetAcquirer((tmp_path,))


async def test_acquirer_finds_compatible_local_asset(tmp_path):
    _video(tmp_path / "good.mp4", seconds=5.0)
    acquirer = LocalAssetAcquirer((tmp_path,), license_name="CC0")
    ref, evidence = await acquirer.acquire(_req(duration="2", resolution="1080", aspect="9:16"),
                                           "local_assets", {})
    assert ref.endswith("good.mp4")
    assert evidence.status is AssetStatus.AVAILABLE


async def test_acquirer_skips_incompatible_and_reports_blocked(tmp_path):
    _video(tmp_path / "tiny.mp4", seconds=0.5, w=160, h=120)
    acquirer = LocalAssetAcquirer((tmp_path,), license_name="CC0")
    ref, evidence = await acquirer.acquire(_req(duration="10", resolution="1080"),
                                           "local_assets", {})
    assert ref == ""
    assert evidence.status is AssetStatus.BLOCKED
    assert "no compatible local asset" in evidence.validation


async def test_acquirer_respects_media_type(tmp_path):
    _video(tmp_path / "clip.mp4")
    acquirer = LocalAssetAcquirer((tmp_path,), license_name="CC0")
    image_req = AssetRequirement(media_type=MediaType.IMAGE,
                                 semantic_role=AssetSemanticRole.SCENE)
    assert acquirer.available(image_req) == ()   # 目录里只有 mp4


# ── 端到端:resolver 消费 Acquirer(既有 seam)──
async def test_resolver_executes_decision_with_local_acquirer(tmp_path):
    from hevi.provider_policy.policy import ProviderDecision

    _video(tmp_path / "asset.mp4", seconds=5.0)
    acquirer = LocalAssetAcquirer((tmp_path,), license_name="CC0")
    decision = ProviderDecision(selected_provider="local_assets", eligible=["local_assets"],
                               considered=["local_assets"])
    out = await AssetResolver(acquirer=acquirer).resolve(
        _req(duration="2", resolution="1080", aspect="9:16"), provider_decision=decision)
    assert out.usable and out.decision_state == "ACCEPTED"
    assert out.selected_source.endswith("asset.mp4")
    assert out.evidence_ids


async def test_resolver_blocked_when_local_pool_empty(tmp_path):
    from hevi.provider_policy.policy import ProviderDecision

    decision = ProviderDecision(selected_provider="local_assets", eligible=["local_assets"],
                               considered=["local_assets"])
    out = await AssetResolver(acquirer=LocalAssetAcquirer((tmp_path / "missing",),
                                                          license_name="CC0")
                               ).resolve(_req(duration="1"), provider_decision=decision)
    assert (out.blocked and "NO_ASSET_EVIDENCE" in out.reason) or out.blocked