# CALLSHIELD Phase 6 Security Audit

Date: 2026-08-11
Scope: repository implementation through version 0.7.0

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

## Not tested

| Area | Status | Reason |
|---|---|---|
| Android compilation | NOT TESTED | JDK, Gradle/wrapper, and Android SDK unavailable |
| Physical Android device | NOT TESTED | No emulator/device or granted screening role available |
| Android/Termux SELinux integration | NOT TESTED | No physical cross-UID deployment environment available |
| External penetration test | NOT TESTED | No independent security lab or adversarial device test was performed |

## Phase boundary

This audit does not add or claim Phase 7 functionality. It covers only the
Phase 6 hardening implemented in this repository.
