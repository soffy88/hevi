import sys
from unittest.mock import MagicMock, patch

sys.modules["docker"] = MagicMock()
sys.modules["docker.errors"] = MagicMock()

from obase.docker import ContainerInfo  # noqa: E402

from oskill.container_health_aggregate import container_health_aggregate  # noqa: E402


def _ci(state: str = "running", health=None) -> ContainerInfo:
    return ContainerInfo(
        container_id="test",
        name="test",
        image="img",
        state=state,
        status=state,
        started_at=None,
        finished_at=None,
        exit_code=None,
        health=health,
        restart_count=0,
        labels={},
        ports=[],
        mounts=[],
    )


# === container_health_aggregate tests ===


def test_container_health_aggregate_all_healthy():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        with patch("oskill.container_health_aggregate.http_health_probe") as mock_probe:
            mock_inspect.return_value = _ci(health="healthy")
            mock_probe.return_value = {"healthy": True, "elapsed_ms": 10, "status_code": 200}

            result = container_health_aggregate(
                container_id="test", check_endpoints=["http://localhost:8080"]
            )
            assert result.overall_status == "healthy"
            assert len(result.passing_checks) == 1
            assert result.aggregate_health_score == 1.0


def test_container_health_aggregate_degraded():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        with patch("oskill.container_health_aggregate.http_health_probe") as mock_probe:
            mock_inspect.return_value = _ci()
            mock_probe.side_effect = [
                {"healthy": True, "elapsed_ms": 10, "status_code": 200},
                {"healthy": False, "elapsed_ms": 0, "status_code": 500, "error": "Internal Error"},
            ]

            result = container_health_aggregate(
                container_id="test", check_endpoints=["http://ok", "http://fail"]
            )
            assert result.overall_status == "degraded"
            assert len(result.passing_checks) == 1
            assert len(result.failing_checks) == 1
            assert result.aggregate_health_score == 0.5


def test_container_health_aggregate_down():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        mock_inspect.return_value = _ci(state="exited")

        result = container_health_aggregate(
            container_id="test", check_endpoints=["http://localhost"]
        )
        assert result.overall_status == "down"
        assert result.aggregate_health_score == 0.0


def test_container_health_aggregate_unhealthy_internal():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        with patch("oskill.container_health_aggregate.http_health_probe") as mock_probe:
            mock_inspect.return_value = _ci(health="unhealthy")
            mock_probe.return_value = {"healthy": True, "elapsed_ms": 10, "status_code": 200}

            result = container_health_aggregate(
                container_id="test", check_endpoints=["http://localhost:8080"]
            )
            assert result.overall_status == "degraded"
            assert any(f.endpoint == "docker-internal-healthcheck" for f in result.failing_checks)


def test_container_health_aggregate_probe_exception():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        with patch("oskill.container_health_aggregate.http_health_probe") as mock_probe:
            mock_inspect.return_value = _ci()
            mock_probe.side_effect = Exception("Probe failed")

            result = container_health_aggregate(
                container_id="test", check_endpoints=["http://error"]
            )
            assert result.overall_status == "degraded"
            assert result.failing_checks[0].error == "Probe failed"


def test_container_health_aggregate_no_endpoints():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        mock_inspect.return_value = _ci()

        result = container_health_aggregate(container_id="test", check_endpoints=[])
        assert result.overall_status == "healthy"
        assert result.aggregate_health_score == 1.0


def test_container_health_aggregate_inspect_exception():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        mock_inspect.side_effect = Exception("Docker daemon down")

        result = container_health_aggregate(
            container_id="test", check_endpoints=["http://localhost"]
        )
        assert result.overall_status == "down"
        assert result.aggregate_health_score == 0.0


def test_container_health_aggregate_custom_host():
    with patch("oskill.container_health_aggregate.docker_container_inspect") as mock_inspect:
        mock_inspect.return_value = _ci()

        result = container_health_aggregate(
            container_id="test", check_endpoints=[], docker_host="tcp://1.2.3.4:2375"
        )
        mock_inspect.assert_called_once_with(container_id="test", docker_host="tcp://1.2.3.4:2375")
        assert result.overall_status == "healthy"
