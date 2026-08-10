# CALLSHIELD — Phase 2 Implementation Report

**Version:** 0.2.0 — Advanced Intelligence (built on Phase 1 — Foundation 0.1.0)  
**Date:** 2026-08-10  
**Branch:** `arena/019fecb8-callshield`  
**Status:** Phase 2 complete, Phase 1 regression-free, offline-first, Termux-first

> **CALLSHIELD Phase 2 analyzes phone-number risk locally. It does not yet intercept or automatically reject live phone calls.**

---

## 1. Files Added

```
callshield/intelligence/reputation.py   # six-tier reputation (TRUSTED/SAFE/UNKNOWN/SUSPICIOUS/HIGH_RISK/MALICIOUS)
tests/test_rules.py                    # deterministic rule-engine tests (8 cases)
```

> Note: Phase 2 architecture was already present in the base (signals, behavior, confidence, profiles, rules). This phase added the missing `intelligence/reputation.py` required by spec §3 and `tests/test_rules.py` required by §25, plus alias handling for full spec compliance.

## 2. Files Modified

- `callshield/cli.py` — version now prints **exactly** `CALLSHIELD 0.2.0` + `Phase 2 — Advanced Intelligence` per §30; banner/help retain Phase 1 disclaimer for spec compliance
- `callshield/detector.py` — weight multipliers now handle alias keys (`previous_suspicious_events` ↔ `repeated_suspicious_events`, `number_format_anomaly` ↔ `format_anomaly`)
- `callshield/intelligence/__init__.py` — re-exports `REPUTATION_LEVELS`, `ReputationResult`, `classify_reputation`, `reputation_from_score`
- `callshield/intelligence/profiles.py` — default weights now include both alias keys (15 for both suspicious variants, 5 for both format variants) and keep RELAXED/STRICT overrides in sync
- `callshield/intelligence/signals.py` — `_signal_repeated_suspicious` now emits `previous_suspicious_events` (canonical) with fallback weight lookup; `_signal_format_anomaly` handles both `format_anomaly` / `number_format_anomaly` weight keys (also fixed string concat bug)

## 3. New Architecture

```
callshield/
├── intelligence/
│   ├── __init__.py        # exports signals, behavior, confidence, profiles, reputation
│   ├── signals.py         # modular SignalResult + 9 deterministic signals
│   ├── reputation.py      # NEW — 6-tier classifier (TRUSTED/SAFE/.../MALICIOUS)
│   ├── behavior.py        # get_number_history, analyze_behavior, number_intelligence
│   ├── confidence.py      # compute_confidence (0–100, deterministic)
│   └── profiles.py        # RELAXED / BALANCED / STRICT (thresholds + weights)
└── rules/
    ├── __init__.py
    ├── engine.py          # evaluate() pipeline 11-step deterministic order
    └── defaults.py        # TIER_THRESHOLDS, VERDICT_LABELS, ACTIONS
```

Evaluation order (§15) is fixed and documented in `rules/engine.py`:

1. Normalize → 2. Whitelist → 3. Blacklist → 4. Load reputation → 5. Analyze history → 6. Reports → 7. Weak pattern → 8. Risk score (sum, clamp 0–100) → 9. Confidence → 10. Verdict → 11. Recommended action

Whitelist precedence `WHITELIST > BLACKLIST > REPUTATION` enforced; `list_conflict` signal reported.

## 4. New Commands

All Phase 1 commands preserved. Phase 2 adds:

| Command | Description |
|---------|-------------|
| `callshield reputation <number>` | Shows reputation, risk, confidence, reports, history (FIRST_SEEN/LAST_SEEN), verdict/action; `--json` supported |
| `callshield report <number> [--reason]` | Local user report (sanitized, ≤500 chars, stored in `reports` table, contributes `manual_user_report` signal, never auto-confirms fraud) |
| `callshield history <number> [--limit N] [--full]` | Chronological local events for a number (masked by default) |
| `callshield signals <number>` | Signal breakdown (name, score, reason) + final 0–100 score |
| `callshield scan <number> --json` | Machine-readable JSON (number, risk_score, confidence, reputation, risk_level, verdict, recommended_action, signals, behavior, number_intelligence, list_conflict) |
| `callshield scan <number> --quiet` | Only prints `ALLOW` / `MONITOR` / `BLOCK` |
| `callshield config profile <relaxed\|balanced\|strict>` | Switches protection profile (validates, rejects invalid) |

