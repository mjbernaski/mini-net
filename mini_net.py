#!/usr/bin/env python3
"""mini-net: live network throughput on a single CLI progress bar."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

LINUX = sys.platform.startswith("linux")

# Virtual interfaces: skipping these keeps VPN/container traffic from
# double-counting the physical link it rides on.
SKIP = ("lo", "gif", "stf", "utun", "awdl", "llw", "bridge",
        "docker", "veth", "br-", "virbr", "tun", "tap", "wg", "tailscale")

RESET = "\033[0m"
DOWN = "\033[38;5;44m"   # cyan
UP = "\033[38;5;170m"    # magenta
DIM = "\033[2m"

BLOCK = "█"
EMPTY = "─"


def _default_groups():
    """Fall back to the "groups" section of report.json (same config
    mini_net_report.py uses) so the split view doesn't require -g every time."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.json")
    try:
        with open(path) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {label: list(ifaces) for label, ifaces in (cfg.get("groups") or {}).items()}


def _keep(name, iface):
    if iface:
        return name == iface
    return not name.startswith(SKIP)


def _read_linux():
    with open("/proc/net/dev") as fh:
        rows = fh.read().splitlines()[2:]  # two header lines
    for line in rows:
        name, sep, rest = line.partition(":")
        f = rest.split()
        if not sep or len(f) < 9:
            continue
        try:
            yield name.strip(), int(f[0]), int(f[8])
        except ValueError:
            continue


def _read_bsd():
    out = subprocess.run(
        ["netstat", "-ib"], capture_output=True, text=True, check=True
    ).stdout
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) < 10 or "<Link" not in f[2]:
            continue  # one row per address; the <Link#n> row is canonical
        try:
            yield f[0], int(f[6]), int(f[9])
        except ValueError:
            continue


def _read_raw():
    return _read_linux() if LINUX else _read_bsd()


def read_counters(iface=None):
    """Return (rx_bytes, tx_bytes) summed over physical interfaces."""
    rx = tx = 0
    for name, r, t in _read_raw():
        if _keep(name, iface):
            rx += r
            tx += t
    return rx, tx


def read_grouped_counters(groups):
    """groups: {label: [exact iface names]}. Returns {label: (rx_bytes, tx_bytes)}."""
    totals = {label: [0, 0] for label in groups}
    for name, r, t in _read_raw():
        for label, ifaces in groups.items():
            if name in ifaces:
                totals[label][0] += r
                totals[label][1] += t
    return {label: (rx, tx) for label, (rx, tx) in totals.items()}


def human(bps):
    """Bytes/sec -> compact human string."""
    for unit, div in (("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if bps >= div:
            v = bps / div
            return f"{v:5.1f} {unit}B/s"
    return f"{bps:5.0f}  B/s"


def nice_scale(v):
    """Round up to the next 1/2/5 x 10^n so the axis doesn't jitter."""
    if v <= 0:
        return 1.0
    mag = 1.0
    while mag * 10 <= v:
        mag *= 10
    while mag > v:
        mag /= 10
    for m in (1, 2, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def render(rx_rate, tx_rate, scale, width, peak):
    total = rx_rate + tx_rate
    filled = min(width, int(round(width * total / scale))) if scale else 0
    # split the filled portion proportionally between down and up
    d_cells = int(round(filled * (rx_rate / total))) if total else 0
    u_cells = filled - d_cells

    bar = (
        DOWN + BLOCK * d_cells + UP + BLOCK * u_cells
        + DIM + EMPTY * (width - filled) + RESET
    )
    return (
        f"{DOWN}↓{RESET} {human(rx_rate)}  "
        f"▕{bar}▏  "
        f"{UP}↑{RESET} {human(tx_rate)}"
        f"{DIM}  peak {human(peak).strip()}{RESET}"
    )


def main():
    p = argparse.ArgumentParser(description="Live network activity on one progress bar.")
    p.add_argument("-i", "--interval", type=float, default=0.5, help="refresh seconds (default 0.5)")
    p.add_argument("-n", "--iface", help="limit to one interface, e.g. en0")
    p.add_argument("-m", "--max", type=float, metavar="MBPS",
                   help="fixed bar scale in MB/s (default: auto)")
    p.add_argument("-g", "--group", action="append", default=[],
                   metavar="NAME=IFACE[,IFACE...]",
                   help="named interface group rendered as its own bar "
                        "(repeatable); e.g. -g eth=enP7s7 "
                        "-g hb=enp1s0f0np0,enp1s0f1np1. Overrides --iface. "
                        "Default (no -g/-n): groups from report.json, if present.")
    args = p.parse_args()

    groups = {}
    for spec in args.group:
        name, sep, ifaces = spec.partition("=")
        ifaces = [x.strip() for x in ifaces.split(",") if x.strip()]
        if not sep or not name or not ifaces:
            sys.exit(f"mini-net: bad --group spec {spec!r}, "
                      "expected NAME=IFACE[,IFACE...]")
        groups[name] = ifaces

    if not groups and not args.iface:
        groups = _default_groups()

    fixed = args.max * (1 << 20) if args.max else None
    floor = 128 * 1024  # don't let the auto-scale zoom in below 128 KB/s

    sys.stdout.write("\033[?25l")  # hide cursor

    def cleanup(*_):
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    def sample():
        if groups:
            return read_grouped_counters(groups)
        return {"": read_counters(args.iface)}

    try:
        prev = sample()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.stdout.write("\033[?25h")
        sys.exit(f"mini-net: cannot read interface counters: {e}")
    prev_t = time.monotonic()
    peaks = {label: 0.0 for label in prev}
    decaying = {label: floor for label in prev}
    label_w = max((len(label) for label in prev), default=0)
    first = True

    while True:
        time.sleep(args.interval)
        now = time.monotonic()
        cur = sample()
        dt = now - prev_t or args.interval
        cols = shutil.get_terminal_size((80, 24)).columns

        lines = []
        for label in prev:
            # counters are cumulative and can reset; clamp negatives to 0
            rx_rate = max(0, cur[label][0] - prev[label][0]) / dt
            tx_rate = max(0, cur[label][1] - prev[label][1]) / dt
            total = rx_rate + tx_rate
            peaks[label] = max(peaks[label], total)

            if fixed:
                scale = fixed
            else:
                decaying[label] = max(total, decaying[label] * 0.96, floor)
                scale = nice_scale(decaying[label])

            prefix = f"{label:>{label_w}} " if label_w else ""
            width = max(10, cols - 52 - len(prefix))
            lines.append(prefix + render(rx_rate, tx_rate, scale, width, peaks[label]))
        prev, prev_t = cur, now

        if not first:
            sys.stdout.write(f"\033[{len(lines)}A")
        first = False
        for line in lines:
            sys.stdout.write("\r\033[K" + line + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
