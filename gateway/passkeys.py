from __future__ import annotations

import json
import time
from urllib.parse import urlsplit
from fido2.server import Fido2Server
from fido2.utils import websafe_encode
from fido2.webauthn import (
    AttestedCredentialData, AuthenticationResponse, PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
)
from . import db, security
from .config import public


def server():
    origin = public()["url"].rstrip("/")
    instance = Fido2Server(
        PublicKeyCredentialRpEntity(id=urlsplit(origin).hostname, name="CHIMERA"),
        verify_origin=lambda candidate: candidate == origin,
    )
    instance.timeout = 60000
    return instance


def credentials(user_id):
    return [AttestedCredentialData(row["credential"]) for row in db.rows(
        "SELECT credential FROM passkeys WHERE user_id=?", (user_id,)
    )]


def begin(user=None):
    instance = server()
    if user:
        if len(credentials(user["id"])) >= 10:
            raise ValueError("Можно сохранить не более 10 ключей входа")
        options, state = instance.register_begin(
            PublicKeyCredentialUserEntity(
                id=user["id"].to_bytes(8, "big"), name=user["login"], display_name=user["login"],
            ),
            credentials=credentials(user["id"]), resident_key_requirement="required",
            user_verification="required",
        )
    else:
        options, state = instance.authenticate_begin(user_verification="required")
    value = security.token()
    with db.transaction() as c:
        c.execute("DELETE FROM auth_challenges WHERE expires<?", (int(time.time()),))
        c.execute("INSERT INTO auth_challenges VALUES(?,?,?,?,?)", (
            security.digest(value), user["id"] if user else None,
            "register" if user else "login", json.dumps(state), int(time.time()) + 300,
        ))
    return dict(options), value


def take_challenge(value, kind, user_id=None):
    with db.transaction() as c:
        row = c.execute("SELECT * FROM auth_challenges WHERE token_hash=? AND expires>? AND kind=?",
                        (security.digest(value), int(time.time()), kind)).fetchone()
        if not row or row["user_id"] != user_id:
            raise ValueError("Проверка входа истекла. Повторите действие")
        c.execute("DELETE FROM auth_challenges WHERE token_hash=?", (security.digest(value),))
    return json.loads(row["state"])


def finish_registration(value, user, response, label):
    state = take_challenge(value, "register", user["id"])
    try:
        auth = server().register_complete(state, response)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Не удалось подтвердить ключ входа") from exc
    credential = auth.credential_data
    if not credential:
        raise ValueError("Устройство не вернуло ключ входа")
    label = str(label).strip()[:64] or "Ключ входа"
    with db.transaction() as c:
        owner = c.execute("SELECT blocked,password FROM users WHERE id=?", (user["id"],)).fetchone()
        if not owner or owner["blocked"] or owner["password"] != user["password"]:
            raise ValueError("Доступ к учётной записи отозван")
        if c.execute("SELECT COUNT(*) FROM passkeys WHERE user_id=?", (user["id"],)).fetchone()[0] >= 10:
            raise ValueError("Можно сохранить не более 10 ключей входа")
        if c.execute("SELECT 1 FROM passkeys WHERE id=?", (websafe_encode(credential.credential_id),)).fetchone():
            raise ValueError("Этот ключ уже добавлен")
        c.execute("INSERT INTO passkeys(id,user_id,label,credential,sign_count,created) VALUES(?,?,?,?,?,?)", (
            websafe_encode(credential.credential_id), user["id"], label, bytes(credential), auth.counter, int(time.time()),
        ))
        db.event(c, user["id"], "passkey_added")


def finish_login(value, response):
    state = take_challenge(value, "login")
    try:
        authentication = AuthenticationResponse.from_dict(response)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Не удалось прочитать ответ ключа входа") from exc
    credential_id = websafe_encode(authentication.raw_id)
    row = db.one("SELECT p.*,u.blocked,u.password FROM passkeys p JOIN users u ON u.id=p.user_id WHERE p.id=?", (credential_id,))
    if not row or row["blocked"] or not row["password"]:
        raise ValueError("Ключ не найден или доступ отозван")
    handle = authentication.response.user_handle
    if handle is not None and handle != row["user_id"].to_bytes(8, "big"):
        raise ValueError("Ключ не соответствует учётной записи")
    try:
        server().authenticate_complete(state, [AttestedCredentialData(row["credential"])], authentication)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("Подпись ключа входа не подтверждена") from exc
    counter = authentication.response.authenticator_data.counter
    with db.transaction() as c:
        current = c.execute("SELECT p.sign_count,u.blocked FROM passkeys p JOIN users u ON u.id=p.user_id WHERE p.id=?", (credential_id,)).fetchone()
        if not current or current["blocked"] or (counter and current["sign_count"] and counter <= current["sign_count"]):
            raise ValueError("Ключ входа отклонил повторное подтверждение")
        c.execute("UPDATE passkeys SET sign_count=?,last_used=? WHERE id=?", (counter, int(time.time()), credential_id))
        db.event(c, row["user_id"], "passkey_login")
    return row["user_id"], row["password"]


def remove(user_id, credential_id):
    with db.transaction() as c:
        result = c.execute("DELETE FROM passkeys WHERE user_id=? AND id=?", (user_id, credential_id))
        if result.rowcount:
            db.event(c, user_id, "passkey_removed")
