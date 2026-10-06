#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run ./install.sh as your logged-in XFCE user, without sudo. Missing packages will be installed using sudo.' >&2
    exit 1
fi
./scripts/install_dependencies.sh "${1:-}"
if [ "${1:-}" = '--check' ]; then exit 0; fi
exec /usr/bin/python3 scripts/setup.py install
