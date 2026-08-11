# CALLSHIELD

> **Hardened, local, explainable, fail-open call protection for Termux and Android.**

CALLSHIELD keeps analysis and persistence on-device. Phase 6 hardens the
existing Phase 1–5 architecture against malformed IPC, replay, corrupt config
or databases, stale runtime state, concurrent requests, resource exhaustion,
and partial writes.

## Phase status

- Phase 1 — Foundation: **COMPLETE**
- Phase 2 — Advanced Intelligence: **COMPLETE**
- Phase 3 — Background Engine: **COMPLETE**
- Phase 4 — Android Screening Bridge: **COMPLETE**
- Phase 5 — Active Call Protection: **COMPLETE**
- Phase 6 — Hardening & Reliability: **COMPLETE**
- Phase 7 — **NOT STARTED**

## Safety invariants

Fresh installations remain:

```text
screening_enabled = false
screening_mode = DRY_RUN
active_mode_confirmed = false
screening_policy = BALANCED
```

```text
DRY_RUN: recommend BLOCK → apply ALLOW
ACTIVE:  valid, confirmed, policy-qualified BLOCK → apply BLOCK
FAILURE / REPLAY / CORRUPTION / TIMEOUT / EMERGENCY → apply ALLOW
```

Whitelist remains an absolute ALLOW override. ACTIVE still requires explicit
interactive confirmation.

## Architecture

```text
Android CallScreeningService
        │
        ▼
strict callshield/1 JSON + UUID + timestamp
        │
        ▼
owner-only AF_UNIX socket
        │
        ├── size/depth/worker bounds
        ├── command allowlist
        └── replay cache
                │
                ▼
DaemonService → EventQueue → EventProcessor
                │
                ▼
existing analyze_number() → PolicyEngine
                │
                ▼
validated ALLOW/BLOCK → SQLite → health/metrics
```

There is no TCP or HTTP server and no second IPC architecture.

## Phase 6 hardening

### IPC

Every CLI/Android request now has:

```json
{
  "protocol": "callshield/1",
  "request_id": "uuid",
  "timestamp": "2026-08-11T12:00:00+00:00"
}
```

Limits:

- request: 16 KiB
- response: 64 KiB
- event payload: 8 KiB
- JSON nesting: 16
- object keys: 128
- array entries: 256
- concurrent IPC workers: 10
- default IPC timeout: 1.5 seconds
- event queue: 256

JSON duplicate keys, invalid constants, invalid protocol/UUID/timestamp,
unknown commands, oversized bodies, stale requests, and disconnected clients
are rejected without terminating the daemon.

### Replay protection

Security-sensitive screening and feedback use the same bounded replay layer as
all IPC envelopes:

- default freshness lifetime: 5 minutes
- default maximum entries: 4096
- thread-safe duplicate detection
- automatic expiry
- deterministic oldest-entry eviction
- persisted screening event-ID lookup across daemon restarts

A duplicate or stale screening request returns:

```text
POLICY_ERROR / ALLOW
```

Feedback uses its own fresh request UUID and carries the original screening ID
separately, preventing an old ACTIVE decision from being re-applied.

### Configuration integrity

Configuration persistence uses:

```text
unique temporary file
→ restrictive mode
→ write + flush
→ fsync(file)
→ atomic replace
→ fsync(parent directory)
```

Empty, malformed, truncated, or invalid config is preserved for diagnosis and
loaded as safe runtime defaults:

```text
screening_enabled = false
screening_mode = DRY_RUN
active_mode_confirmed = false
```

Strict validation remains available to doctor. A malformed SIGHUP reload does
not kill the daemon; it updates policy/processor/health to the fail-safe config
and leaves heartbeat operational.

### Database integrity

SQLite schema version 5 enforces:

- `foreign_keys = ON`
- WAL journal mode
- FULL synchronous mode
- bounded busy timeout
- transaction rollback
- startup quick integrity check
- full doctor integrity check
- required table/column/index validation

Screening indexes cover timestamp, number hash, event ID, applied action, and
policy action. Migrations preserve existing Phase 1–5 data.

### Emergency-off

```bash
callshield emergency-off
callshield emergency-reset
```

The 0600 emergency marker is checked before policy can apply BLOCK. Creation is
durable and idempotent; removal syncs its parent directory. Reset always leaves
screening disabled, DRY_RUN, and unconfirmed.

