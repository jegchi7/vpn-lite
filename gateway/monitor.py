from __future__ import annotations

import asyncio
import json
import logging
import time
import httpx
from . import db, rpc
from .config import ETC, read_json

log = logging.getLogger("ruvpn.monitor")


class PathState:
    def __init__(self):
        self.state = "unknown"
        self.failures = 0
        self.successes = 0
        self.targets = [{"state": "unknown", "failures": 0}, {"state": "unknown", "failures": 0}]

    def observe(self, results, threshold):
        for target, success in zip(self.targets, results):
            target["state"] = "available" if success else "unavailable"
            target["failures"] = 0 if success else target["failures"] + 1
        if any(results):
            self.successes += 1
            self.failures = 0
            self.state = "available"
        else:
            self.successes = 0
            self.failures += 1
            if self.failures >= threshold:
                self.state = "unavailable"

    def export(self):
        return {"state": self.state, "successes": self.successes, "failures": self.failures, "destinations": self.targets}


async def request_through(proxy, url):
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=8, follow_redirects=False, trust_env=False) as client:
            response = await client.get(url, headers={"User-Agent": "ruvpn-path-monitor/1.0"})
            return response.status_code == 204
    except (httpx.HTTPError, OSError, ValueError):
        return False


async def run():
    config = read_json(ETC / "control.json")
    paths = config["paths"]
    states = {"primary": PathState(), "backup": PathState()}
    active = "primary" if paths.get("primary_enabled", True) else "backup"
    for name, state in states.items():
        if not paths.get(name + "_enabled", True):
            state.state = "disabled"
    last_switch = 0.0
    down_since = None
    down_notified = False
    while True:
        try:
            credentials = config["proxy_auth"]
            proxies = {name: f"http://{credentials['username']}:{credentials['password']}@127.0.0.1:{port}" for name, port in [("primary", 10081), ("backup", 10082)]}
            checks = await asyncio.gather(*(request_through(proxies[name], url) if paths.get(name + "_enabled", True) else asyncio.sleep(0, result=False) for name in states for url in paths["urls"]))
            for n, state in enumerate(states.values()):
                if state.state != "disabled":
                    state.observe(checks[n * 2:n * 2 + 2], paths["failures"])
            mode = db.setting("path_mode", paths["mode"])
            now = time.monotonic()
            desired = active
            if mode in {"primary", "backup"}:
                desired = mode if states[mode].state != "disabled" else "closed"
            elif all(s.state in {"unavailable", "disabled"} for s in states.values()):
                desired = "closed"
            elif states["primary"].state == "disabled":
                desired = "backup"
            elif states["backup"].state == "disabled":
                desired = "primary"
            elif active == "closed":
                if now - last_switch < paths["hold_seconds"]:
                    desired = "closed"
                elif states["primary"].state == "available":
                    desired = "primary"
                elif states["backup"].state == "available":
                    desired = "backup"
            elif now - last_switch >= paths["hold_seconds"]:
                if active == "primary" and states["primary"].state == "unavailable" and states["backup"].state == "available":
                    desired = "backup"
                elif active == "backup" and states["primary"].state == "available" and (states["primary"].successes >= paths["recovery_successes"] or states["backup"].state == "unavailable"):
                    desired = "primary"
            # Assert selection on every iteration: a data-plane restart resets it.
            await asyncio.to_thread(rpc.call, "select", path=desired)
            if desired != active:
                with db.transaction() as c:
                    db.event(c, None, "path_changed", f"{active} -> {desired}; mode={mode}")
                active, last_switch = desired, now
            unavailable = all(s.state in {"unavailable", "disabled"} for s in states.values())
            if unavailable:
                down_since = down_since or now
                if not down_notified and now - down_since >= config["telegram"]["notify_after"]:
                    with db.transaction() as c:
                        db.event(c, None, "foreign_down", "Оба защищённых пути недоступны")
                    down_notified = True
            else:
                if down_notified:
                    with db.transaction() as c:
                        db.event(c, None, "foreign_recovered", "Защищённый путь снова доступен")
                down_since, down_notified = None, False
            status = {"checked_at": int(time.time()), "active": active, "mode": mode, **{name: state.export() for name, state in states.items()}}
            with db.transaction() as c:
                db.set_setting(c, "monitor", json.dumps(status, ensure_ascii=False, indent=2))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not log request objects or proxy credentials.
            log.warning("Контроль транспорта временно недоступен")
        await asyncio.sleep(paths["interval"])
