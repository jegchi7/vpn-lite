#!/usr/bin/env python3
import argparse
import ipaddress
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="Создать один setup.toml для обоих серверов")
parser.add_argument("--ru", required=True)
parser.add_argument("--foreign", required=True)
parser.add_argument("--domain", required=True)
parser.add_argument("--email", required=True)
parser.add_argument("--output", default="setup.toml")
args = parser.parse_args()
for address in [args.ru, args.foreign]:
    if not ipaddress.IPv4Address(address).is_global:
        parser.error("Нужны реальные публичные IPv4 адреса")
if args.ru == args.foreign:
    parser.error("Нужны два разных сервера")
root = Path(__file__).resolve().parent.parent
text = (root / "setup.example.toml").read_text()
text = text.replace('ru_ipv4 = "CHANGE_ME"', 'ru_ipv4 = ' + json.dumps(args.ru)).replace('ipv4 = "CHANGE_ME"', 'ipv4 = ' + json.dumps(args.foreign))
text = text.replace('domain = "vpn.example.com"', 'domain = ' + json.dumps(args.domain)).replace('email = "owner@example.com"', 'email = ' + json.dumps(args.email))
output = Path(args.output)
if output.exists():
    parser.error("Файл уже существует; он не перезаписан")
output.write_text(text)
print("Конфигурация создана: " + str(output))
