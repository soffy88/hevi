from pathlib import Path

import pytest

from hevi.assembly.remotion_render_workflow import RemotionConfig
from hevi.production_graph import ExecutionProfile, ResourceUnavailableError, assert_concurrency


def test_profile_caps_runtime_concurrency_to_cpu_quota() -> None:
    profile = ExecutionProfile(
        cpu_quota=2.5,
        render_concurrency=8,
        provider_concurrency=4,
        io_concurrency=3,
    )
    assert profile.cpu_concurrency_limit == 2
    assert assert_concurrency(profile, 8) == 2
    assert profile.effective_concurrency(4, "provider") == 2


def test_fractional_cpu_is_serialized_and_zero_cpu_is_blocked() -> None:
    assert ExecutionProfile(cpu_quota=0.5).effective_concurrency(4) == 1
    with pytest.raises(ResourceUnavailableError):
        ExecutionProfile(cpu_quota=0).effective_concurrency(1)


def test_gpu_absence_is_not_accepted_as_gpu_capacity() -> None:
    profile = ExecutionProfile(cpu_quota=1, gpu_available=False)
    with pytest.raises(ResourceUnavailableError):
        profile.require(gpu_count=1)


def test_system_profile_reads_cgroup_limits_without_gpu_claim(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("150000 100000\n", encoding="utf-8")
    (tmp_path / "memory.max").write_text(str(512 * 1024 * 1024), encoding="utf-8")
    profile = ExecutionProfile.from_system(cgroup_root=tmp_path, render_concurrency=4)
    assert profile.cpu_quota == 1.5
    assert profile.memory_limit_mb == 512
    assert not profile.gpu_available


def test_remotion_config_accepts_explicit_profile() -> None:
    profile = ExecutionProfile(cpu_quota=1, render_concurrency=1)
    config = RemotionConfig(
        project_dir=Path("/tmp"),
        composition_id="x",
        output_path=Path("/tmp/x.mp4"),
        execution_profile=profile,
    )
    assert config.execution_profile is profile
