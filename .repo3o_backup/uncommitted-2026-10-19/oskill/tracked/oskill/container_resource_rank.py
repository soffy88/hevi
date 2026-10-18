"""Container resource ranking oskill."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from obase.docker import docker_container_list, docker_container_stats
from pydantic import BaseModel


class ContainerResourceEntry(BaseModel):
    container_id: str
    name: str
    image: str
    cpu_percent: float
    memory_percent: float
    memory_usage_bytes: int
    pids: int


class ContainerResourceRankResult(BaseModel):
    ranked: list[ContainerResourceEntry]
    sort_by: Literal["cpu", "mem"]
    docker_host: str


def container_resource_rank(
    *,
    docker_host: str = "unix:///var/run/docker.sock",
    sort_by: Literal["cpu", "mem"] = "cpu",
    top_n: int = 20,
    max_workers: int = 10,
) -> ContainerResourceRankResult:
    """批量获取运行中容器资源使用并排名.

    Args:
        docker_host: docker daemon 地址
        sort_by: 排序依据
        top_n: 返回前 N 个
        max_workers: 并发拉取 stats 的线程数

    Returns:
        ContainerResourceRankResult
    """
    containers = docker_container_list(all=False, docker_host=docker_host)

    def _fetch_stats(c) -> ContainerResourceEntry | None:
        try:
            s = docker_container_stats(container_id=c.container_id, docker_host=docker_host)
            return ContainerResourceEntry(
                container_id=c.container_id,
                name=c.name,
                image=c.image,
                cpu_percent=s.cpu_percent,
                memory_percent=s.memory_percent,
                memory_usage_bytes=s.memory_usage_bytes,
                pids=s.pids,
            )
        except Exception:
            return None

    entries: list[ContainerResourceEntry] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(containers) or 1)) as ex:
        for result in ex.map(_fetch_stats, containers):
            if result is not None:
                entries.append(result)

    key = (lambda e: e.cpu_percent) if sort_by == "cpu" else (lambda e: e.memory_percent)
    entries.sort(key=key, reverse=True)

    return ContainerResourceRankResult(
        ranked=entries[:top_n],
        sort_by=sort_by,
        docker_host=docker_host,
    )
