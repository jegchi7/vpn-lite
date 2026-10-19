from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import grp
import ipaddress
import json
import os
import pwd
import re
import secrets
import shutil
import stat
import sys
import time
import tomllib
import uuid
from pathlib import Path
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from . import compiler, control, crypto, db, helper, lists, network, rpc, security, topology
from .config import ETC, ROOT, STATE, atomic, read_json, setup, validate_setup, write_json
from .system import BIN, run, service


def load_setup(path):
    path = Path(path)
    if path.suffix == ".json":
        c = read_json(path)
    else:
        with path.open("rb") as f:
            c = tomllib.load(f)
    if c["network"]["uplink"] == "auto":
        route = json.loads(run(["ip", "-j", "route", "get", "1.1.1.1"]).stdout)
        c["network"]["uplink"] = route[0]["dev"]
    return validate_setup(c)


def app_file(path, data):
    atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", 0o640)
    os.chown(path, 0, grp.getgrnam("ruvpn").gr_gid)


def ensure_secrets(role):
    path = ETC / "secrets.json"
    if path.exists():
        return read_json(path)
    s = {}
    if role == "ru":
        private, public = control.keypair()
        entry_private, entry_public = control.keypair()
        s.update(awg_private=private, awg_public=public, entry_reality_private=entry_private.rstrip("=").replace("+", "-").replace("/", "_"), entry_reality_public=entry_public.rstrip("=").replace("+", "-").replace("/", "_"), entry_short_id=secrets.token_hex(8), api_secret=security.token(), admin_slug=secrets.token_urlsafe(18), proxy_auth={"username": "controller", "password": secrets.token_hex(24)}, bot_token="")
        # 3.1 HP protects message types; no ranged H in RandomTrailers mode.
        s["awg_obfuscation"] = {"Jc": 5, "Jmin": 40, "Jmax": 100, "S1": 24, "S2": 24, "S3": 24, "S4": 24, "H1": "1", "H2": "2", "H3": "3", "H4": "4", "HeaderProtectionKey": base64.b64encode(secrets.token_bytes(32)).decode(), "ContentPaddingAddition": "16-64", "RandomTrailers": "on"}
        if not (ETC / "vault.key").exists():
            atomic(ETC / "vault.key", Fernet.generate_key(), 0o640)
            os.chown(ETC / "vault.key", 0, grp.getgrnam("ruvpn").gr_gid)
    else:
        private, public = control.keypair()
        s.update(hop_reality_private=private.rstrip("=").replace("+", "-").replace("/", "_"), hop_reality_public=public.rstrip("=").replace("+", "-").replace("/", "_"), hop_short_id=secrets.token_hex(8), hop_uuid=str(uuid.uuid4()), hop_password=security.token(), obfs_password=security.token())
    write_json(path, s)
    return s


