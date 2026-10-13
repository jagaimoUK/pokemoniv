#!/bin/sh
set -eu

# Railway mounts volumes as root. Only initialization runs with root privileges;
# the PvPoke application and Chromium continue to run as unprivileged appuser.
if [ "$(id -u)" -ne 0 ]; then
  echo 'Volume bootstrap must run as root' >&2
  exit 1
fi

if [ -n "${RAILWAY_VOLUME_MOUNT_PATH:-}" ]; then
  mount_path="$RAILWAY_VOLUME_MOUNT_PATH"
  case "$mount_path" in
    /*) ;;
    *) echo 'Railway volume mount must be an absolute path' >&2; exit 1 ;;
  esac
  if [ "$mount_path" = '/' ]; then
    echo 'Refusing filesystem root as volume mount' >&2
    exit 1
  fi
  # Do not chown the whole volume, only the one directory managed by PvPoke.
  mkdir -p "$mount_path/pvpoke_archives"
  chown appuser:appuser "$mount_path/pvpoke_archives"
fi

exec gosu appuser /app/start.sh
