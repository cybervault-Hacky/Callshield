# CALLSHIELD — Phase 5 Final Report

**Version:** 0.5.0 — Active Call Protection
**Date:** 2026-08-11
**Branch:** `arena/019ff0f4-callshield`
**Verified Phase 4 baseline:** `05a2d90849062a96667c365672c803bbdfc8da84`
**Python tests:** 220 passed

## Phase state

```text
Phase 1 — COMPLETE
Phase 2 — COMPLETE
Phase 3 — COMPLETE
Phase 4 — COMPLETE
Phase 5 — COMPLETE
Phase 6 — NOT STARTED
```

## Safe installation defaults

Fresh installations use:

```text
screening_enabled = false
screening_mode = DRY_RUN
active_mode_confirmed = false
screening_policy = BALANCED
```

An upgrade cannot silently activate blocking. An ACTIVE value without the
separate confirmation marker is downgraded to disabled DRY_RUN during config
load.

## Policy engine

Created:

```text
callshield/policy/
├── __init__.py
├── engine.py
├── models.py
└── thresholds.py
```

The engine accepts the existing detection result and returns a structured
`PolicyDecision` containing recommendation, applied action, risk, confidence,
active/confidence thresholds, reason, policy, mode, enabled state, whitelist,
emergency state, and policy-error state. It cannot call Android or directly
reject a call.

Default policies:

| Policy | Active block | Confidence |
|---|---:|---:|
| RELAXED | 92 | 90 |
| BALANCED | 85 | 80 |
| STRICT | 80 | 75 |

All six configurable threshold fields are validated in the range 0–100.
Invalid thresholds, policy, mode, activation state, or detection values fail
open to ALLOW.

## ACTIVE and DRY_RUN behavior

DRY_RUN:

```text
risk 95 + confidence 95
recommended BLOCK
applied ALLOW
```

ACTIVE applies BLOCK only when all safety conditions hold:

- screening enabled
- ACTIVE mode
- explicit confirmation marker
- risk at/above selected threshold
- confidence at/above selected threshold
- no whitelist
- no emergency marker
- valid policy decision

A final daemon response boundary independently rechecks mode, confirmation,
enabled state, recommendation, and emergency state before returning BLOCK.

## Whitelist

Whitelist detection is an absolute ALLOW override. This is enforced by the
policy engine using the existing whitelist signal/reputation, including when
risk/confidence are 100 and ACTIVE is confirmed.

## Emergency off

Implemented owner-only state:

```text
~/.callshield/state/emergency_off  (0600)
```

Commands:

```text
callshield emergency-off
callshield emergency-reset
```

Both are safe and idempotent. Uncertain path type/ownership is treated as
emergency ON. `emergency-off` also persists screening disabled, DRY_RUN, and
unconfirmed state. `emergency-reset` removes only the owned regular marker and
does not enable or resume ACTIVE protection.

## Event and screening pipeline

```text
Android CallScreeningService
  → existing Unix IPC
  → INCOMING_CALL Event
  → EventProcessor
  → existing analyze_number()
  → PolicyEngine
  → PolicyDecision
  → ALLOW/BLOCK response
```

No duplicate detector was introduced. Invalid/missing numbers, analyzer errors,
timeout, database failure, and malformed requests retain Phase 4 fail-open
fallbacks.

## Database

Schema version 4 safely rebuilds the Phase 4 screening table while preserving
all existing rows and privacy fields. Added:

- `policy_action`
- `policy_name`
- `threshold`
- `confidence_threshold`
- `policy_reason`
- `emergency_off`
- ACTIVE-capable `applied_action`/`mode` constraints
- `actually_rejected`
- `rejection_confirmed_at`

Database/API validation permits an applied BLOCK only with ACTIVE mode, a BLOCK
policy recommendation, and emergency off. Migrated Phase 4 rows remain DRY_RUN,
applied ALLOW, and unconfirmed.

## Android bridge

The Kotlin protocol now validates both DRY_RUN and ACTIVE decisions. Android
requests rejection only for the exact valid combination:

```text
recommended_action = BLOCK
applied_action = BLOCK
mode = ACTIVE
emergency_off = false
```

Every other action/mode/error is ALLOW. After successfully delivering a valid
ACTIVE BLOCK response, `BridgeClient` sends bounded local
`screening_feedback`. Invalid or unavailable feedback never changes the call
decision.

## Actual rejection metric

Metrics are deliberately distinct:

- Block Recommended — policy selected BLOCK
- Screening Blocked — daemon applied BLOCK
- Actually Rejected — Android feedback confirmed response delivery

