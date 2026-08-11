#!/usr/bin/env python3
"""Post a rolling network-usage summary to the mini-status-service note API."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

from mini_net import human, read_counters, read_grouped_counters

MAX_NOTE = 500  # server rejects longer

DEFAULTS = {
    "url": "http://localhost:9999/note",
    "sample_interval_sec": 15,
    "post_interval_sec": 60,
    "window_sec": 300,
    "iface": None,
    "groups": None,  # e.g. {"eth": ["enP7s7"], "hb": ["enp1s0f0np0", "enp1s0f1np1"]}
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


def _group_stats(samples, label):
    """samples: deque of (monotonic_t, {label: (rx, tx)}). Returns (d_rx, d_tx, peak_rx, peak_tx, span)."""
    t0, d0 = samples[0]
    t1, d1 = samples[-1]
    span = t1 - t0
    rx0, tx0 = d0[label]
    rx1, tx1 = d1[label]
    d_rx, d_tx = max(0, rx1 - rx0), max(0, tx1 - tx0)

    peak_rx = peak_tx = 0.0
    prev = None
    for entry in samples:
        if prev is not None:
            dt = entry[0] - prev[0]
            if dt > 0:
                pr, pt = prev[1][label]
                cr, ct = entry[1][label]
                peak_rx = max(peak_rx, max(0, cr - pr) / dt)
                peak_tx = max(peak_tx, max(0, ct - pt) / dt)
        prev = entry
    return d_rx, d_tx, peak_rx, peak_tx, span


def summarize(samples, group_order):
    """samples: deque of (monotonic_t, {label: (rx, tx)}). Returns note text."""
    span = samples[-1][0] - samples[0][0]
    if span <= 0:
        return None

    mins = span / 60
    stamp = datetime.now().astimezone().strftime("%H:%M:%S %Z")

    if group_order == [""]:
        d_rx, d_tx, peak_rx, peak_tx, span = _group_stats(samples, "")
        body = (
            f"down {human_total(d_rx)} (avg {human(d_rx / span).strip()}, peak {human(peak_rx).strip()}) | "
            f"up {human_total(d_tx)} (avg {human(d_tx / span).strip()}, peak {human(peak_tx).strip()})"
        )
    else:
        parts = []
        for label in group_order:
            d_rx, d_tx, peak_rx, peak_tx, span = _group_stats(samples, label)
            parts.append(
                f"{label} down {human_total(d_rx)} (avg {human(d_rx / span).strip()}, peak {human(peak_rx).strip()}) "
                f"up {human_total(d_tx)} (avg {human(d_tx / span).strip()}, peak {human(peak_tx).strip()})"
            )
        body = " | ".join(parts)

    text = f"net {mins:.1f}m: {body} | {len(samples)} samples @ {stamp}"
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
    window = cfg["window_sec"]
    sample_every = cfg["sample_interval_sec"]
    post_every = cfg["post_interval_sec"]
    groups = cfg.get("groups")
    group_order = list(groups) if groups else [""]

    samples = deque()
    last_post = 0.0

    while True:
        now = time.monotonic()
        try:
            data = read_grouped_counters(groups) if groups else {"": read_counters(cfg["iface"])}
        except Exception as e:  # transient /proc read failure shouldn't kill the daemon
            print(f"sample failed: {e}", file=sys.stderr, flush=True)
            time.sleep(sample_every)
            continue

        samples.append((now, data))
        while len(samples) > 2 and now - samples[0][0] > window:
            samples.popleft()

        ready = len(samples) >= 2 and (args.once or now - last_post >= post_every)
        if ready:
            text = summarize(samples, group_order)
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
