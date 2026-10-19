from __future__ import annotations

import base64
import ipaddress
import json
import os
import pwd
import socket
import time
from pathlib import Path
from .compiler import PRIVATE
from .config import ETC, ROOT, atomic, read_json, setup, write_json
from .system import run, service
from . import topology

TX = ETC / "network-transaction.json"
OWNED = ["role", "setup.json", "guard.nft", "public.json", "control.json", "Caddyfile", "sing-box.json", "awg.conf", "applied.json", "paired.json"]
TABLE = "51823"
PRIORITY = "11000"


def table_dump():
    p = run(["nft", "list", "table", "inet", "ruvpn_guard"], check=False)
    return p.stdout if p.returncode == 0 else None


def own_table_apply(body):
    exists = table_dump() is not None
    batch = ("delete table inet ruvpn_guard\n" if exists else "") + body
    run(["nft", "-c", "-f", "-"], input=batch)
    run(["nft", "-f", "-"], input=batch)


def preflight(c, role):
    n = c["network"]
    if not (ROOT / "release.json").exists():
        raise ValueError("Нет release manifest")
    if run(["ip", "link", "show", "dev", n["uplink"]], check=False).returncode:
        raise ValueError("Указанный uplink отсутствует")
    rules = run(["nft", "list", "tables"]).stdout
    others = [s for s in rules.splitlines() if s.strip() and s.strip() != "table inet ruvpn_guard"]
    if others:
        raise ValueError("Обнаружен сторонний firewall: " + ", ".join(others) + ". Существующие правила не изменены; нужна явная адаптация сети.")
    for daemon in ["ufw", "firewalld", "docker"]:
        if run(["systemctl", "is-active", daemon], check=False).returncode == 0:
            raise ValueError(f"Активен {daemon}; автоматическая установка в эту сеть отключена")
    tcp = {n["ssh_port"], *n.get("extra_tcp_ports", [])}
    udp = {68, 546, *n.get("extra_udp_ports", [])}
    if role == "ru":
        addresses = json.loads(run(["ip", "-j", "addr", "show"]).stdout)
        local_ips = {a["local"] for interface in addresses for a in interface.get("addr_info", []) if "local" in a}
        if any(svc["ip"] in local_ips for svc in n.get("allowed_services", [])):
            raise ValueError("Пользовательский сервис не может указывать на адрес входного хоста")
        tcp |= {80, c["panel"]["port"], c["vless"]["port"]}
        udp.add(c["awg"]["port"])
    else:
        tcp.add(c["foreign"]["reality_port"])
        udp.add(c["foreign"]["hysteria_port"])
    managed_ports = [("t", c["vless"]["port"], "sing-box"), ("t", c["panel"]["port"], "caddy"), ("t", 80, "caddy"), ("u", c["awg"]["port"], "amneziawg-go")] if role == "ru" else [("t", c["foreign"]["reality_port"], "sing-box"), ("u", c["foreign"]["hysteria_port"], "sing-box")]
    for proto, port, owner in managed_ports:
        occupied = run(["ss", "-H", "-ln" + proto + "p", "sport", "=", str(port)]).stdout
        if occupied.strip() and owner not in occupied:
            raise ValueError(f"Порт {port}/{proto} занят сторонним процессом; он не остановлен")
    for proto, allowed in [("t", tcp), ("u", udp)]:
        p = run(["ss", "-H", "-ln" + proto + "p"])
        for line in p.stdout.splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            local = fields[3]
            host, _, port = local.rpartition(":")
            host = host.strip("[]").split("%", 1)[0]
            if host in {"127.0.0.1", "127.0.0.53", "127.0.0.54", "::1"}:
                continue
            if (ETC / "role").exists() and any('"' + name + '"' in line for name in ["caddy", "sing-box", "amneziawg-go"]):
                continue
            if port.isdecimal() and int(port) not in allowed:
                raise ValueError(f"Сторонний сервис слушает {local}/{proto}. Добавьте его порт в extra_{'tcp' if proto=='t' else 'udp'}_ports, чтобы сохранить доступ.")
    if role == "ru":
        connected = json.loads(run(["ip", "-j", "route", "show", "scope", "link"]).stdout)
        wanted = [ipaddress.ip_network(c["awg"]["subnet"]), ipaddress.ip_network(n.get("tun_subnet", "172.29.255.0/30"))]
        for route in connected:
            if route.get("dev") in {"awg0", "ruvpn-tun"} or "dst" not in route or route["dst"] == "default":
                continue
            occupied = ipaddress.ip_network(route["dst"], strict=False)
            if any(occupied.version == x.version and occupied.overlaps(x) for x in wanted):
                raise ValueError("AWG/TUN подсеть пересекается с существующим маршрутом " + route["dst"] + ". Измените awg.subnet или network.tun_subnet")
        for number in [10081, 10082, 10083, 19090, 8088]:
            p = run(["ss", "-H", "-lnt", "sport", "=", str(number)])
            if p.stdout.strip() and not (ETC / "role").exists():
                raise ValueError(f"Локальный служебный порт {number} уже занят")
        routes = run(["ip", "route", "show", "table", TABLE], check=False).stdout
        if routes.strip() and not (ETC / "role").exists():
            raise ValueError(f"Таблица маршрутизации {TABLE} уже используется")
        reserved = run(["ip", "rule", "show", "priority", PRIORITY]).stdout
        if reserved.strip() and not (ETC / "role").exists():
            raise ValueError(f"Приоритет ip rule {PRIORITY} уже используется")
    connection = os.environ.get("SSH_CONNECTION", "").split()
    if connection:
        source = ipaddress.ip_address(connection[0])
        if not any(source in ipaddress.ip_network(v) for v in n["management_cidrs"]):
            raise ValueError("Текущий SSH-адрес не входит в management_cidrs")
        if int(connection[3]) != n["ssh_port"]:
            raise ValueError("ssh_port не совпадает с портом текущей SSH-сессии")


