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

## How it works

Polls cumulative interface byte counters and diffs them against wall time — `/proc/net/dev` on Linux, `netstat -ib` on macOS and BSD.

- **Auto-scale** decays 4% per tick with a 128 KB/s floor and snaps to 1/2/5×10ⁿ, so the axis doesn't jitter frame to frame. A burst widens the scale instantly, then it drifts back down.
- **Interfaces** — virtual ones (`lo`, `utun`, `awdl`, `bridge`, `docker`, `veth`, `wg`, `tailscale`, …) are excluded by default so VPN tunnels and container bridges don't double-count the physical link they ride on.
- Bar width tracks terminal width; the cursor is hidden during the run and restored on Ctrl-C or SIGTERM.

Counter resets are clamped to zero rather than producing a negative spike.

## Notes

`--iface` with a name that doesn't exist shows a flat zero bar rather than an error.
