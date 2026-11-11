"""Unit tests for core/client_ip.py and the trusted_proxy_cidrs setting (D92/RN-186)."""

from __future__ import annotations

from ipaddress import ip_network
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.client_ip import client_ip

TRUSTED = [ip_network("172.16.0.0/12"), ip_network("127.0.0.1/32"), ip_network("::1/128")]


def _request(peer: str | None, xff: str | None = None) -> SimpleNamespace:
    headers = {} if xff is None else {"x-forwarded-for": xff}
    client = None if peer is None else SimpleNamespace(host=peer)
    return SimpleNamespace(client=client, headers=headers)


def test_trusted_peer_with_single_xff_entry():
    assert client_ip(_request("172.18.0.5", "203.0.113.7"), TRUSTED) == "203.0.113.7"


def test_spoofed_left_entry_is_ignored():
    assert client_ip(_request("172.18.0.5", "1.2.3.4, 203.0.113.7"), TRUSTED) == "203.0.113.7"


def test_trusted_hops_on_the_right_are_skipped():
    # client -> outer proxy (172.17.0.2, trusted) -> nginx (peer)
    assert client_ip(_request("172.18.0.5", "203.0.113.7, 172.17.0.2"), TRUSTED) == "203.0.113.7"


def test_untrusted_peer_cannot_spoof():
    assert client_ip(_request("198.51.100.9", "203.0.113.7"), TRUSTED) == "198.51.100.9"


def test_missing_header_falls_back_to_peer():
    assert client_ip(_request("172.18.0.5"), TRUSTED) == "172.18.0.5"


def test_garbage_header_falls_back_to_peer():
    assert client_ip(_request("172.18.0.5", "not-an-ip, , unknown"), TRUSTED) == "172.18.0.5"


def test_garbage_entries_are_skipped_not_trusted():
    assert client_ip(_request("172.18.0.5", "203.0.113.7, garbage"), TRUSTED) == "203.0.113.7"


def test_all_entries_trusted_falls_back_to_peer():
    assert client_ip(_request("172.18.0.5", "172.17.0.2, 172.19.0.3"), TRUSTED) == "172.18.0.5"


def test_ipv6_client_behind_trusted_peer():
    assert client_ip(_request("::1", "2001:db8::7"), TRUSTED) == "2001:db8::7"
    assert client_ip(_request("172.18.0.5", "2001:DB8:0:0:0:0:0:7"), TRUSTED) == "2001:db8::7"


def test_ipv4_mapped_ipv6_peer_matches_ipv4_network():
    assert client_ip(_request("::ffff:172.18.0.5", "203.0.113.7"), TRUSTED) == "203.0.113.7"


def test_no_client_returns_unknown():
    assert client_ip(_request(None), TRUSTED) == "unknown"


def test_default_trusted_list_comes_from_settings(monkeypatch):
    # Patch the settings object bound in client_ip: other tests reload app.core.config,
    # which rebinds `app.core.config.settings`.
    from app.core import client_ip as client_ip_module

    monkeypatch.setattr(client_ip_module.settings, "trusted_proxy_cidrs", [ip_network("10.0.0.0/8")])
    assert client_ip(_request("10.1.2.3", "203.0.113.7")) == "203.0.113.7"
    assert client_ip(_request("172.18.0.5", "203.0.113.7")) == "172.18.0.5"


# ── settings ──────────────────────────────────────────────────────────────────


def _settings(monkeypatch, value: str | None):
    from app.core.config import Settings

    if value is None:
        monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    else:
        monkeypatch.setenv("TRUSTED_PROXY_CIDRS", value)
    return Settings(_env_file=None)


def test_setting_default_is_loopback(monkeypatch):
    assert _settings(monkeypatch, None).trusted_proxy_cidrs == [
        ip_network("127.0.0.1/32"),
        ip_network("::1/128"),
    ]


def test_setting_parses_csv_with_spaces(monkeypatch):
    cfg = _settings(monkeypatch, "10.0.0.0/8, 172.16.0.0/12 ,192.168.0.0/16")
    assert cfg.trusted_proxy_cidrs == [
        ip_network("10.0.0.0/8"),
        ip_network("172.16.0.0/12"),
        ip_network("192.168.0.0/16"),
    ]


def test_setting_empty_means_no_trusted_proxy(monkeypatch):
    assert _settings(monkeypatch, "").trusted_proxy_cidrs == []


def test_setting_invalid_entry_is_named(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        _settings(monkeypatch, "10.0.0.0/8,no-es-una-red")
    assert "no-es-una-red" in str(exc.value)
