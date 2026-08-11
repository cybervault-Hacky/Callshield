# CALLSHIELD

> **Local, explainable, fail-open call protection for Termux and Android.**

CALLSHIELD keeps analysis and persistence on-device. Phase 5 adds an explicit
active policy layer to the existing Phase 4 Android screening bridge without
duplicating the Phase 2 detector or replacing Phase 3 Unix IPC.

## Phase status

- Phase 1 — Foundation: **COMPLETE**
- Phase 2 — Advanced Intelligence: **COMPLETE**
- Phase 3 — Background Engine: **COMPLETE**
- Phase 4 — Android Screening Bridge: **COMPLETE**
- Phase 5 — Active Call Protection: **COMPLETE**
- Phase 6 — **NOT STARTED**

## Safe defaults

Fresh installations always start with:

```text
screening_enabled = false
screening_mode = DRY_RUN
active_mode_confirmed = false
screening_policy = BALANCED
```

Installing or upgrading CALLSHIELD never silently activates rejection.

```text
DRY_RUN: recommend BLOCK → apply ALLOW
ACTIVE:  policy-qualified BLOCK → apply BLOCK
ERROR / TIMEOUT / UNCERTAINTY / EMERGENCY: apply ALLOW
```

ACTIVE requires an explicit user confirmation:

```bash
callshield screening mode active
# Enable ACTIVE call protection? [y/N]
```

The default answer is no. `callshield screening enable` is intentionally a
DRY_RUN-only enable path.

## Policy engine

The decision-only policy package is:

```text
callshield/policy/
├── __init__.py
├── engine.py
├── models.py
└── thresholds.py
```

It receives the existing detection result and returns a structured decision.
It never calls Android and cannot reject a call itself.

Default policies:

| Policy | Active block | Confidence |
|---|---:|---:|
| RELAXED | 92 | 90 |
| BALANCED | 85 | 80 |
| STRICT | 80 | 75 |

All thresholds are configurable and restricted to 0–100. Invalid thresholds or
policy names fail open to ALLOW.

An ACTIVE block requires all of the following:

1. `screening_enabled = true`
2. `screening_mode = ACTIVE`
3. explicit confirmation marker present in validated configuration
4. risk at or above the selected active threshold
5. confidence at or above the selected confidence threshold
6. no whitelist match
7. emergency-off inactive
8. valid policy result and IPC response

Everything else applies ALLOW.

## Whitelist precedence

The existing whitelist is absolute. A whitelisted number is ALLOW even if its
risk/confidence values are 100, the mode is ACTIVE, or it is also blacklisted.
No policy threshold overrides the whitelist.

## Emergency off

```bash
callshield emergency-off
callshield emergency-reset
```

The marker is owner-only:

```text
~/.callshield/state/emergency_off  (0600)
```

While it exists, every screening decision applies ALLOW. `emergency-off` is
idempotent and also persists disabled DRY_RUN state. `emergency-reset` only
removes the marker; it does not enable screening or ACTIVE mode.

## Architecture

```text
Incoming Android call
        │
        ▼
CallShieldScreeningService
        │
        ▼
BridgeClient / callshield/1
        │
        ▼
~/.callshield/run/callshield.sock (AF_UNIX, 0600)
        │
        ▼
DaemonService → INCOMING_CALL → EventProcessor
        │
        ▼
analyze_number()  (existing Phase 2 detector)
        │
        ▼
PolicyEngine
        │
        ├── fail-open ALLOW
        └── validated ACTIVE BLOCK
                │
                ▼
Android response
                │
                ▼
screening_feedback only after rejection response delivery
```

There is one local IPC architecture. CALLSHIELD has no TCP or HTTP server.

## CLI

```bash
callshield version
callshield daemon start
callshield status
callshield metrics

callshield screening status
callshield screening mode
callshield screening mode dry-run
callshield screening mode active
callshield screening enable
callshield screening disable
callshield screening policy
callshield screening policy strict
callshield screening health
callshield screening metrics

callshield policy test
callshield policy test --risk 95 --confidence 95 --mode active
callshield policy test --risk 100 --confidence 100 --mode active --whitelist
callshield policy test --risk 100 --confidence 100 --mode active --emergency-off

callshield emergency-off
callshield emergency-reset
```

Policy simulation is explicitly labeled `SIMULATION ONLY` and never invokes a
real Android call action.

## Screening status

Status shows activation and policy state separately from device readiness:

```text
Screening Enabled:   YES/NO
Mode:                DRY_RUN/ACTIVE
Policy:              BALANCED
Active Threshold:    85
Confidence Threshold: 80
Auto Reject:         ENABLED/DISABLED
Block Recommended:   n
Applied Blocks:      n
Actually Rejected:   n
Emergency Off:       YES/NO
Android:             NOT VERIFIED
```

