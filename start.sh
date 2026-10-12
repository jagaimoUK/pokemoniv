#!/bin/sh
set -eu
: "${PVP_API_KEY:?Set a random 32+ character PVP_API_KEY in the host secret settings}"
if [ "${#PVP_API_KEY}" -lt 32 ]; then
  echo 'PVP_API_KEY must be at least 32 characters' >&2
  exit 1
fi
python /app/pvpoke_web.py >/tmp/pvpoke-web.log 2>&1 &
WEB_PID=$!
trap 'kill "$WEB_PID" 2>/dev/null || true' EXIT INT TERM
for i in $(seq 1 30); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/status',timeout=2)" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    echo 'Web engine exited unexpectedly:' >&2
    tail -n 30 /tmp/pvpoke-web.log >&2 || true
    exit 1
  fi
  sleep 1
done
exec python /app/pvpoke_mcp_remote.py
