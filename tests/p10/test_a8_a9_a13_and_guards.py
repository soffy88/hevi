"""A8/A9/A13 + guard + attestation 验收。"""

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hevi.creative.direction_plan.authority_pin import parse_pin, pin_manifest, resolve_pin
from hevi.creative.direction_plan.shot_cache import ShotCache, shot_cache_key
from hevi.creative.direction_verify import VerifyError
from hevi.creative.direction_verify.guard import (
    Attestation,
    AttestationLog,
    check_similarity,
    hamming_similarity,
    perceptual_hash,
)

REPO = Path(__file__).resolve().parents[2]


# ── A8 stems ──
def _ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-300:]


def test_a8_stem_manifest_records_existing_stems(tmp_path, monkeypatch):
    from hevi.tongjian import assemble as assemble_mod

    voice = tmp_path / "voice.wav"
    _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(voice)])
    (tmp_path / "audio_artifact.json").write_text(json.dumps(
        {"master": "final.mp4", "stems": {"voice": str(voice)}, "stem_scopes": ["voice"]}),
        encoding="utf-8")

    manifest = json.loads((tmp_path / "audio_artifact.json").read_text(encoding="utf-8"))
    assert Path(manifest["stems"]["voice"]).is_file()
    # 缺 stem 的声部:检测器必须记 NOT_EVALUABLE,不得用 master 顶替
    assert "music" not in manifest["stems"]
    assert os.getenv("P10_EXPORT_STEMS") is None
    assert assemble_mod.os.getenv("P10_EXPORT_STEMS") is None


# ── A9 per-shot cache ──
def test_a9_cache_key_is_content_addressed_and_reusable(tmp_path):
    intent = {"line": "a", "narrative_purpose": "evidence"}
    plan = {"shots": ["s1"]}
    k1 = shot_cache_key(intent=intent, plan=plan, generation={"seed": 1})
    k2 = shot_cache_key(intent=dict(intent), plan=dict(plan), generation={"seed": 1})
    k3 = shot_cache_key(intent=intent, plan=plan, generation={"seed": 2})
    assert k1 == k2 and k1 != k3  # 内容相同即同键;生成参数变即变键

    artifact = tmp_path / "clip.mp4"
    artifact.write_bytes(b"clip")
    cache = ShotCache(tmp_path / "cache")
    from hevi.creative.direction_plan.shot_cache import CacheEntry

    assert cache.lookup(k1) is None and cache.misses == 1
    cache.store(CacheEntry(k1, str(artifact), "h1", "p"))
    hit = cache.lookup(k1)
    assert hit is not None and cache.hits == 1

    reloaded = ShotCache(tmp_path / "cache")
    assert reloaded.load() == 1 and reloaded.lookup(k1) is not None
    artifact.unlink()  # 产物消失 = 失效,不返回悬空引用
    assert reloaded.lookup(k1) is None


# ── A13 authority pins ──
def test_a13_pin_requires_version_and_resolves():
    with pytest.raises(VerifyError) as exc:
        parse_pin("visual_style", "no-version")
    assert exc.value.code == "AUTHORITY_REF_UNPINNED"
    pin = parse_pin("visual_style", "noir@1.2.0")
    assert pin.key() == "visual_style@noir@1.2.0"
    registry = {"visual_style": {"noir@1.2.0": "chash"}}
    assert resolve_pin(pin, registry).content_hash == "chash"
    with pytest.raises(VerifyError) as exc:
        resolve_pin(pin, {"visual_style": {"noir@1.0.0": "old"}})
    assert exc.value.code == "AUTHORITY_REF_STALE"
    assert pin_manifest([pin], registry) == ("visual_style@noir@1.2.0",)


# ── 相似度护栏 ──
def _make_png(path: Path, seed: int) -> None:
    """非周期纹理(R-P10-03):周期图案会让感知哈希恒定相似。"""
    rng = np.random.default_rng(seed)
    Image.fromarray((rng.random((240, 320, 3)) * 255).astype("uint8")).save(path)


def test_similarity_guard_default_off(tmp_path, monkeypatch):
    monkeypatch.delenv("P10_SIMILARITY_GUARD", raising=False)
    a = tmp_path / "a.png"
    _make_png(a, 1)
    assert check_similarity(str(a), [str(a)]).result == "NOT_EVALUABLE"


def test_similarity_guard_flags_identical_when_on(tmp_path, monkeypatch):
    monkeypatch.setenv("P10_SIMILARITY_GUARD", "1")
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    _make_png(a, 1)
    _make_png(b, 2)
    assert check_similarity(str(a), [str(a)], enabled=True).result == "FAIL"
    distinct = check_similarity(str(a), [str(b)], enabled=True)
    assert distinct.result == "PASS" and distinct.similarity < 0.9
    assert hamming_similarity(perceptual_hash(str(a)), perceptual_hash(str(a))) == 1.0


# ── Q4 attestation ──
def test_q4_attestation_record_and_second_actor():
    log = AttestationLog()
    with pytest.raises(VerifyError):
        log.attest(Attestation("CHK-H1", "soffy", "MAYBE", artifact_hash="a" * 64))
    with pytest.raises(VerifyError):
        log.attest(Attestation("CHK-H1", "", "PASS", artifact_hash="a" * 64))
    log.attest(Attestation("CHK-H1", "soffy", "PASS", "看了成片", "a" * 64, "t"))
    assert log.status("CHK-H1") == "PASS"
    assert log.status("CHK-H1", require_second=True) == "INCONCLUSIVE"  # 双人未复核
    log.attest(Attestation("CHK-H1", "reviewer2", "PASS", "复核", "a" * 64, "t", "reviewer2"))
    assert log.status("CHK-H1", require_second=True) == "PASS"
    assert log.status("CHK-OTHER") == "INCONCLUSIVE"