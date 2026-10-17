from pathlib import Path

import pytest

from hevi.assembly.remotion_render_workflow import RemotionConfig
from hevi.production_graph import ExecutionProfile, ResourceUnavailableError, assert_concurrency


@pytest.mark.parametrize(
    ("cpu_limit", "configured", "expected"),
    [(1, 4, 1), (2, 4, 2), (8, 4, 4), (8, 1, 1)],
)
def test_remotion_effective_concurrency_never_exceeds_cpu_limit(
    cpu_limit: int, configured: int, expected: int
) -> None:
    from hevi.explainer.render import effective_remotion_concurrency

    profile = ExecutionProfile(cpu_quota=cpu_limit, render_concurrency=configured)
    assert effective_remotion_concurrency(configured, execution_profile=profile) == expected


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


def test_malformed_cgroup_metadata_uses_scheduler_safe_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hevi.production_graph import resources

    (tmp_path / "cpu.max").write_text("not-a-quota", encoding="utf-8")
    (tmp_path / "cpuset.cpus.effective").write_text("broken-range", encoding="utf-8")
    monkeypatch.setattr(resources.os, "sched_getaffinity", lambda _pid: {0, 1})
    profile = ExecutionProfile.from_system(cgroup_root=tmp_path, render_concurrency=4)
    assert profile.cpu_capacity == 2
    assert profile.effective_concurrency(4, "render") == 2


def test_explainer_remotion_path_passes_capped_concurrency_to_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    import hevi.explainer.render as render

    remotion_dir = tmp_path / "remotion"
    remotion_dir.mkdir()
    remotion_bin = remotion_dir / "node_modules" / ".bin" / "remotion"
    remotion_bin.parent.mkdir(parents=True)
    remotion_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)
    monkeypatch.setattr(render, "_REMOTION_BIN", remotion_bin)
    captured: dict[str, object] = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", None

    async def fake_exec(*args: object, **kwargs: object) -> Process:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(render.asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(
        render._run_remotion_render(
            "Explainer-Portrait",
            tmp_path / "out.mp4",
            configured_concurrency=4,
            execution_profile=ExecutionProfile(cpu_quota=1, render_concurrency=4),
        )
    )
    assert "--concurrency=1" in captured["args"]


def test_remotion_config_accepts_explicit_profile() -> None:
    profile = ExecutionProfile(cpu_quota=1, render_concurrency=1)
    config = RemotionConfig(
        project_dir=Path("/tmp"),
        composition_id="x",
        output_path=Path("/tmp/x.mp4"),
        execution_profile=profile,
    )
    assert config.execution_profile is profile
