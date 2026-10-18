from __future__ import annotations

import base64
import fcntl
import getpass
import json
import os
import pwd
import sqlite3
import tempfile
import time
from pathlib import Path, PurePosixPath
from . import control, crypto, network
from .config import DB_PATH, ETC, STATE, atomic, read_json
from .system import run


def backup(output):
    password = getpass.getpass("Пароль копии (16+ символов): ")
    if password != getpass.getpass("Повторите пароль: "):
        raise ValueError("Пароли не совпадают")
    output = Path(output).resolve()
    if output == DB_PATH or output.is_relative_to(ETC):
        raise ValueError("Копия должна находиться вне рабочих конфигураций")
    if output.exists():
        raise ValueError("Выберите новое имя копии; существующий файл не перезаписан")
    role = (ETC / "role").read_text().strip()
    payload = {"schema": 1, "role": role, "created": int(time.time()), "files": {}, "links": {}, "database": None}
    STATE.mkdir(parents=True, exist_ok=True)
    Path("/run/ruvpn").mkdir(parents=True, exist_ok=True, mode=0o755)
    with control.serialized(), Path("/run/ruvpn/apply.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in ETC.rglob("*"):
            relative = path.relative_to(ETC).as_posix()
            if path.is_symlink():
                target = path.resolve()
                if not target.is_relative_to(ETC):
                    raise ValueError("Обнаружена внешняя ссылка в конфигурации")
                payload["links"][relative] = target.relative_to(ETC).as_posix()
            elif path.is_file() and path.name != "network-transaction.json":
                payload["files"][relative] = base64.b64encode(path.read_bytes()).decode()
        if DB_PATH.exists():
            with tempfile.TemporaryDirectory(prefix="ruvpn-backup-") as tmp:
                copy = Path(tmp) / "db.sqlite3"
                with sqlite3.connect(DB_PATH) as source, sqlite3.connect(copy) as destination:
                    source.backup(destination)
                payload["database"] = base64.b64encode(copy.read_bytes()).decode()
    atomic(output, crypto.encrypt(json.dumps(payload).encode(), password))
    print("Зашифрованная копия: " + str(output))
    print("Пароль храните отдельно. Копия содержит пользовательские и межсерверные ключи.")


def safe_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Небезопасный путь в копии")
    return path


def restore(filename):
    if network.TX.exists():
        raise ValueError("Сначала подтвердите или откатите ожидающее изменение сети")
    source = Path(filename).resolve(strict=True)
    if source.stat().st_size > 100_000_000:
        raise ValueError("Копия превышает допустимый размер")
    data = json.loads(crypto.decrypt(source.read_bytes(), getpass.getpass("Пароль копии: ")))
    if data.get("schema") != 1 or data.get("role") not in {"ru", "foreign"}:
        raise ValueError("Неизвестная схема копии")
    role = (ETC / "role").read_text().strip()
    if data["role"] != role:
        raise ValueError("Роль копии не совпадает с установленной ролью")
    if "setup.json" not in data["files"] or "secrets.json" not in data["files"]:
        raise ValueError("В копии отсутствует конфигурация")
    from .config import validate_setup
    c = validate_setup(json.loads(base64.b64decode(data["files"]["setup.json"])))
    # Restore only onto the same network identity. Moving to another VPS needs
    # a new setup/pairing; importing a foreign NIC name could cut SSH access.
    current = read_json(ETC / "setup.json")
    if c["network"] != current["network"] or c["foreign"]["ipv4"] != current["foreign"]["ipv4"]:
        raise ValueError("Сеть копии отличается. Сначала установите эту роль с теми же адресами и uplink; перенос на другой VPS выполняйте с новым сопряжением")
    for name, target in data["links"].items():
        safe_relative(name)
        safe_relative(target)
    for name in data["files"]:
        safe_relative(name)
        if name in data["links"]:
            raise ValueError("Конфликт файлов в копии")
    network.stage(c, role, full_restore=True)
    services = ["ruvpn-panel", "ruvpn-helper", "ruvpn-awg", "ruvpn-sing", "ruvpn-caddy"] if role == "ru" else ["ruvpn-sing"]
    for service in services:
        run(["systemctl", "stop", service], check=False)
    with tempfile.TemporaryDirectory(prefix="ruvpn-restore-") as tmp:
        # Preserve a recovery copy of all pre-restore bytes until success.
        old = {p.relative_to(ETC).as_posix(): p.read_bytes() for p in ETC.rglob("*") if p.is_file() and not p.is_symlink()}
        old_db = DB_PATH.read_bytes() if DB_PATH.exists() else None
        try:
            for name in data["links"]:
                (ETC / name).unlink(missing_ok=True)
            for name, encoded in data["files"].items():
                target = ETC / name
                if not target.resolve().is_relative_to(ETC):
                    raise ValueError("Путь выходит за пределы конфигурации")
                atomic(target, base64.b64decode(encoded))
            for name, target in data["links"].items():
                path = ETC / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(ETC / target)
            if data["database"]:
                for suffix in ["-wal", "-shm"]:
                    Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
                atomic(DB_PATH, base64.b64decode(data["database"]))
            # Apply current desired credentials from the restored DB; profile
            # revision numbers alone do not make credentials active.
            repair_permissions(role)
            network.start(c, role)
            if role == "ru":
                from .ops import publish
                publish(c, read_json(ETC / "secrets.json"))
                for service in ["ruvpn-awg", "ruvpn-helper"]:
                    run(["systemctl", "start", service])
                with control.serialized():
                    control.apply_locked()
            for service in reversed(services):
                run(["systemctl", "start", service])
        except BaseException:
            for name, content in old.items():
                atomic(ETC / name, content)
            if old_db:
                atomic(DB_PATH, old_db)
            repair_permissions(role)
            network.rollback()
            raise
    print("Копия восстановлена. Повторно подтвердите сеть: scripts/configure.sh --confirm-network")
    print("Восстановленные учётные данные соответствуют дате копии; последующие отзывы нужно повторить.")


def repair_permissions(role):
    import grp
    ETC.chmod(0o755)
    for directory in (ETC / "lists").rglob("*") if (ETC / "lists").exists() else []:
        if directory.is_dir():
            directory.chmod(0o755)
        elif not directory.is_symlink() and directory.is_file():
            directory.chmod(0o644)
    if (ETC / "lists").exists():
        (ETC / "lists").chmod(0o755)
    for name in ["sing-box.json", "hop.crt", "hop.key"]:
        path = ETC / name
        if path.exists():
            path.chmod(0o640)
            os.chown(path, 0, grp.getgrnam("ruvpn-net").gr_gid)
    if role == "ru":
        for name in ["public.json", "control.json", "vault.key"]:
            path = ETC / name
            if path.exists():
                path.chmod(0o640)
                os.chown(path, 0, grp.getgrnam("ruvpn").gr_gid)
        account = pwd.getpwnam("ruvpn")
        os.chown(STATE, account.pw_uid, account.pw_gid)
        for path in STATE.iterdir():
            if path.is_file():
                path.chmod(0o600)
                os.chown(path, account.pw_uid, account.pw_gid)
    (ETC / "role").chmod(0o644)
    if (ETC / "Caddyfile").exists():
        (ETC / "Caddyfile").chmod(0o644)
