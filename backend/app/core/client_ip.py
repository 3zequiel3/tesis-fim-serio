"""
Real client IP behind a trusted reverse proxy (D92/RN-186).

uvicorn is NOT started with ``--forwarded-allow-ips`` (that would rewrite
``request.client`` for the whole app: logs, SSE ticket, audit). Instead this
single helper resolves the client IP and is used by the login and its
``audit_log`` entry only.

Rule: if the TCP peer is inside ``trusted_proxy_cidrs``, the client is the
right-most ``X-Forwarded-For`` entry that is not itself a trusted proxy
(entries that do not parse as an IP are discarded). Otherwise the header is
ignored and the peer is the client.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address
from typing import Protocol

from app.core.config import settings

_Network = IPv4Network | IPv6Network
_Address = IPv4Address | IPv6Address


class _RequestLike(Protocol):
    @property
    def client(self): ...  # noqa: E704

    @property
    def headers(self): ...  # noqa: E704


def _parse(value: str) -> _Address | None:
    try:
        addr = ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_trusted(addr: _Address, trusted: list[_Network]) -> bool:
    return any(addr.version == net.version and addr in net for net in trusted)


def client_ip(request: _RequestLike, trusted: list[_Network] | None = None) -> str:
    """Return the client IP as a string (``"unknown"`` if there is no peer)."""
    nets = settings.trusted_proxy_cidrs if trusted is None else trusted
    peer = request.client.host if request.client else None
    if peer is None:
        return "unknown"
    peer_addr = _parse(peer)
    if peer_addr is None or not _is_trusted(peer_addr, nets):
        return peer

    header = request.headers.get("x-forwarded-for")
    if not header:
        return peer
    for entry in reversed(header.split(",")):
        addr = _parse(entry)
        if addr is None or _is_trusted(addr, nets):
            continue
        return str(addr)
    return peer
