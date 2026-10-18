#!/usr/bin/env bash
set -euo pipefail
cd /opt/ruvpn/current
for attempt in {1..50}; do
  if [[ -S /run/amneziawg/awg0.sock ]]; then
    exec .venv/bin/python -m gateway.ops awg-setup
  fi
  sleep 0.1
done
echo 'AWG control socket не появился' >&2
exit 1
