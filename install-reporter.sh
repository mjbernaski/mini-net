#!/bin/sh
# Install the network-usage reporter as a systemd --user service on Linux hosts.
# Targets hosts in hosts.json with "reporter": true, or one host by name:
#   ./install-reporter.sh            all reporter hosts
#   ./install-reporter.sh spark-1    just one
set -e

here=$(cd -P "$(dirname "$0")" && pwd)
cfg="$here/hosts.json"
[ -f "$cfg" ] || { echo "missing $cfg" >&2; exit 1; }

targets=$(python3 -c '
import json,sys
c=json.load(open(sys.argv[1]))
want=sys.argv[2] if len(sys.argv)>2 else None
d=c.get("install_dir","~/.local/bin")
for h in c["hosts"]:
    if not h.get("reporter"): continue
    if want in (None,h["name"]): print(h["name"],h["ssh"],d)
' "$cfg" "$@")

[ -n "$targets" ] || { echo "no reporter hosts matched" >&2; exit 1; }

echo "$targets" | while read -r name target dir; do
    echo "=== $name ($target) ==="
    ssh "$target" "mkdir -p ${dir} ~/.config/systemd/user" </dev/null
    scp -q "$here/mini_net.py" "$here/mini_net_report.py" "$here/report.json" "$target:${dir}/"
    scp -q "$here/mini-net-report.service" "$target:.config/systemd/user/"
    ssh "$target" '
        chmod +x ~/.local/bin/mini_net_report.py
        systemctl --user daemon-reload
        systemctl --user enable --now mini-net-report.service
        sleep 1
        systemctl --user is-active mini-net-report.service
    ' </dev/null
done
