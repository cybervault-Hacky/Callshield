# Changelog

## 0.4.0 — Phase 4: Android Screening Bridge

### Added
- Android CallScreeningService bridge (`android/`): `CallShieldScreeningService.kt` (extends CallScreeningService, handles incoming calls, extracts number, normalizes, sends to daemon with timeout, logs, returns dry-run ALLOW), `BridgeClient.kt` (Unix socket LocalSocket, fallback paths, 1500ms timeout, size-limited 16KB/64KB, no eval/exec, validates protocol/request_id/number), `Protocol.kt` (versioned callshield/1, request/response, size limits, timeout/error handling), `ScreeningResult.kt` (dry-run never blocks), `BridgeSetupActivity.kt` (minimal no-UI)
- Real incoming-call screening event `INCOMING_CALL` (Phase 3 had no fake, Phase 4 extends `events/types.py` with `INCOMING_CALL` + `SOURCE_ANDROID`, extensible)
- Versioned bridge protocol (JSON, `protocol: callshield/1`, `request_id` uuid, `number`, `timestamp` → response `risk_score`, `confidence`, `verdict`, `recommended_action`, `applied_action`, `mode: DRY_RUN`, validated)
- Screening timeout handling (default 1500ms, configurable `screening_timeout_ms` 200–5000, on timeout returns `UNKNOWN`/`ALLOW`/`SCREENING_TIMEOUT`, fail-safe)
- Dry-run mode (`screening_mode=DRY_RUN` default, `screening_enabled` toggle, `callshield screening enable/disable/mode/status/health/metrics`, Phase 4 always `applied_action=ALLOW` even if `recommended BLOCK`)
- Daemon availability handling (if STOPPED/UNAVAILABLE/CRASHED/TIMEOUT → UNKNOWN/ALLOW, never pretends screened)
- Android bridge health: `callshield screening status` (Bridge CONNECTED/AVAILABLE, Daemon RUNNING, Mode DRY_RUN, Timeout 1500ms, Live Calls READY, Auto Reject DISABLED), extends `callshield status` (Android Bridge, Screening Mode/Events, Timeouts, Bridge Errors) and `callshield metrics` (Incoming Calls, Screened, Timeouts, Bridge Errors, High Risk, Block Recommendations, Actually Rejected 0)
- Event persistence: `screening_events` table (id, timestamp, number, number_masked, number_hash, risk_score, confidence, verdict, recommended_action, applied_action, result_reason, latency_ms, source, event_id) with hash/masked privacy, `add_screening_event`/`screening_metrics`/`recent_screening_events`
- Screening log: `CALLSHIELD SCREENING EVENT` (Time, Number masked, Risk, Confidence, Verdict, Recommended BLOCK / Applied ALLOW, Mode DRY_RUN, Reason Phase 4 disabled)
- Minimal Android permissions (no CAMERA/MIC/LOCATION/SMS/CONTACTS/STORAGE/root, only BIND_SCREENING_SERVICE via system dialog, documented RoleManager)
- Termux-first: `callshield screening status` is authoritative, Android has no UI
- Android unit tests: `ProtocolTest` (9 tests: valid/invalid, response parsing, timeout, request ID, size), `ScreeningResultTest` (5 tests: dry-run, unknown, high-risk, safe, timeout), `BridgeClientTest` (4 tests: daemon unavailable, invalid number, dry-run enforcement, request ID)

### Security
- Local-only Unix socket (700, no TCP), IPC validation, request-size limits, timeout enforcement, response validation, minimal permissions, no automatic rejection (Phase 4 dry-run enforced in both Python `processor.py` and Kotlin `CallShieldScreeningService`), safe failure

### Improved
- Daemon IPC now handles `incoming_call`/`screening` synchronously with timeout via thread, updates health screening metrics, persists screening_events
- HealthMonitor now tracks `screening_received/processed/timeouts/bridge_errors/last_screening`
- CLI `metrics` and `status` extended with screening fields, `config show` includes screening config
- Database migration v2→v3 adds `screening_events` with indexes, preserves data, backup

