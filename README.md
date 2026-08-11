# CALLSHIELD

> **Local, explainable fraud-number analysis with a persistent Termux daemon
> and a Phase 4 Android screening bridge.**

CALLSHIELD keeps its database on-device and reuses one deterministic Python
analyzer for CLI scans, daemon events, and Android screening requests.

## Phase status

- **Phase 1 — Foundation:** CLI, normalization, SQLite, local lists
- **Phase 2 — Advanced Intelligence:** signals, reputation, confidence, profiles
- **Phase 3 — Background Engine:** persistent daemon, bounded events, health,
  heartbeat, recovery, and owner-only Unix IPC
- **Phase 4 — Android Screening Bridge:** Kotlin `CallScreeningService` bridge,
  versioned local protocol, screening persistence, health, and metrics

> **Phase 4 is DRY_RUN only. A recommendation may be BLOCK, but the applied
> action is always ALLOW. Automatic call rejection is disabled and not
> implemented. Actually Rejected is always 0.**

## Phase 4 scope

Implemented:

- minimal Kotlin Android project under `android/`
- incoming-call service with safe `tel:` handle extraction
- local Android `LocalSocket` bridge to the existing daemon socket
- strict `callshield/1` JSON protocol and 1500 ms timeout
- fail-open behavior for all errors
- `INCOMING_CALL` event using the existing `EventProcessor` and
  `analyze_number()` engine
- schema v3 `screening_events` audit records
- screening CLI, health, and metrics

Not implemented:

- active call blocking
- automatic rejection
- active policy package or blocking thresholds
- emergency-off control
- network server or HTTP API
- root integration
- Phase 5 or Phase 6 functionality

## Safety invariant

```text
RECOMMEND BLOCK → APPLY ALLOW
ACTUALLY REJECTED = 0
```

Android always builds an explicit allow response with disallow/reject flags set
to `false`. The Python response boundary and SQLite schema independently enforce
`applied_action = ALLOW` and `mode = DRY_RUN`.

## Architecture

```text
Incoming Android call
        │
        ▼
CallShieldScreeningService (Kotlin)
        │
        ▼
BridgeClient / Protocol callshield/1
        │
        ▼
~/.callshield/run/callshield.sock (AF_UNIX, 0600)
        │
        ▼
DaemonService
        │
        ▼
INCOMING_CALL Event → EventProcessor
        │
        ▼
Existing Phase 2 analyze_number()
        │
        ▼
Screening result + SQLite + health metrics
        │
        ▼
Recommended action / Applied ALLOW
```

There is one local IPC architecture. Phase 4 does not add a second server,
network listener, or duplicated detector.

## Repository layout

```text
callshield/
├── callshield/
│   ├── cli.py
│   ├── config.py
│   ├── database.py
│   ├── detector.py
│   ├── daemon/
│   │   ├── service.py
│   │   ├── process.py
│   │   ├── heartbeat.py
│   │   ├── health.py
│   │   ├── signals.py
│   │   └── recovery.py
│   ├── events/
│   │   ├── models.py
│   │   ├── queue.py
│   │   ├── processor.py
│   │   └── types.py
│   ├── intelligence/
│   └── rules/
├── android/
│   ├── app/src/main/AndroidManifest.xml
│   ├── app/src/main/java/com/callshield/bridge/
│   │   ├── CallShieldScreeningService.kt
│   │   ├── BridgeClient.kt
│   │   ├── Protocol.kt
│   │   ├── ScreeningResult.kt
│   │   └── BridgeSetupActivity.kt
│   └── README.md
├── tests/
├── scripts/
├── VERSION
└── PHASE4_REPORT_FINAL.md
```

## Termux installation

Requirements: Python 3.8+, POSIX shell, no root.

```bash
pkg update
pkg install python git
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

The installer creates owner-only state under:

```text
~/.callshield/
├── data/
│   ├── callshield.db
│   └── config.json
├── logs/
├── run/
│   ├── callshield.pid
│   ├── callshield.sock
│   └── heartbeat.json
└── state/daemon_metrics.json
```

It is idempotent and preserves existing data.

## CLI quick start

```bash
callshield version
callshield daemon start
callshield status
callshield metrics
callshield event test +919876543210

callshield screening status
callshield screening health
callshield screening metrics
callshield screening enable
callshield screening disable
callshield screening mode

callshield scan +919876543210
callshield reputation +919876543210
callshield history +919876543210
callshield signals +919876543210
callshield report +919876543210 --reason "suspected scam"
callshield block +919876543210
callshield allow +919876543210
```

`callshield event test` remains clearly labeled as a test event and does not
represent a physical call.

### Screening status meaning

Example:

```text
CALLSHIELD SCREENING

