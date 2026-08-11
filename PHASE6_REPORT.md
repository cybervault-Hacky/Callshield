# CALLSHIELD — Phase 6 Final Report

**Version:** 0.6.0 — Hardening & Reliability
**Date:** 2026-08-11
**Branch:** `arena/019ff0f4-callshield`
**Verified Phase 5 baseline:** `51e81509c715d123a675f80fce8351c3e6db2868`
**Python tests:** 271 passed

## Phase boundary

```text
Phase 1 — COMPLETE
Phase 2 — COMPLETE
Phase 3 — COMPLETE
Phase 4 — COMPLETE
Phase 5 — COMPLETE
Phase 6 — COMPLETE
Phase 7 — NOT STARTED
```

Phase 6 changes hardening and reliability only. Existing active policy,
whitelist, emergency, fail-open, Android bridge, and Unix IPC behavior remain.

## Audit and baseline

No Phase 6 implementation existed on any local/remote branch. The pushed Phase
5 tree was reconciled and verified at `51e8150`; all 220 baseline tests passed
before changes.

Audited areas:

- all IPC producers/consumers
- config read/write and SIGHUP reload
- database schema/migrations/transactions
- daemon PID/socket lifecycle
- event isolation and queue bounds
- policy fail-open path
- Android protocol/service/result validation
- available Git refs/history

## IPC hardening

Every request now uses an envelope with exact protocol, UUID, and timezone
freshness timestamp. Strict parser limits:

```text
request bytes       16 KiB
response bytes      64 KiB
JSON depth          16
JSON object keys    128
JSON array entries  256
concurrent workers  10
IPC timeout         1.5 seconds default
event payload       8 KiB
event queue         256
```

Strict JSON rejects duplicate keys, invalid constants, excessive nesting,
oversized structures, malformed UTF-8/JSON, unknown commands, and extra data.
Disconnected clients and per-request exceptions remain isolated.

`SOCK_STREAM` is used only with `AF_UNIX`; there is no IP or HTTP listener.

## Replay protection

Implemented `callshield/security/replay.py`:

- canonical UUID validation
- timezone timestamp parsing
- default 5-minute freshness window
- future/expired rejection
- thread-safe duplicate detection
- default 4096-entry maximum
- automatic expiry
- deterministic oldest-entry eviction
- indexed persisted event-ID check across daemon restarts

Duplicate/expired screening requests return `POLICY_ERROR / ALLOW` and are not
reprocessed or persisted as active blocks. Android feedback uses a fresh
request UUID/timestamp and identifies the original screening ID separately.

## Configuration integrity

`safe_write_text` now performs:

1. unique temporary creation in the destination directory
2. restrictive descriptor mode
3. write and flush
4. file fsync
5. atomic replace
6. final chmod
7. parent-directory fsync

Failures clean temporary state and preserve the prior complete file.

Empty, malformed, non-object, or invalid config files are preserved but normal
runtime receives fail-safe defaults:

```text
screening_enabled = false
screening_mode = DRY_RUN
active_mode_confirmed = false
```

Strict config inspection is available to doctor. Concurrency tests verify ten
simultaneous writers still leave complete valid JSON.

## SIGHUP reload

Safe reload updates daemon config, EventProcessor/PolicyEngine inputs, health,
heartbeat interval/config, and signal state. Restart-required runtime paths and
replay parameters remain fixed for the process lifetime. Invalid reload applies
fail-safe disabled DRY_RUN config, marks health config integrity ERROR, leaves
heartbeat functional, and does not terminate the daemon.

## Database integrity

Schema version 5 adds non-destructive indexes:

- screening event ID
- applied action + timestamp
- policy action + timestamp

Existing timestamp and number-hash indexes remain.

Database initialization enforces/verifies:

- foreign keys ON
- WAL mode
- FULL synchronous mode
- bounded busy timeout
- required tables/columns/indexes
- exact schema version
- rollback on transaction failure

Startup runs `quick_check`; doctor runs full `integrity_check`. Corrupt database,
missing schema, lock contention, rollback, index, and partial-screening-write
tests pass.

## Fail-open guarantee

Automated/manual verification covers database unavailable/locked, daemon/socket
unavailable, IPC timeout, malformed request/response, malformed number, invalid
policy/config/mode/activation, replay, Android error, unexpected policy
exception, stale PID/socket, and corrupt state/config/database. Screening never
produces BLOCK from these failures.

## Emergency-off

Emergency marker creation uses the durable atomic writer with mode 0600. Reset
uses atomic unlink plus parent fsync. Both commands remain idempotent. The marker
is read before any apply path, and uncertain marker type/read state is treated
as emergency ON. Reset persists screening disabled, DRY_RUN, and unconfirmed.

## PID/socket and daemon reliability

