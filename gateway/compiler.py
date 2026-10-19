from __future__ import annotations

import base64
import ipaddress
import re
import uuid
from .config import ETC, domain
from . import topology

PRIVATE = ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "192.0.0.0/24", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4"]
PRIVATE_DOMAINS = ["localhost", "local", "internal", "home.arpa", "metadata.google.internal"]


def valid_key(value):
    try:
        return isinstance(value, str) and len(base64.b64decode(value, validate=True)) == 32
    except (ValueError, TypeError):
        return False


def validate_snapshot(data, c):
    if not isinstance(data, dict) or set(data) != {"devices", "rules"}:
        raise ValueError("Некорректная конфигурация")
    if not isinstance(data["devices"], list) or len(data["devices"]) > c["limits"]["devices"]:
        raise ValueError("Превышен лимит устройств")
    identifiers, addresses, pubkeys, uuids = set(), set(), set(), set()
    subnet = ipaddress.ip_network(c["awg"]["subnet"])
    for d in data["devices"]:
        if set(d) != {"id", "address", "public_key", "psk", "uuid"}:
            raise ValueError("Некорректные поля устройства")
        for value in [d["id"], d["uuid"]]:
            if str(uuid.UUID(value)) != value:
                raise ValueError("Некорректный UUID")
        if not isinstance(d["address"], int) or not 2 <= d["address"] < subnet.num_addresses - 1:
            raise ValueError("Некорректный адрес устройства")
        if not all(valid_key(d[k]) for k in ["public_key", "psk"]):
            raise ValueError("Некорректный ключ устройства")
        for seen, value in [(identifiers, d["id"]), (addresses, d["address"]), (pubkeys, d["public_key"]), (uuids, d["uuid"])]:
            if value in seen:
                raise ValueError("Повторяющееся устройство или ключ")
            seen.add(value)
    if not isinstance(data["rules"], list) or len(data["rules"]) > 1000:
        raise ValueError("Слишком много правил")
    for r in data["rules"]:
        if r["kind"] not in {"domain", "suffix", "cidr"} or r["action"] not in {"RU_DIRECT", "FOREIGN", "BLOCK"}:
            raise ValueError("Некорректное правило")
        if not isinstance(r["priority"], int) or not -10000 <= r["priority"] <= 10000:
            raise ValueError("Некорректный приоритет")
        if r["kind"] == "cidr":
            ipaddress.ip_network(r["value"], strict=True)
        else:
            domain(r["value"])
    return data


def match(rule):
    return {{"domain": "domain", "suffix": "domain_suffix", "cidr": "ip_cidr"}[rule["kind"]]: [rule["value"]]}


def reality_in(tag, port, private, short_id, server_name, users, uplink, resolver):
    return {"type": "vless", "tag": tag, "listen": "0.0.0.0", "listen_port": port, "users": users,
            "tls": {"enabled": True, "server_name": server_name, "reality": {"enabled": True, "handshake": {"server": server_name, "server_port": 443, "bind_interface": uplink, "domain_resolver": resolver}, "private_key": private, "short_id": [short_id]}}}


def foreign_config(c, s, certificate_dir=None):
    f = c["foreign"]
    uplink = c["network"]["uplink"]
    certificate_dir = certificate_dir if certificate_dir is not None else ETC
    return {
        "log": {"disabled": True},
        "dns": {"servers": [{"type": "udp", "tag": "resolver", "server": c["dns"][topology.remote_region(c)], "bind_interface": uplink}], "final": "resolver", "strategy": "ipv4_only"},
        "inbounds": [
            reality_in("hop-reality", f["reality_port"], s["hop_reality_private"], s["hop_short_id"], f["server_name"], [{"uuid": s["hop_uuid"], "flow": "xtls-rprx-vision"}], uplink, "resolver"),
            {"type": "hysteria2", "tag": "hop-hysteria", "listen": "0.0.0.0", "listen_port": f["hysteria_port"], "users": [{"name": "ru-gateway", "password": s["hop_password"]}], "obfs": {"type": "salamander", "password": s["obfs_password"]}, "tls": {"enabled": True, "server_name": f["tls_server_name"], "certificate_path": str(certificate_dir / "hop.crt"), "key_path": str(certificate_dir / "hop.key")}},
        ],
        "outbounds": [{"type": "direct", "tag": "direct", "bind_interface": uplink, "domain_resolver": "resolver"}],
        "route": {"default_domain_resolver": "resolver", "rules": [
            {"ip_version": 6, "action": "reject"},
            {"ip_cidr": PRIVATE + ["198.18.0.0/15", f["ipv4"] + "/32", c["network"]["ru_ipv4"] + "/32"], "action": "reject"},
            {"domain_suffix": PRIVATE_DOMAINS, "action": "reject"},
        ], "final": "direct"},
    }


