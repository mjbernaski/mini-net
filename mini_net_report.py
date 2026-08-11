#!/usr/bin/env python3
"""Post a rolling network-usage summary to the mini-status-service note API."""

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

from mini_net import human, read_counters

MAX_NOTE = 500  # server rejects longer

DEFAULTS = {
    "url": "http://localhost:9999/note",
    "sample_interval_sec": 15,
    "post_interval_sec": 60,
    "window_sec": 300,
    "iface": None,
}


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if not k.startswith("_")})
    return cfg


def human_total(n):
    for unit, div in (("TB", 1 << 40), ("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n:.0f} B"


def summarize(samples, host):
    """samples: deque of (monotonic_t, rx, tx). Returns note text."""
    (t0, rx0, tx0), (t1, rx1, tx1) = samples[0], samples[-1]
    span = t1 - t0
    if span <= 0:
        return None

    d_rx, d_tx = max(0, rx1 - rx0), max(0, tx1 - tx0)

    peak_rx = peak_tx = 0.0
    for (ta, ra, ta_tx), (tb, rb, tb_tx) in zip(samples, list(samples)[1:]):
        dt = tb - ta
        if dt <= 0:
            continue
        peak_rx = max(peak_rx, max(0, rb - ra) / dt)
        peak_tx = max(peak_tx, max(0, tb_tx - ta_tx) / dt)

    mins = span / 60
    stamp = datetime.now().astimezone().strftime("%H:%M:%S %Z")
    text = (
        f"{host} net {mins:.1f}m: "
        f"down {human_total(d_rx)} (avg {human(d_rx / span).strip()}, peak {human(peak_rx).strip()}) | "
        f"up {human_total(d_tx)} (avg {human(d_tx / span).strip()}, peak {human(peak_tx).strip()}) | "
        f"{len(samples)} samples @ {stamp}"
    )
    return text[:MAX_NOTE]


def post(url, text, timeout=10):
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-c", "--config", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "report.json"))
    p.add_argument("--once", action="store_true",
                   help="collect one window and post a single note, then exit")
    args = p.parse_args()

    cfg = load_config(args.config)
    host = socket.gethostname()
    window = cfg["window_sec"]
    sample_every = cfg["sample_interval_sec"]
    post_every = cfg["post_interval_sec"]

    samples = deque()
    last_post = 0.0

    while True:
        now = time.monotonic()
        try:
            rx, tx = read_counters(cfg["iface"])
        except Exception as e:  # transient /proc read failure shouldn't kill the daemon
            print(f"sample failed: {e}", file=sys.stderr, flush=True)
            time.sleep(sample_every)
            continue

        samples.append((now, rx, tx))
        while len(samples) > 2 and now - samples[0][0] > window:
            samples.popleft()

        ready = len(samples) >= 2 and (args.once or now - last_post >= post_every)
        if ready:
            text = summarize(samples, host)
            if text:
                try:
                    post(cfg["url"], text)
                    last_post = now
                    print(f"posted: {text}", flush=True)
                except (urllib.error.URLError, OSError) as e:
                    print(f"post failed: {e}", file=sys.stderr, flush=True)
            if args.once:
                return

        time.sleep(sample_every)


if __name__ == "__main__":
    main()