Existing strict process ownership and PID identity checks are retained. Doctor
repair removes only owner-verified stale PID/socket state and never signals an
unrelated process. Missing/stale/active endpoint cases remain deterministic.

Event exceptions remain isolated in the worker loop. Failed-event, queue,
heartbeat, health, and graceful-drain regressions pass.

## Resource limits

Automated tests verify queue saturation/drop accounting, event UTF-8 payload
limits, IPC request/response bounds, JSON structure limits, replay-cache bound,
10-worker IPC bound, database query limits, timeout behavior, and existing log
rotation.

## Android bridge

Android screening requests and feedback include fresh timestamps. Protocol
validation still requires valid ACTIVE + BLOCK + BLOCK recommendation,
non-emergency state, and no policy error. Invalid/missing/unexpected responses
remain ALLOW.

The service retains incoming-only and `tel:` checks, masked logging, bounded
IPC/timeouts, minimal permissions, and now cancels its bounded coroutine scope
on lifecycle destruction. Lifecycle/transport failures remain fail-open.

## Concurrency

Dedicated real Unix IPC tests exercise:

- 5 simultaneous unique requests
- 10 simultaneous unique requests
- 10 simultaneous duplicates of one request

Unique response IDs match, duplicate processing occurs at most once, replay
cache remains consistent, metrics remain valid, and daemon ping succeeds after
the race.

## Doctor

Added:

```text
callshield doctor
callshield doctor --json
callshield doctor --repair
```

Checks runtime, Python, database, schema, config, daemon, IPC, permissions,
Android bridge, screening, policy, and storage with HEALTHY/WARNING/ERROR/NOT
VERIFIED statuses.

Safe repair is limited to owner/type-verified stale PID/socket cleanup,
permission correction, and abandoned config-temp cleanup. It never enables
screening or ACTIVE mode and does not overwrite corrupt config.

## Block inspection

Added:

```text
callshield blocks
callshield blocks inspect <id>
```

Queries select only masked number, timestamp, risk, confidence, policy,
recommendation, applied action, reason, and confirmation. Manual inspection
showed `+919*****0601`; plaintext was not emitted.

## Security audit

`SECURITY_AUDIT.md` records PASS/NOT TESTED explicitly. Automated AST/text audits
found no dynamic evaluation, shell execution, unsafe deserialization, IP socket,
HTTP/TCP server, Java process execution, dangerous Android permission, root
operation, or plaintext screening log.

Android build/device/SELinux and independent penetration testing remain NOT
TESTED.

## Performance

A reproducible policy-only microbenchmark was run:

```text
events       5000
concurrency  10
Python       3.11.2
platform     Linux 6.1.158+ x86_64
p50          0.006790 ms
p95          0.021914 ms
p99          0.039164 ms
wall         0.14853265799979454 s
```

This does not claim Android, IPC, SQLite, end-to-end call, or phone performance.
See `PERFORMANCE_PHASE6.md` and `scripts/benchmark_phase6.py`.

## Tests

```text
OLD TESTS (Phase 1–5): 220 PASS
NEW PHASE 6 TESTS:       51 PASS
TOTAL:                  271 PASS
FAILURES:                 0
```

Dedicated suites:

- `test_security_audit.py`
- `test_ipc_hardening.py`
- `test_config_integrity.py`
- `test_database_integrity.py`
- `test_resource_limits.py`
- `test_policy_safety.py`
- `test_replay_protection.py`
- `test_concurrency.py`
- `test_doctor.py`

## Manual verification

Fresh isolated installer and 271-test self-test: PASS.

Verified commands:

- version/status/metrics
- doctor text/JSON/repair
- blocks list/inspect
- config show
- screening status/metrics
- policy simulation
- daemon start/status/stop

Running doctor was HEALTHY for config/database/schema/daemon/IPC/permissions and
reported Android Bridge NOT VERIFIED. Stopped doctor correctly reported daemon
and IPC WARNING.

A valid ACTIVE request produced BLOCK. Replaying the same UUID/timestamp
produced `POLICY_ERROR / ALLOW / DUPLICATE_REQUEST`. Metrics distinguished one
applied block from zero confirmed rejections. Stale PID/socket and config mode
0644 were safely repaired; final daemon status was STOPPED with no process left.

Socket inode appeared in `/proc/net/unix`, not `/proc/net/tcp*`; `ss -ltnp`
showed no CALLSHIELD listener.

## Android build/device

```text
ANDROID BUILD = NOT VERIFIED
PHYSICAL DEVICE = NOT VERIFIED
```

JDK, Gradle/wrapper, Android SDK, emulator, and physical device remain absent.
No APK or physical call result is claimed.

## Known limitations

- Cross-UID Android/Termux filesystem socket access remains deployment-specific
  and unverified.
- Full end-to-end Android/IPC/database/phone performance was not measured.
- No external penetration test or physical-device SELinux test was performed.
- Phase 7 is not started.
