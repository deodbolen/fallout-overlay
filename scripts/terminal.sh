#!/bin/sh
base=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "${1:-}" = '--keys' ]; then
    exec /usr/bin/python3 "$base/scripts/key_probe.py"
fi
# SSH always stays in its terminal, even if X forwarding supplies DISPLAY.
# --terminal also makes the text UI available from a local terminal.
if [ "${1:-}" = '--terminal' ]; then
    shift
    mode=terminal
elif [ "${1:-}" = '--desktop' ]; then
    shift
    mode=desktop
elif [ -n "${SSH_CONNECTION:-}${SSH_TTY:-}" ] || [ -z "${DISPLAY:-}" ]; then
    mode=terminal
else
    mode=desktop
fi
if [ "$mode" = terminal ]; then
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        echo 'The navigator requires an interactive terminal. Connect with ssh -t.' >&2
        exit 1
    fi
    unset FALLOUT_EMBEDDED_SOCKET FALLOUT_SOUND_SOCKET
    export FALLOUT_TERMINAL_ONLY=1
    exec /usr/bin/python3 "$base/scripts/browser.py" "$@"
fi
exec /usr/bin/python3 "$base/scripts/embedded_app.py" "$@"
