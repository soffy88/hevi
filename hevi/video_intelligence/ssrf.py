"""Fail-closed URL validation for external case media ingestion."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlparse

MAX_REDIRECTS = 3
MAX_CONTENT_LENGTH = 500 * 1024 * 1024
_METADATA = {"169.254.169.254", "100.100.100.200", "metadata.google.internal"}


def _blocked_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        address.is_loopback or address.is_private or address.is_link_local
        or address.is_unspecified or address.is_reserved or address.is_multicast
        or value in _METADATA
    )


async def resolve_public_addresses(host: str, port: int | None = None) -> list[str]:
    if host.lower() in {"localhost", *_METADATA}:
        raise ValueError("SSRF_PRIVATE_OR_METADATA_HOST")
    try:
        direct = ipaddress.ip_address(host)
    except ValueError:
        direct = None
    if direct is not None:
        if _blocked_ip(str(direct)):
            raise ValueError("SSRF_PRIVATE_OR_LOCAL_ADDRESS")
        return [str(direct)]
    infos = await asyncio.to_thread(
        socket.getaddrinfo, host, port or 443, type=socket.SOCK_STREAM
    )
    addresses = sorted({str(item[4][0]) for item in infos})
    if not addresses or any(_blocked_ip(item) for item in addresses):
        raise ValueError("SSRF_DNS_RESOLVES_TO_PRIVATE_OR_LOCAL_ADDRESS")
    return addresses


async def validate_external_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("SSRF_ONLY_HTTP_HTTPS_ALLOWED")
    await resolve_public_addresses(parsed.hostname, parsed.port)
    return url


async def fetch_external_media(
    url: str,
    *,
    request: Callable[[str], Awaitable[tuple[int, str | None, bytes, str | None]]],
    max_redirects: int = MAX_REDIRECTS,
) -> tuple[bytes, str | None, str]:
    """Fetch through an injected HTTP transport, revalidating every redirect.

    The transport is deliberately injected so the policy can be tested without
    network access and so the ingest service cannot accidentally bypass it.
    """
    current = await validate_external_url(url)
    for _ in range(max_redirects + 1):
        status, location, body, content_type = await request(current)
        if len(body) > MAX_CONTENT_LENGTH:
            raise ValueError("SSRF_CONTENT_LENGTH_EXCEEDED")
        if status in {301, 302, 303, 307, 308}:
            if not location:
                raise ValueError("SSRF_REDIRECT_LOCATION_MISSING")
            current = await validate_external_url(urljoin(current, location))
            continue
        if status < 200 or status >= 300:
            raise ValueError(f"EXTERNAL_MEDIA_HTTP_{status}")
        return body, content_type, current
    raise ValueError("SSRF_REDIRECT_LIMIT_EXCEEDED")


__all__ = ["MAX_CONTENT_LENGTH", "MAX_REDIRECTS", "fetch_external_media", "resolve_public_addresses", "validate_external_url"]
