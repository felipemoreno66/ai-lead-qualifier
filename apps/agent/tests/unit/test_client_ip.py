from __future__ import annotations

import pytest

from lead_qualifier.http.client_ip import parse_networks, resolve_client_ip
from lead_qualifier.security import hash_value

PROXIES = parse_networks(["10.0.0.0/8", "192.168.1.5/32"])


@pytest.mark.parametrize(
    ("peer", "xff", "expected"),
    [
        ("203.0.113.9", None, "203.0.113.9"),
        ("203.0.113.9", "1.2.3.4", "203.0.113.9"),  # untrusted peer: header is ignored
        ("10.0.0.2", None, "10.0.0.2"),
        ("10.0.0.2", "198.51.100.4", "198.51.100.4"),
        ("10.0.0.2", "6.6.6.6, 198.51.100.4", "198.51.100.4"),  # spoofed left entry ignored
        ("10.0.0.2", "198.51.100.4, 10.1.1.1", "198.51.100.4"),  # chained trusted proxies
        ("10.0.0.2", "10.9.9.9, 10.1.1.1", "10.0.0.2"),  # nothing but proxies
        ("10.0.0.2", "garbage", "10.0.0.2"),
        ("10.0.0.2", "1.1.1.1, garbage", "10.0.0.2"),
        ("not-an-ip", "1.1.1.1", "unknown"),
        (None, "1.1.1.1", "unknown"),
        ("2001:db8::1", None, "2001:db8::1"),
    ],
)
def test_resolve_client_ip(peer: str | None, xff: str | None, expected: str):
    assert resolve_client_ip(peer, xff, PROXIES) == expected


def test_without_trusted_proxies_the_header_never_counts():
    assert resolve_client_ip("10.0.0.2", "1.2.3.4", []) == "10.0.0.2"


def test_hash_value_is_keyed_and_stable():
    first = hash_value("1.2.3.4", "secret-a")
    assert first == hash_value("1.2.3.4", "secret-a")
    assert first != hash_value("1.2.3.4", "secret-b")
    assert "1.2.3.4" not in first