Bridge:              CONNECTED
Daemon:              RUNNING
Android:             NOT VERIFIED
Mode:                DRY_RUN
Timeout:             1500 ms
Live Screening:      IPC READY — DEVICE NOT VERIFIED
Auto Reject:         DISABLED
Actually Rejected:   0
```

`Bridge: CONNECTED` means only that the CLI reached the daemon's local Unix
socket. It does not claim that an Android device is attached, that the Android
role is granted, or that a physical incoming call was tested.

## Android/Termux socket limitation

The Android bridge defaults to:

```text
/data/data/com.termux/files/home/.callshield/run/callshield.sock
```

Termux and a separately installed Android bridge normally have different app
UIDs. Android filesystem permissions and SELinux commonly prevent the bridge
from traversing Termux's private home or opening its 0600 socket. No physical
connection was available in this environment, and CALLSHIELD does not replace
this with a public or network endpoint.

A production deployment needs a separately designed, user-approved shared Unix
endpoint or same-UID/companion integration. Until then, inaccessible socket,
unavailable Termux, timeout, or malformed response all fail open to
`UNKNOWN / ALLOW`. See `android/README.md`.

## IPC protocol

Exact Android request (one UTF-8 JSON line, maximum 16 KiB):

```json
{
  "protocol": "callshield/1",
  "request_id": "24fd51e1-f576-4f23-b097-b05d500d6f16",
  "number": "+919876543210",
  "source": "android_call_screening"
}
```

Dry-run response (maximum 64 KiB):

```json
{
  "protocol": "callshield/1",
  "request_id": "24fd51e1-f576-4f23-b097-b05d500d6f16",
  "risk_score": 92,
  "confidence": 95,
  "verdict": "MALICIOUS",
  "recommended_action": "BLOCK",
  "applied_action": "ALLOW",
  "mode": "DRY_RUN",
  "reason": "DRY_RUN",
  "latency_ms": 14
}
```

The daemon continues to support all Phase 3 IPC commands (`ping`, `status`,
`metrics`, `health`, `daemon_info`, `event`, and `stop`) on the same socket.

## Database

SQLite schema version 3 preserves Phase 1–3 data and adds
`screening_events`:

- timestamp and event UUID
- number, masked number, and SHA-256 hash
- risk and confidence
- verdict and recommendation
- applied action and mode
- reason and latency
- source

The database is local, parameterized, WAL-backed, and owner-only. A schema
constraint prevents a screening row from recording a non-ALLOW applied action.
Plaintext numbers are never written to daemon or Android logs.

## Configuration

Phase 4 adds only:

| Key | Default | Validation |
|---|---:|---|
| `screening_enabled` | `true` | boolean |
| `screening_mode` | `DRY_RUN` | DRY_RUN only |
| `screening_timeout_ms` | `1500` | 200–5000 ms |

Invalid loaded screening values fail safe: mode becomes `DRY_RUN`, timeout
becomes 1500 ms, and a malformed enable flag disables screening. Attempts to
select another mode are rejected.

All Phase 3 resource settings remain intact, including the 256-event queue,
8 KiB event payload bound, IPC bounds/timeouts, heartbeat, and graceful
shutdown timeout.

## Screening metrics

`callshield screening metrics` reports:

- incoming calls
- screened
- timeouts
- bridge errors
- high risk
- screening allowed
- screening unknown
- block recommended
- screening blocked
- actually rejected

For version 0.4.0:

```text
Screening Blocked: 0
Actually Rejected: 0
```

## Fail-open matrix

| Condition | Verdict | Recommendation | Applied |
|---|---|---|---|
| low risk | detector result | ALLOW | ALLOW |
| high risk | detector result | BLOCK | ALLOW |
| invalid number | UNKNOWN | ALLOW | ALLOW |
| screening disabled | UNKNOWN | ALLOW | ALLOW |
| timeout | UNKNOWN | ALLOW | ALLOW |
| daemon/socket unavailable | UNKNOWN | ALLOW | ALLOW |
| invalid protocol/response | UNKNOWN | ALLOW | ALLOW |
| database/internal error | UNKNOWN | ALLOW | ALLOW |

## Permissions and security

The Android manifest requests no camera, microphone, contacts, SMS, location,
storage, accessibility, or Internet permission. The user must grant Android's
Call Screening role through the system role dialog.

Implementation checks confirm:

- Unix-domain sockets only
- no network listener or HTTP server
- no root requirement
- no shell execution
- bounded IPC and timeout
- masked logging
- explicit ALLOW response on every Android path
- no active policy package, emergency-off, or automatic rejection

## Tests

```bash
pytest -q
# 189 passed
```

The 163 verified Phase 3 tests remain, with 26 Phase 4 Python tests covering
protocol compatibility, safe/high-risk/invalid/null inputs, timeout, unavailable
persistence, internal failure, concurrency, migration, CLI, health, metrics,
and the invariant `BLOCK recommendation → ALLOW applied`.

Kotlin unit-test sources cover the exact JSON request, strict response parsing,
invalid data, unavailable daemon, and immutable ALLOW result.

## Android build/device verification

The implementation environment had no Java/JDK, Gradle, Android SDK, emulator,
or physical device. Therefore:

```text
ANDROID BUILD = NOT VERIFIED
DEVICE TEST = NOT VERIFIED
```

No build or device success is claimed.

## Roadmap and limitations

- Phase 4 does not automatically reject calls.
- Physical Android-to-Termux socket access remains device/deployment-specific
  and was not verified.
- Daemon startup remains user-managed; boot integration is not installed.
- Memory reporting depends on platform support.
- Phase 5 is reserved for future active protection after separate consent,
  policy, and safety design. **Phase 5 has not started.**

## License

MIT — see `LICENSE`.