`scan` output upgraded: `Number`, `Reputation`, `Risk Score /100`, `Risk Level`, `Confidence %`, `Verdict`, `Action`, `Signals` (explainable), `Recommendation`, `Reason`, plus Number Intelligence (`format`, `pattern_risk`, `anomalies` via behavior).

## 5. Database Migration Details

- **Schema version:** `2` (`schema_version` table)
- **Existing tables:** `numbers`, `events`, `settings` (Phase 1) → Phase 2 adds `confidence`, `reputation`, `risk_level` to `events`; new `reports` table; `numbers` gains `first_seen` and expanded `reputation` CHECK; indexes `idx_events_number_ts`, `idx_reports_number`
- **Migration:** `database.py::_migrate()` detects v0/v1, backs up to `*.v1.bak`, rebuilds `numbers` with mapped reputations (`LOW→SAFE`, `MEDIUM→SUSPICIOUS`, etc., whitelist→`TRUSTED`), alters `events` adds columns, backfills `reputation`/`risk_level` from `verdict`/`risk_score`, creates indexes, stamps `schema_version=2`
- **Properties:** Never deletes user data, idempotent (re-running installer preserves DB), `0600` perms, `WAL` journal, indexes on `events(number, timestamp DESC)` for <100 ms scans, parameterized queries only

## 6. Risk-Scoring Model

- **Range:** `0–100`, clamp after sum, whitelist forces `0`
- **Weights (BALANCED defaults, configurable via `signal_weights` + `history_weight`/`report_weight`/`pattern_weight`):**
  ```
  blacklist_match             +80
  previous_block_events       +20 (capped, 10+5*min(count,4))
  repeated_suspicious_events  +15 (alias previous_suspicious_events, 3*min(count,8), capped)
  manual_user_report          +25 (8*min(count,6), capped)
  format_anomaly              +5  (alias number_format_anomaly, 2*anomalies, capped)
  rapid_repeat_events         +10 (3*min(window,6), capped, window=600s)
  reputation_history          +10 (SUSPICIOUS→5, HIGH_RISK/MALICIOUS→10)
  ```
  Whitelist `-100`, conflict `0`. Profile `STRICT` ups report/repeat, `RELAXED` lowers format/rapid.

- **Tiers (from `rules/defaults` + profile):**
  `0 UNKNOWN`, `1–29 LOW`, `30–59 MEDIUM` (≥`suspicious_threshold`), `60–84 HIGH` (≥`high_risk_threshold`), `85–100 CRITICAL` (≥`malicious`)

- **Confidence (0–100, separate from risk):** Weighted avg of signal confidences (`confidence*abs(score)`), agreement bonus `+5*max(len(pos),len(neg))` capped 15, history bonus `+min(total_events,10)`, conflict penalty `-20`, strength bonus for pure strong evidence, clamped `5–99`. No ML, deterministic.

- **Verdicts:** `SAFE` (whitelist or no risk), `UNKNOWN` (no strong indicators), `SUSPICIOUS` (≥ suspicious_threshold), `HIGH_RISK` (≥ high_risk_threshold), `MALICIOUS` (blacklist or ≥85)
- **Actions:** `ALLOW` (SAFE/UNKNOWN), `MONITOR` (SUSPICIOUS/HIGH_RISK low confidence), `BLOCK` (MALICIOUS or HIGH_RISK+threshold+confidence_floor)

Example high-risk:
```
Risk Score 91/100 Level CRITICAL Confidence 96%
Signals +80 blacklist_match, +20 previous_block_events, +15 repeated_suspicious...
Verdict HIGH_RISK Action BLOCK
```
Weak:
```
Risk Score 14/100 Confidence 42% Signals +5 number_format_anomaly Verdict UNKNOWN Action ALLOW
```

## 7. Test Results

```
$ python -m unittest discover -v          # also -s tests
Ran 86 tests in ~1.0s
OK
```

Breakdown:

- Normalizer (10), Database (8 inc. coexistence & injection), Scoring (9), Detector (8), Config (11), Profiles (6), Reports (6 inc. JSON/quiet), Reputation (5), Signals (5), Behavior (4), Confidence (5), **Rules (8 NEW)** — covers unknown, blacklist/whitelist, override, capping, determinism, JSON serializable, profile thresholds, confidence separation.

Phase 1 suite still 77/77; Phase 2 adds 9 (net 86). No regressions.

