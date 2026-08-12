# Changelog

## 0.8.0 — Phase 8.5.2: Universal Number Intelligence

### Added
- Local-only Universal Number Intelligence: `callshield number <number>` and `--json`, composing the existing normalizer, ReputationEngine, BehaviorEngine and Policy data into a `UniversalNumberProfile`.
- Explicit contact import (`callshield contacts import|status|list|remove|clear|scan`) for user-provided CSV/JSON. No Android contact access, no remote lookup.
- Privacy-preserving `local_contacts` storage (hash + masked number + display name only).
- NUMBER INTELLIGENCE TUI with Number Scan, Saved Contacts, Imported Numbers, Scan History, Compare Numbers and Export Report.
- Identity fields never invent age, address, occupation or ownership. Missing data is `NOT AVAILABLE` / `NOT VERIFIED`.

### Safety
- No HTTP/TCP/DNS, no remote reputation, no scraping, no telemetry.
- Existing `callshield scan` remains unchanged. Schema version stays 7; contact table is additive.
- Fail-open: invalid or unavailable analysis still recommends ALLOW.

## 0.8.0 — Phase 8.5.1: Professional TUI Visual Redesign

### Presentation
- Restyled the terminal interface around a quiet, instrument-panel aesthetic (Apple/Linear/Vercel-inspired hierarchy): a clean two-line header (`CALLSHIELD` wordmark, right-aligned version, `Local Threat Analysis` subtitle and a single subtle rule), plain uppercase section headings instead of dash-filled rules, and spacing-driven layout.
- Dashboard rebuilt as a vertical, focused posture report: SYSTEM (Daemon, Engine, Database, IPC, Policy), THREAT OVERVIEW (Events, High Risk, Recommended, Rejected), INTELLIGENCE (Profiles, Observations, Trend), QUICK ACTIONS and a compact `Daemon/Policy/Screening` status strip.
- Menus are now unnumbered with a minimal highlight — a single cursor glyph plus accent-coloured label; full-line inverse video was removed while keeping 1-9 shortcuts.
- Startup sequence restyled as a restrained staged initialisation: each of the nine real probes ends with a right-aligned `[OK]`, no rotating-bar spinner, skippable in non-interactive mode and cancellable with `q`/Ctrl+C between stages.
- Scan Center results are now a compact `SCAN RESULT` card (masked number, Risk `n / 100`, Confidence, Risk Level, Trend, Recommendation, Applied Action, Mode), followed by a labelled Reason block.
- Reputation Center shows a `PROFILE` card (Number, Risk, Confidence, Trend, Trust, First/Last Seen) above Signals, History and Reasons sections.
- Intelligence Center reorganised into CURRENT / BASELINE / DELTA / TREND / PATTERNS / EVIDENCE sections.
- Screening Center keeps its safety state obvious: Status / Mode / Policy, then Android `NOT VERIFIED` and Auto Reject, with ACTIVE still requiring the CLI confirmation prompt.
- Policy Center renders RELAXED / BALANCED / STRICT as cards with active thresholds and confidence; the current policy is marked `[current]`; simulation remains read-only.
- Daemon Control now shows STATUS, PID, UPTIME, ENGINE, QUEUE, IPC and HEARTBEAT plus lifecycle actions.
- Live Monitor became a compact console-style stream (`HH:MM:SS  VERDICT  MASKED  SCORE  ACTION`) over the real event log, with `Waiting for events...` when empty.
- Settings grouped under GENERAL / SCAN / DATA with each value shown on the right; reset still rewrites only `ui_state.json`.
- About screen reduced to a professional minimal presentation (product, developer, channels, platform, architecture, Android Bridge `NOT VERIFIED`).
- Subtle semantic palette (muted green/yellow/red/cyan, bold white headings, no neon, no inverse video); Dark default with Light/System retained; monochrome terminals render the same words with no escape codes; `TERM=dumb` now falls back to the classic banner.
- Verified responsive across 20/40/60/80/100/120/200 columns with no horizontal overflow; CJK and Devanagari label alignment preserved via display-width aware padding.

### Verification
- Full suite: 582 passed (554 pre-existing plus 28 new redesign tests). No existing test was modified or removed; the redesign is covered by `tests/test_ui_redesign.py` (dashboard structure, selection highlight, status badges, responsive widths, masking, settings groups, startup `[OK]` frames, cancellation, terminal restoration, no-emoji, no direct engine imports).
- Rendered and driven interactively under a real PTY at 60/100/200 columns with a running daemon, a stopped daemon, `TERM=dumb`, and no-colour caps.
- Security audit unchanged: no `eval`/`exec`, no `shell=True`, no `os.system`, no `AF_INET`, no HTTP/TCP/`requests`/`urllib`, no cloud APIs, no telemetry, no new network access; the UI remains presentation-only with all mutations delegated to the existing CLI handlers.

