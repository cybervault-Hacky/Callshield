# CALLSHIELD

> **Local fraud-number analysis and protection foundation — now with persistent background engine.**
>
> Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls.
>
> Phase 2 — Advanced Intelligence builds on Phase 1.
>
> Phase 3 — Background Engine adds a real Termux daemon, event queue, and IPC. **It does not yet receive or reject real Android phone calls.**
>
> **CALLSHIELD does NOT yet intercept or reject live phone calls.**
> It runs locally on Android/Termux (or any Linux system), keeps its database
> on-device, and never uploads your phone numbers.

```
CALLSHIELD
────────────────────────────────────────
Fraud Protection Engine

Status      READY
Engine      LOCAL
Database    ONLINE
Protection  STANDBY
Profile     BALANCED

Use `callshield --help` for commands.
```

---

## Features

- **Professional CLI** — clean, minimal, scriptable, no gimmicks.
- **SQLite database** — local, persistent, parameterized queries only, WAL, 0600 perms.
- **Number normalization** — spaces, punctuation, `+`, `00` prefixes, default country handling, strict validation.
- **Blacklist / Whitelist** — explicit user control with clear precedence: **WHITELIST > BLACKLIST > REPUTATION**. Conflicts are detected and reported.
- **Advanced reputation engine** — six tiers (TRUSTED / SAFE / UNKNOWN / SUSPICIOUS / HIGH_RISK / MALICIOUS) derived purely from local signals.
- **Modular signal system** — every signal is independently testable, deterministic, explicitly weighted, visible.
- **Deterministic, explainable risk scoring (0–100)** — no ML; confidence (0–100) separate.
- **Historical behavior analysis** — prior scans/blocks/reports per number.
- **Number intelligence** — safe local pattern checks (repeated digits, length, invalid chars) as weak signals.
- **Local user reports** — `callshield report <number>` contributes capped signal.
- **Protection profiles** — RELAXED / BALANCED / STRICT (tune thresholds/weights only).
- **Event logging** — every analysis recorded; masked by default (`--full` reveals).
- **JSON output** — `callshield scan <number> --json`; `QUIET` mode.
- **Persistent background daemon (Phase 3)** — real Linux process, PID + socket, `start`/`stop`/`status`, graceful shutdown, stale-PID recovery, never kills unrelated PIDs.
- **Event pipeline** — bounded thread-safe queue (default 256), `NUMBER_SCAN`/`USER_REPORT`/`BLOCK_ACTION`/`ALLOW_ACTION`/`SYSTEM`/`HEARTBEAT` (extensible, no fake `INCOMING_CALL`).
- **Event processor** — validates, normalizes, calls `analyze_number()`, persists, logs, updates metrics; per-event exception isolated.
- **Local IPC** — Unix domain socket `~/.callshield/run/callshield.sock` (700), JSON, size-limited (16KB req/64KB resp), timeout, no `eval`/`exec`, no TCP/network listener.
- **Health monitoring** — uptime, PID, queue size/peak, processed/failed/received/dropped, last event/heartbeat, DB status, memory.
- **Heartbeat** — configurable (default 30s), lightweight state file + DB `heartbeat`.
- **Metrics** — `callshield metrics` (uptime, events, high-risk, blocked, queue peak).
- **Daemon logging + rotation** — `~/.callshield/logs/daemon.log` (2MB ×3, size-based, no leak).
- **Resource control** — bounded queue, sleeps when idle, no busy loops, transactions, timeouts.
- **Crash recovery** — single malformed event never kills daemon; fatal init exits cleanly.
- **Offline-first, privacy-preserving** — zero network, no analytics, masked logs.
- **Termux-friendly** — pure stdlib, no root, no GUI/APK, PID/socket in `~/.callshield/run`.
- **Well tested** — 128 unit tests covering every subsystem.

---

## Architecture

