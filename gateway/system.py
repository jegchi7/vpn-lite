from __future__ import annotations

import subprocess
from .config import ROOT

BIN = ROOT / "bin"


def run(argv, *, input=None, timeout=45, check=True):
    p = subprocess.run([str(v) for v in argv], input=input, text=True, capture_output=True, timeout=timeout, env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})
    if check and p.returncode:
        # Never propagate stderr: parsers can echo credential-bearing lines.
        raise ValueError(f"Команда {argv[0].name if hasattr(argv[0], 'name') else argv[0]} не выполнена (код {p.returncode})")
    return p


def service(name, action):
    if name not in {"ruvpn-sing", "ruvpn-awg", "ruvpn-panel", "ruvpn-helper", "ruvpn-caddy", "ruvpn-netguard"} or action not in {"start", "stop", "restart", "reload", "is-active", "enable"}:
        raise ValueError("Недопустимая служебная операция")
    return run(["systemctl", action, name], check=action != "is-active", timeout=60)
