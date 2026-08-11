#!/usr/bin/env python3
"""mini-net: live network throughput on a single CLI progress bar."""

import argparse
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


def read_counters(iface=None):
    """Return (rx_bytes, tx_bytes) summed over physical interfaces."""
    rx = tx = 0
    for name, r, t in (_read_linux() if LINUX else _read_bsd()):
        if _keep(name, iface):
            rx += r
            tx += t
    return rx, tx


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
    args = p.parse_args()

    fixed = args.max * (1 << 20) if args.max else None
    floor = 128 * 1024  # don't let the auto-scale zoom in below 128 KB/s

    sys.stdout.write("\033[?25l")  # hide cursor

    def cleanup(*_):
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        prev = read_counters(args.iface)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.stdout.write("\033[?25h")
        sys.exit(f"mini-net: cannot read interface counters: {e}")
    prev_t = time.monotonic()
    peak = 0.0
    decaying = floor

    while True:
        time.sleep(args.interval)
        now = time.monotonic()
        cur = read_counters(args.iface)
        dt = now - prev_t or args.interval

        # counters are cumulative and can reset; clamp negatives to 0
        rx_rate = max(0, cur[0] - prev[0]) / dt
        tx_rate = max(0, cur[1] - prev[1]) / dt
        prev, prev_t = cur, now

        total = rx_rate + tx_rate
        peak = max(peak, total)

        if fixed:
            scale = fixed
        else:
            decaying = max(total, decaying * 0.96, floor)
            scale = nice_scale(decaying)

        cols = shutil.get_terminal_size((80, 24)).columns
        width = max(10, cols - 52)
        sys.stdout.write("\r\033[K" + render(rx_rate, tx_rate, scale, width, peak))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
