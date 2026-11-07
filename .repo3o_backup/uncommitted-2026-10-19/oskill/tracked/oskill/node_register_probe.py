"""Node register probe oskill."""

from __future__ import annotations

import json
from typing import Literal

from obase.docker import docker_node_info
from oprim import ssh_exec, tcp_port_check
from pydantic import BaseModel


class NodeRegisterProbeResult(BaseModel):
    host: str
    ssh_reachable: bool
    docker_mode: Literal["tcp", "ssh", "unreachable"]
    server_version: str | None = None
    os: str | None = None
    arch: str | None = None
    cpus: int | None = None
    memory_bytes: int | None = None
    docker_host_url: str | None = None
    error: str | None = None


def node_register_probe(
    *,
    host: str,
    username: str,
    key_path: str | None = None,
    password: str | None = None,
    ssh_port: int = 22,
    docker_tcp_port: int = 2375,
    timeout_sec: int = 10,
) -> NodeRegisterProbeResult:
    """Probes a node for registration info."""
    # 1. SSH Reachability check
    ssh_check = tcp_port_check(host=host, port=ssh_port, timeout_sec=timeout_sec)
    if not ssh_check.reachable:
        return NodeRegisterProbeResult(
            host=host,
            ssh_reachable=False,
            docker_mode="unreachable",
            error="SSH port unreachable",
        )

    last_error = None

    # 2. Try TCP mode
    tcp_url = f"tcp://{host}:{docker_tcp_port}"
    try:
        info = docker_node_info(docker_host=tcp_url, timeout_sec=timeout_sec)
        if info.reachable:
            return NodeRegisterProbeResult(
                host=host,
                ssh_reachable=True,
                docker_mode="tcp",
                server_version=info.server_version,
                os=info.os,
                arch=info.arch,
                cpus=info.cpus,
                memory_bytes=info.memory_bytes,
                docker_host_url=tcp_url,
            )
        else:
            last_error = info.error
    except Exception as exc:
        last_error = str(exc)

    # 3. Try SSH mode
    try:
        # docker info --format '{{json .}}'
        ssh_res = ssh_exec(
            host=host,
            username=username,
            command="docker info --format '{{json .}}'",
            port=ssh_port,
            key_path=key_path,
            password=password,
            timeout_sec=timeout_sec,
        )
        if ssh_res.exit_code == 0:
            data = json.loads(ssh_res.stdout)
            return NodeRegisterProbeResult(
                host=host,
                ssh_reachable=True,
                docker_mode="ssh",
                server_version=data.get("ServerVersion"),
                os=data.get("OperatingSystem"),
                arch=data.get("Architecture"),
                cpus=data.get("NCPU"),
                memory_bytes=data.get("MemTotal"),
                docker_host_url=None,
            )
        else:
            last_error = f"docker info via SSH failed (exit {ssh_res.exit_code}): {ssh_res.stderr}"
    except Exception as exc:
        last_error = str(exc)

    return NodeRegisterProbeResult(
        host=host,
        ssh_reachable=True,
        docker_mode="unreachable",
        error=last_error or "Failed to detect docker via TCP or SSH",
    )
