# CALLSHIELD Android Bridge — Phase 4

Minimal privileged bridge between Android's `CallScreeningService` and the Termux daemon.

> **Phase 4 receives and analyzes real Android call-screening events but does not automatically reject calls. Automatic rejection is intentionally disabled until Phase 5.**

## Architecture

```
REAL INCOMING CALL
        │
        ▼
Android CallScreeningService (CallShieldScreeningService.kt)
        │
        ▼
BridgeClient (Protocol.kt / ScreeningResult.kt)
        │
        ▼
Local CALLSHIELD IPC (~/.callshield/run/callshield.sock, Unix socket, 700)
        │
        ▼
Termux Daemon 0.3.0+ (DaemonService + EventProcessor)
        │
        ▼
Detection Engine (analyze_number)
        │
        ▼
DetectionResult → Bridge response
        │
        ▼
Android Bridge (logs, returns dry-run ALLOW)
```

The fraud engine remains in Python/Termux. The Android component is only a privileged bridge.

## Permissions

- **Required:** No manifest permission for call screening; Android grants via `RoleManager` / Settings → Default apps → Call screening.
- **NOT requested:** CAMERA, MICROPHONE, LOCATION, SMS, CONTACTS, STORAGE, root.

## Screening Setup

1. Install Termux: `pkg update && pkg upgrade && pkg install python git`
2. Install CALLSHIELD: `git clone <repo> && cd Callshield && bash scripts/install.sh`
3. Build Android bridge (if SDK available):
   ```bash
   cd android
   ./gradlew assembleDebug  # or use Android Studio
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```
   If SDK/Gradle is not available, the bridge cannot be built on this host — see "Build Validation" below.
4. Enable call screening:
   - Android Settings → Apps → Default apps → Call screening app → select **CallShield Bridge**
   - Or: `adb shell telecom set-call-screening-service com.callshield.bridge/.CallShieldScreeningService`
5. Verify:
   ```bash
   callshield screening status  # Bridge CONNECTED, Mode DRY_RUN, Timeout 1500ms
   callshield status            # Daemon RUNNING, Call Screening NOT CONNECTED (dry-run) until real call
   callshield metrics           # Incoming Calls, Screened, etc.
   ```

## Dry-Run Mode

- `screening_mode` defaults to `DRY_RUN` (config `screening_mode=DRY_RUN`, `screening_timeout_ms=1500`).
- Every call is analyzed (real `risk_score`, `verdict`, `recommended_action`), but **applied is always `ALLOW`**:
  ```
  Recommended: BLOCK (risk 94)
  Applied:     ALLOW
  Reason:      DRY_RUN
  ```
- Change (Phase 4 only allows DRY_RUN):
  ```bash
  callshield screening mode          # show
  callshield screening enable        # enable bridge
  callshield screening disable       # disable
  ```

## Termux IPC

- **Primary:** Unix socket `~/.callshield/run/callshield.sock` (700, local-only, JSON, 16KB req, 64KB resp, timeout, no TCP).
- **Android sandbox:** Direct access to Termux private `~/.callshield` may be blocked on Android 10+ (SELinux). The bridge first tries `LocalSocket` to the Termux path, then fallback to `/data/local/tmp/callshield.sock` (documented alternative, also 700, still local, no network). **No insecure world-readable bridge is created.** If both fail, the bridge fails safely (`UNKNOWN`/`ALLOW`, reason `DAEMON_UNAVAILABLE`/`SCREENING_TIMEOUT`).

## Protocol

Request (`callshield/1`):
```json
{
  "protocol": "callshield/1",
  "type": "incoming_call",
  "request_id": "uuid",
  "number": "+919876543210",
  "timestamp": "2026-08-10T12:00:00Z"
}
```

Response:
```json
{
  "protocol": "callshield/1",
  "request_id": "uuid",
  "risk_score": 87,
  "confidence": 92,
  "verdict": "HIGH_RISK",
  "recommended_action": "BLOCK",
  "applied_action": "ALLOW",
  "mode": "DRY_RUN"
}
```

Validated: protocol version, request_id, number format, size. Never `eval`/`exec`.

## Timeout

- `screening_timeout_ms` default 1500ms.
- If daemon doesn't respond in time, bridge returns `UNKNOWN`/`ALLOW`/`SCREENING_TIMEOUT`, never rejects.

## Privacy

- Local only, no upload, masked logs (`+91******210`), minimal `screening_events` table (masked + hash, not raw), documented.

## Build Validation

If `ANDROID_HOME`/`gradle` not available, build is skipped and reported as limitation; Python/Termux tests still validate.

```bash
./gradlew testDebugUnitTest  # runs Protocol/ScreeningResult/BridgeClient tests
```

## No Auto-Rejection

Phase 4 never calls `setDisallowCall(true)`, `setRejectCall(true)`, `setSilenceCall(true)`, root, or hidden APIs. See `CallShieldScreeningService.kt` — always builds `CallResponse.Builder().setDisallowCall(false).setRejectCall(false)...`.

## Troubleshooting

- `callshield screening status` shows `NOT CONNECTED` → check `callshield status` (daemon RUNNING?), `callshield metrics`, `adb logcat | grep CallShieldScreening`
- `TIMEOUT` → increase `screening_timeout_ms` via `callshield config set screening_timeout_ms 2000` (200–5000)
- Permissions: ensure call-screening role granted in Settings.