`Bridge: CONNECTED` means only that the local daemon Unix socket answered. It
does not verify an Android device, role grant, or physical call.

## IPC and fail-open behavior

The existing `callshield/1` screening request remains:

```json
{
  "protocol": "callshield/1",
  "request_id": "uuid",
  "number": "+919876543210",
  "source": "android_call_screening"
}
```

Phase 5 responses add policy context:

```json
{
  "protocol": "callshield/1",
  "request_id": "uuid",
  "risk_score": 90,
  "confidence": 89,
  "verdict": "MALICIOUS",
  "recommended_action": "BLOCK",
  "applied_action": "BLOCK",
  "mode": "ACTIVE",
  "reason": "ACTIVE_POLICY_BLOCK",
  "policy_name": "BALANCED",
  "threshold": 85,
  "confidence_threshold": 80,
  "emergency_off": false,
  "policy_error": false,
  "latency_ms": 4
}
```

Android permits rejection only for the exact valid pair:

```text
applied_action = BLOCK
mode = ACTIVE
```

Unexpected action, mode, protocol, missing fields, malformed JSON, timeout,
unavailable daemon/socket, database error, emergency state, or internal error
produces ALLOW.

## Persistence and metrics

Schema version 4 rebuilds the existing `screening_events` table without losing
Phase 4 rows. New fields include:

- policy action and policy name
- active and confidence thresholds
- policy reason
- emergency state
- applied ALLOW/BLOCK
- Android-confirmed rejection state and timestamp

Existing number, masked number, SHA-256 hash, risk, confidence, verdict, reason,
latency, source, event ID, and mode fields remain.

Metrics distinguish:

- **Block Recommended** — policy selected BLOCK
- **Screening Blocked** — daemon applied BLOCK
- **Actually Rejected** — Android sent successful rejection feedback

DRY_RUN may have recommendations but always has zero applied blocks. Actual
rejection is never inferred from a daemon decision.

## Android bridge

The Kotlin bridge validates protocol, action, mode, policy fields, emergency
state, and timeout. It requests rejection only for a valid ACTIVE BLOCK result.
After delivering that response, it sends bounded local `screening_feedback` so
the daemon may increment `Actually Rejected`.

The manifest requests no camera, microphone, contacts, SMS, location, storage,
accessibility, or Internet permission.

### Android/Termux isolation limitation

Android and Termux normally use different application UIDs. Filesystem
permissions and SELinux commonly prevent a separately installed bridge from
opening Termux's private 0600 socket. No public or network fallback is added.
A secure shared Unix endpoint or same-UID/companion deployment remains required
for physical use. Device connectivity is not claimed by CLI IPC status.

## Installation

```bash
pkg update
pkg install python git
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

The installer creates `~/.callshield/{data,logs,run,state}` with owner-only
permissions, preserves existing data, runs without root, and leaves active
protection disabled.

## Security properties

- fail-open on uncertainty and errors
- owner-only local Unix IPC
- no TCP/HTTP listener
- no root requirement
- no arbitrary or dynamic code execution
- no plaintext phone numbers in logs
- bounded queue, payloads, responses, and timeouts
- strict PID ownership and stale-state recovery retained from Phase 3
- no doctor command, replay protection, or Phase 6 diagnostics

## Tests

```bash
pytest -q
# 220 passed
```

The suite preserves all Phase 3 and Phase 4 tests and adds Phase 5 coverage for
policy thresholds, ACTIVE/DRY_RUN decisions, whitelist override, emergency
state, invalid configuration, explicit CLI confirmation, simulation,
persistence migration, feedback metrics, concurrency, and fail-open behavior.

Kotlin unit-test sources cover valid ACTIVE rejection, DRY_RUN/ALLOW behavior,
emergency state, invalid actions/modes, unavailable daemon, and feedback.

## Android, device, and performance verification

The implementation environment does not include a JDK, Gradle, Android SDK,
emulator, or physical device:

```text
ANDROID BUILD = NOT VERIFIED
DEVICE TEST = NOT VERIFIED
PERFORMANCE BENCHMARK = NOT INDEPENDENTLY VERIFIED
```

No APK, physical rejection, device readiness, or benchmark result is claimed.

## Known limitations

- Physical Android-to-Termux socket integration is deployment-specific and
  unverified.
- `Actually Rejected` requires bridge feedback; without a verified device it
  remains zero during manual Termux simulation.
- Daemon startup remains user-managed.
- Phase 6 is not implemented and has not started.

## License

MIT — see `LICENSE`.
