# Changelog

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
