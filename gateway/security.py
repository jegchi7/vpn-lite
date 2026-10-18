from __future__ import annotations

import hashlib
import json
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from . import db
from .config import ETC

PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY = PH.hash(secrets.token_urlsafe(24))


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def token():
    return secrets.token_urlsafe(32)


def password_hash(value):
    if not 12 <= len(value) <= 256:
        raise ValueError("Пароль: от 12 до 256 символов")
    return PH.hash(value)


def verify_password(hashed, value):
    try:
        return PH.verify(hashed or DUMMY, value[:256])
    except (VerificationError, InvalidHashError):
        return False


def vault():
    return Fernet((ETC / "vault.key").read_bytes().strip())


def encrypt(value):
    return vault().encrypt(json.dumps(value).encode()).decode()


def decrypt(value):
    return json.loads(vault().decrypt(value.encode()))


def allow_attempt(bucket, limit=8, window=900):
    now = int(time.time())
    bucket = digest(bucket)
    with db.transaction() as c:
        row = c.execute("SELECT * FROM throttle WHERE bucket=?", (bucket,)).fetchone()
        if row and row["reset_at"] > now:
            if row["attempts"] >= limit:
                return False
            c.execute("UPDATE throttle SET attempts=attempts+1 WHERE bucket=?", (bucket,))
        else:
            c.execute("INSERT INTO throttle VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET attempts=1,reset_at=excluded.reset_at", (bucket, now + window))
        c.execute("DELETE FROM throttle WHERE reset_at < ?", (now,))
    return True


def new_session(user_id):
    value, csrf = token(), token()
    now = int(time.time())
    with db.transaction() as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(value), user_id, csrf, now + 43200))
    return value


def session(value):
    if not value or len(value) > 128:
        return None
    return db.one("SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.blocked=0", (digest(value), int(time.time())))


def csrf_ok(given, expected):
    return isinstance(given, str) and isinstance(expected, str) and len(given) >= 32 and len(expected) >= 32 and secrets.compare_digest(given, expected)
