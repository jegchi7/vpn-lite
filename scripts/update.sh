#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Запустите от root' >&2; exit 1; fi
release_dir=$(realpath -- "${1:?Укажите каталог нового распакованного релиза}")
if [[ ! -f $release_dir/release.json || ! -f $release_dir/scripts/bootstrap.sh ]]; then echo 'Это не каталог релиза' >&2; exit 1; fi
if [[ -e /etc/ruvpn/network-transaction.json ]]; then echo 'Ожидается подтверждение сети' >&2; exit 1; fi
role=$(cat /etc/ruvpn/role)
old_schema=$(python3 -c 'import json;print(json.load(open("/opt/ruvpn/current/release.json"))["schema"])')
new_schema=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["schema"])' "$release_dir/release.json")
if [[ $new_schema != "$old_schema" ]]; then echo 'Нужна явная миграция схемы; автоматическое обновление остановлено' >&2; exit 1; fi
exec "$release_dir/scripts/bootstrap.sh" "$role" --setup /etc/ruvpn/setup.json
