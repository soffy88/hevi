"""Multi-node health sweep oskill."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from obase.docker import docker_container_list, docker_node_info
from pydantic import BaseModel


class NodeHealthReport(BaseModel):
    docker_host: str
    reachable: bool
    server_version: str | None
    cpus: int | None
    memory_bytes: int | None
    containers_running: int
    containers_total: int
    error: str | None


class MultiNodeSweepResult(BaseModel):
    nodes: list[NodeHealthReport]
    reachable_count: int
    unreachable_count: int


def multi_node_health_sweep(
    *,
    docker_hosts: list[str],
    timeout_sec: int = 5,
    max_workers: int = 8,
) -> MultiNodeSweepResult:
    """并发探测多个 Docker 节点健康状态.

    Args:
        docker_hosts: docker daemon 地址列表
        timeout_sec: 单节点连接超时
        max_workers: 并发数

    Returns:
        MultiNodeSweepResult
    """

    def _probe(host: str) -> NodeHealthReport:
        info = docker_node_info(docker_host=host, timeout_sec=timeout_sec)
        if not info.reachable:
            return NodeHealthReport(
                docker_host=host,
                reachable=False,
                server_version=None,
                cpus=None,
                memory_bytes=None,
                containers_running=0,
                containers_total=0,
                error=info.error,
            )
        try:
            all_containers = docker_container_list(all=True, docker_host=host)
            running = [c for c in all_containers if c.state == "running"]
        except Exception as exc:
            return NodeHealthReport(
                docker_host=host,
                reachable=True,
                server_version=info.server_version,
                cpus=info.cpus,
                memory_bytes=info.memory_bytes,
                containers_running=info.containers_running or 0,
                containers_total=0,
                error=f"container list failed: {exc}",
            )
        return NodeHealthReport(
            docker_host=host,
            reachable=True,
            server_version=info.server_version,
            cpus=info.cpus,
            memory_bytes=info.memory_bytes,
            containers_running=len(running),
            containers_total=len(all_containers),
            error=None,
        )

    reports: list[NodeHealthReport] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(docker_hosts))) as ex:
        futures = {ex.submit(_probe, h): h for h in docker_hosts}
        for fut in as_completed(futures):
            reports.append(fut.result())

    # sort by docker_host for determinism
    reports.sort(key=lambda r: r.docker_host)
    reachable = sum(1 for r in reports if r.reachable)
    return MultiNodeSweepResult(
        nodes=reports,
        reachable_count=reachable,
        unreachable_count=len(reports) - reachable,
    )
