#!/bin/sh
set -eu
python /app/pvpoke_cloud_runtime.py
: "${PVP_API_KEY:?Set a random 32+ character PVP_API_KEY in the host secret settings}"
if [ "${#PVP_API_KEY}" -lt 32 ]; then
  echo 'PVP_API_KEY must be at least 32 characters' >&2
  exit 1
fi
python /app/pvpoke_web.py >/tmp/pvpoke-web.log 2>&1 &
WEB_PID=$!
APP_PID=''
PROXY_PID=''
cleanup() {
  for pid in "$WEB_PID" "$APP_PID" "$PROXY_PID"; do
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
trap 'exit 0' INT TERM
# The local engine must be ready before the HTTP gateway can serve users.
WEB_READY=0
for i in $(seq 1 60); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/status',timeout=2)" >/dev/null 2>&1; then
    WEB_READY=1
    break
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    echo 'Web engine exited unexpectedly:' >&2
    tail -n 30 /tmp/pvpoke-web.log >&2 || true
    exit 1
  fi
  sleep 1
done
if [ "$WEB_READY" -ne 1 ]; then
  echo 'Web engine did not become ready before startup deadline' >&2
  tail -n 30 /tmp/pvpoke-web.log >&2 || true
  exit 1
fi
# Render/validate before opening the public socket. Application port stays private.
python /app/pvpoke_proxy_config.py
mkdir -p /tmp/pokemoniv-nginx/body /tmp/pokemoniv-nginx/proxy /tmp/pokemoniv-nginx/fastcgi /tmp/pokemoniv-nginx/uwsgi /tmp/pokemoniv-nginx/scgi
# Nginx is not given the application's secrets.
env -i PATH="$PATH" nginx -t -e stderr -c /tmp/pokemoniv-nginx.conf
PVP_BIND_HOST=127.0.0.1 PORT=8788 python /app/pvpoke_mcp_remote.py &
APP_PID=$!
# Do not expose nginx until the actual HTTP upstream responds. Cloud Run's
# default TCP startup probe sees nginx first and otherwise admits 502 traffic.
APP_READY=0
for i in $(seq 1 60); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/health',timeout=2)" >/dev/null 2>&1; then
    APP_READY=1
    break
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo 'HTTP gateway exited before becoming ready' >&2
    exit 1
  fi
  sleep 1
done
if [ "$APP_READY" -ne 1 ]; then
  echo 'HTTP gateway did not become ready before startup deadline' >&2
  exit 1
fi
env -i PATH="$PATH" nginx -e stderr -c /tmp/pokemoniv-nginx.conf -g 'daemon off;' &
PROXY_PID=$!
while kill -0 "$WEB_PID" && kill -0 "$APP_PID" && kill -0 "$PROXY_PID"; do
  sleep 1
done
echo 'A required service exited; restarting the container' >&2
exit 1
