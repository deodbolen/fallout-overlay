#!/bin/sh
# Run as the desktop user; elevate only apt, never desktop configuration.
set -eu
packages='python3 python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good xfce4-panel xfconf xfwm4 xfdesktop4 xfce4-terminal xfce4-genmon-plugin fonts-dejavu-core nano openssh-client libglib2.0-bin librsvg2-common xdg-utils bash'
if ! command -v apt-get >/dev/null 2>&1 || ! command -v dpkg-query >/dev/null 2>&1; then
    echo 'This installer requires Debian or an apt-based Debian derivative.' >&2
    exit 1
fi
missing=''
for package in $packages; do
    status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)
    case "$status" in
        'install ok installed') ;;
        *) missing="$missing $package" ;;
    esac
done
if [ -z "$missing" ]; then
    echo 'All required Debian packages are installed.'
    exit 0
fi
echo "Missing dependencies:$missing"
if [ "${1:-}" = '--check' ]; then exit 1; fi
if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y $missing
elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y $missing
else
    echo 'Install sudo (or have an administrator install the listed packages), then rerun ./install.sh as your desktop user.' >&2
    exit 1
fi
# Ensure partial apt operations cannot proceed to desktop configuration.
exec "$0" --check
