# CALLSHIELD Android Bridge — Phase 6

The Kotlin bridge connects Android `CallScreeningService` to the existing
Termux daemon using a bounded filesystem `LocalSocket` only.

## Decision safety

Android requests rejection only when a strictly validated response contains:

```text
recommended_action = BLOCK
applied_action = BLOCK
mode = ACTIVE
emergency_off = false
policy_error = false
```

Every other state is ALLOW, including malformed input/response, unexpected
action or mode, timeout, unavailable daemon/socket, emergency, cancellation,
and internal errors.

## Phase 6 protocol hardening

Screening requests now include:

- exact `callshield/1` protocol
- fresh UUID request ID
- timezone timestamp within the replay window
- validated `tel:` number
- `android_call_screening` source

Rejection feedback uses a separate fresh request UUID/timestamp and carries the
original screening request ID as `screening_request_id`. The daemon maintains a
bounded replay cache and confirms only a persisted ACTIVE applied block.

Request/response sizes and read time remain bounded. Invalid daemon JSON is
rejected before `ScreeningResult` can request a block.

## Lifecycle

The service processes incoming calls only. Null, non-`tel`, empty, or malformed
handles immediately ALLOW. The coroutine scope is tied to service destruction;
lifecycle cancellation remains fail-open.

## Permissions

The manifest requests no camera, microphone, contacts, SMS, location, storage,
accessibility, or Internet permission. Android's protected Call Screening role
must be explicitly granted by the user.

## Safe defaults and emergency

Fresh Termux configuration is screening disabled and DRY_RUN. ACTIVE requires
explicit CLI confirmation. The owner-only emergency marker overrides ACTIVE,
and reset leaves protection disabled and DRY_RUN.

## Android/Termux isolation limitation

Termux and a separately installed Android bridge normally use different UIDs.
Filesystem permissions and SELinux commonly prevent opening Termux's private
0600 socket. No TCP, HTTP, public socket, or root workaround is provided. A
secure shared Unix endpoint or same-UID companion deployment remains required
for physical use.

CLI `Bridge: CONNECTED` means local CLI-to-daemon IPC only; it does not verify a
device or granted Android role.

## Build status

JDK, Gradle/wrapper, Android SDK, emulator, and physical device were unavailable:

```text
ANDROID BUILD = NOT VERIFIED
PHYSICAL DEVICE = NOT VERIFIED
```

No APK or physical rejection result is claimed.

## Phase boundary

Phase 7 has not started.
