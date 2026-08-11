# CALLSHIELD Android Screening Bridge — Phase 4

This directory contains the minimal Kotlin bridge from Android's
`CallScreeningService` API to the existing CALLSHIELD Termux daemon.

> **Phase 4 is DRY_RUN only. A recommendation may be BLOCK, but the applied
> action is always ALLOW. Automatic call rejection is not implemented.**

## Components

- `CallShieldScreeningService.kt` — accepts incoming `tel:` call details,
  rejects malformed bridge input (not the call), and always sends an explicit
  ALLOW response to Android.
- `BridgeClient.kt` — bounded 1500 ms local Unix-socket client.
- `Protocol.kt` — strict `callshield/1` request and response contract.
- `ScreeningResult.kt` — immutable `appliedAction = ALLOW` and
  `mode = DRY_RUN` invariants.
- `BridgeSetupActivity.kt` — minimal Android role-request activity with no app
  configuration UI.

The fraud engine remains in Python and is not duplicated in this project.

## Architecture

```text
Incoming call
    │
    ▼
CallShieldScreeningService
    │
    ▼
BridgeClient (Android LocalSocket)
    │
    ▼
Existing ~/.callshield/run/callshield.sock
    │
    ▼
Termux Daemon → EventProcessor → analyze_number()
    │
    ▼
Recommended ALLOW/BLOCK/UNKNOWN
    │
    ▼
Applied ALLOW
```

No Internet permission or network listener is used. The bridge uses a local
filesystem Unix domain socket only.

## Permissions and data access

The manifest requests none of the following:

- camera
- microphone
- contacts
- SMS
- location
- storage
- accessibility
- Internet

The screening service is protected by Android's
`android.permission.BIND_SCREENING_SERVICE`. The user must explicitly grant the
Call Screening role through the system role dialog or Android settings.

## Important Android/Termux isolation limitation

The production default socket path is:

```text
/data/data/com.termux/files/home/.callshield/run/callshield.sock
```

Termux and the Android bridge normally run under different Android application
UIDs. Modern Android filesystem permissions and SELinux commonly prevent the
bridge app from traversing the Termux private home directory or opening its
0600 socket. **The code does not claim that this connection works on a physical
device, and it does not fall back to TCP or a public socket.**

A real deployment therefore needs an explicitly designed, user-approved shared
Unix-socket endpoint or same-UID/companion integration that preserves local-only
access. That device-specific integration was not available or verified in this
build environment. When the socket cannot be reached, the bridge returns
`UNKNOWN / ALLOW` with a fail-open reason.

`callshield screening status` reports `Bridge: CONNECTED` only when the local
CLI reached the daemon's Unix socket. It reports `Android: NOT VERIFIED`; it
must not be interpreted as proof that an Android device, role, or service is
connected.

## Wire protocol

The exact Android request is one bounded UTF-8 JSON line:

```json
{
  "protocol": "callshield/1",
  "request_id": "24fd51e1-f576-4f23-b097-b05d500d6f16",
  "number": "+919876543210",
  "source": "android_call_screening"
}
```

Successful analysis response:

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

Requests are limited to 16 KiB and responses to 64 KiB. Protocol version,
request UUID, source, number, response ranges, actions, mode, and UTF-8 encoding
are validated.

## Fail-open behavior

All of these produce an ALLOW response:

- null or missing call handle
- non-`tel` handle
- empty or malformed number
- unavailable Termux or daemon
- inaccessible or missing Unix socket
- timeout
- malformed or mismatched response
- invalid protocol
- database or internal error
- service cancellation/recreation

The Android response builder explicitly sets disallow and reject flags to
`false`, along with normal call-log and notification behavior. There is no code
path that applies a blocked call result.

## Configuration

Termux configuration controls:

```text
screening_enabled = true
screening_mode = DRY_RUN
screening_timeout_ms = 1500
```

`screening_timeout_ms` is bounded to 200–5000 ms. Any loaded invalid mode is
coerced to `DRY_RUN`; CLI attempts to select another mode are rejected.

Useful commands:

```bash
callshield daemon start
callshield screening status
callshield screening health
callshield screening metrics
callshield screening enable
callshield screening disable
callshield screening mode
```

## Build and device verification

Open `android/` in Android Studio or use a compatible installed Gradle, JDK 17,
and Android SDK 34:

```bash
cd android
gradle test
gradle assembleDebug
```

No Gradle executable, JDK, Android SDK, emulator, or physical device was
available in the implementation environment. Consequently:

```text
ANDROID BUILD = NOT VERIFIED
DEVICE TEST = NOT VERIFIED
```

This is reported as a limitation rather than represented as a successful build.

## Phase boundary

Phase 5 is the future phase reserved for active protection after separate
design, consent, policy, and safety work. Phase 5 has not been started here.
