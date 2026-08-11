# CALLSHIELD Android Bridge — Phase 5

This minimal Kotlin project connects Android's `CallScreeningService` to the
existing Termux daemon through local Unix IPC.

## Phase 5 behavior

The bridge may request rejection only when a strictly validated daemon response
contains both:

```text
applied_action = BLOCK
mode = ACTIVE
```

It also requires a BLOCK recommendation, valid protocol fields, and emergency
off. Every other response applies ALLOW, including DRY_RUN, UNKNOWN, timeout,
unavailable daemon, malformed JSON, invalid action/mode, and internal error.

After successfully delivering an ACTIVE BLOCK response to Android, the bridge
sends a bounded `screening_feedback` acknowledgement. The daemon increments
`Actually Rejected` only when that acknowledgement matches a persisted ACTIVE
applied block.

## Safe defaults and activation

Termux defaults remain:

```text
screening_enabled = false
screening_mode = DRY_RUN
active_mode_confirmed = false
```

ACTIVE mode requires explicit confirmation in Termux:

```bash
callshield screening mode active
# Enable ACTIVE call protection? [y/N]
```

Emergency off immediately overrides every active decision:

```bash
callshield emergency-off
callshield emergency-reset
```

Reset does not enable ACTIVE mode.

## Components

- `CallShieldScreeningService.kt` — validates incoming `tel:` handles and
  constructs the Android response.
- `BridgeClient.kt` — bounded filesystem `LocalSocket` requests and feedback.
- `Protocol.kt` — strict `callshield/1` request/response/feedback models.
- `ScreeningResult.kt` — applies the exact ACTIVE BLOCK validation rule.
- `BridgeSetupActivity.kt` — minimal Android call-screening role request.

The fraud detector and policy engine remain in Python/Termux.

## Permissions

The manifest requests no camera, microphone, contacts, SMS, location, storage,
accessibility, or Internet permission. The screening service is protected by
`android.permission.BIND_SCREENING_SERVICE`; the user must grant the system Call
Screening role.

## Fail-open matrix

| Result | Android action |
|---|---|
| ACTIVE + valid BLOCK | request rejection |
| ACTIVE + ALLOW | allow |
| DRY_RUN + BLOCK recommendation | allow |
| emergency off | allow |
| invalid/missing fields | allow |
| unexpected mode/action | allow |
| timeout/socket/daemon unavailable | allow |
| malformed response | allow |

## Android/Termux isolation limitation

The default socket is inside Termux's private home:

```text
/data/data/com.termux/files/home/.callshield/run/callshield.sock
```

A separately installed Android application normally has a different UID, and
Android filesystem/SELinux rules commonly prevent access to this 0600 socket.
The bridge does not add a public or network fallback. A secure shared Unix
endpoint or same-UID/companion integration remains a deployment requirement.

`callshield screening status` verifies local CLI-to-daemon IPC only and reports
Android/device state as unverified.

## Build status

A build requires JDK 17, compatible Gradle, and Android SDK 34. Those tools,
along with an emulator or physical device, were unavailable in the implementation
environment.

```text
ANDROID BUILD = NOT VERIFIED
DEVICE TEST = NOT VERIFIED
```

No physical rejection or APK result is claimed.

## Phase boundary

Phase 6 has not started. This project does not add doctor diagnostics, replay
protection, or unrelated Phase 6 hardening.
