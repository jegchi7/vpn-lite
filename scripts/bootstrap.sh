#!/usr/bin/env bash
set -euo pipefail
umask 077
role=${1:?ru or foreign}; shift
if [[ $EUID -ne 0 ]]; then echo 'Запустите от root' >&2; exit 1; fi
case "$role" in ru|foreign) ;; *) exit 2;; esac
source /etc/os-release
if [[ $ID != ubuntu || ( $VERSION_ID != 24.04 && $VERSION_ID != 26.04 ) ]]; then
  echo 'Поддерживаются Ubuntu 24.04 / 26.04 LTS. ОС не изменена.' >&2; exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
setup_file=''; pair_file=''; skip_apt=0
while (($#)); do
  case "$1" in
    --setup) setup_file=$(realpath -- "${2:?setup file}"); shift 2;;
    --pair) pair_file=$(realpath -- "${2:?encrypted pairing package}"); shift 2;;
    --skip-apt) skip_apt=1; shift;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2;;
  esac
done
if [[ -z $setup_file || ! -f $setup_file ]]; then echo 'Нужен --setup /root/setup.toml' >&2; exit 2; fi
if [[ -e /etc/ruvpn/network-transaction.json ]]; then
  echo 'Сначала подтвердите или откатите ожидающее изменение сети.' >&2; exit 1
fi
if (( ! skip_apt )); then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-venv ca-certificates nftables iproute2 procps build-essential curl tar openssl
fi
for binary in python3 nft ip ss make cc systemctl; do command -v "$binary" >/dev/null || { echo "Отсутствует $binary" >&2; exit 1; }; done
python3 -c 'import sys; assert (3,12) <= sys.version_info < (3,15), "Нужен Python 3.12–3.14"'
for account in ruvpn ruvpn-net ruvpn-web; do
  if ! id "$account" &>/dev/null; then useradd --system --user-group --home-dir "/var/lib/$account" --shell /usr/sbin/nologin "$account"; fi
  install -d -m 0700 -o "$account" -g "$account" "/var/lib/$account"
done
install -d -m 0755 /etc/ruvpn /opt/ruvpn/releases /run/ruvpn
# Code and all executable assets remain root-owned, never writable by the panel.
release_version=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$source_dir/release.json")
if [[ ! $release_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo 'Некорректная версия релиза' >&2; exit 1; fi
release_dir="/opt/ruvpn/releases/$release_version-$(date -u +%Y%m%dT%H%M%S)"
install -d -m 0755 "$release_dir"
tar -C "$source_dir" --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude='*.pyc' --exclude=setup.toml --exclude=setup.json --exclude='*.ruvpn' --exclude='.env*' -cf - . | tar --no-same-owner -C "$release_dir" -xf -
chmod -R u=rwX,go=rX "$release_dir"
chmod 0755 "$release_dir"/scripts/*.sh "$release_dir"/scripts/*.py
python3 "$release_dir/scripts/assets.py" --role "$role"
python3 -m venv "$release_dir/.venv"
if [[ -d $release_dir/vendor/wheels ]]; then
  "$release_dir/.venv/bin/pip" install --no-index --find-links "$release_dir/vendor/wheels" -r "$release_dir/requirements.lock"
else
  "$release_dir/.venv/bin/pip" install -r "$release_dir/requirements.lock"
fi
# These files contain code/dependencies only. Daemons must be able to traverse
# directories created while the installer used a restrictive umask.
chmod -R u=rwX,go=rX "$release_dir"
previous=''
if [[ -L /opt/ruvpn/current ]]; then previous=$(readlink -f /opt/ruvpn/current); fi
if [[ -n $previous ]]; then ln -sfn -- "$previous" /opt/ruvpn/previous; fi
ln -sfn -- "$release_dir" /opt/ruvpn/current.new
mv -Tf -- /opt/ruvpn/current.new /opt/ruvpn/current
for unit in "$release_dir"/systemd/*; do
  if [[ $role == foreign && $(basename -- "$unit") != ruvpn-sing.service && $(basename -- "$unit") != ruvpn-netguard.service ]]; then continue; fi
  install -m 0644 "$unit" /etc/systemd/system/
done
if [[ $role == ru ]]; then
  install -d -m 0755 /etc/systemd/system/ruvpn-sing.service.d
  cat > /etc/systemd/system/ruvpn-sing.service.d/ru.conf <<'UNIT'
[Unit]
After=ruvpn-awg.service
Wants=ruvpn-awg.service
UNIT
fi
systemctl daemon-reload
cd /opt/ruvpn/current
args=(install "$role" --setup "$setup_file")
if [[ -n $pair_file ]]; then args+=(--pair "$pair_file"); fi
if ! "$release_dir/.venv/bin/python" -m gateway.ops "${args[@]}"; then
  if [[ -n $previous ]]; then
    ln -sfn -- "$previous" /opt/ruvpn/current
    systemctl daemon-reload
  fi
  echo 'Установка не завершена. Сеть возвращена, если успела измениться. Смотрите сообщение выше.' >&2
  exit 1
fi
dpkg-query -W -f='${binary:Package}=${Version}\n' python3 nftables iproute2 > /etc/ruvpn/os-packages.txt
chmod 0600 /etc/ruvpn/os-packages.txt
