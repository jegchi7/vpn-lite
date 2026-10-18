#!/usr/bin/env bash
set -euo pipefail
cd /opt/ruvpn/current
case "${1:-}" in
  --confirm-network) exec .venv/bin/python -m gateway.ops network-confirm;;
  --rollback-network) exec .venv/bin/python -m gateway.ops network-rollback;;
  --set-bot) exec .venv/bin/python -m gateway.ops set-bot;;
  --export-pair) shift; exec .venv/bin/python -m gateway.ops export-pair "$@";;
  --rotate-pair) shift; exec .venv/bin/python -m gateway.ops rotate-pair "$@";;
  *) exec .venv/bin/python -m gateway.ops configure "$@";;
esac
