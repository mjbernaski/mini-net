# mini-net

Live network throughput on a single CLI progress bar. macOS and Linux, stdlib-only Python, no dependencies.

```
↓  48.7 MB/s  ▕██████████████──────────────▏  ↑  80.4 KB/s  peak 48.7 MB/s
```

One bar, redrawn in place. The filled portion is total throughput against the current scale; within it, the cyan segment is download and magenta is upload, split proportionally.

## Usage

```bash
mini-net            # auto-scaling, 0.5s refresh
mini-net -i 0.2     # faster refresh
mini-net -n en0     # limit to one interface
mini-net -m 10      # fixed 10 MB/s scale
```

## Install

```bash
git clone https://github.com/mjbernaski/mini-net.git
cd mini-net
python3 -m venv .venv          # optional; falls back to system python3
ln -sf "$PWD/mini-net.sh" ~/.local/bin/mini-net
```

The launcher resolves symlinks to find its own directory, so it works from any working directory.

## Installing on other machines

Copy `hosts.example.json` to `hosts.json`, set each `ssh` field to a hostname or `~/.ssh/config` alias, then:

```bash
./install-remote.sh            # every host in hosts.json
./install-remote.sh spark-1    # just one, by name
```

It copies both files over SSH, symlinks `mini-net` into `install_dir`, runs a smoke test, and warns if that directory isn't on the remote `PATH`. `hosts.json` is gitignored so your internal addresses stay out of the repo.

## Reporting to a status service

`mini_net_report.py` is a headless daemon — no terminal, no bar — that samples counters into a rolling window and POSTs a summary to the [mini-status-service](#) note API. It reports **volume moved**, not rates:

```
eth ↓ 574.2 KB  ↑ 85.3 KB
hb ↓ 40.1 KB  ↑ 23.9 KB
last 5m @ 10:43
```

One line per group, then the window and timestamp. Each host posts to its own note service on `localhost:9999`.

Settings live in `report.json`:

| key | default | meaning |
|---|---|---|
| `url` | `http://localhost:9999/note` | where to POST `{"text": ...}` |
| `sample_interval_sec` | 15 | how often counters are read |
| `post_interval_sec` | 60 | how often a note is posted (floored at 60) |
| `window_sec` | 300 | rolling window the summary covers |
| `iface` | `null` | limit to one interface |
| `groups` | `null` | named interface groups, one output line each |

`groups` is a single fleet-wide map — a group naming interfaces the current host doesn't have is dropped on that host, so `eth`/`hb` render only on the sparks and `wifi` only on the Mac. The same map backs `mini-net -g`, so the live bar and the notes agree without a second config.

### Linux

Install as a `systemd --user` service on every host flagged `"reporter": true` in `hosts.json`:

```bash
./install-reporter.sh              # all reporter hosts
./install-reporter.sh spark-1      # just one
systemctl --user status mini-net-report      # on the host
journalctl --user -u mini-net-report -f
```

The user service needs no root. It requires lingering (`loginctl enable-linger $USER`) so it starts at boot without a login session. Re-running the installer restarts the service, so a redeploy takes effect immediately.

### macOS

macOS has no systemd, so the Mac uses a launchd user agent instead:

```bash
./install-mac.sh
launchctl print gui/$(id -u)/com.mjbernaski.mini-net-report
tail -f ~/Library/Logs/mini-net-report.log
```

It creates `.venv` if missing and writes the plist with absolute paths, since launchd has no `%h` equivalent.

Notes are capped at the server's 500-char limit; posting failures are logged and retried on the next cycle rather than killing the daemon.

## How it works

Polls cumulative interface byte counters and diffs them against wall time — `/proc/net/dev` on Linux, `netstat -ib` on macOS and BSD.

- **Auto-scale** decays 4% per tick with a 128 KB/s floor and snaps to 1/2/5×10ⁿ, so the axis doesn't jitter frame to frame. A burst widens the scale instantly, then it drifts back down.
- **Interfaces** — virtual ones (`lo`, `utun`, `awdl`, `bridge`, `docker`, `veth`, `wg`, `tailscale`, …) are excluded by default so VPN tunnels and container bridges don't double-count the physical link they ride on.
- Bar width tracks terminal width; the cursor is hidden during the run and restored on Ctrl-C or SIGTERM.

Counter resets are clamped to zero rather than producing a negative spike.

## Notes

`--iface` with a name that doesn't exist shows a flat zero bar rather than an error.
