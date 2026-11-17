"""Fonte Wi-Fi: normalização, hash, ARP e varrimento com fakes (sem rede)."""

import pytest

from homemind.features.presence.wifi import (
    ArpScanner,
    FakeWifiScanner,
    WifiConfigError,
    hosts_of,
    match_key,
    normalize_mac,
    parse_neighbors,
)

MAC = "02:00:00:aa:00:01"


def test_normalize_mac_handles_macos_missing_zeros_and_separators():
    assert normalize_mac("2:0:0:aa:0:1") == MAC
    assert normalize_mac("02-00-00-AA-00-01") == MAC
    for bad in ("", "aa:bb", "zz:00:00:aa:00:01", "02:00:00:aa:00:01:ff", "002:0:0:aa:0:1"):
        with pytest.raises(ValueError):
            normalize_mac(bad)


def test_match_key_is_salted_stable_and_not_the_mac():
    k = match_key("sal", MAC)
    assert k == match_key("sal", "2:0:0:AA:0:1")  # o mesmo telemóvel, outra grafia
    assert k != match_key("outro-sal", MAC)
    assert MAC.replace(":", "") not in k and MAC not in k
    assert 16 <= len(k) <= 128
    with pytest.raises(WifiConfigError):
        match_key("", MAC)


MACOS = """\
? (192.168.50.1) at 2:0:0:aa:0:1 on en0 ifscope [ethernet]
? (192.168.50.23) at (incomplete) on en0 ifscope [ethernet]
? (192.168.50.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]
? (224.0.0.251) at 1:0:5e:0:0:fb on en0 ifscope permanent [ethernet]
"""
LINUX = (
    "192.168.50.7 dev wlan0 lladdr 02:00:00:aa:00:02 REACHABLE\n" "192.168.50.9 dev wlan0  FAILED\n"
)


def test_parse_neighbors_macos_and_linux():
    t = parse_neighbors(MACOS)
    assert t["192.168.50.1"] == MAC
    assert "192.168.50.23" not in t and "192.168.50.255" not in t
    assert parse_neighbors(LINUX) == {"192.168.50.7": "02:00:00:aa:00:02"}


def test_subnet_validation_is_private_and_bounded():
    assert len(hosts_of("192.168.50.0/24")) == 254
    for bad in ("8.8.8.0/24", "10.0.0.0/8", "127.0.0.0/24", "nao-e-rede", "fe80::/64", ""):
        with pytest.raises(WifiConfigError):
            hosts_of(bad)


def test_arp_scanner_returns_only_who_answered_now_without_network():
    table = {"192.168.50.7": "02:00:00:aa:00:02", "192.168.50.9": "02:00:00:aa:00:03",
             "10.9.9.9": "02:00:00:aa:00:04"}  # fmt: skip
    scanner = ArpScanner(
        "192.168.50.0/24", ping=lambda ip: ip == "192.168.50.7", neighbors=lambda: table
    )
    # 192.168.50.9 está na ARP mas não respondeu (entrada antiga); 10.9.9.9 é de fora da sub-rede
    assert scanner.scan() == {"02:00:00:aa:00:02"}
    assert scanner.origin == "real"


def test_fake_scanner_is_simulated_and_can_fail():
    f = FakeWifiScanner(["2:0:0:aa:0:1"])
    assert f.origin == "simulated" and f.scan() == {MAC}
    f.fail = True
    with pytest.raises(OSError):
        f.scan()


def test_hostscan_sends_only_hashes_never_macs(monkeypatch):
    from homemind.features.presence import hostscan

    sent = {}
    monkeypatch.setattr(hostscan, "post_keys", lambda url, token, keys: sent.update(keys=keys))
    n = hostscan.scan_once(FakeWifiScanner([MAC, "02:00:00:aa:00:02"]), "sal", "http://x", "t")
    assert n == 2 and len(sent["keys"]) == 2
    assert all(k.startswith("hmac-sha256:") and "02:00" not in k for k in sent["keys"])
