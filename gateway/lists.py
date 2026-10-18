from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import time
import urllib.request
from pathlib import Path
from .config import ETC, ROOT, domain, read_json, write_json

BASE = ETC / "lists"


def pointer(name, target):
    temporary = BASE / (name + ".new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, BASE / name)


def current():
    return (BASE / "current").resolve(strict=True)


def initialize():
    BASE.mkdir(parents=True, exist_ok=True, mode=0o755)
    BASE.chmod(0o755)
    if (BASE / "current").exists():
        return
    target = BASE / "bundled-v1"
    shutil.copytree(ROOT / "data", target, dirs_exist_ok=True)
    pointer("current", target)


def fetch(url):
    if not url.startswith("https://"):
        raise ValueError("Источник списков должен использовать HTTPS")
    with urllib.request.urlopen(url, timeout=25) as r:
        if not r.url.startswith("https://"):
            raise ValueError("Небезопасное перенаправление источника")
        data = r.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("Список слишком большой")
        return data


def update(c):
    old = current()
    old_meta = read_json(old / "sources.json")
    if time.time() - old_meta.get("updated_at", 0) < 86400:
        raise ValueError("Обновление разрешено не чаще раза в сутки")
    version = str(int(time.time()))
    target = BASE / ("revision-" + version)
    if target.exists():
        raise ValueError("Обновление уже подготовлено")
    shutil.copytree(old, target)
    sources = c.get("lists", {})
    changes = 0
    try:
        for key, filename in [("ip_url", "ru-ip.json"), ("domains_url", "ru-services.json")]:
            url = sources.get(key, "")
            if not url:
                continue
            data = fetch(url)
            values = [line.strip() for line in data.decode().splitlines() if line.strip() and not line.lstrip().startswith("#")]
            if key == "ip_url":
                networks = [ipaddress.IPv4Network(v, strict=True) for v in values]
                if not 50 <= len(networks) <= 100000 or any(n.prefixlen < 8 or n.is_private or n.is_multicast or n.is_loopback or n.is_link_local for n in networks):
                    raise ValueError("Некорректный RU-IP список")
                payload = {"version": 3, "rules": [{"ip_cidr": [str(n) for n in networks]}]}
            else:
                if not 10 <= len(values) <= 100000:
                    raise ValueError("Некорректный список RU-сервисов")
                payload = {"version": 3, "rules": [{"domain_suffix": sorted(set(domain(v) for v in values))}]}
            write_json(target / filename, payload, 0o644)
            old_meta[key] = {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "license": sources.get("ip_license" if key == "ip_url" else "domains_license", "owner-specified")}
            changes += 1
        if not changes:
            raise ValueError("Источники обновления не настроены")
        old_meta.update(version=version, updated_at=int(time.time()))
        write_json(target / "sources.json", old_meta, 0o644)
        pointer("previous", old)
        pointer("current", target)
        write_json(BASE / "pending.json", {"previous": str(old)})
    except BaseException:
        shutil.rmtree(target)
        raise
    return version


def commit():
    (BASE / "pending.json").unlink(missing_ok=True)


def abort():
    path = BASE / "pending.json"
    if path.exists():
        pointer("current", Path(read_json(path)["previous"]))
        path.unlink()


def rollback():
    old = current()
    try:
        previous = (BASE / "previous").resolve(strict=True)
    except FileNotFoundError as e:
        raise ValueError("Предыдущей версии списков нет") from e
    if not previous.is_dir() or previous == old:
        raise ValueError("Предыдущей версии списков нет")
    pointer("current", previous)
    pointer("previous", old)
    write_json(BASE / "pending.json", {"previous": str(old)})
    return read_json(previous / "sources.json")["version"]


def explain(c, snapshot, value):
    value = value.strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
        value = domain(value)
    if address:
        denied = address.version == 6 or any(address in ipaddress.ip_network(n) for n in __import__("gateway.compiler", fromlist=["PRIVATE"]).PRIVATE) or str(address) in {c["network"]["ru_ipv4"], c["foreign"]["ipv4"]}
    else:
        denied = any(value == d or value.endswith("." + d) for d in ["local", "localhost", "internal", "home.arpa", c["panel"]["domain"]])
    if denied:
        return {"value": value, "route": "BLOCK", "reason": "Служебный адрес, приватная сеть или IPv6. DNS на gateway:53 обрабатывается отдельно."}
    for rule in sorted(snapshot["rules"], key=lambda r: (r["priority"], r["id"])):
        hit = (address and rule["kind"] == "cidr" and address in ipaddress.ip_network(rule["value"])) or (not address and rule["kind"] == "domain" and value == rule["value"]) or (not address and rule["kind"] == "suffix" and (value == rule["value"] or value.endswith("." + rule["value"])))
        if hit:
            return {"value": value, "route": rule["action"], "reason": f"Ручное правило #{rule['id']} с приоритетом {rule['priority']}"}
    if not address:
        domains = read_json(current() / "ru-services.json")["rules"][0]["domain_suffix"]
        if any(value == d or value.endswith("." + d) for d in domains):
            return {"value": value, "route": "RU_DIRECT", "reason": "Имя входит в список RU-сервисов; иностранный CDN сам по себе не меняет маршрут."}
        return {"value": value, "route": "FOREIGN", "reason": "Известное имя отсутствует в RU-services. Российский IP не переопределяет это решение."}
    networks = read_json(current() / "ru-ip.json")["rules"][0]["ip_cidr"]
    hit = any(address in ipaddress.ip_network(n) for n in networks)
    return {"value": value, "route": "RU_DIRECT" if hit else "FOREIGN", "reason": "IP-ветка: доменное назначение неизвестно. " + ("Адрес входит в RU-IP." if hit else "Адрес отсутствует в RU-IP.")}
