import sys
from unittest.mock import MagicMock, patch

from obase.docker import ContainerInfo

from oskill.restart_and_verify import restart_and_verify

sys.modules["docker"] = MagicMock()
sys.modules["docker.errors"] = MagicMock()


def _ci(state: str = "running") -> ContainerInfo:
    return ContainerInfo(
        container_id="c1",
        name="c1",
        image="img",
        state=state,
        status=state,
        started_at=None,
        finished_at=None,
        exit_code=None,
        health=None,
        restart_count=0,
        labels={},
        ports=[],
        mounts=[],
    )


def test_restart_and_verify_success_with_http():
    """Test successful restart and HTTP health check."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            with patch("oskill.restart_and_verify.http_health_probe") as mock_probe:
                mock_inspect.return_value = _ci()
                mock_probe.return_value = {"healthy": True, "elapsed_ms": 100, "status_code": 200}

                result = restart_and_verify(
                    container_id="c1",
                    health_check_url="http://localhost/health",
                    health_check_interval_sec=1,  # No sleep for tests
                )

                assert result.restarted
                assert result.verified_healthy
                assert result.health_check_attempts == 1


def test_restart_and_verify_inspect_before_failure():
    """Test when inspect before restart fails."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        mock_inspect.side_effect = Exception("Docker down")

        result = restart_and_verify(container_id="c1")
        assert not result.restarted
        assert not result.verified_healthy
        assert "Docker down" in result.health_check_results[0]["error"]


def test_restart_and_verify_restart_failure():
    """Test when restart command fails."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart") as mock_restart:
            mock_inspect.return_value = _ci()
            mock_restart.side_effect = Exception("Restart error")

            result = restart_and_verify(container_id="c1")
            assert not result.restarted
            assert not result.verified_healthy


def test_restart_and_verify_health_timeout():
    """Test reaching timeout while waiting for healthy state."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            with patch("oskill.restart_and_verify.http_health_probe") as mock_probe:
                # State is running, but probe fails
                mock_inspect.return_value = _ci()
                mock_probe.return_value = {"healthy": False}

                # Mock time.sleep to avoid waiting
                with patch("time.sleep"):
                    result = restart_and_verify(
                        container_id="c1",
                        health_check_url="http://fail",
                        timeout_sec=2,
                        health_check_interval_sec=1,
                        rollback_on_failure=False,
                    )

                    assert not result.verified_healthy
                    assert result.health_check_attempts == 2


def test_restart_and_verify_not_running():
    """Test when container stops running during health check."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            # First inspect (before) returns running
            # Second inspect (during loop) returns not running
            mock_inspect.side_effect = [_ci(), _ci(state="exited")]

            with patch("time.sleep"):
                result = restart_and_verify(
                    container_id="c1", timeout_sec=1, health_check_interval_sec=1
                )
                assert not result.verified_healthy
                assert result.health_check_results[0]["error"] == "Container not running"


def test_restart_and_verify_rollback():
    """Test rollback (stopping container) on failure."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            with patch("obase.docker.docker_container_stop") as mock_stop:
                # Loop will see it's not running
                mock_inspect.return_value = _ci(state="exited")

                with patch("time.sleep"):
                    result = restart_and_verify(
                        container_id="c1",
                        rollback_on_failure=True,
                        timeout_sec=1,
                        health_check_interval_sec=1,
                    )

                    assert result.rolled_back
                    mock_stop.assert_called_once()


def test_restart_and_verify_probe_exception():
    """Test when HTTP probe raises an exception."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            with patch("oskill.restart_and_verify.http_health_probe") as mock_probe:
                mock_inspect.return_value = _ci()
                mock_probe.side_effect = Exception("Probe crashed")

                with patch("time.sleep"):
                    result = restart_and_verify(
                        container_id="c1",
                        health_check_url="http://x",
                        timeout_sec=1,
                        health_check_interval_sec=1,
                    )
                    assert not result.verified_healthy
                    assert "Probe crashed" in result.health_check_results[0]["error"]


def test_restart_and_verify_no_url():
    """Test success without HTTP probe (just running state)."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            mock_inspect.return_value = _ci()

            with patch("time.sleep"):
                result = restart_and_verify(container_id="c1", health_check_url=None)
                assert result.verified_healthy
                assert "Container is running" in result.health_check_results[0]["info"]


def test_restart_and_verify_inspect_loop_exception():
    """Test exception inside health check loop."""
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            mock_inspect.side_effect = [
                _ci(),  # before
                Exception("Loop error"),  # during loop
            ]

            with patch("time.sleep"):
                result = restart_and_verify(
                    container_id="c1", timeout_sec=1, health_check_interval_sec=1
                )
                assert not result.verified_healthy
                assert "Loop error" in result.health_check_results[0]["error"]
