from __future__ import annotations

import io
import base64
import ipaddress
import json
import urllib.parse
import zlib
import qrcode
from qrcode.exceptions import DataOverflowError
from . import control, db, security
from .config import public


def profile(user_id, device_id, protocol):
    d = control.device_for(user_id, device_id)
    if not d["desired"] or d["state"] != "applied":
        raise ValueError("Профиль выдаётся только после успешного применения")
    row = db.one("SELECT ciphertext FROM credentials WHERE device_id=?", (device_id,))
    cred = security.decrypt(row["ciphertext"])
    cfg = public()
    if protocol in {"awg", "amnezia"}:
        a = cfg["awg"]
        subnet, subnet6 = ipaddress.ip_network(a["subnet"]), ipaddress.ip_network(a["subnet6"])
        lines = ["[Interface]", f"PrivateKey = {cred['private']}", f"Address = {subnet[d['address']]}/32, {subnet6[d['address']]}/128", f"DNS = {subnet[1]}", f"MTU = {a['mtu']}"]
        lines += [f"{k} = {v}" for k, v in a["obfuscation"].items()]
        lines += ["", "[Peer]", f"PublicKey = {a['public_key']}", f"PresharedKey = {cred['psk']}", f"Endpoint = {cfg['endpoint']}:{a['port']}", "AllowedIPs = 0.0.0.0/0, ::/0", "PersistentKeepalive = 25", ""]
        text = "\n".join(lines)
        if protocol == "awg":
            return "CHIMERA.conf", text
        # Amnezia's native import preserves description; a plain .conf import
        # generates a new generic name regardless of its filename. Match the
        # official importer's last_config fields and Qt qCompress envelope.
        last = {
            "config": text, "hostName": cfg["endpoint"], "port": int(a["port"]),
            "client_priv_key": cred["private"], "client_pub_key": d["public_key"],
            "client_ip": f"{subnet[d['address']]}/32, {subnet6[d['address']]}/128",
            "server_pub_key": a["public_key"], "psk_key": cred["psk"],
            "mtu": str(a["mtu"]), "persistent_keep_alive": "25",
            "allowed_ips": ["0.0.0.0/0", "::/0"],
            **{k: str(v) for k, v in a["obfuscation"].items()},
        }
        native = {
            "description": "CHIMERA · " + d["name"], "hostName": cfg["endpoint"],
            "dns1": str(subnet[1]), "dns2": str(subnet[1]),
            "defaultContainer": "amnezia-awg",
            "containers": [{"container": "amnezia-awg", "awg": {
                "last_config": json.dumps(last, ensure_ascii=False, separators=(",", ":")),
                "isThirdPartyConfig": True, "port": str(a["port"]), "transport_proto": "udp",
            }}],
        }
        payload = json.dumps(native, ensure_ascii=False, separators=(",", ":")).encode()
        compressed = len(payload).to_bytes(4, "big") + zlib.compress(payload, 8)
        return "CHIMERA.vpn", "vpn://" + base64.urlsafe_b64encode(compressed).decode().rstrip("=") + "\n"
    v = cfg["vless"]
    # Pin the Xray ClientHello instead of a browser alias that changes on update.
    # Confirmed with Happ and v2rayNG on the deployed REALITY entry.
    query = urllib.parse.urlencode({"encryption": "none", "security": "reality", "type": "tcp", "flow": "xtls-rprx-vision", "sni": v["server_name"], "fp": "hellosafari_16_0", "pbk": v["public_key"], "sid": v["short_id"], "packetEncoding": "xudp"})
    uri = f"vless://{cred['uuid']}@{cfg['endpoint']}:{v['port']}?{query}#{urllib.parse.quote('CHIMERA · '+d['name'])}"
    if protocol == "vless":
        return "CHIMERA-vless.txt", uri + "\n"
    if protocol != "singbox":
        raise ValueError("Неизвестный протокол")
    outbound = {"type": "vless", "tag": "proxy", "server": cfg["endpoint"], "server_port": v["port"], "uuid": cred["uuid"], "flow": "xtls-rprx-vision", "packet_encoding": "xudp", "tls": {"enabled": True, "server_name": v["server_name"], "utls": {"enabled": True, "fingerprint": "safari"}, "reality": {"enabled": True, "public_key": v["public_key"], "short_id": v["short_id"]}}}
    result = {
        "log": {"level": "error"},
        "dns": {"servers": [{"type": "udp", "tag": "gateway", "server": str(ipaddress.ip_network(cfg['awg']['subnet'])[1]), "detour": "proxy"}], "final": "gateway"},
        "inbounds": [{"type": "tun", "tag": "vpn", "address": ["172.30.0.1/30", "fd78:7275:7670::1/126"], "auto_route": True, "strict_route": True, "stack": "mixed"}],
        "outbounds": [outbound],
        "route": {"rules": [{"port": 53, "action": "hijack-dns"}, {"ip_version": 6, "action": "reject"}], "final": "proxy", "auto_detect_interface": True},
    }
    return "CHIMERA-sing-box.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def qr_png(text):
    if len(text.encode()) > 2800:
        raise ValueError("Профиль слишком большой для QR; скачайте файл")
    try:
        code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=6, border=4)
        code.add_data(text)
        code.make(fit=True)
        image = code.make_image(fill_color="black", back_color="white")
        target = io.BytesIO()
        image.save(target, format="PNG")
        return target.getvalue()
    except DataOverflowError as e:
        raise ValueError("Профиль слишком большой для QR; скачайте файл") from e
