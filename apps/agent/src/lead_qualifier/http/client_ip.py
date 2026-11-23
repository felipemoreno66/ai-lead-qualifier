"""Client IP resolution that only honours X-Forwarded-For from trusted proxies."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(cidrs: Iterable[str]) -> list[Network]:
    return [ipaddress.ip_network(c, strict=False) for c in cidrs]


def _in(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, networks: list[Network]) -> bool:
    return any(ip in n for n in networks)


def resolve_client_ip(peer: str | None, forwarded_for: str | None, trusted: list[Network]) -> str:
    """Return the client IP.

    ``X-Forwarded-For`` is only read when the direct peer is a trusted proxy; the chain is
    then walked from the right, skipping trusted proxies, so a client cannot spoof its IP by
    sending its own header.
    """
    if not peer:
        return "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return "unknown"
    if not trusted or not forwarded_for or not _in(peer_ip, trusted):
        return str(peer_ip)
    for raw in reversed([p.strip() for p in forwarded_for.split(",") if p.strip()]):
        try:
            hop = ipaddress.ip_address(raw)
        except ValueError:
            return str(peer_ip)
        if not _in(hop, trusted):
            return str(hop)
    return str(peer_ip)