def render(c, role):
    n = c["network"]
    uid = pwd.getpwnam("ruvpn-net").pw_uid
    tcp = sorted(set(n.get("extra_tcp_ports", [])))
    udp = sorted(set(n.get("extra_udp_ports", [])))
    management4 = [x for x in n["management_cidrs"] if ipaddress.ip_network(x).version == 4]
    management6 = [x for x in n["management_cidrs"] if ipaddress.ip_network(x).version == 6]
    lines = ["table inet ruvpn_guard {", "chain input { type filter hook input priority -10; policy accept;", "iifname lo accept"]
    if role == "ru":
        gateway = str(ipaddress.ip_network(c["awg"]["subnet"])[1])
        # Restrictions on VPN interfaces precede the established rule.
        lines += [f'iifname "awg0" ip daddr {gateway} meta l4proto {{ tcp, udp }} th dport 53 accept', 'iifname "awg0" drop', 'iifname "ruvpn-tun" drop']
    lines += ["ct state established,related accept", "ct state invalid drop", "ip protocol icmp accept", "meta l4proto ipv6-icmp accept", f'iifname "{n["uplink"]}" udp sport 67 udp dport 68 accept', f'iifname "{n["uplink"]}" udp sport 547 udp dport 546 accept']
    if management4:
        lines.append(f"ip saddr {{ {', '.join(management4)} }} tcp dport {n['ssh_port']} accept")
    if management6:
        lines.append(f"ip6 saddr {{ {', '.join(management6)} }} tcp dport {n['ssh_port']} accept")
    if role == "ru":
        tcp += [80, c["panel"]["port"], c["vless"]["port"]]
        udp += [c["awg"]["port"]]
    else:
        lines += [f"ip saddr {topology.entry_ip(c)} tcp dport {c['foreign']['reality_port']} accept", f"ip saddr {topology.entry_ip(c)} udp dport {c['foreign']['hysteria_port']} accept"]
    if tcp:
        lines.append("tcp dport { " + ", ".join(map(str, sorted(set(tcp)))) + " } accept")
    if udp:
        lines.append("udp dport { " + ", ".join(map(str, sorted(set(udp)))) + " } accept")
    lines += ["drop", "}", "chain forward { type filter hook forward priority -10; policy accept;"]
    if role == "ru":
        subnet = c["awg"]["subnet"]
        lines += [f'iifname "awg0" oifname "ruvpn-tun" ip saddr {subnet} accept', f'iifname "ruvpn-tun" oifname "awg0" ip daddr {subnet} accept', 'iifname { "awg0", "ruvpn-tun" } drop', 'oifname { "awg0", "ruvpn-tun" } drop']
    else:
        lines += ["drop"]
    lines += ["}", "chain output { type filter hook output priority -10; policy accept;", f"meta skuid {uid} ct state established,related accept", f"meta skuid {uid} meta nfproto ipv6 reject"]
    if role == "ru":
        lines += [f"meta skuid {uid} ip daddr {svc['ip']} {svc['protocol']} dport {svc['port']} accept" for svc in n.get("allowed_services", [])]
    lines += [f"meta skuid {uid} ip daddr {{ {', '.join(PRIVATE + ['198.18.0.0/15'])} }} reject", "}", "}"]
    return "\n".join(lines) + "\n"