### Notes
- Android SDK/Gradle not available in this environment — build not executed, reported as limitation, Python/Termux components fully validated (137 tests OK)
- Bridge fallback: if Termux socket inaccessible due to Android sandbox, tries `/data/local/tmp/callshield.sock`, otherwise fails safe to UNKNOWN/ALLOW, documented in `android/README.md` and `callshield/daemon/service.py`

## 0.3.0 — Phase 3: Background Engine

### Added
- Persistent background daemon (`callshield/daemon/`): `service.py` (EventQueue, Processor, Heartbeat, Health, IPC, signals), `process.py` (PID/socket/run-dir, stale detection, verify callshield, never kill unrelated), `heartbeat.py` (configurable 30s, lightweight state file + DB), `health.py` (uptime, PID, queue, processed/failed/received/dropped, last event/heartbeat, DB, memory), `signals.py` (SIGTERM/SIGINT/SIGHUP), `recovery.py` (validate_startup, per-event isolation)
- Event pipeline (`callshield/events/`): `types.py` (NUMBER_SCAN/USER_REPORT/BLOCK_ACTION/ALLOW_ACTION/SYSTEM/HEARTBEAT, extensible), `models.py` (Event with uuid, timestamp, source, payload, 8KB limit), `queue.py` (EventQueue bounded 256, thread-safe, metrics, close), `processor.py` (validate→normalize→analyze_number→persist→log→metrics)
- Local IPC via Unix domain socket `~/.callshield/run/callshield.sock` (700, JSON, 16KB req limit, timeout, no eval/exec, no TCP, validated commands: status/metrics/health/daemon_info/event/stop/ping, fallback to PID/DB when IPC unavailable)
- Health monitoring and heartbeat: `callshield status` now shows Daemon RUNNING/PID/Uptime/Engine/Database/Queue 0/256/Events Processed/Failed/Last Event/Heartbeat/Call Screening NOT CONNECTED (IPC) with PID fallback
- Real-time status: `callshield status --watch` (configurable interval, Ctrl+C exits watch only, no animation)
- Daemon logging with rotation: `~/.callshield/logs/daemon.log` (2MB ×3, size-based)
- Resource controls: bounded queue, sleep when idle (queue timeout 0.5s, heartbeat 1s), no busy loops, transactions, timeouts
- Metrics: `callshield metrics` (Uptime, Received/Processed/Failed/Dropped, High Risk, Block, Queue Peak/Size, Memory, NOT CONNECTED)
- Event injection for testing: `callshield event test <number> [--reason]` (real NUMBER_SCAN via queue, labeled TEST EVENT, not a phone call)
- New CLI: `callshield metrics`, `callshield status --watch`, `callshield daemon [start|stop|restart|status|info|health]`, `callshield event test`
- Daemon wrapper commands: `callshield daemon start/stop/restart/status` with backward compat `callshield start/stop/status`
- Startup validation (10 steps): config, DB, run/log dirs, IPC, duplicate check, queue, workers, heartbeat, RUNNING
- Filesystem layout `~/.callshield/{config,data,logs,run,state}` (run for pid/sock/heartbeat, state reserved)
- Configuration extensions: `daemon_enabled`, `heartbeat_interval` (5–600), `event_queue_size` (16–2048), `shutdown_timeout` (1–60), `status_refresh_interval` (1–10), `max_log_size` (64KB–100MB), `max_log_files` (1–10), `ipc_enabled`, `run_dir`, `socket_path`, `daemon_log_file` (all validated)
- Tests: 42 new (128 total) — `test_daemon`, `test_process`, `test_events`, `test_queue`, `test_health`, `test_ipc`, `test_metrics`, `test_recovery` plus existing Phase 1/2 preserved

### Improved
- Runtime status now reflects actual daemon state via IPC
- Process management: safe PID verification via `/proc/<pid>/cmdline`, stale- PID age check, socket cleanup on shutdown, never kills unrelated PIDs
- Background architecture: queue saturation recorded, health `is_healthy()` checks DB/heartbeat/queue
- CLI `start` now shows PID/Status/Queue/Engine + `Live call screening: NOT CONNECTED` and Phase 3 disclaimer

### Notes
- Phase 3 is still offline, no network listener, no APK/GUI/ML/cloud, no `INCOMING_CALL` fake events — extensible for Phase 4
- `Termux:Boot` compatible but not auto-installed

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
