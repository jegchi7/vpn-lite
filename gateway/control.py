from __future__ import annotations

import base64
import contextlib
import fcntl
import ipaddress
import json
import re
import secrets
import time
import uuid
import os
import pwd
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from . import db, rpc, security
from .config import STATE, domain, public


@contextlib.contextmanager
def serialized():
    with (STATE / "control.lock").open("a") as f:
        if os.geteuid() == 0:
            user = pwd.getpwnam("ruvpn")
            os.fchown(f.fileno(), user.pw_uid, user.pw_gid)
            os.fchmod(f.fileno(), 0o600)
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def keypair():
    private = X25519PrivateKey.generate()
    encode = lambda k: base64.b64encode(k).decode()
    return (
        encode(private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())),
        encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
    )


def credentials():
    private, pub = keypair()
    return pub, {"private": private, "psk": base64.b64encode(secrets.token_bytes(32)).decode(), "uuid": str(uuid.uuid4())}


def require_user(user_id):
    user = db.one("SELECT * FROM users WHERE id=? AND blocked=0", (user_id,))
    if not user:
        raise ValueError("Учётная запись недоступна")
    return user


def require_admin(user_id):
    user = require_user(user_id)
    if not user["admin"]:
        raise ValueError("Нужны права администратора")
    return user


def device_for(user_id, device_id):
    require_user(user_id)
    row = db.one("SELECT * FROM devices WHERE id=? AND user_id=?", (device_id, user_id))
    if not row:
        raise ValueError("Устройство не найдено")
    return row


def snapshot():
    peers = []
    for d in db.rows("SELECT d.*,c.ciphertext FROM devices d JOIN credentials c ON c.device_id=d.id JOIN users u ON u.id=d.user_id WHERE d.desired=1 AND u.blocked=0 ORDER BY d.address"):
        cred = security.decrypt(d["ciphertext"])
        peers.append({"id": d["id"], "address": d["address"], "public_key": d["public_key"], "psk": cred["psk"], "uuid": cred["uuid"]})
    return {"devices": peers, "rules": db.rows("SELECT id,kind,value,action,priority FROM route_overrides ORDER BY priority,id")}


def apply_locked(actor=None):
    data = snapshot()
    with db.transaction() as c:
        revision = c.execute("INSERT INTO applied_revisions(state,created) VALUES('pending',?)", (int(time.time()),)).lastrowid
    try:
        result = rpc.call("apply", revision=revision, snapshot=data)
    except ValueError as e:
        with db.transaction() as c:
            c.execute("UPDATE applied_revisions SET state='failed',error=? WHERE id=?", (str(e), revision))
            c.execute("UPDATE devices SET state='failed' WHERE state='pending'")
            db.event(c, actor, "apply_failed", f"revision={revision}")
        raise
    with db.transaction() as c:
        c.execute("UPDATE applied_revisions SET state='applied',digest=? WHERE id=?", (result["digest"], revision))
        c.execute("UPDATE devices SET state='applied',revision=?", (revision,))
        db.event(c, actor, "applied", f"revision={revision}; existing VLESS sessions restarted")
    return revision


def reapply(actor):
    require_admin(actor)
    with serialized():
        return apply_locked(actor)


def create_device(user_id, name, request_key):
    name = name.strip()
    if not 1 <= len(name) <= 48 or any(ord(c) < 32 for c in name):
        raise ValueError("Имя устройства: от 1 до 48 символов")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{12,80}", request_key):
        raise ValueError("Обновите страницу и повторите действие")
    with serialized():
        user = require_user(user_id)
        found = db.one("SELECT * FROM devices WHERE user_id=? AND (request_key=? OR (name=? AND desired=1))", (user_id, request_key, name))
        if found:
            if found["state"] != "applied":
                apply_locked(user_id)
            return found["id"]
        limits = public()["limits"]
        with db.transaction() as c:
            count = c.execute("SELECT COUNT(*) FROM devices WHERE user_id=? AND desired=1", (user_id,)).fetchone()[0]
            total = c.execute("SELECT COUNT(*) FROM devices WHERE desired=1").fetchone()[0]
            if count >= user["device_limit"] or total >= limits["devices"]:
                raise ValueError("Достигнут лимит устройств")
            occupied = {r[0] for r in c.execute("SELECT address FROM devices")}
            max_address = ipaddress.ip_network(public()["awg"]["subnet"]).num_addresses - 2
            address = next((x for x in range(2, max_address + 1) if x not in occupied), None)
            if address is None:
                raise ValueError("В подсети больше нет свободных адресов")
            device_id = str(uuid.uuid4())
            pub, cred = credentials()
            c.execute("INSERT INTO devices(id,user_id,name,address,public_key,request_key,created) VALUES(?,?,?,?,?,?,?)", (device_id, user_id, name, address, pub, request_key, int(time.time())))
            c.execute("INSERT INTO credentials VALUES(?,?)", (device_id, security.encrypt(cred)))
            db.event(c, user_id, "device_created", device_id)
        apply_locked(user_id)
        return device_id