def stage(c, role, full_restore=False):
    if TX.exists():
        raise ValueError("Ожидается подтверждение предыдущего изменения сети: scripts/configure.sh --confirm-network или --rollback-network")
    originals = {name: base64.b64encode((ETC / name).read_bytes()).decode() if (ETC / name).exists() else None for name in OWNED}
    sysctls = {name: run(["sysctl", "-n", name]).stdout.strip() for name in ["net.ipv4.ip_forward", "net.ipv4.conf.all.rp_filter", "net.ipv4.conf.default.rp_filter"]}
    transaction = {"files": originals, "nft": table_dump(), "role": role, "sysctls": sysctls, "created": int(time.time()), "boot_id": Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    if full_restore:
        import sqlite3
        import tempfile
        from .config import DB_PATH
        transaction["files"] = {p.relative_to(ETC).as_posix(): base64.b64encode(p.read_bytes()).decode() for p in ETC.rglob("*") if p.is_file() and not p.is_symlink()}
        transaction["links"] = {p.relative_to(ETC).as_posix(): str(p.resolve()) for p in ETC.rglob("*") if p.is_symlink()}
        if DB_PATH.exists():
            with tempfile.TemporaryDirectory(prefix="ruvpn-net-") as tmp:
                copy = Path(tmp) / "db.sqlite3"
                with sqlite3.connect(DB_PATH) as source, sqlite3.connect(copy) as target:
                    source.backup(target)
                transaction["database"] = base64.b64encode(copy.read_bytes()).decode()
    write_json(TX, transaction)
    try:
        run(["systemd-run", "--quiet", "--collect", "--unit=ruvpn-rollback", "--working-directory=/opt/ruvpn/current", f"--on-active={c['network']['rollback_seconds']}s", "/opt/ruvpn/current/.venv/bin/python", "-m", "gateway.ops", "network-rollback"], timeout=15)
    except BaseException:
        TX.unlink(missing_ok=True)
        raise


def confirm():
    if not TX.exists():
        raise ValueError("Нет ожидающего изменения сети")
    run(["systemctl", "stop", "ruvpn-rollback.timer"], check=False)
    run(["systemctl", "reset-failed", "ruvpn-rollback.service"], check=False)
    TX.unlink()


def start(c, role):
    own_table_apply((ETC / "guard.nft").read_text())
    if role == "ru":
        for key, value in [("net.ipv4.ip_forward", "1"), ("net.ipv4.conf.all.rp_filter", "0"), ("net.ipv4.conf.default.rp_filter", "0")]:
            run(["sysctl", "-q", "-w", key + "=" + value])
        run(["ip", "route", "replace", "unreachable", "default", "table", TABLE, "metric", "32760"])
        route(c)


def awg_setup(c):
    a = c["awg"]
    network4, network6 = ipaddress.ip_network(a["subnet"]), ipaddress.ip_network(a["subnet6"])
    run(["ip", "addr", "replace", f"{network4[1]}/{network4.prefixlen}", "dev", "awg0"])
    run(["sysctl", "-q", "-w", "net.ipv6.conf.awg0.disable_ipv6=0"])
    run(["ip", "-6", "addr", "replace", f"{network6[1]}/{network6.prefixlen}", "dev", "awg0"])
    run(["ip", "link", "set", "dev", "awg0", "mtu", str(a["mtu"]), "up"])
    # New VPN interfaces can inherit forwarding=0 while global ip_forward is 1.
    run(["sysctl", "-q", "-w", "net.ipv4.conf.awg0.rp_filter=0", "net.ipv4.conf.awg0.forwarding=1"])
    from .system import BIN
    run([BIN / "awg", "setconf", "awg0", ETC / "awg.conf"])
    route(c)


def route(c):
    # An unreachable default is retained when the TUN route disappears.
    run(["ip", "route", "replace", "unreachable", "default", "table", TABLE, "metric", "32760"])
    if run(["ip", "link", "show", "dev", "awg0"], check=False).returncode == 0:
        existing = run(["ip", "rule", "show", "priority", PRIORITY]).stdout
        if not existing.strip():
            run(["ip", "rule", "add", "priority", PRIORITY, "iif", "awg0", "lookup", TABLE])
        elif "iif awg0" not in existing or TABLE not in existing:
            raise ValueError("Зарезервированный приоритет ip rule занят")
    if run(["ip", "link", "show", "dev", "ruvpn-tun"], check=False).returncode == 0:
        run(["sysctl", "-q", "-w", "net.ipv4.conf.ruvpn-tun.rp_filter=0", "net.ipv4.conf.ruvpn-tun.forwarding=1"])
        run(["ip", "route", "replace", "default", "dev", "ruvpn-tun", "table", TABLE, "metric", "10"])


def rollback(restart=True):
    if not TX.exists():
        return
    tx = read_json(TX)
    for name in ["ruvpn-panel", "ruvpn-helper", "ruvpn-awg", "ruvpn-sing", "ruvpn-caddy"]:
        run(["systemctl", "stop", name], check=False)
    for name, data in tx["files"].items():
        if data is None:
            (ETC / name).unlink(missing_ok=True)
        else:
            atomic(ETC / name, base64.b64decode(data))
    for name, target in tx.get("links", {}).items():
        path = ETC / name
        path.unlink(missing_ok=True)
        path.symlink_to(target)
    if tx.get("database"):
        from .config import DB_PATH
        for suffix in ["-wal", "-shm"]:
            Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
        atomic(DB_PATH, base64.b64decode(tx["database"]))
    if table_dump() is not None:
        run(["nft", "delete", "table", "inet", "ruvpn_guard"])
    if tx["nft"]:
        run(["nft", "-f", "-"], input=tx["nft"])
    run(["ip", "rule", "del", "priority", PRIORITY, "iif", "awg0", "lookup", TABLE], check=False)
    run(["ip", "route", "flush", "table", TABLE], check=False)
    for key, value in tx["sysctls"].items():
        run(["sysctl", "-q", "-w", key + "=" + value], check=False)
    TX.unlink()
    run(["systemctl", "stop", "ruvpn-rollback.timer"], check=False)
    if (ETC / "setup.json").exists():
        from .backup import repair_permissions
        repair_permissions(tx["role"])
        old = setup()
        start(old, tx["role"])
        if not restart:
            return
        if tx["role"] == "ru":
            for name in ["ruvpn-awg", "ruvpn-helper"]:
                service(name, "start")
            # Roll back network settings while preserving current desired
            # credentials. A revoked key must not reappear from an old config.
            from . import control
            with control.serialized():
                control.apply_locked()
            for name in ["ruvpn-caddy", "ruvpn-panel"]:
                service(name, "start")
        else:
            service("ruvpn-sing", "start")
