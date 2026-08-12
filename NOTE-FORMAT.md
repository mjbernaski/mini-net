# mini-net note format

Spec for any host posting network-usage notes, so every machine reads alike.
Written for a Windows host (Vengeance); the Linux/macOS hosts follow this via `mini_net_report.py`.

## Endpoint

```
POST http://localhost:9999/note
Content-Type: application/json
Body: {"text": "<note>"}
```

Max 500 characters — longer notes are rejected. Each host posts to its own local note
service; notes are not aggregated, so do not prefix the hostname.

## Cadence

- Read interface byte counters every **15 seconds**.
- Keep a rolling **300 second (5 minute)** window.
- POST once every **60 seconds**. Never faster than 60s — the server keeps every note in memory.

## What to report

**Volume moved during the window — not rates.** No averages, no peaks.

For each group: `down` = received bytes at end of window minus at start; `up` = same for sent.
Clamp negatives to zero so a counter reset doesn't produce a negative spike.

## Format

One line per interface group, then a final line with the window and time:

```
<group> ↓ <total>  ↑ <total>
<group> ↓ <total>  ↑ <total>
last <N>m @ <HH:MM>
```

Example:

```
eth ↓ 574.2 KB  ↑ 85.3 KB
hb ↓ 40.1 KB  ↑ 23.9 KB
last 5m @ 10:43
```

Exact details:

- Group label, one space, then `↓`. **Two** spaces between the down total and `↑`.
- Lines joined with `\n`.
- Units are binary (1024): `B`, `KB`, `MB`, `GB`, `TB`. Use the largest unit where the
  value is at least 1. One decimal place, except bare bytes which are whole numbers.
  A single space between number and unit — `574.2 KB`, `1.2 GB`, `512 B`.
- `last <N>m` is the window length in whole minutes, rounded.
- Timestamp is local 24-hour `HH:MM`.
- Include a group only if its interfaces exist on this host.

## Groups

Use short lowercase labels for the physical NICs — `eth` for the wired link, and so on.
Skip virtual adapters (loopback, VPN/tun, Hyper-V and WSL vSwitches, Bluetooth, container
bridges) so tunnelled traffic isn't double-counted against the physical link it rides on.

## Counters on Windows

`Get-NetAdapterStatistics` exposes `ReceivedBytes` and `SentBytes` per adapter:

```powershell
Get-NetAdapterStatistics | Select-Object Name, ReceivedBytes, SentBytes
```

Note that `mini_net.py` itself does **not** run on Windows — it reads `/proc/net/dev` on
Linux and shells out to `netstat -ib` on macOS/BSD, with no third branch.