def revoke_device(user_id, device_id):
    device_for(user_id, device_id)
    with serialized():
        with db.transaction() as c:
            c.execute("UPDATE devices SET desired=0,state='pending' WHERE id=?", (device_id,))
            c.execute("DELETE FROM downloads WHERE device_id=?", (device_id,))
            db.event(c, user_id, "device_revoke", device_id)
        return apply_locked(user_id)


def rotate_device(user_id, device_id):
    device = device_for(user_id, device_id)
    if not device["desired"]:
        raise ValueError("Отозванное устройство нельзя ротировать")
    with serialized():
        pub, cred = credentials()
        with db.transaction() as c:
            c.execute("UPDATE devices SET public_key=?,state='pending' WHERE id=?", (pub, device_id))
            c.execute("UPDATE credentials SET ciphertext=? WHERE device_id=?", (security.encrypt(cred), device_id))
            c.execute("DELETE FROM downloads WHERE device_id=?", (device_id,))
            db.event(c, user_id, "device_rotate", device_id)
        return apply_locked(user_id)


def create_user(actor, login, limit):
    require_admin(actor)
    login = login.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", login):
        raise ValueError("Логин: 3–32 латинских символа, цифры, . _ -")
    limit = int(limit)
    if not 1 <= limit <= public()["limits"]["devices"]:
        raise ValueError("Недопустимый лимит устройств")
    with db.transaction() as c:
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= public()["limits"]["users"]:
            raise ValueError("Достигнут лимит пользователей")
        if c.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
            raise ValueError("Этот логин уже занят")
        user_id = c.execute("INSERT INTO users(login,device_limit,created) VALUES(?,?,?)", (login, limit, int(time.time()))).lastrowid
        db.event(c, actor, "user_created", str(user_id))
    return user_id, invite(actor, user_id, "join")


def invite(actor, user_id, kind):
    owner = require_user(actor)
    if user_id != actor and not owner["admin"]:
        raise ValueError("Нет доступа")
    target = require_user(user_id)
    if kind not in {"join", "telegram"}:
        raise ValueError("Неизвестный тип приглашения")
    if kind == "join" and target["password"]:
        raise ValueError("Пароль уже установлен; приглашение входа больше не выдаётся")
    if kind == "telegram" and target["telegram_id"]:
        raise ValueError("Telegram уже привязан; сначала отвяжите его в панели")
    value = security.token()
    with db.transaction() as c:
        c.execute("DELETE FROM invitations WHERE user_id=? AND kind=?", (user_id, kind))
        c.execute("INSERT INTO invitations VALUES(?,?,?,?,NULL)", (security.digest(value), user_id, kind, int(time.time()) + (86400 if kind == "join" else 3600)))
        db.event(c, actor, "invitation_created", f"user={user_id}; kind={kind}")
    return value


def consume_invitation(value, *, password=None, telegram_id=None):
    now = int(time.time())
    hashed = security.password_hash(password) if password is not None else None
    kind = "join" if hashed else "telegram"
    with db.transaction() as c:
        row = c.execute("SELECT i.*,u.blocked,u.password,u.telegram_id FROM invitations i JOIN users u ON u.id=i.user_id WHERE i.token_hash=? AND i.kind=? AND i.expires>? AND i.consumed IS NULL", (security.digest(value), kind, now)).fetchone()
        if not row or row["blocked"]:
            raise ValueError("Приглашение истекло или уже использовано")
        if hashed:
            if row["password"]:
                raise ValueError("Приглашение уже использовано")
            c.execute("UPDATE users SET password=? WHERE id=?", (hashed, row["user_id"]))
        else:
            if not isinstance(telegram_id, int) or telegram_id <= 0 or row["telegram_id"]:
                raise ValueError("Привязка недоступна")
            if c.execute("SELECT 1 FROM users WHERE telegram_id=?", (telegram_id,)).fetchone():
                raise ValueError("Этот Telegram уже привязан")
            c.execute("UPDATE users SET telegram_id=? WHERE id=?", (telegram_id, row["user_id"]))
        c.execute("UPDATE invitations SET consumed=? WHERE token_hash=?", (now, security.digest(value)))
        db.event(c, row["user_id"], "invitation_consumed", kind)
        return row["user_id"]


