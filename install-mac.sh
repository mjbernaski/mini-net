#!/bin/sh
# Install the network-usage reporter as a launchd user agent on this Mac.
# macOS has no systemd, so the Linux hosts use install-reporter.sh instead.
set -e

here=$(cd -P "$(dirname "$0")" && pwd)
label=com.mjbernaski.mini-net-report
plist="$HOME/Library/LaunchAgents/$label.plist"
log="$HOME/Library/Logs/mini-net-report.log"

[ -d "$here/.venv" ] || python3 -m venv "$here/.venv"
py="$here/.venv/bin/python"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$py</string>
    <string>$here/mini_net_report.py</string>
  </array>
  <key>WorkingDirectory</key><string>$here</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
sleep 1
launchctl print "gui/$(id -u)/$label" | grep -E "^\s+(state|pid) " || true
echo "logs: $log"