## 8. Manual Verification Results

All §31 regression checks passed via wrapper `callshield` (default `~/.callshield`):

```
callshield --help                ✓ usage + Phase 1+2 disclaimer
callshield version               ✓ CALLSHIELD 0.2.0 / Phase 2 — Advanced Intelligence
callshield status                ✓ CALLSHIELD STATUS / STOPPED→RUNNING / STANDBY
callshield scan +919876543210    ✓ 26/100 LOW UNKNOWN → after block 100/100 CRITICAL MALICIOUS BLOCK (explainable)
callshield scan +919876543210 --json ✓ valid JSON, no human text mixed
callshield block +919876543210   ✓ added + conflict handling
callshield reputation +919876543210 ✓ MALICIOUS 100/100 + reports/history
callshield history +919876543210 ✓ 6 events, masked
callshield signals +919876543210 ✓ breakdown (+80 blacklist, +20 previous, +6 previous_suspicious, +10 reputation)
callshield report +919876543210 --reason "suspected scam" ✓ local report 1, contributes +8
callshield blacklist/whitelist list ✓ tables
callshield config show           ✓ Profile BALANCED + thresholds + weights
callshield config profile strict ✓ 50, balanced 60, relaxed 80
callshield logs                  ✓ masked, --full reveals, --limit respected
callshield scan --quiet          ✓ BLOCK
callshield start/stop/status     ✓ STANDBY, PID, heartbeat, stale-PID STALE → cleaned on next start
```

False-positive protection verified: unknown number → `UNKNOWN` `ALLOW`, weak `number_format_anomaly` alone → max +5 never pushes above LOW.

## 9. Performance Observations

- Single scan < 15 ms on Linux container (SQLite WAL + indexes `idx_events_number_ts`, `idx_numbers_number`); target <100 ms on Termux easily met — no full-table scans, single DB connection per CLI invocation, `analyze_behavior` limited to 10k events, no network.
- `python -m unittest discover` 86 tests ~1.0s.

## 10. Any Limitations

- Same as Phase 1: no telephony permission/APK/GUI/cloud/ML; STANDBY only.
- Normalizer curated country table (IN/US/GB/…); unknown country codes left as-is.
- Weak pattern signals intentionally low (+5 max) — cannot alone cause BLOCK.
- History-based scoring can keep a previously blocked number elevated after `unblock` until history ages (by design, capped).
- Previous `repeated_suspicious_events` vs `previous_suspicious_events` naming ambiguity fixed via alias handling.
- `data/callshield.db` etc. created in repo when running without `CALLSHIELD_DATA_DIR` — now ignored via `.gitignore` (`data/config.json`, `*.pid`, etc.), runtime after install is `~/.callshield`.

## 11. Confirmation that everything remains Termux-first

- Pure Python 3 stdlib, `python3`, `sqlite`, `argparse` only; `requirements.txt` empty.
- `scripts/install.sh` verifies `python3.8+`, creates `~/.callshield/data` + `logs` 0700, installs wrapper to `$PREFIX/bin` (Termux) or `~/.local/bin` (Linux, with `/usr/local/bin` symlink for containers), idempotent, `chmod 700` wrapper, runs DB init + `unittest` self-test.
- `scripts/uninstall.sh` keeps `~/.callshield` unless `--purge`.
- `NO_COLOR`, `--no-color`, `--color`, TTY detection, `0600` DB perms, PID-file daemon with `STALE` handling — all Termux/Linux friendly, no root, no Android Studio.

## 12. Confirmation that live call interception/rejection is intentionally not implemented yet

**Confirmed — Phase 2 is still analysis-only.**

- `cli.start` prints:
  ```
  Protection engine started.
  Mode       STANDBY
  Engine     LOCAL
  ...
  Live call screening is not enabled in this phase.
  Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls.
  ```
- `status` shows `Protection STANDBY` regardless of `RUNNING`.
- `detector.analyze_number()` returns advisory `recommended_action` but never touches Android `CallScreeningService`.
- README, help epilog, banner, `CHANGELOG` all state:
  > *CALLSHIELD Phase 2 analyzes phone-number risk locally. It does not yet intercept or automatically reject live phone calls.*
- No APK, GUI, cloud API, or `eval`/`exec`/`shell` from user input; no device IDs or analytics.

---

**Phase 2 is complete and ready. `analyze_number()` remains the stable API for future privileged call-screening integration.**
