# CALLSHIELD Phase 6 Security Audit

Date: 2026-08-11
Scope: repository implementation through version 0.8.0 (including the Phase 8.5 terminal interface)

## Results

| Area | Status | Evidence |
|---|---|---|
| Dynamic Python execution | PASS | AST scan found no calls to dynamic evaluation functions or `os.system` |
| Shell execution | PASS | No `shell=True`; daemon subprocess is a fixed argument list used only for process startup |
| Unsafe deserialization | PASS | No pickle import/use; IPC accepts strict bounded JSON only |
| Network listener | PASS | Python listeners use `AF_UNIX`; Android uses `LocalSocket`; no `AF_INET`, HTTP, or TCP server |
| `SOCK_STREAM` review | PASS | Present only with `AF_UNIX`, providing a local Unix stream socket |
| IPC bounds | PASS | 16 KiB request, 64 KiB response, 16-level JSON depth, bounded keys/arrays, 1.5 s default timeout |
| IPC protocol | PASS | Version, UUID, timezone timestamp, command allowlist, duplicate keys, freshness, and replay checks |
| Replay protection | PASS | Thread-safe 5-minute/4096-entry cache plus persisted screening event-ID check across daemon restart |
| Configuration writes | PASS | Unique same-directory temporary file, flush, file fsync, chmod, atomic replace, parent fsync |
| Invalid configuration | PASS | Empty/malformed/invalid config produces disabled DRY_RUN fallback; strict diagnostics remain available |
| Database | PASS | WAL, foreign keys, full synchronous mode, integrity/schema checks, bounded lock tests, rollback tests |
| PID/socket recovery | PASS | Existing strict process ownership and owner/type checks retained; stale repair tests pass |
| Emergency-off | PASS | Atomic owner-only marker, parent sync on reset, idempotency, pre-policy check, disabled DRY_RUN reset state |
| Phone-number logging | PASS | Python and Android screening logs use masked values; block inspection selects masked number only |
| Android permissions | PASS | Manifest has no camera, microphone, contacts, SMS, location, storage, accessibility, or Internet permission |
| Android decision validation | PASS | Source review/tests require valid ACTIVE + BLOCK + non-emergency + no policy error; all other states ALLOW |
| Concurrent IPC | PASS | Automated 5-request, 10-request, and duplicate-race tests; daemon remains responsive |
| Root requirement | PASS | Installation/runtime use user-owned paths and request no root operation |
| Phase 7 reputation privacy | PASS | Package has no network imports; profile/history/trust storage uses masked identifiers and canonical SHA-256 hashes only |
| Reputation fail-open | PASS | Unavailable/corrupt reputation marks policy unavailable and applies ALLOW; trust/whitelist remain overrides |
| Phase 8 adaptive privacy | PASS | Adaptive package has no network imports and derived tables use hashes/masks without unsupported telemetry fields |
| Adaptive policy safety | PASS | Intelligence unavailable applies ALLOW; trend/pattern context cannot raise detector risk or bypass existing gates |
| Intelligence retention | PASS | Derived observations/profiles have count/age bounds and cleanup does not delete core Phase 1–7 evidence |
| Phase 8.5 interface network isolation | PASS | AST scan of all 39 `callshield/ui/` modules found no networking import, no hardcoded URL/host, and no non-stdlib dependency; the only transport remains the pre-existing local `AF_UNIX` IPC |
| Interface execution safety | PASS | No `eval`, `exec`, `compile`, `os.system`, `subprocess`, `shell=True`, `pickle` or `AF_INET` in the interface; CLI actions dispatch through the `cli._COMMANDS` function table with no shell |
| Interface privilege boundary | PASS | The interface writes no security configuration; `save_config`, `set_value`, `set_profile`, `enable_emergency_off` and `reset_emergency_off` appear nowhere in `callshield/ui/` |
| ACTIVE confirmation preservation | PASS | The interface hands the real terminal to the existing CLI handler for ACTIVE mode; `screening enable` from the interface stays DRY_RUN with `active_mode_confirmed=false` |
| Policy simulation isolation | PASS | Simulated decisions are wrapped in a read-only view flagged `simulation=True`; configuration bytes are asserted unchanged after simulation |
| Interface preference isolation | PASS | Reset rewrites only `ui_state.json`; config contents, database size, list entries and report counts are asserted unchanged |
| Interface number masking | PASS | Every rendered screen is asserted to contain no plaintext number; display uses `mask_number` throughout |

## Not tested

| Area | Status | Reason |
|---|---|---|
| Android compilation | NOT TESTED | JDK, Gradle/wrapper, and Android SDK unavailable |
| Physical Android device | NOT TESTED | No emulator/device or granted screening role available |
| Android/Termux SELinux integration | NOT TESTED | No physical cross-UID deployment environment available |
| External penetration test | NOT TESTED | No independent security lab or adversarial device test was performed |
| Terminal interface on a Termux device | NOT TESTED | Verified under a Linux pseudo-terminal only; no physical Android device running Termux was available |

## Phase boundary

This audit does not add or claim Phase 7 functionality. It covers only the
Phase 6 hardening implemented in this repository.