The database confirmation update matches only a persisted ACTIVE applied BLOCK
and is idempotent. No manual Termux simulation increments the final counter.

## CLI

Added/updated:

```text
callshield screening mode active
callshield screening mode dry-run
callshield screening policy [RELAXED|BALANCED|STRICT]
callshield policy test [safe simulation options]
callshield emergency-off
callshield emergency-reset
```

ACTIVE prompts:

```text
Enable ACTIVE call protection? [y/N]
```

Empty input, EOF, interrupt, captured/noninteractive stdin, or any response
other than `y`/`yes` leaves ACTIVE disabled. Generic `screening enable` always
selects DRY_RUN.

Status/health show enabled state, mode, policy, thresholds, last screening,
recommendations, applied blocks, confirmed rejections, policy errors, and
emergency state. Android remains `NOT VERIFIED`.

## Policy simulation

`callshield policy test` supports risk, confidence, mode, policy, whitelist,
emergency, and disabled-state overrides. Output is marked:

```text
SIMULATION ONLY — no real call action is performed.
```

It exercises the policy engine only and never sends Android IPC feedback.

## Automated tests

Final Python suite:

```text
220 passed
```

The 189 Phase 3/4 tests remain, plus 31 Phase 5 tests covering:

- safe/unknown/suspicious ALLOW
- active high-risk/high-confidence BLOCK
- low-confidence ALLOW
- DRY_RUN BLOCK recommendation with ALLOW application
- whitelist override
- emergency override and file safety
- invalid threshold/policy/mode fail-open
- configurable/default policies
- explicit CLI confirmation and default denial
- policy display and simulation
- v3→v4 migration
- final response-boundary validation
- concurrent ACTIVE requests
- applied-block versus actual-rejection counters
- valid, duplicate, malformed, and ALLOW feedback
- exact active Unix IPC request/feedback contract

Kotlin unit-test sources were updated for ACTIVE BLOCK, ACTIVE ALLOW, DRY_RUN,
emergency, invalid mode/action, unavailable daemon, and feedback behavior.

## Manual Termux verification

A fresh isolated `scripts/install.sh` run succeeded and its self-test passed all
220 tests. Fresh status showed disabled + DRY_RUN + BALANCED.

Policy simulation:

```text
risk 95 / confidence 95 / ACTIVE → BLOCK / BLOCK
risk 95 / confidence 70 / ACTIVE → ALLOW / ALLOW
risk 100 / confidence 100 / whitelist → ALLOW / ALLOW
risk 100 / confidence 100 / emergency → BLOCK / ALLOW
```

Exact Unix-wire screening matrix:

```text
DRY_RUN high risk → recommended BLOCK / applied ALLOW
ACTIVE high risk  → recommended BLOCK / applied BLOCK
ACTIVE whitelist  → recommended ALLOW / applied ALLOW
Emergency/disabled high risk → applied ALLOW
```

Final manual metrics:

```text
Incoming Calls:      4
Screened:            4
Allowed:             3
Block Recommended:   2
Screening Blocked:   1
Actually Rejected:   0
Policy Errors:       0
```

Emergency marker mode was 0600. Reset left screening disabled and DRY_RUN.
PID/socket cleanup passed.

## Security audit

Implementation retains:

- Unix socket only
- no TCP/HTTP listener
- no root requirement
- no dynamic evaluation or shell execution
- no arbitrary command execution
- bounded queue, IPC, Android response, and timeout handling
- masked phone numbers in logs
- fail-open handling on all unexpected failures

No doctor command, replay protection, Phase 6 audit framework, or Phase 6 report
was added.

## Android build/device status

Environment prerequisites remain unavailable:

```text
JDK:               NOT AVAILABLE
Gradle/wrapper:    NOT AVAILABLE
Android SDK:       NOT AVAILABLE
Emulator/device:   NOT AVAILABLE
```

Therefore:

```text
ANDROID BUILD = NOT VERIFIED
DEVICE TEST = NOT VERIFIED
```

No APK, physical rejection, or device feedback success is claimed.

## Performance

No independent benchmark was run:

```text
PERFORMANCE BENCHMARK = NOT INDEPENDENTLY VERIFIED
```

## Known limitations

- Physical Android-to-Termux private-socket access remains deployment-specific
  because of separate app UIDs and SELinux.
- `Actually Rejected` depends on Android feedback and remains zero without a
  verified physical bridge/device path.
- Feedback is bounded and idempotent at the database row but does not add Phase
  6 replay protection.
- Daemon startup remains user-managed.
- Phase 6 is not started.
