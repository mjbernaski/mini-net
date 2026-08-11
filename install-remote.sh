#!/bin/sh
# Install mini-net on every host listed in hosts.json.
#   ./install-remote.sh            install everywhere
#   ./install-remote.sh spark-1    install on one host by name
set -e

here=$(cd -P "$(dirname "$0")" && pwd)
cfg="$here/hosts.json"
[ -f "$cfg" ] || { echo "missing $cfg" >&2; exit 1; }

py=$(command -v python3) || { echo "python3 required to read hosts.json" >&2; exit 1; }
targets=$("$py" -c '
import json,sys
c=json.load(open(sys.argv[1]))
want=sys.argv[2] if len(sys.argv)>2 else None
d=c.get("install_dir","~/.local/bin")
for h in c["hosts"]:
    if want in (None,h["name"]):
        print(h["name"],h["ssh"],d)
' "$cfg" "$@")

[ -n "$targets" ] || { echo "no matching hosts in hosts.json" >&2; exit 1; }

echo "$targets" | while read -r name target dir; do
    echo "=== $name ($target) ==="
    # shell-expand ~ on the remote side, then place both files
    ssh "$target" "mkdir -p ${dir}" </dev/null
    scp -q "$here/mini_net.py" "$here/mini-net.sh" "$target:${dir}/"
    ssh "$target" "
        chmod +x ${dir}/mini-net.sh ${dir}/mini_net.py
        ln -sf ${dir}/mini-net.sh ${dir}/mini-net
        ${dir}/mini-net --help >/dev/null && echo 'installed: ok'
        case \":\$PATH:\" in
            *\":\$HOME/.local/bin:\"*) ;;
            *) echo \"note: ${dir} is not on PATH -- run it as ${dir}/mini-net\" ;;
        esac
    " </dev/null
done