### PID/socket and daemon reliability

Existing strict `/proc/<pid>/cmdline` ownership verification remains. Recovery
never signals unrelated processes and safely handles stale PID/socket state.
One event or client failure increments failure metrics and does not terminate
the queue worker, heartbeat, health monitor, or daemon.

## Doctor diagnostics

```bash
callshield doctor
callshield doctor --json
callshield doctor --repair
```

Checks:

- Runtime
- Python
- Database
- Schema
- Config
- Daemon
- IPC
- Permissions
- Android Bridge
- Screening
- Policy
- Storage

Statuses are `HEALTHY`, `WARNING`, `ERROR`, and `NOT VERIFIED`.

`--repair` is deliberately narrow:

- remove owner-verified stale PID/socket state
- restore restrictive permissions on known owned paths
- remove owned abandoned config temporary files

It never enables screening or ACTIVE mode and does not overwrite a corrupt
configuration silently.

## Applied block inspection

```bash
callshield blocks
callshield blocks inspect <id>
```

Output contains only masked number, timestamp, risk, confidence, policy,
recommendation, applied action, reason, and confirmation status. Plaintext
numbers are not selected or displayed.

## Main CLI

```bash
callshield version
callshield status
callshield metrics
callshield doctor
callshield blocks
callshield config show

callshield daemon start
callshield daemon status
callshield daemon stop

callshield screening status
callshield screening policy
callshield screening metrics
callshield screening mode dry-run
callshield screening mode active

callshield policy test
callshield emergency-off
callshield emergency-reset
```

Policy simulation is marked `SIMULATION ONLY` and cannot affect a real call.

## Active policy defaults

| Policy | Active block | Confidence |
|---|---:|---:|
| RELAXED | 92 | 90 |
| BALANCED | 85 | 80 |
| STRICT | 80 | 75 |

Thresholds remain configurable from 0–100. Invalid policy state fails open.

## Android bridge hardening

Android requests and rejection feedback include fresh timestamps and distinct
UUIDs. The bridge validates protocol, fields, response bounds, policy state,
emergency state, and the exact ACTIVE + BLOCK combination before requesting
rejection. All unexpected actions/modes, malformed responses, unavailable
socket/daemon, timeout, lifecycle cancellation, and internal errors remain
ALLOW.

The manifest requests no camera, microphone, contacts, SMS, location, storage,
accessibility, or Internet permission.

### Android/Termux limitation

A separately installed Android app normally cannot traverse Termux's private
0600 socket because of separate UIDs and SELinux. No public or network fallback
is added. Physical integration remains deployment-specific and unverified.

## Tests

```bash
pytest -q
# 271 passed
```

All 220 Phase 1–5 tests remain. Fifty-one Phase 6 tests cover:

- static security audit
- strict IPC parsing and limits
- replay and expiry
- atomic config writes and SIGHUP fallback
- database integrity/schema/lock/rollback behavior
- resource bounds
- policy fail-open safety
- 5-request and 10-request concurrent IPC
- doctor output/repair
- masked block inspection

See `SECURITY_AUDIT.md` for PASS versus NOT TESTED results.

## Performance

A reproducible in-memory policy microbenchmark was run with 5,000 decisions and
10 worker threads:

| Percentile | Latency |
|---|---:|
| p50 | 0.006790 ms |
| p95 | 0.021914 ms |
| p99 | 0.039164 ms |

These are policy-only measurements, not Android, database, IPC, or physical
call latency. See `PERFORMANCE_PHASE6.md` and `scripts/benchmark_phase6.py`.

## Installation

```bash
pkg update
pkg install python git
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

The installer creates owner-only `~/.callshield/{data,logs,run,state}`, keeps
ACTIVE disabled, preserves user data, requires no root, and runs the Python
self-test.

## Verification limitations

The environment has no JDK, Gradle/wrapper, Android SDK, emulator, or physical
device:

```text
ANDROID BUILD = NOT VERIFIED
PHYSICAL DEVICE = NOT VERIFIED
END-TO-END ANDROID PERFORMANCE = NOT VERIFIED
```

No APK, physical rejection, cross-UID socket success, or Android benchmark is
claimed.

## Phase boundary

Phase 7 has not started. No Phase 7 functionality is included.

## License

MIT — see `LICENSE`.
