# CALLSHIELD

CALLSHIELD is a local-first phone-number security tool for Termux and Linux. It analyzes numbers, scores risk, and can screen incoming-call requests through a local daemon — entirely on your device.

It is a CLI and terminal UI project. It is not a standalone Android app, not a cloud service, and not an online identity or phone-number lookup.

**Version 0.8.0** — MIT License

## What is CALLSHIELD?

CALLSHIELD helps you inspect a phone number using only data that already exists on your machine: your scans, reports, lists, trust settings, and an optional contact file you import yourself.

There is no remote reputation API, no web scraping, and no account. An optional Android screening bridge can talk to the local daemon over a Unix socket. That bridge is **NOT VERIFIED** and is not the primary product.

## Features

- Phone-number analysis and deterministic risk scoring
- Local reputation, behavioral intelligence, and trust
- Blacklist, whitelist, user reports, and history
- Background daemon with owner-only Unix socket IPC
- Fail-open screening: uncertain or broken state allows the call
- Universal Number Intelligence (`callshield number`)
- Explicit CSV/JSON contact import (never automatic)
- Terminal UI with nine interface languages
- Policy engine with DRY_RUN / ACTIVE modes and emergency off
- Privacy-first local storage (masked numbers in the UI)

## Requirements

- Termux or Linux
- Python 3.8 or newer
- Standard library only (no extra pip packages required)
- Android bridge is optional and not required to use the CLI or TUI

## Installation

```bash
pkg update
pkg install python git
git clone https://github.com/cybervault-Hacky/Callshield.git
cd Callshield
chmod +x install.sh
./install.sh
```

On a regular Linux desktop the same `./install.sh` works. The installer creates `~/.callshield/`, puts a `callshield` wrapper on your PATH, and initializes the local database. Root is not required.

```bash
callshield version
callshield
```

## Quick start

```bash
callshield                      # terminal interface
callshield scan +919XXXXXXXXX
callshield number +919XXXXXXXXX
callshield reputation +919XXXXXXXXX
callshield intelligence +919XXXXXXXXX
callshield status
callshield metrics
callshield doctor
callshield daemon start
```

## Universal Number Intelligence

`callshield number` builds a local profile from what CALLSHIELD already knows:

- normalization
- reputation and history
- reports and trust
- behavioral intelligence
- policy-related measurements
- contacts you explicitly imported

```bash
callshield number +919XXXXXXXXX
callshield number +919XXXXXXXXX --json
```

### Local contacts

CALLSHIELD does not read Android contacts and does not discover a person's identity.

```bash
callshield contacts import contacts.csv
callshield contacts status
callshield contacts list
callshield contacts scan
callshield contacts remove +919XXXXXXXXX
callshield contacts clear
```

Supported import formats: **CSV** and **JSON** with fields such as `name` and `number`.

If the number is in your imported file, the stored name may be shown and labelled **Source: Local Contacts**.

Otherwise:

```text
Name:      NOT AVAILABLE
Age:       NOT AVAILABLE
Identity:  NOT VERIFIED
```

Age and identity are never guessed.

## Privacy

- All analysis and storage stay on this device
- No cloud reputation, telemetry, analytics, or hidden network calls
- The daemon listens on a local Unix socket only (`AF_UNIX`)
- The UI masks phone numbers
- Contact data is imported only when you run `contacts import`
- New contact storage keeps a hash, a masked number, and a display name

SQLite files on disk are owner-restricted. The project does not add a separate encryption layer.

## Screening and safety

Fresh installs start with screening **disabled** and mode **DRY_RUN**. Recommendations can be recorded without rejecting a call.

**ACTIVE** mode requires an explicit confirmation prompt. Even then, whitelist and emergency-off take precedence. If configuration, policy, the database, or the daemon is unavailable, CALLSHIELD **fails open** (ALLOW).

```bash
callshield screening status
callshield screening enable          # DRY_RUN
callshield screening mode active     # confirmation required
callshield emergency-off
callshield emergency-reset
```

Android / device readiness is shown as **NOT VERIFIED**. Physical call rejection on a phone has not been verified in this project.

## Terminal interface

`callshield` with no arguments opens the TUI (when you have a real terminal).

Screens include Dashboard, Scan Center, Number Intelligence, Reputation, Intelligence, Screening, Policy, Blocks, Reports, History, Daemon, Live Monitor, Settings, and About.

| Key | Action |
|-----|--------|
| Arrows | Move |
| Enter | Select |
| 1–9 | Jump to a menu item |
| Esc | Back (exits at the root) |
| q | Quit |
| r | Refresh |

If stdin/stdout is not a terminal, CALLSHIELD prints a short status banner instead.

### Languages

Settings can switch the interface to English, Hindi, Hinglish, Spanish, French, Japanese, Chinese, Portuguese, or Russian. Command names and status words stay in their canonical English form.

## CLI reference

| Command | Purpose |
|---------|---------|
| `callshield` | Open the terminal interface |
| `version` | Show version |
| `status` | Engine and daemon status |
| `scan <number>` | Analyze a number |
| `number <number>` | Universal Number Intelligence |
| `reputation [number]` | Local reputation |
| `intelligence [number]` | Behavioral intelligence |
| `signals <number>` | Signal breakdown |
| `history <number>` | Events for one number |
| `logs` | Recent events |
| `report <number>` | File a local report |
| `block` / `unblock` | Blacklist |
| `allow` / `unallow` | Whitelist |
| `blacklist list` / `whitelist list` | Show lists |
| `trust` / `untrust` | Local trust |
| `contacts import\|status\|list\|remove\|clear\|scan` | Imported contacts |
| `start` / `stop` | Daemon lifecycle |
| `daemon start\|stop\|restart\|status\|info\|health` | Daemon control |
| `metrics` | Counters |
| `screening status\|enable\|disable\|mode\|policy\|health\|metrics` | Screening |
| `policy test` | Simulate a policy decision |
| `emergency-off` / `emergency-reset` | Force ALLOW / reset |
| `blocks` / `blocks inspect <id>` | Applied blocks |
| `doctor` | Local diagnostics |
| `config show` / `config set` / `config profile` | Configuration |
| `event test <number>` | Send a test scan through the daemon |

`scan`, `number`, `reputation`, `intelligence`, `doctor`, and `contacts scan` accept `--json` where implemented.

## Architecture

```text
User
  ↓
CLI / TUI
  ↓
CALLSHIELD engines
  ├─ Number analysis
  ├─ Reputation
  ├─ Intelligence
  ├─ Policy
  └─ Screening
  ↓
Local database / Unix IPC
```

## Data and storage

Installed state lives under `~/.callshield/` (override with `CALLSHIELD_HOME`):

| Path | Contents |
|------|----------|
| `data/` | SQLite database and config |
| `logs/` | Application and daemon logs |
| `run/` | PID file and Unix socket |
| `state/` | Emergency-off marker |

## Project status

Current release **0.8.0** includes adaptive intelligence, the professional terminal UI, and Universal Number Intelligence.

## Development

```bash
git clone https://github.com/cybervault-Hacky/Callshield.git
cd Callshield
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -q
```

## About

**Developer:** Sarthak Bharambe  
**YouTube:** CyberVault  
**Instagram:** @cyber_vault123

## License

MIT. See [LICENSE](LICENSE).
