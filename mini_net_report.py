#!/usr/bin/env python3
"""Post per-link data transferred to the mini-status-service note API."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

from mini_net import present_groups, read_counters, read_grouped_counters

MAX_NOTE = 500  # server rejects longer

DEFAULTS = {
    "url": "http://localhost:9999/note",
    "sample_interval_sec": 15,
    "post_interval_sec": 60,  # the server keeps every note in memory; don't post faster
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


def transferred(samples, label):
    """Bytes moved over `label` across the whole window."""
    rx0, tx0 = samples[0][1][label]
    rx1, tx1 = samples[-1][1][label]
    return max(0, rx1 - rx0), max(0, tx1 - tx0)


def summarize(samples, group_order):
    """samples: deque of (monotonic_t, {label: (rx, tx)}). Returns note text."""
    span = samples[-1][0] - samples[0][0]
    if span <= 0:
        return None

    parts = []
    for label in group_order:
        d_rx, d_tx = transferred(samples, label)
        name = f"{label} " if label else ""
        parts.append(f"{name}↓ {human_total(d_rx)}  ↑ {human_total(d_tx)}")

    stamp = datetime.now().astimezone().strftime("%H:%M")
    parts.append(f"last {span / 60:.0f}m @ {stamp}")
    return "\n".join(parts)[:MAX_NOTE]


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
    post_every = max(60, cfg["post_interval_sec"])  # never faster than once a minute
    groups = present_groups(cfg.get("groups"))
    group_order = list(groups) if groups else [""]

    samples = deque()
    last_post = 0.0

    while True:
        now = time.monotonic()
        try:
            data = read_grouped_counters(groups) if groups else {"": read_counters(cfg["iface"])}
        except Exception as e:  # a transient counter read failure shouldn't kill the daemon
            print(f"sample failed: {e}", file=sys.stderr, flush=True)
            time.sleep(sample_every)
            continue

        samples.append((now, data))
        while len(samples) > 2 and now - samples[0][0] > window:
            samples.popleft()

        if len(samples) >= 2 and (args.once or now - last_post >= post_every):
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
