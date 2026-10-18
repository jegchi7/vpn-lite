from __future__ import annotations

import fcntl
import grp
import hashlib
import json
import logging
import os
import pwd
import socket
import struct
import time
import urllib.request
from pathlib import Path
from . import compiler, lists, network
from .config import ETC, SOCKET, atomic, read_json, setup, write_json
from .system import BIN, run, service

log = logging.getLogger("ruvpn.helper")


def net_file(path, contents):
    atomic(path, contents, 0o640)
    os.chown(path, 0, grp.getgrnam("ruvpn-net").gr_gid)


def apply_configuration(snapshot, revision):
    c = setup()
    s, paired = read_json(ETC / "secrets.json"), read_json(ETC / "paired.json")
    compiler.validate_snapshot(snapshot, c)
    sb = compiler.ru_config(c, s, paired, snapshot, lists.current())
    sb_text = json.dumps(sb, ensure_ascii=False, indent=2) + "\n"
    awg_text = compiler.awg_config(c, s, snapshot)
    candidate = ETC / "candidate.json"
    write_json(candidate, sb)
    try:
        run([BIN / "sing-box", "check", "-c", candidate])
    except BaseException:
        lists.abort()
        raise ValueError("Ядро отклонило конфигурацию. Сохранена предыдущая ревизия; профиль не выдан")
    finally:
        candidate.unlink(missing_ok=True)
    active_sb, active_awg = ETC / "sing-box.json", ETC / "awg.conf"
    old_sb = active_sb.read_bytes() if active_sb.exists() else None
    old_awg = active_awg.read_bytes() if active_awg.exists() else None
    try:
        net_file(active_sb, sb_text)
        atomic(active_awg, awg_text)
        if service("ruvpn-awg", "is-active").returncode:
            service("ruvpn-awg", "start")
        run([BIN / "awg", "syncconf", "awg0", active_awg])
        service("ruvpn-sing", "restart")
        network.route(c)
    except BaseException as exc:
        lists.abort()
        try:
            if old_sb is not None and old_awg is not None:
                net_file(active_sb, old_sb)
                atomic(active_awg, old_awg)
                run([BIN / "awg", "syncconf", "awg0", active_awg])
                service("ruvpn-sing", "restart")
                network.route(c)
            else:
                service("ruvpn-awg", "stop")
                service("ruvpn-sing", "stop")
        except BaseException:
            service("ruvpn-awg", "stop")
            service("ruvpn-sing", "stop")
            raise ValueError("Применение и откат не завершены. VPN остановлен с закрытым forwarding; SSH не изменён") from exc
        raise ValueError("Применение не завершено. Восстановлена предыдущая конфигурация; новое состояние не подтверждено") from exc
    checksum = hashlib.sha256(sb_text.encode() + awg_text.encode()).hexdigest()
    applied = {"revision": revision, "digest": checksum, "snapshot": snapshot, "applied_at": int(time.time()), "lists_version": read_json(lists.current() / "sources.json")["version"]}
    if (ETC / "applied.json").exists():
        atomic(ETC / "previous-applied.json", (ETC / "applied.json").read_bytes())
    write_json(ETC / "applied.json", applied)
    revisions = ETC / "revisions"
    revisions.mkdir(exist_ok=True, mode=0o700)
    write_json(revisions / f"{time.time_ns()}.json", applied)
    for path in sorted(revisions.glob("*.json"))[:-10]:
        path.unlink()
    lists.commit()
    return {"digest": checksum, "revision": revision}


def select(path):
    if path not in {"primary", "backup", "closed"}:
        raise ValueError("Неизвестный путь")
    if path != "closed" and not setup()["paths"].get(path + "_enabled", True):
        raise ValueError("Путь отключён в setup")
    secret = read_json(ETC / "secrets.json")["api_secret"]
    request = urllib.request.Request("http://127.0.0.1:19090/proxies/foreign", data=json.dumps({"name": path}).encode(), method="PUT", headers={"Content-Type": "application/json", "Authorization": "Bearer " + secret})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 204:
                raise ValueError("Ядро не подтвердило выбор пути")
    except OSError as e:
        raise ValueError("Ядро недоступно для переключения пути") from e
    return {"path": path}


def status():
    result = {"components": {name: service(name, "is-active").stdout.strip() or "inactive" for name in ["ruvpn-sing", "ruvpn-awg", "ruvpn-helper", "ruvpn-caddy", "ruvpn-panel"]}}
    applied = read_json(ETC / "applied.json") if (ETC / "applied.json").exists() else {}
    result["revision"] = applied.get("revision")
    result["lists_version"] = applied.get("lists_version", "unknown")
    return result


def dispatch(request):
    operation = request.get("op")
    if operation == "apply":
        revision = request.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("Некорректная ревизия")
        return apply_configuration(request.get("snapshot"), revision)
    if operation == "select":
        return select(request.get("path"))
    if operation == "status":
        return status()
    if operation == "explain":
        value = request.get("value")
        if not isinstance(value, str) or len(value) > 253:
            raise ValueError("Укажите домен или IP")
        snapshot = read_json(ETC / "applied.json")["snapshot"]
        return lists.explain(setup(), snapshot, value)
    if operation in {"lists-update", "lists-rollback"}:
        version = lists.update(setup()) if operation == "lists-update" else lists.rollback()
        return {"version": version}
    raise ValueError("Операция не разрешена")


def main():
    if os.geteuid() != 0:
        raise SystemExit("helper требует root")
    os.umask(0o077)
    Path(SOCKET).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.unlink(SOCKET)
    except FileNotFoundError:
        pass
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(SOCKET)
        os.chmod(SOCKET, 0o660)
        os.chown(SOCKET, 0, grp.getgrnam("ruvpn").gr_gid)
        server.listen(16)
        allowed = {0, pwd.getpwnam("ruvpn").pw_uid}
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    connection.settimeout(5)
                    _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                    if uid not in allowed:
                        continue
                    data = bytearray()
                    while b"\n" not in data:
                        part = connection.recv(65536)
                        if not part:
                            raise ValueError("Неполный запрос")
                        data.extend(part)
                        if len(data) > 1_000_000:
                            raise ValueError("Слишком большой запрос")
                    request = json.loads(data)
                    if not isinstance(request, dict):
                        raise ValueError("Некорректный запрос")
                    with (Path(SOCKET).parent / "apply.lock").open("a") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX)
                        result = dispatch(request)
                    response = {"ok": True, "result": result}
                except ValueError as e:
                    response = {"ok": False, "error": str(e)}
                except Exception:
                    log.error("Операция helper не завершена; содержимое запроса скрыто")
                    response = {"ok": False, "error": "Внутренняя ошибка применения. Нужна диагностика службы helper"}
                try:
                    connection.sendall(json.dumps(response, ensure_ascii=False).encode() + b"\n")
                except OSError:
                    pass


if __name__ == "__main__":
    main()
