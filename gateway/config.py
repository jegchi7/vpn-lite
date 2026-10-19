from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETC = Path(os.environ.get("RUVPN_ETC", "/etc/ruvpn"))
STATE = Path(os.environ.get("RUVPN_STATE", "/var/lib/ruvpn"))
SOCKET = os.environ.get("RUVPN_SOCKET", "/run/ruvpn/helper.sock")
DB_PATH = STATE / "control.sqlite3"


def read_json(path: Path):
    with path.open() as f:
        return json.load(f)


def atomic(path: Path, data: str | bytes, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    # Root-owned destinations only; never follow a pre-existing temporary link.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(temporary, flags, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode() if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: Path, data, mode: int = 0o600):
    atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", mode)


def domain(value: str) -> str:
    value = value.strip().lower().rstrip(".").lstrip(".")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise ValueError("Некорректное имя домена") from e
    if len(value) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in value.split(".")):
        raise ValueError("Некорректное имя домена")
    return value


def validate_setup(c: dict):
    deployment = c.get("deployment", {})
    if not isinstance(deployment, dict) or deployment.get("entry", "ru") not in {"ru", "foreign"}:
        raise ValueError("deployment.entry: ru или foreign")
    required = ("network", "panel", "awg", "vless", "dns", "foreign", "paths", "telegram", "limits")
    for section in required:
        if not isinstance(c.get(section), dict):
            raise ValueError(f"Отсутствует раздел {section}")
    n = c["network"]
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", n["uplink"]) or n["uplink"] == "auto":
        raise ValueError("Нужен существующий uplink-интерфейс")
    ipaddress.IPv4Address(n["ru_ipv4"])
    if c["foreign"].get("ipv4"):
        ipaddress.IPv4Address(c["foreign"]["ipv4"])
    if n["ru_ipv4"] == c["foreign"].get("ipv4"):
        raise ValueError("RU и зарубежный сервер должны иметь разные IPv4")
    for network in n["management_cidrs"]:
        ipaddress.ip_network(network, strict=False)
    for port in [n["ssh_port"], c["panel"]["port"], c["awg"]["port"], c["vless"]["port"], c["foreign"]["reality_port"], c["foreign"]["hysteria_port"], *n.get("extra_tcp_ports", []), *n.get("extra_udp_ports", [])]:
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Порт должен быть в диапазоне 1–65535")
    tcp = [c["panel"]["port"], c["vless"]["port"], n["ssh_port"], 80]
    if len(set(tcp)) != len(tcp):
        raise ValueError("Конфликт портов панели, SSH, HTTP-01 и VLESS")
    for group, key in [("panel", "domain"), ("vless", "server_name"), ("foreign", "server_name"), ("foreign", "tls_server_name"), ("dns", "foreign_server_name")]:
        c[group][key] = domain(c[group][key])
    for name in ["ru", "foreign"]:
        ipaddress.IPv4Address(c["dns"][name])
    net = ipaddress.ip_network(c["awg"]["subnet"])
    if net.version != 4 or not 22 <= net.prefixlen <= 28 or not net.is_private:
        raise ValueError("AWG subnet: частная IPv4-подсеть от /22 до /28")
    tun = ipaddress.IPv4Network(n.get("tun_subnet", "172.29.255.0/30"))
    if tun.prefixlen != 30 or not tun.is_private or tun.overlaps(net):
        raise ValueError("TUN subnet: отдельная частная IPv4 подсеть /30")
    if len(n.get("allowed_services", [])) > 20:
        raise ValueError("Разрешено не больше 20 пользовательских сервисов")
    for svc in n.get("allowed_services", []):
        address = ipaddress.IPv4Address(svc["ip"])
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address in net or address in tun or str(address) in {n["ru_ipv4"], c["foreign"]["ipv4"]}:
            raise ValueError("Пользовательский сервис не может быть служебным адресом шлюза")
        if svc["protocol"] not in {"tcp", "udp"} or not isinstance(svc["port"], int) or not 1 <= svc["port"] <= 65535:
            raise ValueError("Укажите IP, порт и tcp/udp пользовательского сервиса")
    subnet6 = ipaddress.IPv6Network(c["awg"]["subnet6"])
    if subnet6.prefixlen != 64 or subnet6.network_address not in ipaddress.IPv6Network("fc00::/7"):
        raise ValueError("AWG IPv6 subnet: отдельная ULA /64")
    if not 1200 <= c["awg"]["mtu"] <= 1400:
        raise ValueError("MTU должен быть между 1200 и 1400")
    if c["paths"]["mode"] not in {"auto", "primary", "backup"}:
        raise ValueError("Неизвестный режим путей")
    enabled = [name for name in ["primary", "backup"] if c["paths"].get(name + "_enabled", True)]
    if not enabled or (c["paths"]["mode"] != "auto" and c["paths"]["mode"] not in enabled):
        raise ValueError("Выбранный путь выключен или выключены оба пути")
    if any(not isinstance(c["paths"].get(name + "_enabled", True), bool) for name in ["primary", "backup"]):
        raise ValueError("Флаги путей должны быть true/false")
    for field, low, high in [("failures", 1, 20), ("hold_seconds", 0, 3600), ("recovery_successes", 1, 50)]:
        if not isinstance(c["paths"][field], int) or not low <= c["paths"][field] <= high:
            raise ValueError("Некорректный параметр путей: " + field)
    if len(c["paths"]["urls"]) != 2 or any(not x.startswith("https://") for x in c["paths"]["urls"]):
        raise ValueError("Нужны два HTTPS назначения контроля доступности")
    if not 10 <= c["paths"]["interval"] <= 3600:
        raise ValueError("Интервал: от 10 до 3600 секунд")
    if c["telegram"]["route"] not in {"direct", "foreign"}:
        raise ValueError("Telegram route: direct или foreign")
    if not 1 <= c["limits"]["devices"] <= 200 or not 1 <= c["limits"]["users"] <= 100:
        raise ValueError("Некорректные лимиты")
    if not 1 <= c["limits"]["default_device_limit"] <= c["limits"]["devices"]:
        raise ValueError("Некорректный начальный лимит устройств пользователя")
    if not 60 <= n["rollback_seconds"] <= 600:
        raise ValueError("Таймер отката: от 60 до 600 секунд")
    return c


def setup():
    return read_json(ETC / "setup.json")


def public():
    return read_json(ETC / "public.json")
