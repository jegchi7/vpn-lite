#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
"$here/bootstrap.sh" relay "$@"
cd /opt/ruvpn/current
exec .venv/bin/python -m gateway.ops export-pair