```
callshield/
├── callshield/
│   ├── __init__.py
│   ├── __main__.py           # python -m callshield
│   ├── cli.py                # argparse CLI (thin, --watch, metrics, daemon, event)
│   ├── config.py             # JSON config + profiles + daemon/IPC settings
│   ├── database.py           # SQLite + migrations + indexes
│   ├── detector.py           # analyze_number() core API (detector never depends on daemon)
│   ├── normalizer.py
│   ├── logger.py             # file + DB events, rotation via daemon
│   ├── utils.py
│   ├── models.py
│   ├── reputation.py         # Phase1 compat
│   ├── scoring.py
│   ├── daemon/               # Phase 3 — persistent engine
│   │   ├── __init__.py       # re-exports legacy daemon API (status/start/stop)
│   │   ├── service.py        # DaemonService (queue, processor, heartbeat, health, IPC, signals)
│   │   ├── process.py        # PID/socket/run-dir management, stale detection, verify callshield
│   │   ├── heartbeat.py      # Heartbeat thread (configurable interval)
│   │   ├── health.py         # HealthMonitor (uptime, queue, processed/failed, DB, memory)
│   │   ├── signals.py        # SIGTERM/SIGINT/SIGHUP handling
│   │   └── recovery.py       # validate_startup, per-event recovery
│   ├── events/               # Phase 3 — event pipeline
│   │   ├── __init__.py
│   │   ├── types.py          # VALID_EVENT_TYPES, sources
│   │   ├── models.py         # Event(event_id, event_type, timestamp, source, number, payload)
│   │   ├── queue.py          # EventQueue (bounded, thread-safe, metrics)
│   │   └── processor.py      # EventProcessor (calls analyze_number)
│   ├── intelligence/         # Phase 2
│   │   ├── __init__.py
│   │   ├── signals.py        # modular signals
│   │   ├── reputation.py     # 6-tier classifier
│   │   ├── behavior.py       # history + number_intelligence
│   │   ├── confidence.py
│   │   └── profiles.py
│   └── rules/                # Phase 2
│       ├── __init__.py
│       ├── engine.py
│       └── defaults.py
├── data/                     # Git-kept seed only; runtime is ~/.callshield/data
├── logs/                     # Git-kept .gitkeep; runtime is ~/.callshield/logs
├── tests/                    # 128 tests (Phase1/2/3)
├── scripts/
│   ├── install.sh
│   └── uninstall.sh
├── pyproject.toml
├── VERSION (0.3.0)
└── README.md
```

Filesystem layout (Termux-safe, outside repo unless `CALLSHIELD_DATA_DIR` set):

```
~/.callshield/
├── config/config.json  (also ~/.callshield/data/config.json for compat)
├── data/callshield.db
├── logs/callshield.log
├── logs/daemon.log (rotated: daemon.log.1, .2)
├── run/callshield.pid
├── run/callshield.sock  (700, Unix socket, local-only)
├── run/heartbeat.json
└── state/
```

Event flow:

```
Event Source (CLI test, future call-screening)
     ↓
EventQueue (bounded 256, thread-safe)
     ↓
EventProcessor → analyze_number() → DetectionResult
     ↓
Database + Logs + Health Metrics
     ↑
Heartbeat / HealthMonitor / IPC (Unix socket)
```

Core API remains:

```python
from callshield.detector import analyze_number
result = analyze_number("+919876543210")
# result.verdict, risk_score, confidence, recommended_action, signals, ...
```

---

## Installation

### Requirements

- Python 3.8+, POSIX shell, no root

### Termux

```bash
pkg update && pkg upgrade
pkg install python git
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

Idempotent — re-running never wipes `~/.callshield/data/callshield.db`.

### Linux (desktop)

```bash
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

Installer: verifies Python, creates `~/.callshield/{data,logs,run,state}` (700), installs wrapper to `$PREFIX/bin` (Termux) or `~/.local/bin` (+ symlink to `/usr/local/bin` if writable), initializes DB, runs 128 tests.

### Uninstall

```bash
bash scripts/uninstall.sh           # keeps ~/.callshield
bash scripts/uninstall.sh --purge   # removes DB, logs, config, run
```

### Termux:Boot concept (future, not installed automatically)

```
Termux:Boot → callshield daemon start → CALLSHIELD (STANDBY, IPC ready)
Documented only; Phase 3 is compatible but does not auto-install.
```

---

## Quick Start

