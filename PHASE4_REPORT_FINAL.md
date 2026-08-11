# CALLSHIELD — Phase 4 Final Report

**Version:** 0.4.0 — Android Screening Bridge
**Date:** 2026-08-11
**Branch:** `arena/019ff0f4-callshield`
**Verified baseline:** `65477673845f199a3f3f1cbaf10e91c4e0a6d23d`
**Python tests:** 189 passed

## Final safety state

```text
RECOMMEND BLOCK → APPLY ALLOW
ACTUALLY REJECTED = 0
AUTO REJECT = DISABLED
```

Phase 4 does not contain active call blocking, an active policy package,
blocking thresholds, emergency-off behavior, automatic rejection, or Phase 6
hardening.

## Baseline preservation and reuse

The clean Phase 3 baseline was inspected and reverified before editing:

- version 0.3.0
- commit `6547767`
- 163 tests passed
- hardened PID/recovery behavior intact
- bounded queue and IPC intact
- exact owner-only Unix socket architecture understood

A historical Phase 4 commit (`c2321c7`) was inspected and reused selectively
for the Android project structure and screening concepts. It was not restored
wholesale because it was based on the older Phase 3 implementation and accepted
an unsafe future mode. The final integration retains the hardened Phase 3
service and makes `DRY_RUN` the only valid screening mode.

## Android bridge

Created the minimal Kotlin project under `android/`:

```text
android/
├── app/
│   ├── build.gradle
│   ├── proguard-rules.pro
│   └── src/
│       ├── main/
│       │   ├── AndroidManifest.xml
│       │   └── java/com/callshield/bridge/
│       │       ├── CallShieldScreeningService.kt
│       │       ├── BridgeClient.kt
│       │       ├── Protocol.kt
│       │       ├── ScreeningResult.kt
│       │       └── BridgeSetupActivity.kt
│       └── test/java/com/callshield/bridge/
├── build.gradle
├── settings.gradle
├── gradle.properties
└── README.md
```

`CallShieldScreeningService`:

- handles only `DIRECTION_INCOMING`
- checks for a non-null `tel:` handle
- conservatively normalizes digits and common formatting
- safely handles null, empty, malformed, and unexpected handles
- applies an explicit Android response with disallow and reject flags set to
  `false`
- catches bridge failure and cancellation/recreation paths
- logs only masked numbers

The manifest requests no camera, microphone, contacts, SMS, location, storage,
accessibility, or Internet permission. The user must grant Android's Call
Screening role through the system role flow.

## IPC protocol

The existing Phase 3 Unix socket is reused. No second IPC service was added.

Exact Android request:

```json
{
  "protocol": "callshield/1",
  "request_id": "uuid",
  "number": "+919876543210",
  "source": "android_call_screening"
}
```

Response:

```json
{
  "protocol": "callshield/1",
  "request_id": "uuid",
  "risk_score": 90,
  "confidence": 89,
  "verdict": "MALICIOUS",
  "recommended_action": "BLOCK",
  "applied_action": "ALLOW",
  "mode": "DRY_RUN",
  "reason": "DRY_RUN",
  "latency_ms": 2
}
```

The daemon detects this versioned commandless request before the normal Phase 3
command dispatch. All existing commands continue on the same socket.

Bounds and validation:

- 16 KiB request maximum
- 64 KiB response maximum
- strict UTF-8 JSON
- UUID request ID
- exact protocol and source
- bounded number and action fields
- configurable 200–5000 ms timeout, default 1500 ms
- eight concurrent local IPC handlers maximum

## Screening pipeline

```text
Android request
  → INCOMING_CALL Event
  → EventProcessor
  → existing analyze_number()
  → recommendation
  → applied ALLOW
  → screening_events persistence
  → Android response
```

No new fraud-scoring engine was created. Concurrent screening also fixed the
existing detector's accidental shared-config mutation by returning a dataclass
copy with adjusted weights.

## Database

Schema version 3 adds `screening_events` through an idempotent v2→v3 migration.
Phase 1–3 data is preserved and backed up by the existing migration mechanism.

Stored fields:

- id and timestamp
- number, masked number, and full SHA-256 number hash
- risk and confidence
- verdict
- recommended action
- applied action
- reason
- latency
- source and event ID
- fixed mode

Database constraints permit only `applied_action = ALLOW` and
`mode = DRY_RUN`. Attempting to persist a different applied action is rejected.
Logs contain masked numbers only.

## Configuration

Added:

```text
screening_enabled     true
screening_mode        DRY_RUN
screening_timeout_ms  1500
```

Timeout is validated from 200 to 5000 ms. Invalid loaded screening values fail
safe: mode resets to `DRY_RUN`, timeout resets to 1500 ms, and a malformed
enable flag disables screening. CLI requests for any other mode are rejected.

## CLI

Added:

```text
callshield screening status
callshield screening enable
callshield screening disable
callshield screening mode
callshield screening health
callshield screening metrics
```

Status deliberately distinguishes local IPC from device verification:

```text
Bridge:              CONNECTED
Daemon:              RUNNING
Android:             NOT VERIFIED
Mode:                DRY_RUN
Live Screening:      IPC READY — DEVICE NOT VERIFIED
Auto Reject:         DISABLED
Actually Rejected:   0
```

`CONNECTED` means only that the daemon Unix socket answered. It does not claim
that a physical device is attached or the Android screening role is active.

## Health and metrics

Added counters:

- incoming calls
- screened
- timeouts
- bridge errors
- screening high risk
- screening allowed
- screening unknown
- screening block recommended
- screening blocked

`screening_blocked` has no increment path and is always returned as zero.
Stopped-daemon metrics combine SQLite with the bounded Phase 3 last-session
snapshot, preserving timeout and bridge-error information even when persistence
was unavailable.

## Fail-open behavior

The following return `UNKNOWN / ALLOW` or otherwise apply ALLOW:

- missing, null, empty, or malformed number
- unexpected URI scheme
- disabled screening
- invalid protocol, request ID, or source
- unavailable Termux daemon or Unix socket
- timeout
- malformed or mismatched daemon response
- database contention/failure
- analyzer or internal exception
- Android service cancellation/recreation

The service reserves part of the timeout budget for response serialization and
uses a 50 ms SQLite persistence timeout. Audit persistence can fail, but the
ALLOW response remains available.

## Automated tests

Final Python result:

```text
189 passed
```

This preserves all 163 Phase 3 tests and adds 26 Phase 4 tests covering:

- event type/source
- safe, unknown, high-risk, invalid, empty, and null numbers
- BLOCK recommendation with ALLOW applied
- disabled screening
- timeout and internal error
- database persistence failure
- privacy fields and database constraints
- v2→v3 migration
- exact Android IPC request
- concurrent service and socket requests
- honest status, CLI, health, and metrics
- stopped-daemon screening metrics
- DRY_RUN-only configuration fallback

Kotlin test sources cover exact request serialization, strict response parsing,
normalization, malformed data, unavailable daemon, and immutable ALLOW results.

## Manual Termux verification

An isolated `scripts/install.sh` run succeeded and its self-test passed all 189
Python tests. Runtime directories/files used 0700/0600 permissions.

Exact-wire matrix:

```text
LOW_RISK  → SAFE / recommended ALLOW / applied ALLOW
HIGH_RISK → MALICIOUS risk 90 / recommended BLOCK / applied ALLOW
INVALID   → UNKNOWN / recommended ALLOW / applied ALLOW
TIMEOUT   → UNKNOWN / recommended ALLOW / applied ALLOW (453 ms wall time)
STOPPED   → DAEMON_UNAVAILABLE / recommended ALLOW / applied ALLOW
```

Final screening metrics after the matrix:

```text
Incoming Calls:      4
Screened:            4
Timeouts:            1
Bridge Errors:       1
High Risk:           1
Screening Allowed:   4
Screening Unknown:   2
Block Recommended:   1
Screening Blocked:   0
Actually Rejected:   0
```

The timeout was exercised against a real daemon while an SQLite write lock was
held. The daemon returned the fail-open response inside the configured 500 ms
budget. The bridge-error count records that timeout audit persistence was also
contended.

## Network and process audit

`ss -lxnp` showed the CALLSHIELD filesystem Unix socket. Its file-descriptor
inode appeared in `/proc/net/unix` and did not appear in `/proc/net/tcp` or
`/proc/net/tcp6`. `ss -ltnp` contained no CALLSHIELD process.

Static implementation checks found no dynamic code execution, shell command,
network socket family, Java process-launch API, root path, active blocking
package, or automatic rejection path. Android source contains only explicit
`false` values for its disallow and reject response flags.

## Android build and device test

Environment inspection found:

```text
java:              NOT AVAILABLE
javac:             NOT AVAILABLE
gradle:            NOT AVAILABLE
ANDROID_HOME:      NOT AVAILABLE
ANDROID_SDK_ROOT:  NOT AVAILABLE
Gradle wrapper:    NOT AVAILABLE
```

Therefore:

```text
ANDROID BUILD = NOT VERIFIED
DEVICE TEST = NOT VERIFIED
```

No Android compile, APK, emulator, role grant, physical call, or device
connection result is claimed.

## Known limitations

- Android and Termux normally run under different UIDs. Android permissions and
  SELinux commonly prevent direct access to Termux's private 0600 socket.
- A secure shared Unix endpoint or same-UID/companion deployment integration is
  still required for a physical deployment; no public or network fallback is
  introduced.
- The bridge build and physical-device behavior are unverified on this host.
- Daemon start remains user-managed.
- Phase 5 active protection is not started.
