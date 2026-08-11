#!/bin/sh
# Launcher for mini-net. Safe to symlink onto your PATH.
set -e

# Resolve this script's real location, following symlinks.
src="$0"
while [ -L "$src" ]; do
    dir=$(cd -P "$(dirname "$src")" && pwd)
    src=$(readlink "$src")
    case "$src" in
        /*) ;;
        *) src="$dir/$src" ;;
    esac
done
here=$(cd -P "$(dirname "$src")" && pwd)

if [ -x "$here/.venv/bin/python" ]; then
    py="$here/.venv/bin/python"
else
    py=$(command -v python3 || true)
    [ -n "$py" ] || { echo "mini-net: no python3 found" >&2; exit 1; }
fi

exec "$py" "$here/mini_net.py" "$@"