```bash
callshield status                       # daemon + DB status
callshield scan +919876543210           # analyze (explainable)
callshield scan +919876543210 --json    # machine-readable
callshield scan +919876543210 --quiet   # only ALLOW/MONITOR/BLOCK
callshield block +919876543210          # blacklist
callshield allow +919876543210          # whitelist (wins over blacklist)
callshield report +919876543210 --reason "suspected scam"
callshield reputation +919876543210     # 6-tier + history
callshield history +919876543210        # masked, --full to reveal
callshield signals +919876543210        # breakdown
callshield logs --limit 20 --full
callshield config show                  # includes daemon section
callshield config profile strict        # relaxed/balanced/strict
callshield start                        # daemon STANDBY (PID + Queue READY)
callshield status                       # Daemon RUNNING, Uptime, Queue 0/256, Events, Last Heartbeat, NOT CONNECTED
callshield status --watch               # live refresh (Ctrl+C to exit watch, daemon stays)
callshield metrics                      # uptime, received/processed/failed/dropped, high-risk, queue peak
callshield event test +919876543210     # TEST NUMBER_SCAN via daemon queue (not a phone call)
callshield daemon info                  # daemon info via IPC
callshield daemon health                # health check
callshield daemon restart               # stop + start
callshield stop                         # graceful shutdown (drains queue, flushes logs, removes PID/socket)
```

---

## Commands

| Command | Description |
|---|---|
| `callshield` | Banner (READY/LOCAL/ONLINE/STANDBY) + disclaimer |
| `callshield --help`, `--version`, `version` | Help / `0.3.0 Phase 3 — Background Engine` |
| `callshield status` | Full daemon status (IPC when running, PID fallback otherwise) |
| `callshield status --watch [--interval N]` | Live watch (default 2s, Ctrl+C exits watch only) |
| `callshield scan <number> [--json] [--quiet] [--no-log]` | Analyze |
| `callshield block/unblock`, `allow/unallow` | List management (conflict reported, whitelist wins) |
| `callshield report <number> [--reason]` | Local report (capped) |
| `callshield blacklist/whitelist list` | Tables |
| `callshield reputation/history/signals <number>` | Intelligence |
| `callshield logs [--limit N] [--full]` | Events (masked) |
| `callshield config [show]` / `config profile <mode>` / `config set <k> <v>` | Config (validates) |
| `callshield start` / `stop` | Daemon (backward compat, maps to `daemon start/stop`) |
| `callshield daemon start/stop/restart/status/info/health` | Explicit daemon management |
| `callshield metrics` | Real daemon metrics (IPC, fallback to DB when stopped) |
| `callshield event test <number> [--reason]` | TEST event via daemon pipeline (labels TEST, not a call) |

All Phase 1/2 commands preserved.

---

## Risk Scoring

Deterministic sum of signal deltas, clamp 0–100, tiers `0 UNKNOWN / 1–29 LOW / 30–59 MEDIUM / 60–84 HIGH / 85–100 CRITICAL`. Confidence separate (signal confidences + agreement + history - conflict). `WHITELIST > BLACKLIST > REPUTATION`. Weak `number_format_anomaly` (+5 max) never alone causes BLOCK.

Signals: `blacklist_match +80`, `previous_block_events +20`, `previous_suspicious_events +15`, `rapid_repeat_events +10`, `manual_user_report +25`, `reputation_history +10`, `number_format_anomaly +5`, `whitelist_match -100`.

Profiles tune thresholds/weights: RELAXED 80, BALANCED 60, STRICT 50.

---

## Database

`~/.callshield/data/callshield.db` (WAL, 0600, parameterized). Tables: `schema_version`, `numbers`, `events` (+`confidence`/`reputation`/`risk_level`), `reports`, `settings`. Indexes `idx_numbers_number`, `idx_events_number_ts`, etc. Migration v1→v2→v3 preserves data, backs up.

---

## Configuration

`~/.callshield/data/config.json` (600). Includes Phase 3:

| Key | Default | Description |
|---|---|---|
| `daemon_enabled` | true | Enable daemon |
| `heartbeat_interval` | 30 | Heartbeat seconds (5–600) |
| `event_queue_size` | 256 | Bounded queue (16–2048) |
| `shutdown_timeout` | 10 | Graceful shutdown seconds (1–60) |
| `status_refresh_interval` | 2 | Watch refresh (1–10) |
| `max_log_size` | 2097152 | Daemon log 2MB (64KB–100MB) |
| `max_log_files` | 3 | Rotated files (1–10) |
| `ipc_enabled` | true | Unix socket IPC |
| `run_dir` | `~/.callshield/run` | PID + socket + heartbeat |
| `socket_path` | `~/.callshield/run/callshield.sock` | 700 socket |
| `daemon_log_file` | `~/.callshield/logs/daemon.log` | Rotated daemon log |

