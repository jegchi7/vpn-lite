from __future__ import annotations

import contextlib
import sqlite3
import time
import os
import pwd
from .config import DB_PATH, STATE

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, password TEXT,
 admin INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0,
 device_limit INTEGER NOT NULL DEFAULT 3, telegram_id INTEGER UNIQUE,
 created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, address INTEGER UNIQUE NOT NULL, public_key TEXT NOT NULL,
 desired INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'pending',
 request_key TEXT NOT NULL, revision INTEGER, created INTEGER NOT NULL,
 UNIQUE(user_id, request_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS device_active_name ON devices(user_id,name) WHERE desired=1;
CREATE TABLE IF NOT EXISTS credentials (
 device_id TEXT PRIMARY KEY REFERENCES devices(id), ciphertext TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invitations (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL, expires INTEGER NOT NULL, consumed INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 device_id TEXT NOT NULL REFERENCES devices(id), protocol TEXT NOT NULL,
 expires INTEGER NOT NULL, consumed INTEGER
);
CREATE TABLE IF NOT EXISTS route_overrides (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL,
 action TEXT NOT NULL, priority INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS applied_revisions (
 id INTEGER PRIMARY KEY, state TEXT NOT NULL, digest TEXT,
 created INTEGER NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS gateways (
 id INTEGER PRIMARY KEY, label TEXT NOT NULL, endpoint TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS transports (
 id TEXT PRIMARY KEY, gateway_id INTEGER NOT NULL REFERENCES gateways(id),
 kind TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, created INTEGER NOT NULL, actor INTEGER,
 kind TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS throttle (
 bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_samples (
 created INTEGER PRIMARY KEY, elapsed REAL NOT NULL, download REAL, upload REAL,
 connections INTEGER, cpu REAL, memory REAL,
 primary_ms REAL, backup_ms REAL
);
CREATE TABLE IF NOT EXISTS passkeys (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 label TEXT NOT NULL, credential BLOB NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0,
 created INTEGER NOT NULL, last_used INTEGER
);
CREATE TABLE IF NOT EXISTS auth_challenges (
 token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
 kind TEXT NOT NULL, state TEXT NOT NULL, expires INTEGER NOT NULL
);
"""


def root_ownership():
    if os.geteuid() != 0:
        return
    try:
        user = pwd.getpwnam("ruvpn")
    except KeyError:
        return
    for path in [DB_PATH, *[DB_PATH.with_name(DB_PATH.name + suffix) for suffix in ("-wal", "-shm")]]:
        if path.exists():
            os.chown(path, user.pw_uid, user.pw_gid)
            path.chmod(0o600)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as c:
        c.executescript(SCHEMA)
    DB_PATH.chmod(0o600)
    root_ownership()


@contextlib.contextmanager
def transaction():
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
        root_ownership()


def rows(query, values=()):
    with contextlib.closing(connect()) as c:
        try:
            return [dict(r) for r in c.execute(query, values)]
        finally:
            root_ownership()


def one(query, values=()):
    result = rows(query, values)
    return result[0] if result else None


def event(c, actor, kind, detail=""):
    # No credentials, URLs, DNS queries or destination history in this journal.
    c.execute("INSERT INTO events(created,actor,kind,detail) VALUES(?,?,?,?)", (int(time.time()), actor, kind, detail[:300]))
    c.execute("DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-2000 FROM events)")


def setting(key, fallback=None):
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else fallback


def set_setting(c, key, value):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
