import json
import socket
import time
from .config import SOCKET


def call(operation, **arguments):
    s = None
    for _ in range(40):
        candidate = socket.socket(socket.AF_UNIX)
        try:
            candidate.settimeout(90)
            candidate.connect(SOCKET)
            s = candidate
            break
        except (FileNotFoundError, ConnectionRefusedError):
            candidate.close()
            time.sleep(0.05)
        except OSError as e:
            candidate.close()
            raise ValueError("Служба применения недоступна") from e
    if s is None:
        raise ValueError("Служба применения недоступна; изменение не применено")
    with s:
        s.settimeout(90)
        try:
            s.sendall(json.dumps({"op": operation, **arguments}).encode() + b"\n")
            result = bytearray()
            while b"\n" not in result:
                chunk = s.recv(65536)
                if not chunk:
                    raise ValueError("helper закрыл соединение")
                result.extend(chunk)
                if len(result) > 2_000_000:
                    raise ValueError("Слишком большой ответ helper")
        except (OSError, ValueError) as e:
            raise ValueError("Служба применения недоступна; изменение не применено") from e
    response = json.loads(result)
    if not response.get("ok"):
        raise ValueError(response.get("error", "Изменение не применено"))
    return response.get("result")
