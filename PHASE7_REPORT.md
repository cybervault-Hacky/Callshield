# CALLSHIELD — Phase 7 Final Report

**Version:** 0.7.0 — Reputation & Explainable Intelligence
**Date:** 2026-08-11
**Branch:** `arena/019ff0f4-callshield`
**Verified Phase 6 baseline:** `f58310117b08a892492b0868049a028c8eb62ec5`
**Python tests:** 332 passed

## Phase boundary

```text
Phase 1–6 — COMPLETE
Phase 7 — COMPLETE
Phase 8 — NOT STARTED
```

No cloud service, account system, telemetry, advertising, remote number lookup,
DNS reputation lookup, HTTP/TCP listener, or Phase 8 functionality was added.

## Baseline audit and reuse

The clean Phase 6 baseline passed all 271 tests. Existing Phase 1/2 reputation
classifiers, behavior analysis, confidence logic, detector signals, canonical
normalizer, indexed event/report history, Phase 5 policy, Phase 6 integrity, and
doctor/block tools were inspected first.

The legacy `callshield/reputation.py` API was preserved as
`callshield/reputation/legacy.py` and re-exported by the new package, so Phase 1
imports and scoring tests remain compatible.

## Reputation package

```text
callshield/reputation/
├── __init__.py
├── legacy.py
├── models.py
├── engine.py
├── history.py
├── signals.py
└── storage.py
```

A `ReputationProfile` contains canonical hash/mask, first/last seen, calls seen,
answered/rejected/allowed counts, block recommendations, reports, deterministic
score, separate confidence, trend, trust state, structured signals, reasons,
bounded history, availability, and fail-open recommendation.

`calls_answered` remains zero because CALLSHIELD has no call-duration/answer
telemetry; no short-call explanation is fabricated.

## Deterministic scoring

The engine reuses the existing detector's current risk/confidence/signals and
combines them with indexed local aggregates:

- calls observed in 24 hours
- local user reports
- historical BLOCK recommendations
- measured high-risk detections
- historical allowed interactions without negative evidence
- explicit local trust

Scores are clamped to 0–100. Current detector risk is blended with at most 20
recent bounded historical scores; measured signal deltas are capped. Repeating
the same inputs produces identical score, confidence, and reasons.

Risk labels:

```text
TRUSTED / LOW / MODERATE / HIGH / CRITICAL / UNKNOWN
```

No evidence produces UNKNOWN rather than a fabricated trust claim.

## Explainability

Every reason comes from a `ReputationSignal` with name, bounded delta,
confidence, measurement, and reason. Existing positive detector signals are
included as zero-delta explanation context so Phase 2 intelligence is reused,
not duplicated.

Trend reasons are added only after actual history establishes IMPROVING or
WORSENING. Tests verify that frequency reasons require at least three measured
calls and that no short-call claim appears without duration data.

## Trend detection

Supported:

```text
IMPROVING / STABLE / WORSENING / UNKNOWN
```

At least three observations are required. Trend calculations use at most ten
recent meaningful observations and require a ten-point average shift for
IMPROVING/WORSENING; otherwise the result is STABLE.

History stores timestamp, old/new score, old/new risk, and measured trigger.
Only first/tier/five-point changes are recorded, with default retention of 100
changes per number.

## Confidence

Reputation confidence is separate from score and derives from bounded counts of
observations, reports, block history, current detector confidence, and signal
diversity. One high-risk signal may therefore produce high score with low
confidence. Values remain 0–100.

## Trust

Commands:

```text
callshield trust <number>
callshield trust <number> --for 24h
callshield untrust <number>
```

Trust is local, explicit, idempotent, reversible, masked, and bounded. Temporary
trust accepts positive minute/hour/day durations up to one configured year;
expired records are removed automatically. Default retention is 1,000 trust
records.

Trusted numbers produce TRUSTED/0/ALLOW profiles and are passed to policy as an
absolute ALLOW override. Whitelist and emergency behavior remain intact.

## Policy integration

Incoming screening still follows:

```text
analyze_number() → ReputationEngine → PolicyEngine
```

Reputation may veto through explicit trust or unavailable/corrupt state. It
does not raise detector risk/confidence and cannot force BLOCK by itself.

```text
REPUTATION FAILURE → REPUTATION_UNAVAILABLE → ALLOW
```

Phase 5 thresholds, ACTIVE confirmation, whitelist, emergency, and Phase 6 final
response checks remain unchanged.

## Database

Schema version 6 adds:

- `reputation_profiles`
- `reputation_history`
- `trusted_numbers`
- optional reputation score/confidence/trend/reasons snapshot columns on
  `screening_events`

