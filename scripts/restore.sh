#!/usr/bin/env bash
set -euo pipefail
cd /opt/ruvpn/current
exec .venv/bin/python -m gateway.ops restore "$@"