Plus Phase 1/2 keys (profile, thresholds, weights, `database_path`, `pid_file`, `log_file`, etc.). Validated, `config set` coerces types, `config profile` resets thresholds/weights.

---

## Security

- No network listener; IPC is local Unix socket only (700, size-limited 16KB req, timeout, no `eval`/`exec`/shell, validates `command` whitelist).
- Parameterized SQL, validated CLI/config, sanitized report reasons (500 char), safe JSON, PID verified via `/proc/<pid>/cmdline` contains `callshield`/`python`, never kills unrelated PID, stale-PID age check.
- Masked numbers by default; `0600`/`0700` perms; no analytics/IDs/telemetry; offline.
- Per-event exception isolated, daemon continues; fatal init (DB/config/IPC) exits cleanly.

---

## Termux Compatibility

- Pure stdlib, `python3`, no root, no GUI/APK.
- Installer creates `~/.callshield/{data,logs,run,state}` 700, handles `$PREFIX/bin` vs `~/.local/bin` + `/usr/local/bin` symlink, adds to PATH if needed, documents `Termux:Boot` concept without installing outside repo.
- Daemon sleeps when idle (`queue.get(timeout=0.5)`, `heartbeat wait 1s`, `status wait 1s`), bounded queue prevents memory growth, no busy loops, low idle CPU.

---

## Development

```bash
git clone <repo-url> Callshield
cd Callshield
python3 -m callshield --help
python3 -m unittest discover -s tests  # 128 tests
```

Core engine has no CLI imports; `analyze_number()` stable for future `CallScreeningService`.

---

## Testing

```bash
python3 -m unittest discover -s tests
# 128 tests: normalizer, database, scoring, detector, config, signals, reputation, behavior, confidence, profiles, reports, rules, daemon, process, events, queue, health, ipc, metrics, recovery
```

Spec-required suites: `test_daemon` (start/duplicate/stop/stale/cleanup), `test_process` (pid alive/write/read/clear/stale), `test_events` (create/valid/invalid/payload limit, processor number/system/missing/malformed), `test_queue` (bounded, full→dropped, thread-safe, close), `test_health` (snapshot/heartbeat fresh/stale/DB/queue/metrics), `test_ipc` (valid status/metrics/invalid/oversized/socket perms/cleanup), `test_metrics` (CLI + HealthMonitor), `test_recovery` (event exception isolated, malformed, DB failure, SIGTERM graceful).

All Phase 1+2 still pass.

---

## Roadmap

- **Phase 1** — Foundation ✅
- **Phase 2** — Advanced Intelligence ✅
- **Phase 3** — Background Engine ✅ (this release)
- **Phase 4** — Optional crowd-sourced (opt-in, privacy-preserving)
- **Phase 5** — Contact integration
- **Phase 6** — Notifications
- **Phase 7** — Hardened daemon
- **Future** — `CallScreeningService` (calls `analyze_number()`)

Nothing beyond promised.

---

## Limitations

- **Phase 3 provides the background processing infrastructure. It does not yet receive or reject real Android phone calls.** `start` is `STANDBY`, `Call Screening: NOT CONNECTED`, `event test` is labeled `TEST EVENT` not a call.
- Normalizer curated country table; weak pattern signals never alone cause BLOCK.
- No network/ML/cloud/GUI/APK; offline; `INCOMING_CALL` not implemented (extensible types only).
- Daemon is not auto-restarted internally; watchdog foundation only (alive/heartbeat/queue/DB checks).

---

## Exit Codes

0 success / 1 general / 2 usage / 3 invalid number / 4 DB / 5 config / 6 daemon

---

## License

MIT — see `LICENSE`.

---

**Remember:** CALLSHIELD Phase 3 provides the background processing infrastructure. It does not yet receive or reject real Android phone calls. Future phases will connect the daemon to Android’s privileged call-screening layer.