def ru_config(c, s, paired, snapshot, lists_path):
    validate_snapshot(snapshot, c)
    n, a, v = c["network"], c["awg"], c["vless"]
    f = paired
    uplink = n["uplink"]
    reverse = topology.entry_region(c) == "foreign"
    local_dns = "foreign-dns" if reverse else "ru-dns"
    bootstrap_dns = "entry-dns" if reverse else "ru-dns"
    ru_out, foreign_out = topology.outbound(c, "RU_DIRECT"), topology.outbound(c, "FOREIGN")
    gateway = str(ipaddress.ip_network(a["subnet"])[1])
    users = [{"name": d["id"], "uuid": d["uuid"], "flow": "xtls-rprx-vision"} for d in snapshot["devices"]]
    inbounds = [
        reality_in("vless-in", v["port"], s["entry_reality_private"], s["entry_short_id"], v["server_name"], users, uplink, bootstrap_dns),
        # The guard blocks local INPUT from TUN; TCP must stay in userspace.
        {"type": "tun", "tag": "awg-in", "interface_name": "ruvpn-tun", "address": [str(ipaddress.ip_network(n.get("tun_subnet", "172.29.255.0/30"))[1]) + "/30"], "mtu": 1500, "auto_route": False, "stack": "gvisor"},
        {"type": "direct", "tag": "gateway-dns", "listen": gateway, "listen_port": 53},
    ]
    for name, port in [("primary", 10081), ("backup", 10082), ("selected", 10083)]:
        inbounds.append({"type": "http", "tag": "local-" + name, "listen": "127.0.0.1", "listen_port": port, "users": [s["proxy_auth"]]})
    outbounds = [
        {"type": "direct", "tag": "direct", "bind_interface": uplink, "domain_resolver": local_dns},
        {"type": "vless", "tag": "primary", "server": f["ipv4"], "server_port": f["reality_port"], "uuid": f["uuid"], "flow": "xtls-rprx-vision", "packet_encoding": "xudp", "bind_interface": uplink, "tls": {"enabled": True, "server_name": f["server_name"], "utls": {"enabled": True, "fingerprint": "chrome"}, "reality": {"enabled": True, "public_key": f["public_key"], "short_id": f["short_id"]}}},
        {"type": "hysteria2", "tag": "backup", "server": f["ipv4"], "server_port": f["hysteria_port"], "password": f["password"], "bind_interface": uplink, "obfs": {"type": "salamander", "password": f["obfs_password"]}, "tls": {"enabled": True, "server_name": f["tls_server_name"], "certificate": f["certificate"].splitlines()}},
        {"type": "block", "tag": "closed"},
        {"type": "selector", "tag": "foreign", "outbounds": ["primary", "backup", "closed"], "default": "primary" if c["paths"].get("primary_enabled", True) else "backup", "interrupt_exist_connections": True},
    ]
    route_rules = [{"inbound": ["local-" + name], "action": "route", "outbound": target} for name, target in [("primary", "primary"), ("backup", "backup"), ("selected", "foreign")]]
    route_rules += [
        {"ip_version": 6, "action": "reject"},
        {"port": 53, "action": "hijack-dns"},
        {"domain_regex": [".+"], "invert": True, "action": "sniff", "sniffer": ["http", "tls", "quic", "dns"], "timeout": "150ms"},
        {"protocol": "dns", "action": "hijack-dns"},
    ]
    route_rules += [{"ip_cidr": [svc["ip"] + "/32"], "port": [svc["port"]], "network": svc["protocol"], "action": "route", "outbound": "direct"} for svc in n.get("allowed_services", [])]
    route_rules += [
        {"ip_cidr": PRIVATE + [topology.entry_ip(c) + "/32", topology.remote_ip(c) + "/32"], "action": "reject"},
        {"domain_suffix": PRIVATE_DOMAINS + [c["panel"]["domain"]], "action": "reject"},
    ]
    dns_rules = [
        {"query_type": ["AAAA"], "action": "predefined", "rcode": "NOERROR"},
        {"domain_suffix": PRIVATE_DOMAINS + [c["panel"]["domain"]], "action": "reject"},
    ]
    for rule in sorted(snapshot["rules"], key=lambda r: (r["priority"], r["id"])):
        route_rules.append({**match(rule), **({"action": "reject"} if rule["action"] == "BLOCK" else {"action": "route", "outbound": topology.outbound(c, rule["action"])})})
        if rule["kind"] != "cidr":
            dns_rules.append({**match(rule), **({"action": "reject"} if rule["action"] == "BLOCK" else {"action": "route", "server": "ru-dns" if rule["action"] == "RU_DIRECT" else "foreign-dns"})})
    # FakeIP establishes one domain per synthetic address, avoiding ambiguous
    # reverse-mapping entries on shared CDNs. Resolver choice happens on dial.
    # Synthetic A responses do not contact any upstream. Ordered manual rules
    # apply when the connection is routed and on non-A DNS queries.
    fake = {"inbound": ["vless-in", "awg-in", "gateway-dns"], "query_type": ["A"], "action": "route", "server": "names"}
    dns_rules = dns_rules[:2] + [fake] + dns_rules[2:]
    dns_rules.append({"rule_set": ["ru-services"], "action": "route", "server": "ru-dns"})
    route_rules += [
        {"rule_set": ["ru-services"], "action": "route", "outbound": ru_out},
        {"domain_regex": [".+"], "action": "route", "outbound": foreign_out},
        {"rule_set": ["ru-ip"], "action": "route", "outbound": ru_out},
    ]
    return {
        "log": {"disabled": True},
        "dns": {"servers": [
            *([{"type": "udp", "tag": "entry-dns", "server": c["dns"]["foreign"], "bind_interface": uplink}] if reverse else []),
            {"type": "udp", "tag": "ru-dns", "server": c["dns"]["ru"], "detour": ru_out},
            {"type": "https", "tag": "foreign-dns", "server": c["dns"]["foreign"], "server_port": 443, "path": "/dns-query", "detour": foreign_out, "tls": {"enabled": True, "server_name": c["dns"]["foreign_server_name"]}},
            {"type": "fakeip", "tag": "names", "inet4_range": "198.18.0.0/15"},
        ], "rules": dns_rules, "final": "foreign-dns", "reverse_mapping": False, "strategy": "ipv4_only"},
        "inbounds": inbounds, "outbounds": outbounds,
        "route": {"default_domain_resolver": local_dns, "default_interface": uplink, "rules": route_rules, "rule_set": [
            {"type": "local", "tag": tag, "format": "source", "path": str(lists_path / filename)} for tag, filename in [("ru-services", "ru-services.json"), ("ru-ip", "ru-ip.json")]
        ], "final": foreign_out},
        "experimental": {"cache_file": {"enabled": True, "path": "/var/lib/ruvpn-net/cache.db", "store_fakeip": True}, "clash_api": {"external_controller": "127.0.0.1:19090", "secret": s["api_secret"]}},
    }


def awg_config(c, s, snapshot):
    validate_snapshot(snapshot, c)
    subnet, subnet6 = ipaddress.ip_network(c["awg"]["subnet"]), ipaddress.ip_network(c["awg"]["subnet6"])
    lines = ["[Interface]", "PrivateKey = " + s["awg_private"], "ListenPort = " + str(c["awg"]["port"])]
    lines += [f"{name} = {value}" for name, value in s["awg_obfuscation"].items()]
    for d in snapshot["devices"]:
        lines += ["", "[Peer]", "PublicKey = " + d["public_key"], "PresharedKey = " + d["psk"], f"AllowedIPs = {subnet[d['address']]}/32, {subnet6[d['address']]}/128"]
    return "\n".join(lines) + "\n"
