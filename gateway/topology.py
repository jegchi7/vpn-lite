"""Geography is independent of the legacy service roles ru/foreign.

The ru service role owns clients/control plane; foreign owns the remote relay.
Keep those on-disk names compatible while exposing entry/relay to operators.
"""
from __future__ import annotations


def entry_region(c):
    return c.get("deployment", {}).get("entry", "ru")


def remote_region(c):
    return "ru" if entry_region(c) == "foreign" else "foreign"


def region_ip(c, region):
    return c["network"]["ru_ipv4"] if region == "ru" else c["foreign"]["ipv4"]


def entry_ip(c):
    return region_ip(c, entry_region(c))


def remote_ip(c):
    return region_ip(c, remote_region(c))


def outbound(c, action):
    # The legacy selector tag "foreign" means the remote relay, never a
    # direct fallback. Geographic FOREIGN is local on a foreign entry.
    local = "FOREIGN" if entry_region(c) == "foreign" else "RU_DIRECT"
    return "direct" if action == local else "foreign"


def public_info(c):
    return {"entry": entry_region(c), "remote": remote_region(c)}
