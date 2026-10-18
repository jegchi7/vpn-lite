from __future__ import annotations

import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"RUVPN1\x00"


def encrypt(data: bytes, password: str):
    if len(password) < 16:
        raise ValueError("Пароль шифрования: минимум 16 символов")
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    key = Scrypt(salt=salt, length=32, n=2**16, r=8, p=1).derive(password.encode())
    return header + AESGCM(key).encrypt(nonce, data, header)


def decrypt(data: bytes, password: str):
    if not data.startswith(MAGIC) or len(data) < 51:
        raise ValueError("Неизвестный формат зашифрованного пакета")
    salt, nonce = data[7:23], data[23:35]
    key = Scrypt(salt=salt, length=32, n=2**16, r=8, p=1).derive(password.encode())
    try:
        return AESGCM(key).decrypt(nonce, data[35:], data[:35])
    except Exception as e:
        raise ValueError("Неверный пароль или повреждённый пакет") from e