def block_user(actor, user_id, blocked):
    require_admin(actor)
    if actor == user_id:
        raise ValueError("Нельзя заблокировать собственную учётную запись")
    if not db.one("SELECT id FROM users WHERE id=?", (user_id,)):
        raise ValueError("Пользователь не найден")
    with serialized():
        with db.transaction() as c:
            c.execute("UPDATE users SET blocked=? WHERE id=?", (int(blocked), user_id))
            if blocked:
                for table in ("sessions", "downloads", "invitations"):
                    c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            c.execute("UPDATE devices SET state='pending' WHERE user_id=?", (user_id,))
            db.event(c, actor, "user_block" if blocked else "user_unblock", str(user_id))
        return apply_locked(actor)


def revoke_all(actor, user_id):
    require_admin(actor)
    with serialized():
        with db.transaction() as c:
            c.execute("UPDATE devices SET desired=0,state='pending' WHERE user_id=?", (user_id,))
            c.execute("DELETE FROM downloads WHERE user_id=?", (user_id,))
            db.event(c, actor, "revoke_all", str(user_id))
        return apply_locked(actor)


def unlink_telegram(user_id):
    require_user(user_id)
    with db.transaction() as c:
        c.execute("UPDATE users SET telegram_id=NULL WHERE id=?", (user_id,))
        c.execute("DELETE FROM invitations WHERE user_id=? AND kind='telegram'", (user_id,))
        db.event(c, user_id, "telegram_unlinked")


def change_password(user_id, old, new):
    user = require_user(user_id)
    if not security.verify_password(user["password"], old):
        raise ValueError("Текущий пароль не подошёл")
    hashed = security.password_hash(new)
    with db.transaction() as c:
        c.execute("UPDATE users SET password=? WHERE id=?", (hashed, user_id))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        db.event(c, user_id, "password_changed")


def add_rule(actor, kind, value, action, priority):
    require_admin(actor)
    if kind not in {"domain", "suffix", "cidr"} or action not in {"BLOCK", "FOREIGN", "RU_DIRECT"}:
        raise ValueError("Неизвестный тип правила или маршрут")
    value = str(ipaddress.ip_network(value.strip(), strict=False)) if kind == "cidr" else domain(value)
    priority = int(priority)
    if not -10000 <= priority <= 10000:
        raise ValueError("Приоритет: от -10000 до 10000")
    with serialized():
        with db.transaction() as c:
            c.execute("INSERT INTO route_overrides(kind,value,action,priority) VALUES(?,?,?,?)", (kind, value, action, priority))
            db.event(c, actor, "rule_added", f"{kind}; {action}")
        return apply_locked(actor)


def delete_rule(actor, rule_id):
    require_admin(actor)
    with serialized():
        with db.transaction() as c:
            c.execute("DELETE FROM route_overrides WHERE id=?", (rule_id,))
            db.event(c, actor, "rule_deleted", str(rule_id))
        return apply_locked(actor)


def set_mode(actor, mode):
    require_admin(actor)
    if mode not in {"auto", "primary", "backup"}:
        raise ValueError("Неизвестный режим")
    if mode != "auto":
        from .config import ETC, read_json
        if not read_json(ETC / "control.json")["paths"].get(mode + "_enabled", True):
            raise ValueError("Путь отключён в setup")
    with db.transaction() as c:
        db.set_setting(c, "path_mode", mode)
        db.event(c, actor, "path_mode", mode)


def download_link(user_id, device_id, protocol):
    device = device_for(user_id, device_id)
    if not device["desired"] or device["state"] != "applied":
        raise ValueError("Профиль ещё не применён или отозван")
    if protocol not in {"awg", "vless", "singbox"}:
        raise ValueError("Неизвестный протокол")
    value = security.token()
    now = int(time.time())
    with db.transaction() as c:
        c.execute("DELETE FROM downloads WHERE expires < ? OR consumed IS NOT NULL", (now,))
        c.execute("INSERT INTO downloads VALUES(?,?,?,?,?,NULL)", (security.digest(value), user_id, device_id, protocol, now + 300))
    return public()["url"] + "/d/" + value


def download_record(value, consume=False):
    now = int(time.time())
    with db.transaction() as c:
        row = c.execute("SELECT t.* FROM downloads t JOIN users u ON u.id=t.user_id JOIN devices d ON d.id=t.device_id WHERE t.token_hash=? AND t.expires>? AND t.consumed IS NULL AND u.blocked=0 AND d.desired=1 AND d.state='applied'", (security.digest(value), now)).fetchone()
        if not row:
            raise ValueError("Ссылка истекла, уже использована или устройство отозвано")
        if consume:
            c.execute("UPDATE downloads SET consumed=? WHERE token_hash=?", (now, security.digest(value)))
        return dict(row)
