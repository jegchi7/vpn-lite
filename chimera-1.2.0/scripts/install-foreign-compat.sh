#!/usr/bin/env bash
# Foreign-only compatibility installer; never starts/stops the Docker daemon.
set -euo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите от root' >&2; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 20.04 ]] || { echo 'Этот режим предназначен для foreign на Ubuntu 20.04 с работающим Docker.' >&2; exit 1; }
command -v docker >/dev/null && docker info >/dev/null 2>&1 || { echo 'Нужен уже работающий Docker; он не устанавливается и не перезапускается.' >&2; exit 1; }
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -x /usr/sbin/iptables-legacy || ! -x /usr/sbin/ip6tables-legacy ]] || ! python3 -c 'import cryptography; from cryptography.hazmat.primitives.asymmetric import x25519' 2>/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-cryptography ca-certificates iptables iproute2
fi
exec python3 "$here/foreign-compat.py" install "$@"
