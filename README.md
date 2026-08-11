# CALLSHIELD

> **Hardened, local-first reputation and explainable call intelligence for Termux and Android.**

CALLSHIELD keeps analysis, trust, history, and persistence on-device. Phase 8
adds bounded behavioral timelines, adaptive trends, measured patterns, and
explainable intelligence snapshots without cloud lookups, surveillance,
telemetry, accounts, advertising, or network reputation services. All Phase 1–7
safety and call-protection behavior remains.

## Phase status

- Phase 1 — Foundation: **COMPLETE**
- Phase 2 — Advanced Intelligence: **COMPLETE**
- Phase 3 — Background Engine: **COMPLETE**
- Phase 4 — Android Screening Bridge: **COMPLETE**
- Phase 5 — Active Call Protection: **COMPLETE**
- Phase 6 — Hardening & Reliability: **COMPLETE**
- Phase 7 — Reputation & Explainable Intelligence: **COMPLETE**
- Phase 8 — Adaptive Threat Intelligence & Behavior Engine: **COMPLETE**
- Phase 9 — **NOT STARTED**

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

## Phase 8 adaptive intelligence

The adaptive architecture is:

```text
OBSERVE → CORRELATE → SCORE → EXPLAIN → ADAPT

analyze_number()
→ ReputationEngine
→ BehaviorEngine
→ PolicyEngine
→ existing safety gates
```

`callshield/adaptive/` stores bounded derived observations using masked
identifiers and canonical hashes. It tracks only CALLSHIELD measurements:
risk/confidence, recommendations, applied outcomes, confirmations, reports,
trust changes, scans, screening outcomes, and timestamps.

It does not infer call duration, answer status, caller identity, location,
audio, contacts, or device contents.

### Adaptive trend

```text
IMPROVING / STABLE / WORSENING / VOLATILE / INSUFFICIENT_DATA
```

Explicit thresholds:

- less than 5 points: statistical noise for direction changes
- at least 10 points: sustained trend
- at least 20 points: sudden change
- range of 25 plus two direction changes: volatility
- fewer than three observations: insufficient data

Trend alone never forces BLOCK. VOLATILE context can only veto an otherwise
active block for safer review.

### Explainable patterns

Measured detectors include repeated high risk, repeated/previous BLOCK
recommendations, repeated reports, rapid increase, recent improvement,
historical trust, expired trust, and inconsistent behavior. Each pattern
contains an ID, evidence, observation count, time window, confidence, and
explanation.

### Intelligence CLI

```bash
callshield intelligence
callshield intelligence +919876543210
callshield intelligence +919876543210 --json
callshield intelligence +919876543210 --history
callshield intelligence +919876543210 --explain
callshield intelligence list
```

Output is masked and explicitly distinguishes OBSERVED, RECOMMENDED, APPLIED,
and CONFIRMED. JSON excludes hashes and plaintext identifiers.

### Retention

Derived intelligence defaults to:

- 100-row lookup bound
- 200 observations per identifier
- 5,000 profile snapshots
- 90-day observation age
- 20 patterns/explanations

Cleanup is deterministic and never deletes core events, screening evidence,
reports, reputation, trust, or block history.

If adaptive intelligence is unavailable or corrupt:

```text
INTELLIGENCE_UNAVAILABLE → ALLOW
```

## Phase 7 reputation and explanations

A dedicated `callshield/reputation/` layer reuses existing Phase 2 detector
signals and bounded local history. It never performs a network lookup and never
forces a BLOCK recommendation by itself.

Profiles include:

- masked number and canonical SHA-256 hash
- first/last seen
- calls seen, allowed, and confirmed rejected
- block recommendations and local reports
- deterministic score (0–100)
- separate evidence confidence (0–100)
- trend: `IMPROVING`, `STABLE`, `WORSENING`, or `UNKNOWN`
- structured signals and reasons tied to actual measurements

Risk labels are `TRUSTED`, `LOW`, `MODERATE`, `HIGH`, `CRITICAL`, and `UNKNOWN`.
A single observation cannot establish a trend; at least three observations are
required. CALLSHIELD does not claim short-call behavior because no call-duration
telemetry exists.

### Reputation CLI

```bash
callshield reputation
callshield reputation +919876543210
callshield reputation +919876543210 --json
callshield reputation list
```

Human and JSON output expose masked identifiers only. Public JSON excludes the
number hash and canonical plaintext number.

### Local trust

```bash
callshield trust +919876543210
callshield trust +919876543210 --for 24h
callshield untrust +919876543210
```

Trust is explicit, local, reversible, bounded, and automatically expires.
Trusted numbers are an ALLOW safety override and cannot be blocked by reputation
alone. Whitelist and emergency-off remain higher-priority safety behavior.

### Bounded storage

Schema version 6 adds:

- `reputation_profiles`
- `reputation_history`
- `trusted_numbers`

These tables contain hashes and masked identifiers, not plaintext numbers.
History defaults to 100 retained changes per number, recent calculations query
at most 100 observations, profiles default to 5,000 retained entries, and trust
defaults to 1,000 records with a maximum temporary duration of one year.

If reputation storage is missing, corrupt, unavailable, or contradictory,
policy receives `REPUTATION_UNAVAILABLE` and applies ALLOW.

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
- Reputation Database / Schema / Integrity
- Trust Database
- Intelligence Database / Schema / Integrity
- Intelligence Storage / Retention
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
recommendation, applied action, reason, and confirmation status. When captured
at decision time it also shows reputation score, confidence, trend, and measured
reasons. Plaintext numbers are not selected or displayed.

## Main CLI

```bash
callshield version
callshield status
callshield metrics
callshield doctor
callshield blocks
callshield config show
callshield reputation
callshield reputation +919876543210 --json
callshield reputation list
callshield intelligence +919876543210 --explain
callshield intelligence +919876543210 --history
callshield intelligence list
callshield trust +919876543210 --for 24h
callshield untrust +919876543210

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
# 396 passed
```

All 332 Phase 1–7 tests remain. Sixty-four Phase 8 tests cover behavioral
timeline, all adaptive trends, volatility, risk/confidence deltas, measured
patterns, snapshots, explanations, CLI/JSON, doctor, retention, schema migration,
5/10-way concurrency, privacy, fail-open behavior, and policy safety.

See `SECURITY_AUDIT.md` for Phase 6–8 PASS versus NOT TESTED results.

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

A separate bounded local reputation benchmark measured 1,000 lookups over 100
indexed events:

| Percentile | Latency |
|---|---:|
| p50 | 0.229418 ms |
| p95 | 0.308114 ms |
| p99 | 0.437614 ms |

This is a sequential local SQLite/reputation lookup workload, not Android or
end-to-end screening. See `PERFORMANCE_PHASE7.md` and
`scripts/benchmark_phase7.py`.

Phase 8 bounded adaptive benchmark (1,000 iterations over 100 observations):

| Workload | p50 | p95 | p99 |
|---|---:|---:|---:|
| intelligence lookup | 0.579679 ms | 0.834626 ms | 1.091556 ms |
| behavioral analysis | 0.072811 ms | 0.098954 ms | 0.120621 ms |
| trend calculation | 0.045488 ms | 0.105911 ms | 0.131718 ms |
| full snapshot | 0.756128 ms | 0.821092 ms | 0.993023 ms |

See `PERFORMANCE_PHASE8.md` and `scripts/benchmark_phase8.py`. These are local
bounded measurements, not Android or physical-call performance.

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

Phase 9 has not started. No Phase 9 functionality is included.

## License

MIT — see `LICENSE`.
