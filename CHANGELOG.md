# Changelog

## 0.3.0 — Phase 3: Background Engine

### Added
- Persistent Termux-first Python daemon in `callshield/daemon/` with startup validation, atomic PID ownership, bounded worker queue, heartbeat, health monitoring, Unix signals, SIGHUP configuration reload, recovery, and graceful shutdown.
- Phase 3 event pipeline in `callshield/events/` with exactly six local event types: `NUMBER_SCAN`, `USER_REPORT`, `BLOCK_ACTION`, `ALLOW_ACTION`, `SYSTEM`, and `HEARTBEAT`.
- Strict event model with UUID, timezone-aware timestamp, bounded source/number fields, JSON-only payloads, and an 8 KiB UTF-8 payload limit.
- Bounded thread-safe `EventQueue` (256 default) with enqueue/dequeue/size/drain APIs and received, dropped, and peak tracking.
- `EventProcessor` integration with the existing Phase 2 `analyze_number()` engine; action events remain advisory records and never perform call blocking.
- Owner-only `AF_UNIX` IPC at `~/.callshield/run/callshield.sock` (0600), strict JSON/UTF-8 validation, 16 KiB request and 64 KiB response bounds, timeouts, and the `status`, `metrics`, `health`, `daemon_info`, `event`, `stop`, and `ping` operations.
- CLI lifecycle commands: `callshield daemon start|stop|restart|status|info|health`, backward-compatible `start`/`stop`, `status --watch`, `metrics`, and clearly labeled `event test <number>`.
- Stopped-daemon metric fallback using persisted database counters and a bounded last-session snapshot.
- Runtime layout `~/.callshield/{data,logs,run,state}` with owner-only permissions and no root requirement.
- Phase 3 settings for heartbeat, queue bounds, shutdown/watch intervals, IPC timeout, payload limit, local paths, and log rotation, all validated with sane bounds.
- 163 Python tests, including the required daemon, process, events, queue, health, IPC, metrics, and recovery suites; all Phase 1/2 behavior remains covered.

### Security
- PID ownership requires the exact `python -m callshield _run-fg` command from `/proc/<pid>/cmdline`; generic Python processes are rejected, and PID start identity is rechecked before a final signal.
- Stale recovery removes only owner-owned CALLSHIELD PID files and stale Unix sockets. Active sockets, symlinks, regular files, and unrelated processes are preserved.
- Malformed, oversized, timed-out, or failing events/IPC requests are isolated and cannot terminate the daemon.
- Queue and IPC memory are bounded; there is no TCP/network listener, shell execution, privilege escalation, live call interception, or automatic call rejection.

### Notes
- Phase 3 is Python-only and Termux-first.
- `Call Screening: NOT CONNECTED` is intentional. Android integration and live call handling are not implemented; Phase 4 remains future work.

## 0.2.0 — Phase 2: Advanced Intelligence

### Added
- Advanced local reputation engine with five tiers: UNKNOWN / SAFE / TRUSTED / SUSPICIOUS / HIGH_RISK / MALICIOUS.
- Modular signal engine (`intelligence/signals.py`). Each signal returns a
  structured `SignalResult(name, score, confidence, reason)` and is
  independently testable.
- Deterministic, explainable risk scoring with signal-by-signal breakdowns.
- Separate confidence score (0–100) communicating how strong the evidence
  is, independent from the risk score.
- Historical behavior analysis (`intelligence/behavior.py`) tracking prior
  events, block decisions, and recent repeat-scan activity.
- User report system: `callshield report <number> [--reason]`.
- Protection profiles: RELAXED / BALANCED / STRICT, each tuning risk
  thresholds and signal weights.
- New CLI commands:
  - `callshield reputation <number>` — show local reputation for a number.
  - `callshield history <number>` — show analysis history for a number.
  - `callshield signals <number>` — show signal breakdown for a number.
  - `callshield report <number> [--reason]` — file a local user report.
  - `callshield scan <number> --json` — machine-readable JSON output.
  - `callshield scan <number> --quiet` — only print recommended action.
  - `callshield config profile <relaxed|balanced|strict>`.
- Number intelligence (format anomalies, suspicious repeated-digit runs).
- Safe SQLite schema migration from Phase 1 (`schema_version` table).
- Masked-number display in `callshield logs` by default; `--full` reveals.

### Improved
- CLI analysis output now shows Reputation, Confidence, and a detailed
  Signals breakdown.
- Database schema extended with `confidence`, `reputation`, and `risk_level`
  columns on `events`; new `reports` table.
- Daemon heartbeat records engine PID & mode in the settings table.
- Better error messages and consistent exit codes.
- Signal weights are configurable and profile-aware.

### Notes
- Phase 2 is fully offline. No network calls, no telemetry, no cloud
  dependency.
- Phase 2 is still a CLI analysis foundation. It does NOT intercept or
  reject live phone calls — see README.

## 0.1.0 — Phase 1: Foundation
- Initial release: CLI, SQLite database, blacklist/whitelist, deterministic
  risk scoring, event logging, configuration, daemon foundation, install
  and uninstall scripts, unit tests.