New tables contain hashes and masked identifiers only—no plaintext-number
column. Foreign keys, WAL, integrity/schema checks, and transactional migration
remain. Indexes cover profile update/risk, hash/time history, and trust expiry.

Bounds:

```text
recent query rows       100 default
history per number      100 default
profiles                5000 default
trust records           1000 default
temporary trust         1 year maximum
signals/reasons         20 each
stored explanation JSON 8 KiB / 4 KiB
```

## CLI and JSON

Added/updated:

```text
callshield reputation
callshield reputation <number>
callshield reputation <number> --json
callshield reputation list
callshield trust <number> [--for 24h]
callshield untrust <number>
```

Human output shows masked number, risk, score, confidence, trend, trust,
history counters, and measured reasons. Public JSON exposes `number_masked` but
not canonical plaintext or `number_hash`.

## Doctor and block inspection

Doctor adds:

- Reputation Database
- Reputation Schema
- Reputation Integrity
- Trust Database

Corrupt profile JSON produces ERROR but doctor never activates protection.

`blocks inspect <id>` retains all existing fields and optionally shows
reputation score/confidence/trend/reasons captured at decision time, with masked
number only.

## Privacy and network audit

Automated AST/privacy tests confirm the reputation package imports no socket,
HTTP client, DNS, cloud, or telemetry module. Static Phase 6 audit remains PASS:

```text
AF_INET             NONE
TCP/HTTP listener   NONE
dynamic execution   NONE
shell execution     NONE
unsafe deserialize  NONE
```

Profile/history/trust public storage and CLI/JSON tests verify plaintext numbers
are absent. Existing event tables remain unchanged for backward compatibility.

## Performance

Actual bounded local lookup benchmark:

```text
lookups       1000
history rows  100
query limit   100
concurrency   1
Python        3.11.2
platform      Linux 6.1.158+ x86_64
p50           0.229418 ms
p95           0.308114 ms
p99           0.437614 ms
wall          0.24667476800004806 s
```

This does not represent Android, IPC, physical-call, or production multi-number
performance. See `PERFORMANCE_PHASE7.md`.

## Tests

```text
OLD TESTS (Phase 1–6): 271 PASS
NEW PHASE 7 TESTS:       61 PASS
TOTAL:                  332 PASS
FAILURES:                 0
```

Dedicated Phase 7 suites cover engine, scoring, history, trends, confidence,
explanations, CLI, JSON, trust, temporary trust, policy, database, privacy,
limits/concurrency, doctor, and block inspection.

Explicitly tested:

- empty/one-event history
- repeated calls and reports
- historical blocks/allows
- worsening/improving/stable/unknown trend
- high score with low confidence
- corrupt/unavailable reputation
- invalid number
- trust/expiry/removal
- ACTIVE/DRY_RUN/emergency/whitelist policy safety
- concurrent lookups
- `REPUTATION FAILURE → ALLOW`

## Manual verification

A fresh isolated installer completed and its self-test passed all 332 tests.
Verified version/status, doctor text/JSON reputation checks, empty/list/profile
reputation output, private JSON, temporary trust, untrust, policy simulation,
blocks listing, and daemon start/status/stop.

Measured profile after four local scans and two reports:

```text
Number:              +919*****3210
Risk:                LOW
Score:               30/100
Confidence:          48%
Trend:               UNKNOWN
Calls Seen:          4
Allowed:             4
Reports:             2
```

Displayed reasons exactly matched stored measurements: two reports, four calls
within 24 hours, four allows, current analysis risk, recent scans, and detector
report signal. JSON omitted plaintext and hash. Temporary `24h` trust changed the
profile to TRUSTED and was then removed successfully.

Running doctor reported all reputation/trust checks HEALTHY. The daemon socket
inode appeared only in `/proc/net/unix`; no CALLSHIELD TCP listener existed.
Final daemon status was STOPPED with no process left running.

## Android build/device

```text
ANDROID BUILD = NOT VERIFIED
PHYSICAL DEVICE = NOT VERIFIED
```

JDK, Gradle/wrapper, Android SDK, emulator, and physical device remain
unavailable. No APK or device result is claimed.

## Known limitations

- No call-duration/answer signal exists, so repeated short calls and answered
  counts cannot be inferred.
- Existing Phase 1–6 event/report tables retain canonical numbers for backward
  compatibility; new Phase 7 profile/history/trust tables do not add plaintext.
- Cross-UID Android/Termux socket integration remains unverified.
- Benchmark scope is a local sequential lookup, not end-to-end screening.
- Phase 8 is not started.
