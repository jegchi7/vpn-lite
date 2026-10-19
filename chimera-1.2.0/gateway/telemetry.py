from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from pathlib import Path
from . import db, rpc
from .config import ETC, read_json
from .system import BIN, run

INTERVAL = 10


def privileged_snapshot():
    """Fixed read-only RPC. Never return endpoints, destinations or key material."""
    snapshot = {"checked_at": int(time.time()), "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    cpu = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    snapshot["cpu_total"], snapshot["cpu_idle"] = sum(cpu), cpu[3] + cpu[4]
    memory = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
    snapshot["memory"] = round(100 * (1 - memory.get("MemAvailable", memory["MemFree"]) / memory["MemTotal"]), 1)
    snapshot["uptime"] = int(float(Path("/proc/uptime").read_text().split()[0]))
    applied = read_json(ETC / "applied.json") if (ETC / "applied.json").exists() else {}
    peers = {d["public_key"]: d["id"] for d in applied.get("snapshot", {}).get("devices", [])}
    devices = {}
    transfers = run([BIN / "awg", "show", "awg0", "transfer"], check=False, timeout=3)
    handshakes = run([BIN / "awg", "show", "awg0", "latest-handshakes"], check=False, timeout=3)
    seen = dict(line.split() for line in handshakes.stdout.splitlines() if len(line.split()) == 2)
    for line in transfers.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] in peers:
            devices[peers[parts[0]]] = {"upload_total": int(parts[1]), "download_total": int(parts[2]), "last_handshake": int(seen.get(parts[0], 0))}
    snapshot["devices"] = devices
    snapshot["awg_available"] = transfers.returncode == 0 and handshakes.returncode == 0
    snapshot["core_available"] = False
    try:
        request = urllib.request.Request("http://127.0.0.1:19090/connections", headers={"Authorization": "Bearer " + read_json(ETC / "secrets.json")["api_secret"]})
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read(8_000_000))
        counts = {"awg": 0, "vless": 0, "service": 0}
        for connection in data.get("connections") or []:
            kind = connection.get("metadata", {}).get("type", "")
            bucket = "awg" if kind == "tun/awg-in" else "vless" if kind == "vless/vless-in" else "service"
            counts[bucket] += 1
        snapshot.update(core_available=True, download_total=int(data["downloadTotal"]), upload_total=int(data["uploadTotal"]), connections=sum(counts.values()), protocols=counts)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return snapshot


def rate(current, previous, field, elapsed):
    a, b = current.get(field), previous.get(field)
    if a is None or b is None or current.get("boot") != previous.get("boot") or a < b or not 0 < elapsed <= 120:
        return None
    return round((a - b) / elapsed, 2)


async def run_collector():
    previous = {}
    last = 0.0
    while True:
        started = time.monotonic()
        try:
            sample = await asyncio.to_thread(rpc.call, "metrics")
            elapsed = started - last if last else 0
            sample["download"] = rate(sample, previous, "download_total", elapsed)
            sample["upload"] = rate(sample, previous, "upload_total", elapsed)
            total = sample["cpu_total"] - previous.get("cpu_total", sample["cpu_total"])
            idle = sample["cpu_idle"] - previous.get("cpu_idle", sample["cpu_idle"])
            sample["cpu"] = round(max(0, min(100, 100 * (1 - idle / total))), 1) if total > 0 and sample["boot"] == previous.get("boot") else None
            for device_id, device in sample["devices"].items():
                before = previous.get("devices", {}).get(device_id, {})
                device["download"] = rate({**device, "boot": sample["boot"]}, {**before, "boot": previous.get("boot")}, "download_total", elapsed)
                device["upload"] = rate({**device, "boot": sample["boot"]}, {**before, "boot": previous.get("boot")}, "upload_total", elapsed)
            monitor = json.loads(db.setting("monitor", "{}"))
            with db.transaction() as c:
                db.set_setting(c, "telemetry", json.dumps(sample))
                c.execute("INSERT OR REPLACE INTO metric_samples VALUES(?,?,?,?,?,?,?,?,?)", (sample["checked_at"], elapsed, sample["download"], sample["upload"], sample.get("connections"), sample["cpu"], sample["memory"], monitor.get("primary", {}).get("latency_ms"), monitor.get("backup", {}).get("latency_ms")))
                c.execute("DELETE FROM metric_samples WHERE created<?", (sample["checked_at"] - 30 * 86400,))
            previous, last = sample, started
        except asyncio.CancelledError:
            raise
        except Exception:
            # A previous snapshot becomes stale; a collection failure is not zero traffic.
            pass
        await asyncio.sleep(max(1, INTERVAL - (time.monotonic() - started)))


def current():
    sample = json.loads(db.setting("telemetry", "{}"))
    sample["stale"] = time.time() - sample.get("checked_at", 0) > 45
    return sample


def history(period="24h"):
    seconds, bucket = {"24h": (86400, 300), "7d": (7 * 86400, 3600), "30d": (30 * 86400, 14400)}.get(period, (86400, 300))
    since = int(time.time()) - seconds
    points = db.rows("SELECT CAST(created / ? AS INTEGER)*? AS created, AVG(download) AS download, AVG(upload) AS upload, AVG(cpu) AS cpu, AVG(memory) AS memory, AVG(connections) AS connections FROM metric_samples WHERE created>? GROUP BY CAST(created / ? AS INTEGER) ORDER BY created", (bucket, bucket, since, bucket))
    totals = db.one("SELECT SUM(download*elapsed) AS download, SUM(upload*elapsed) AS upload FROM metric_samples WHERE created>?", (since,))
    return {"period": period, "points": points, "totals": totals or {"download": None, "upload": None}}