## 0.8.0 — Phase 8.5: Professional Terminal Interface

### Added
- Interactive terminal interface launched by a bare `callshield`, implemented in a new `callshield/ui/` package (`app.py`, `screens/`, `components/`, `navigation/`, `theme/`, `i18n/`, `state/`, `formatters/`) using only the Python standard library and no new dependency.
- Staged start-up sequence with nine named phases (initialize, security engine, intelligence modules, daemon connect, database check, policy, reputation, adaptive intelligence, prepare interface), a progress indicator and no artificial delay; the daemon is reported `OFFLINE` with a "Start daemon" action when it is not running.
- Dashboard with SYSTEM, THREAT OVERVIEW, INTELLIGENCE and QUICK ACTIONS sections, all values read from the real backend.
- Fourteen screens: Dashboard, Scan Center (Basic, Advanced, History, Compare), Live Monitor, Daemon Control, Screening Center, Policy Center, Reputation Center, Intelligence Center, Block Center, Report Center, History, Diagnostics, Settings and About.
- Advanced Scan with IDENTITY NORMALIZATION, REPUTATION, RISK SIGNALS, CONFIDENCE, BEHAVIOR, TREND, TRUST, POLICY, SCREENING and HISTORY sections rendered from the existing detection, reputation, adaptive and policy engines.
- Keyboard navigation: arrows, Enter, Esc, number shortcuts, PgUp/PgDn, `r` refresh, `h` dashboard, `q` and Ctrl+C quit. Esc at the root exits rather than trapping the user.
- Nine languages through translation dictionaries: English (default), Hindi, Hinglish (Roman Hindi), Spanish, French, Japanese, Chinese, Portuguese, Russian, with English fallback for missing keys. Technical command names are never translated.
- Interface preferences (`ui_state.json`): Language, Appearance (Dark default/Light/System), Animation, Refresh Rate (1s/2s/5s/10s/Manual), Default Scan Mode, Notifications, Data and Reset.
- Non-interactive fallback: the classic banner is printed when stdin/stdout is not a terminal, when `CALLSHIELD_NO_UI` is set, or if the interface fails to import or start.
- `CALLSHIELD_UI_ASCII` and `CALLSHIELD_UI_STATE` environment overrides for ASCII-only rendering and a relocated preferences file.

### Safety and privacy
- The interface is presentation only. All data and every mutation are delegated to the existing CLI handlers, engines and databases through a single `callshield/ui/state/backend.py` adapter.
- ACTIVE protection still requires the existing CLI confirmation prompt; the interface hands over the real terminal rather than reimplementing or bypassing it.
- `screening enable` from the interface remains DRY_RUN with `active_mode_confirmed = false`; ACTIVE cannot be reached without the prompt.
- Policy testing is simulation only and is wrapped so a simulated decision cannot be mistaken for an applied one; the configuration is never written.
- Emergency-off remains immediately reachable, and destructive actions confirm with an explicit `[y/N]` default of no.
- Reset only rewrites the interface preferences file: databases, reports, daemon state, trust records, lists, and screening/security configuration are untouched.
- Phone numbers are masked in every rendered screen; no call duration, caller identity, location, audio analysis, contact data, answered state, carrier or external reputation is displayed or inferred.
- `Android: NOT VERIFIED` is shown wherever screening state appears. No second daemon, no duplicated intelligence calculation, and no policy bypass.
- Zero network communication: the interface imports no networking module and opens no socket. The only transport remains the daemon's existing local `AF_UNIX` IPC through `cli._ipc_request`. No `eval`, `exec`, `shell=True`, `os.system`, `subprocess` or `pickle`.

### Presentation
- No emojis, no ASCII art, no fake hacking effects. Status is never conveyed by colour alone: `READY`, `ONLINE`, `OFFLINE`, `ERROR`, `WARNING`, `NOT VERIFIED`, `DRY RUN`, `ACTIVE` and `DISABLED` are always spelled out.
- Graceful degradation across colour/no-colour, Unicode/ASCII, and 40–200 column terminals, with a legible message and a working quit key below the minimum width.

### Verification
- Python suite: 554 passed (396 pre-existing plus 158 new interface tests). No existing test was modified or removed.
- Verified under a pseudo-terminal at 46/80/90/92/160/200 columns, with `NO_COLOR`, with `CALLSHIELD_UI_ASCII`, and against both a running and a stopped daemon.
- Android build/device remain NOT VERIFIED. A run on a physical Android device inside Termux was not performed.
- Phase 9 has not started.

## 0.8.0 — Phase 8: Adaptive Threat Intelligence & Behavior Engine

