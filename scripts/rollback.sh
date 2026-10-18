#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Запустите от root' >&2; exit 1; fi
if [[ -e /etc/ruvpn/network-transaction.json ]]; then
  /opt/ruvpn/current/scripts/configure.sh --rollback-network
fi
previous=$(readlink -f /opt/ruvpn/previous)
current=$(readlink -f /opt/ruvpn/current)
if [[ ! -d $previous || $previous == "$current" ]]; then echo 'Предыдущего релиза нет' >&2; exit 1; fi
role=$(cat /etc/ruvpn/role)
ln -sfn -- "$previous" /opt/ruvpn/current
ln -sfn -- "$current" /opt/ruvpn/previous
for unit in "$previous"/systemd/*; do
  if [[ $role == foreign && $(basename -- "$unit") != ruvpn-sing.service && $(basename -- "$unit") != ruvpn-netguard.service ]]; then continue; fi
  install -m 0644 "$unit" /etc/systemd/system/
done
systemctl daemon-reload
cd /opt/ruvpn/current
exec .venv/bin/python -m gateway.ops configure --setup /etc/ruvpn/setup.json
