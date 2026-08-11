# Changelog

## 0.6.0 — Phase 6: Hardening & Reliability

### Added
- Strict versioned IPC envelopes for every request with UUID and timezone timestamp validation.
- Thread-safe replay protection with a 5-minute default freshness window, 4096-entry bounded cache, expiry, duplicate detection, and deterministic eviction.
- Strict JSON duplicate-key, constant, nesting, key-count, array-size, request-size, and response-size validation while retaining Unix sockets only.
- Durable atomic file writes: unique same-directory temporary file, flush, file fsync, restrictive mode, atomic replace, and parent-directory fsync.
- Fail-safe config loading for empty, malformed, or invalid files; runtime falls back to screening disabled, DRY_RUN, and unconfirmed ACTIVE state while preserving the corrupt file for doctor.
- SQLite schema version 5, full/quick integrity checks, schema/PRAGMA validation, WAL/foreign-key enforcement, FULL synchronous mode, bounded lock behavior, and screening indexes for event ID, applied action, and policy action.
- `callshield doctor`, `callshield doctor --json`, and `callshield doctor --repair` for runtime, Python, database, schema, config, daemon, IPC, permissions, Android bridge, screening, policy, and storage diagnostics.
- Safe masked block history with `callshield blocks` and `callshield blocks inspect <id>`.
- `SECURITY_AUDIT.md` with explicit PASS and NOT TESTED distinctions.
- Reproducible policy microbenchmark script and `PERFORMANCE_PHASE6.md` with measured p50/p95/p99 results and clearly limited scope.
- 51 dedicated Phase 6 Python tests (271 total) covering replay, IPC parsing, config durability, DB integrity, resource bounds, policy safety, 5/10-request concurrency, doctor repair, static audit, and block inspection.

### Hardened
- SIGHUP reload propagates safe config to processor/policy, health, signal handling, and heartbeat without terminating the daemon.
- Emergency reset uses a synced atomic unlink and remains disabled DRY_RUN.
- Startup performs SQLite quick integrity/schema validation before accepting work.
- Android screening and feedback now carry fresh timestamps and independent request IDs; feedback identifies the original screening request separately.
- Android service lifecycle cancels its bounded coroutine scope; invalid/lifecycle/transport state remains fail-open.
- Concurrent IPC workers remain bounded at 10 and malformed/disconnected clients remain isolated.

### Safety and verification
- All system/config/database/replay/IPC failures continue to produce ALLOW for screening decisions.
- No TCP/HTTP listener, root requirement, unsafe deserialization, dynamic execution, shell execution, or plaintext screening log was added.
- Python suite: 271 passed; all 220 Phase 1–5 tests preserved.
- Android build/device and end-to-end phone performance remain NOT VERIFIED due missing JDK, Gradle, SDK, emulator, and device.
- Phase 7 has not started.

## 0.5.0 — Phase 5: Active Call Protection

### Added
- Isolated `callshield/policy/` decision layer with structured policy results; it never invokes Android or rejects calls directly.
- Configurable RELAXED (92/90), BALANCED (85/80), and STRICT (80/75) active-block/confidence thresholds, each validated from 0 to 100.
- Explicit `ACTIVE` mode requiring interactive confirmation. Fresh installs default to `screening_enabled=false`, `screening_mode=DRY_RUN`, and no active confirmation marker.
- Owner-only `~/.callshield/state/emergency_off` switch plus idempotent `callshield emergency-off` and `callshield emergency-reset` commands. Emergency activation also persists disabled DRY_RUN state so reset cannot resume active protection.
- `callshield screening policy` display/selection and safe `callshield policy test` simulation.
- Schema v3→v4 migration adding policy action/name/threshold/reason, emergency state, active applied action, and Android-confirmed rejection fields while preserving Phase 4 rows.
- Versioned `screening_feedback` IPC acknowledgement. `Actually Rejected` increments only after Android confirms delivery of a valid ACTIVE BLOCK response.
- Phase 5 health/metrics for policy errors, block recommendations, applied blocks, actual rejections, emergency state, and last screening.
- Android bridge validation requiring the exact `applied_action=BLOCK` and `mode=ACTIVE` pair before requesting rejection; all other responses remain ALLOW.
- 31 Phase 5 Python tests (220 total) plus updated Kotlin test sources for active/dry-run/error/emergency decisions.

### Safety
- Whitelist remains an absolute ALLOW override in every mode.
- Invalid policy, threshold, activation state, mode, input, response, timeout, database state, bridge state, or emergency state fails open to ALLOW.
- General `screening enable` always enables DRY_RUN; ACTIVE cannot be selected through generic config editing.
- Emergency reset never enables screening or ACTIVE mode.
- Applied blocks and confirmed rejections are distinct metrics; no device rejection is claimed without feedback.
- Unix IPC only; no TCP/HTTP server, root requirement, dynamic execution, replay protection, doctor command, or Phase 6 diagnostics.

### Verification notes
- Python/Termux suite: 220 passed.
- Android build/device verification remains unavailable because JDK, Gradle, Android SDK, emulator, and physical device are absent.
- Performance benchmark was not independently verified.
- Phase 6 has not started.

## 0.4.0 — Phase 4: Android Screening Bridge

### Added
- Minimal Kotlin Android project under `android/` with `CallShieldScreeningService`, local `BridgeClient`, strict `Protocol`, immutable `ScreeningResult`, role-request activity, manifest, and unit-test sources.
- Exact versioned `callshield/1` request contract: `protocol`, UUID `request_id`, `number`, and `source=android_call_screening` over the existing Unix socket.
- Phase 4 `INCOMING_CALL` event and `SOURCE_ANDROID`, routed through the existing `EventProcessor` and Phase 2 `analyze_number()` engine.
- Safe schema v2→v3 migration and `screening_events` audit table with number, masked number, SHA-256 hash, risk, confidence, verdict, recommendation, applied action, reason, latency, source, and event ID.
- DRY_RUN-only settings: `screening_enabled`, fixed `screening_mode=DRY_RUN`, and bounded `screening_timeout_ms` (200–5000; default 1500).
- `callshield screening status|enable|disable|mode|health|metrics` with honest device state (`Android: NOT VERIFIED`).
- Screening health/metrics for incoming, screened, timeout, bridge-error, high-risk, allowed, unknown, block-recommended, and blocked counts.
- Bounded concurrent Unix IPC handling for simultaneous screening requests while preserving Phase 3 queue and lifecycle behavior.
- 26 Phase 4 Python tests (189 total) plus Kotlin test sources for protocol, fail-open bridge behavior, and immutable ALLOW results.

### Safety
- Every daemon response and Android call response applies `ALLOW`, including BLOCK recommendations, invalid input, timeout, unavailable daemon, malformed response, database failure, and internal error.
- Database schema constrains persisted `applied_action` to `ALLOW` and `mode` to `DRY_RUN`; `screening_blocked` and `Actually Rejected` remain zero.
- Android requests no camera, microphone, contacts, SMS, location, storage, accessibility, or Internet permission.
- Local Unix IPC only; no network server, root requirement, shell execution, active policy engine, emergency-off feature, or automatic rejection.

### Verification notes
- Python/Termux suite: 189 passed.
- Android build and device test were not verified because Gradle, Java/JDK, Android SDK, emulator, and physical device were unavailable.
- Direct app access to Termux's private 0600 socket is commonly blocked by Android UID/SELinux isolation and is documented without an insecure fallback.
- Phase 5 active protection has not started.

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
