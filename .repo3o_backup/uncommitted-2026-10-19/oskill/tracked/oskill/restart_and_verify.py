import time
from typing import Any, cast

from obase.docker import docker_container_inspect, docker_container_restart
from oprim import http_health_probe
from pydantic import BaseModel


class RestartAndVerifyOutcome(BaseModel):
    restarted: bool
    verified_healthy: bool
    health_check_attempts: int
    health_check_results: list[dict[str, Any]]
    rolled_back: bool
    elapsed_ms: int


def restart_and_verify(
    *,
    container_id: str,
    health_check_url: str
    | None = None,  # 若 None, 不做 HTTP health check, 仅检查容器 state=running
    timeout_sec: int = 60,
    health_check_interval_sec: int = 5,
    rollback_on_failure: bool = True,
    docker_host: str = "unix:///var/run/docker.sock",
) -> RestartAndVerifyOutcome:
    """重启容器 + 等健康 + 失败回滚 (复合操作, 不是 oprim)."""
    start_time = time.time()

    # 1. Record state before
    try:
        docker_container_inspect(container_id=container_id, docker_host=docker_host)
    except Exception as e:
        return RestartAndVerifyOutcome(
            restarted=False,
            verified_healthy=False,
            health_check_attempts=0,
            health_check_results=[{"error": f"Inspect before failed: {e}"}],
            rolled_back=False,
            elapsed_ms=int((time.time() - start_time) * 1000),
        )

    # 2. Restart
    try:
        docker_container_restart(container_id=container_id, docker_host=docker_host)
        restarted = True
    except Exception as e:
        return RestartAndVerifyOutcome(
            restarted=False,
            verified_healthy=False,
            health_check_attempts=0,
            health_check_results=[{"error": f"Restart failed: {e}"}],
            rolled_back=False,
            elapsed_ms=int((time.time() - start_time) * 1000),
        )

    # 3. Verify Health
    attempts = 0
    results: list[dict[str, Any]] = []
    healthy = False

    if health_check_interval_sec <= 0:
        health_check_interval_sec = 1

    max_attempts = timeout_sec // health_check_interval_sec

    while attempts < max_attempts:
        attempts += 1
        time.sleep(health_check_interval_sec)

        # Check container state
        try:
            inspect_now = docker_container_inspect(
                container_id=container_id, docker_host=docker_host
            )
            if inspect_now.state != "running":
                results.append(
                    {"step": attempts, "healthy": False, "error": "Container not running"}
                )
                continue
        except Exception as e:
            results.append({"step": attempts, "healthy": False, "error": str(e)})
            continue

        # Check HTTP health if URL provided
        if health_check_url:
            try:
                probe = http_health_probe(
                    url=health_check_url, timeout_sec=health_check_interval_sec
                )
                results.append(
                    {"step": attempts, "healthy": cast(bool, probe["healthy"]), "probe": probe}
                )
                if cast(bool, probe["healthy"]):
                    healthy = True
                    break
            except Exception as e:
                results.append({"step": attempts, "healthy": False, "error": str(e)})
        else:
            # If no URL, just running state is enough
            healthy = True
            results.append({"step": attempts, "healthy": True, "info": "Container is running"})
            break

    # 4. Rollback (Stop if failure)
    rolled_back = False
    if not healthy and rollback_on_failure:
        try:
            from obase.docker import docker_container_stop

            docker_container_stop(container_id=container_id, docker_host=docker_host)
            rolled_back = True
        except Exception:
            pass

    return RestartAndVerifyOutcome(
        restarted=restarted,
        verified_healthy=healthy,
        health_check_attempts=attempts,
        health_check_results=results,
        rolled_back=rolled_back,
        elapsed_ms=int((time.time() - start_time) * 1000),
    )