### Added
- Dedicated `callshield/adaptive/` package with bounded behavioral observations, deterministic adaptive trends, explainable patterns, privacy-preserving storage, and JSON-serializable intelligence snapshots.
- Trend states `IMPROVING`, `STABLE`, `WORSENING`, `VOLATILE`, and `INSUFFICIENT_DATA` with explicit 5-point noise, 10-point sustained, 20-point sudden-change, and 25-point volatility thresholds.
- Measured patterns for repeated high risk, repeated/previous BLOCK recommendation, repeated reports, rapid increase, recent improvement, historical trust, expired trust, and inconsistent behavior.
- Risk/confidence deltas against the previous persisted intelligence baseline.
- Schema version 7 with bounded derived `intelligence_observations` and `intelligence_profiles` tables, hash/mask identifiers, indexes, age/count cleanup, and no deletion of core Phase 1–7 evidence.
- Optional adaptive context between ReputationEngine and PolicyEngine; context may only preserve or reduce blocking, never create a BLOCK by itself.
- `callshield intelligence [number|list] [--json] [--history] [--explain]` with masked OBSERVED/RECOMMENDED/APPLIED/CONFIRMED output.
- Doctor checks for Intelligence Database, Schema, Integrity, Storage, and Retention.
- Trust/report/scan/screening observations and Android feedback confirmation updates in the local timeline.
- Reproducible Phase 8 benchmark measuring lookup, behavioral analysis, trend calculation, and full snapshot p50/p95/p99.
- 64 Phase 8 Python tests (396 total) covering timeline, trends, volatility, deltas, patterns, snapshots, explanations, CLI/JSON, doctor, retention, migration, concurrency, privacy, fail-open, policy gates, and performance structure.

### Safety and privacy
- Trend or pattern context never bypasses PolicyEngine, explicit ACTIVE confirmation, whitelist/trust, emergency-off, final response validation, or fail-open behavior.
- Volatile intelligence vetoes an otherwise active block for review; unavailable/corrupt intelligence returns ALLOW.
- Derived intelligence tables store only hashes and masked identifiers; no call duration, answer state, identity, location, audio, contact, or device-content inference.
- No cloud API, remote lookup, DNS lookup, telemetry, analytics, advertising, account, HTTP/TCP listener, or new network communication.
- Retention defaults: 200 observations per identifier, 5,000 profiles, 90-day age, and 100-row lookup bound.

### Verification
- Python suite: 396 passed; all 332 Phase 1–7 tests preserved.
- Android build/device remain NOT VERIFIED; existing Phase 5 blocking behavior was not expanded.
- Phase 9 has not started.

## 0.7.0 — Phase 7: Reputation & Explainable Intelligence

### Added
- Dedicated `callshield/reputation/` package while preserving the legacy Phase 1 `ReputationSignals` import API.
- Deterministic, bounded local reputation profiles with masked number/hash, observations, allowed/rejected counts, block recommendations, reports, score, separate confidence, and measured trend.
- Structured explanations where every reason maps to a measured local signal or actual historical trend.
- Bounded trend detection (`IMPROVING`, `STABLE`, `WORSENING`, `UNKNOWN`) requiring at least three observations.
- Schema version 6 with privacy-preserving `reputation_profiles`, bounded `reputation_history`, and `trusted_numbers` tables plus indexed lookups and screening-time reputation snapshots.
- `callshield reputation`, `callshield reputation <number>`, `--json`, and `reputation list` with masked output and no plaintext/hash in public JSON.
- Explicit reversible local trust through `callshield trust`, `callshield untrust`, and bounded temporary durations such as `--for 24h`.
- Reputation context integrated into incoming-call policy as a safety veto/trust override only; reputation alone never raises detector risk or forces BLOCK.
- Doctor checks for Reputation Database, Reputation Schema, Reputation Integrity, and Trust Database.
- Optional reputation score/confidence/trend/reasons in masked block inspection.
- Reproducible bounded lookup benchmark in `scripts/benchmark_phase7.py` and `PERFORMANCE_PHASE7.md`.
- 61 Phase 7 Python tests (332 total) covering scoring, history, trends, confidence, explanations, CLI/JSON, trust/expiry, policy fail-open, schema/privacy, doctor, retention, block inspection, and concurrent lookup.

### Privacy and safety
- No cloud reputation service, remote lookup, telemetry, analytics, accounts, advertising, DNS/HTTP request, or network listener.
- New profile/history/trust tables store only canonical SHA-256 hashes and masked identifiers; no plaintext number column is added.
- Reputation failure/corruption/database unavailability produces UNKNOWN / ALLOW.
- Whitelist, explicit trust, emergency-off, config integrity, replay protection, IPC bounds, and all Phase 1–6 fail-open guarantees remain absolute.
- History is capped per number, profiles/trust have global bounds, and all event/detail queries are indexed and bounded.

### Verification
- Python suite: 332 passed; all 271 Phase 1–6 tests preserved.
- Android build/device remain NOT VERIFIED; no device result is claimed.
- Phase 8 has not started.

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