def certificate(c):
    if (ETC / "hop.crt").exists() and (ETC / "hop.key").exists():
        return
    key = ec.generate_private_key(ec.SECP256R1())
    name = c["foreign"]["tls_server_name"]
    now = dt.datetime.now(dt.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    crt = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365)).add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256()))
    helper.net_file(ETC / "hop.crt", crt.public_bytes(serialization.Encoding.PEM))
    helper.net_file(ETC / "hop.key", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def publish(c, s):
    a, v = c["awg"], c["vless"]
    p = {"endpoint": topology.entry_ip(c), "topology": topology.public_info(c), "url": f"https://{c['panel']['domain']}:{c['panel']['port']}", "admin_slug": s["admin_slug"], "bot_username": c["telegram"]["username"].lstrip("@"), "limits": c["limits"], "awg": {**a, "gateway": str(ipaddress.ip_network(a["subnet"])[1]), "public_key": s["awg_public"], "obfuscation": s["awg_obfuscation"]}, "vless": {**v, "public_key": s["entry_reality_public"], "short_id": s["entry_short_id"]}}
    app_file(ETC / "public.json", p)
    app_file(ETC / "control.json", {"paths": c["paths"], "telegram": c["telegram"], "topology": topology.public_info(c), "bot_token": s.get("bot_token", ""), "proxy_auth": s["proxy_auth"]})


def create_owner(c):
    db.initialize()
    with db.transaction() as conn:
        conn.execute("INSERT INTO gateways(id,label,endpoint) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,endpoint=excluded.endpoint", (topology.remote_region(c), topology.remote_ip(c)))
        for tag, kind in [("primary", "vless-reality"), ("backup", "hysteria2")]:
            conn.execute("INSERT INTO transports(id,gateway_id,kind,enabled) VALUES(?,1,?,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled", (tag, kind, int(c["paths"].get(tag + "_enabled", True))))
    if db.one("SELECT id FROM users WHERE admin=1"):
        return
    login = c["panel"]["admin_login"].lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", login):
        raise ValueError("Недопустимый admin_login")
    password = security.token()
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(login,password,admin,device_limit,created) VALUES(?,?,1,?,?)", (login, security.password_hash(password), c["limits"]["default_device_limit"], int(time.time())))
    atomic(Path("/root/ruvpn-owner.txt"), "Логин: " + login + "\nПароль: " + password + "\nПосле входа замените пароль в разделе учётной записи.\n")
    account = pwd.getpwnam("ruvpn")
    os.chown(STATE, account.pw_uid, account.pw_gid)
    for path in STATE.iterdir():
        if path.is_file():
            os.chown(path, account.pw_uid, account.pw_gid)
            path.chmod(0o600)


def caddy_config(c):
    host, port = c["panel"]["domain"], c["panel"]["port"]
    email = c["panel"]["email"]
    if not re.fullmatch(r"[a-zA-Z0-9_.+@-]+", email):
        raise ValueError("Некорректный email ACME")
    # Only HTTP-01: TCP/443 belongs to the VLESS inbound.
    body = f"""{{
    admin off
    auto_https disable_redirects
    email {email}
    http_port 80
    https_port {port}
}}
https://{host}:{port} {{
    tls {{
        issuer acme {{
            disable_tlsalpn_challenge
        }}
    }}
    request_body {{
        max_size 64KB
    }}
    reverse_proxy 127.0.0.1:8088
}}
"""
    atomic(ETC / "Caddyfile", body, 0o644)
    run([BIN / "caddy", "validate", "--config", ETC / "Caddyfile", "--adapter", "caddyfile"])


def validate_pair(p, c):
    expected = {"schema", "ipv4", "reality_port", "hysteria_port", "server_name", "tls_server_name", "uuid", "public_key", "short_id", "password", "obfs_password", "certificate"}
    if isinstance(p, dict) and p.get("schema") == 2:
        expected |= {"entry_location", "entry_ipv4"}
    if not isinstance(p, dict) or set(p) != expected or p["schema"] not in {1, 2}:
        raise ValueError("Неизвестная схема пакета сопряжения")
    if p["schema"] == 1 and topology.entry_region(c) != "ru":
        raise ValueError("Для зарубежного входа нужен новый пакет RU-выхода со схемой 2")
    if p["schema"] == 2 and (p["entry_location"] != topology.entry_region(c) or p["entry_ipv4"] != topology.entry_ip(c)):
        raise ValueError("Пакет выпущен для другой точки входа")
    if p["ipv4"] != topology.remote_ip(c) or p["ipv4"] == topology.entry_ip(c):
        raise ValueError("IP пакета не совпадает с отдельным межсерверным выходом в setup")
    ipaddress.IPv4Address(p["ipv4"])
    for k in ["reality_port", "hysteria_port"]:
        if not isinstance(p[k], int) or not 1 <= p[k] <= 65535:
            raise ValueError("Некорректный порт в пакете")
    from .config import domain
    domain(p["server_name"])
    domain(p["tls_server_name"])
    uuid.UUID(p["uuid"])
    if not re.fullmatch(r"[a-zA-Z0-9_-]{43}", p["public_key"]) or not re.fullmatch(r"[a-f0-9]{16}", p["short_id"]):
        raise ValueError("Некорректные параметры REALITY")
    if any(not isinstance(p[k], str) or not 20 <= len(p[k]) <= 256 for k in ["password", "obfs_password"]):
        raise ValueError("Некорректный секрет транспорта")
    crt = x509.load_pem_x509_certificate(p["certificate"].encode())
    names = crt.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    if p["tls_server_name"] not in names or crt.not_valid_after_utc <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("Сертификат Hysteria2 истёк или имеет другое имя")
    return p


def read_pair(path, c):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 65536:
        raise ValueError("Пакет сопряжения слишком большой")
    password = getpass.getpass("Пароль пакета сопряжения: ")
    return path, validate_pair(json.loads(crypto.decrypt(path.read_bytes(), password)), c)


def pair_import(path, c):
    path, p = read_pair(path, c)
    write_json(ETC / "paired.json", p)
    return path


def export_pair(c, output):
    s = read_json(ETC / "secrets.json")
    f = c["foreign"]
    p = {"schema": 1, "ipv4": topology.remote_ip(c), "reality_port": f["reality_port"], "hysteria_port": f["hysteria_port"], "server_name": f["server_name"], "tls_server_name": f["tls_server_name"], "uuid": s["hop_uuid"], "public_key": s["hop_reality_public"], "short_id": s["hop_short_id"], "password": s["hop_password"], "obfs_password": s["obfs_password"], "certificate": (ETC / "hop.crt").read_text()}
    if topology.entry_region(c) == "foreign":
        p.update(schema=2, entry_location="foreign", entry_ipv4=topology.entry_ip(c))
    password = getpass.getpass("Новый пароль пакета (16+ символов): ")
    if password != getpass.getpass("Повторите пароль пакета: "):
        raise ValueError("Пароли не совпадают")
    atomic(Path(output), crypto.encrypt(json.dumps(p).encode(), password))
    print("Зашифрованный пакет: " + str(output))


def install(role, setup_path, pair_path=None):
    ETC.mkdir(parents=True, exist_ok=True, mode=0o755)
    ETC.chmod(0o755)
    c = load_setup(setup_path)
    if (ETC / "role").exists() and (ETC / "role").read_text().strip() != role:
        raise ValueError("На этом хосте уже установлена другая роль")
    if (ETC / "setup.json").exists() and topology.entry_region(setup()) != topology.entry_region(c):
        raise ValueError("Смена страны входа требует отдельного развёртывания входа и relay; существующая сеть не изменена")
    network.preflight(c, role)
    s = ensure_secrets(role)
    imported = None
    imported_data = None
    if role == "ru":
        if pair_path:
            imported, imported_data = read_pair(pair_path, c)
        if not imported_data and not (ETC / "paired.json").exists():
            raise ValueError("Сначала нужен зашифрованный пакет межсерверного выхода: --pair /root/ruvpn-pair.ruvpn")
        validate_pair(imported_data or read_json(ETC / "paired.json"), c)
        lists.initialize()
    else:
        certificate(c)
    network.stage(c, role)
    try:
        if imported_data:
            write_json(ETC / "paired.json", imported_data)
        write_json(ETC / "setup.json", c)
        atomic(ETC / "role", role + "\n", 0o644)
        atomic(ETC / "guard.nft", network.render(c, role))
        if role == "ru":
            publish(c, s)
            create_owner(c)
            caddy_config(c)
            # DNS binds to AWG's gateway; start it only after its interface exists.
            if not (ETC / "awg.conf").exists():
                atomic(ETC / "awg.conf", compiler.awg_config(c, s, {"devices": [], "rules": []}))
        else:
            helper.net_file(ETC / "sing-box.json", json.dumps(compiler.foreign_config(c, s), indent=2))
            run([BIN / "sing-box", "check", "-c", ETC / "sing-box.json"])
        network.start(c, role)
        service("ruvpn-netguard", "enable")
        service("ruvpn-sing", "enable")
        if role == "ru":
            for name in ["ruvpn-awg", "ruvpn-helper", "ruvpn-caddy", "ruvpn-panel"]:
                service(name, "enable")
            service("ruvpn-awg", "restart")
            service("ruvpn-helper", "restart")
            with control.serialized():
                control.apply_locked()
            service("ruvpn-caddy", "restart")
            for path in STATE.glob("*"):
                if path.is_file():
                    os.chown(path, pwd.getpwnam("ruvpn").pw_uid, grp.getgrnam("ruvpn").gr_gid)
                    path.chmod(0o600)
            service("ruvpn-panel", "restart")
            run(["systemctl", "enable", "--now", "ruvpn-lists.timer"])
            if imported:
                imported.unlink()
            print(f"Панель: https://{c['panel']['domain']}:{c['panel']['port']}")
            print("Первый пароль, если создан: /root/ruvpn-owner.txt")
        else:
            service("ruvpn-sing", "restart")
        print(f"Сеть ожидает подтверждения {c['network']['rollback_seconds']} секунд.")
        print("Сохраните SSH-доступ и выполните: /opt/ruvpn/current/scripts/configure.sh --confirm-network")
    except BaseException:
        network.rollback()
        raise


def wait_tun():
    if (ETC / "role").read_text().strip() != "ru":
        return
    for _ in range(80):
        if run(["ip", "link", "show", "dev", "ruvpn-tun"], check=False).returncode == 0:
            network.route(setup())
            return
        time.sleep(0.1)
    raise ValueError("Ядро не создало TUN; запуск не подтверждён")


def show_status():
    role = (ETC / "role").read_text().strip()
    c = setup()
    location = topology.entry_region(c) if role == "ru" else topology.remote_region(c)
    print("CHIMERA · " + ("вход" if role == "ru" else "межсерверный выход") + " · " + ("Россия" if location == "ru" else "зарубежный"))
    names = ["ruvpn-netguard", "ruvpn-sing"] + (["ruvpn-awg", "ruvpn-helper", "ruvpn-panel", "ruvpn-caddy"] if role == "ru" else [])
    for name in names:
        print(name + ": " + (service(name, "is-active").stdout.strip() or "inactive"))
    if network.TX.exists():
        print("ВНИМАНИЕ: ожидается подтверждение сети; действует таймер автоматического отката")
    if role == "ru":
        raw = db.setting("monitor")
        if raw:
            p = json.loads(raw)
            age = max(0, int(time.time()) - p["checked_at"])
            print(f"Путь: {p['active']}; режим: {p['mode']}; обновлено {age} сек. назад")
            for name in ["primary", "backup"]:
                print(name + ": " + p[name]["state"])
            if age > 120:
                print("Статус устарел; доступность межсерверного выхода сейчас не подтверждена")
        else:
            print("Пути: unknown; успешных эксплуатационных запросов ещё нет")
        latest = db.one("SELECT id,state FROM applied_revisions ORDER BY id DESC LIMIT 1")
        print("Последняя ревизия: " + json.dumps(latest, ensure_ascii=False))
        print("AWG forwarding разрешён только в TUN; общего MASQUERADE нет")
    cert_path = ETC / ("hop.crt" if role == "foreign" else "paired.json")
    if cert_path.exists():
        text = cert_path.read_text() if role == "foreign" else read_json(cert_path)["certificate"]
        cert = x509.load_pem_x509_certificate(text.encode())
        print("Hysteria TLS до: " + cert.not_valid_after_utc.isoformat())


def main():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise SystemExit("Запустите от root")
    parser = argparse.ArgumentParser(description="CHIMERA operations")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install")
    p.add_argument("role", choices=["ru", "foreign"])
    p.add_argument("--setup", required=True)
    p.add_argument("--pair")
    p = sub.add_parser("configure")
    p.add_argument("--setup", default=str(ETC / "setup.json"))
    p = sub.add_parser("pair")
    p.add_argument("file")
    p = sub.add_parser("export-pair")
    p.add_argument("--output", default="/root/ruvpn-pair.ruvpn")
    p = sub.add_parser("rotate-pair")
    p.add_argument("--output", default="/root/ruvpn-pair.ruvpn")
    for name in ["network-start", "network-confirm", "network-rollback", "awg-setup", "wait-tun", "status", "lists-update", "set-bot"]:
        sub.add_parser(name)
    p = sub.add_parser("backup")
    p.add_argument("output")
    p = sub.add_parser("restore")
    p.add_argument("file")
    args = parser.parse_args()
    command = args.command
    if command == "install":
        install(args.role, args.setup, args.pair)
    elif command == "configure":
        install((ETC / "role").read_text().strip(), args.setup)
    elif command == "network-start":
        if network.TX.exists():
            transaction = read_json(network.TX)
            boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            if transaction.get("boot_id") != boot_id:
                # Transient rollback timers do not survive a reboot. Restore
                # the old network and keep VPN units stopped; starting units
                # from inside their own netguard dependency would deadlock.
                network.rollback(restart=False)
                raise ValueError("После перезагрузки возвращена предыдущая сеть. Повторите configure.sh с вашим setup; VPN до этого закрыт")
        network.start(setup(), (ETC / "role").read_text().strip())
    elif command == "network-confirm":
        network.confirm()
        print("Сеть подтверждена. Автоматический откат отменён.")
    elif command == "network-rollback":
        network.rollback()
    elif command == "awg-setup":
        network.awg_setup(setup())
    elif command == "wait-tun":
        wait_tun()
    elif command == "status":
        show_status()
    elif command == "pair":
        old = (ETC / "paired.json").read_bytes() if (ETC / "paired.json").exists() else None
        source = pair_import(args.file, setup())
        try:
            with control.serialized():
                control.apply_locked()
        except BaseException:
            if old:
                atomic(ETC / "paired.json", old)
            raise
        source.unlink()
        print("Межсерверный выход импортирован, конфигурация применена, пакет удалён.")
    elif command == "export-pair":
        if (ETC / "role").read_text().strip() != "foreign":
            raise ValueError("Экспорт выполняется только на межсерверном выходе (relay)")
        export_pair(setup(), args.output)
    elif command == "rotate-pair":
        if (ETC / "role").read_text().strip() != "foreign":
            raise ValueError("Ротация выполняется только на межсерверном выходе (relay)")
        # Explicit owner action, separate from idempotent installation.
        (ETC / "secrets.json").unlink()
        (ETC / "hop.crt").unlink(missing_ok=True)
        (ETC / "hop.key").unlink(missing_ok=True)
        s = ensure_secrets("foreign")
        certificate(setup())
        helper.net_file(ETC / "sing-box.json", json.dumps(compiler.foreign_config(setup(), s), indent=2))
        service("ruvpn-sing", "restart")
        export_pair(setup(), args.output)
        print("Прежние межсерверные секреты отозваны. Импортируйте новый пакет на входной узел.")
    elif command == "lists-update":
        with control.serialized():
            rpc.call("lists-update")
            control.apply_locked()
    elif command == "set-bot":
        c = setup()
        if (ETC / "role").read_text().strip() != "ru":
            raise ValueError("Бот устанавливается только на входном узле, где размещена панель")
        value = getpass.getpass("Токен Telegram-бота (пусто — отключить): ")
        if value and not re.fullmatch(r"[0-9]+:[a-zA-Z0-9_-]{25,}", value):
            raise ValueError("Некорректный токен")
        username = input("Username бота без @ (пусто — отключить): ").strip().lstrip("@")
        if username and not re.fullmatch(r"[a-zA-Z0-9_]{5,32}", username):
            raise ValueError("Некорректный username")
        s = read_json(ETC / "secrets.json")
        s["bot_token"] = value
        write_json(ETC / "secrets.json", s)
        c["telegram"]["enabled"], c["telegram"]["username"] = bool(value and username), username
        write_json(ETC / "setup.json", c)
        publish(c, s)
        service("ruvpn-panel", "restart")
        print("Настройки бота сохранены.")
    elif command in {"backup", "restore"}:
        from .backup import backup, restore
        backup(args.output) if command == "backup" else restore(args.file)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
