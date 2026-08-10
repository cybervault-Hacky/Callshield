# CALLSHIELD

> **Local fraud-number analysis and protection foundation.**
>
> Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls.
>
> Phase 2 — Advanced Intelligence builds on Phase 1.
>
> **CALLSHIELD does NOT yet intercept or reject live phone calls.**
> It runs locally on Android/Termux (or any Linux system), keeps its database
> on-device, and never uploads your phone numbers.

```
CALLSHIELD
────────────────────────────────────────
Fraud Protection Engine

Status      READY
Engine      LOCAL
Database    ONLINE
Protection  STANDBY
Profile     BALANCED

Use `callshield --help` for commands.
```

---

## Features

- **Professional CLI** — clean, minimal, scriptable, no gimmicks.
- **SQLite database** — local, persistent, parameterized queries only.
- **Number normalization** — spaces, punctuation, `+`, `00` prefixes, default
  country handling, strict validation.
- **Blacklist / Whitelist** — explicit user control with clear precedence:
  **WHITELIST > BLACKLIST > REPUTATION**. Conflicts are detected and reported.
- **Advanced reputation engine** — six tiers (TRUSTED / SAFE / UNKNOWN /
  SUSPICIOUS / HIGH_RISK / MALICIOUS) derived purely from local signals.
- **Modular signal system** — every positive/negative signal is:
  - independently testable,
  - deterministic,
  - explicitly weighted,
  - visible in the output.
- **Deterministic, explainable risk scoring (0–100)** — no fake ML.
- **Confidence score (0–100)** — how strong the evidence is, separate from
  how risky the number looks.
- **Historical behavior analysis** — uses prior scans, blocks, and reports
  for the same number.
- **Number intelligence** — safe local pattern checks (length,
  repeated-digit runs, unexpected characters).
- **Local user reports** — `callshield report <number>` records a local
  note; reports contribute to score but never auto-confirm fraud.
- **Protection profiles** — RELAXED / BALANCED / STRICT.
- **Event logging** — every analysis is recorded; numbers are masked in
  listings by default (`--full` reveals).
- **JSON output** — `callshield scan <number> --json` for scripting and
  future integration.
- **Background engine (STANDBY)** — start/stop/status with PID management,
  stale-PID cleanup, heartbeat, graceful shutdown.
- **Offline-first, privacy-preserving** — zero network calls, zero
  analytics, zero telemetry.
- **Termux-friendly** — pure Python 3 standard library, no root required.
- **Well tested** — 77 unit tests covering every subsystem.

---

## Architecture

```
callshield/
├── callshield/
│   ├── __init__.py
│   ├── __main__.py           # python -m callshield
│   ├── cli.py                # argparse CLI (thin layer)
│   ├── config.py             # JSON config + profiles
│   ├── database.py           # SQLite layer + schema migrations
│   ├── detector.py           # analyze_number() core API
│   ├── normalizer.py         # Phone number normalization
│   ├── logger.py             # Event + file logging
│   ├── daemon.py             # Background engine (STANDBY)
│   ├── utils.py              # Exit codes, masking, helpers
│   ├── intelligence/         # Phase 2
│   │   ├── signals.py        # Modular signal engine
│   │   ├── behavior.py       # Historical behavior + number intelligence
│   │   ├── confidence.py     # Confidence scoring
│   │   └── profiles.py       # RELAXED / BALANCED / STRICT
│   └── rules/                # Phase 2 rule engine
│       ├── engine.py         # evaluate() pipeline
│       └── defaults.py       # Threshold constants
├── data/                     # Runtime state (db, config, pid)
├── logs/                     # Text logs
├── tests/                    # unittest suite
├── scripts/
│   ├── install.sh            # Termux/Linux installer
│   └── uninstall.sh
├── pyproject.toml
├── requirements.txt
├── CHANGELOG.md
├── VERSION
├── LICENSE
└── README.md
```

The core API for future phases (including a live Android call-screening
service) is:

```python
from callshield.detector import analyze_number
result = analyze_number("+919876543210")
# result.verdict, result.risk_score, result.confidence,
# result.recommended_action, result.signals, ...
```

It returns a structured dataclass — no stdout, no prompts, no global state
— so the same engine can drive both the CLI and (later) an Android
call-screening service.

---

## Installation

### Requirements

- Python 3.8+
- A POSIX shell (Linux / Termux)
- No root required

### Termux

```bash
pkg update && pkg upgrade
pkg install python git
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

The installer is idempotent — running it twice will not wipe your database.

### Linux (desktop)

```bash
git clone <repo-url> Callshield
cd Callshield
bash scripts/install.sh
```

The installer:

1. Verifies Python 3.8+.
2. Creates `~/.callshield/` (override with `CALLSHIELD_HOME`).
3. Installs the `callshield` wrapper on PATH (`$PREFIX/bin` on Termux,
   `~/.local/bin` on Linux).
4. Initializes the SQLite database.
5. Runs the unit-test suite as a self-test.

### Uninstall

```bash
bash scripts/uninstall.sh           # keeps user data
bash scripts/uninstall.sh --purge   # removes database, logs, config
```

---

## Quick Start

```bash
callshield status                       # check engine/db state
callshield scan +919876543210           # analyze a number
callshield block +919876543210          # add to blacklist
callshield allow +919876543210          # add to whitelist
callshield report +919876543210 --reason "suspected scam"
callshield reputation +919876543210     # show local reputation
callshield history +919876543210        # show event history
callshield signals +919876543210        # show signal breakdown
callshield logs --limit 20             # recent events (masked)
callshield logs --full                 # recent events (unmasked)
callshield config profile strict       # switch profile
callshield start                       # start STANDBY engine
callshield stop                        # stop engine
```

JSON output (scripting / future integrations):

```bash
callshield scan +919876543210 --json
```

Quiet mode (exit-code friendly):

```bash
callshield scan +919876543210 --quiet   # prints only ALLOW / MONITOR / BLOCK
```

---

## Commands

| Command                                  | Description                                      |
|------------------------------------------|--------------------------------------------------|
| `callshield`                             | Banner + status summary                          |
| `callshield --help`                      | Full CLI help                                    |
| `callshield --version`                   | Version banner                                   |
| `callshield version`                     | Version information                              |
| `callshield status`                      | Engine / database / PID status                   |
| `callshield scan <number>`               | Analyze a phone number                           |
| `callshield scan <number> --json`        | Analyze and emit JSON                            |
| `callshield scan <number> --quiet`       | Only print recommended action                    |
| `callshield scan <number> --no-log`      | Analyze without writing an event                 |
| `callshield block <number> [--reason]`   | Add a number to the blacklist                    |
| `callshield unblock <number>`            | Remove from the blacklist                        |
| `callshield allow <number> [--reason]`   | Add a number to the whitelist                    |
| `callshield unallow <number>`            | Remove from the whitelist                        |
| `callshield report <number> [--reason]`  | File a local user report                         |
| `callshield blacklist list`              | List blacklisted numbers                         |
| `callshield whitelist list`              | List whitelisted numbers                         |
| `callshield reputation <number>`         | Show detailed local reputation                   |
| `callshield history <number>`            | Show event history for a number                  |
| `callshield signals <number>`            | Show signal breakdown for a number               |
| `callshield logs [--limit N] [--full]`   | Show recent analysis events                      |
| `callshield config [show]`               | Show current configuration                       |
| `callshield config profile <mode>`       | Set protection profile (relaxed/balanced/strict) |
| `callshield config set <key> <value>`    | Set a single configuration value                 |
| `callshield start`                       | Start background engine in STANDBY mode          |
| `callshield stop`                        | Stop background engine                           |

---

## Risk Scoring

Risk scores are **deterministic** and **explainable**. Every score is the sum
of contributions from fired signals, clamped to 0–100.

| Score  | Tier     | Meaning                              |
|-------:|----------|--------------------------------------|
|  0     | UNKNOWN  | No signals — number is unknown       |
|  1–29  | LOW      | Minor/weak signals only              |
| 30–59  | MEDIUM   | Some suspicious indicators           |
| 60–79  | HIGH     | Elevated risk — review recommended   |
| 80–100 | CRITICAL | Strong local evidence — block        |

Confidence is computed independently: it reflects how many independent
signals agree and how strong the evidence is. A number can be high-risk
with low confidence ("we don't know much") or low-risk with high confidence
("we have good evidence it's safe").

### Precedence rule

```
WHITELIST  >  BLACKLIST  >  REPUTATION
```

If a number exists in both lists, CALLSHIELD reports the conflict and
applies the whitelist. No data is silently deleted.

### Built-in signals

| Signal                    | Default weight | Notes                                         |
|---------------------------|---------------:|-----------------------------------------------|
| `whitelist_match`         |           −100 | Forces score 0 and verdict SAFE               |
| `blacklist_match`         |            +80 | Explicit user block                           |
| `previous_block_events`   |       up to +20 | Past BLOCK verdicts for this number           |
| `repeated_suspicious_events` | up to +15   | Multiple prior suspicious verdicts            |
| `rapid_repeat_events`     |       up to +10 | Many scans in a short window                  |
| `manual_user_report`      |        up to +25 | Local user reports (capped)                   |
| `reputation_history`      |            +10 | Previously stored HIGH_RISK/MALICIOUS label   |
| `number_format_anomaly`   |         up to +5 | Weak pattern signals (repeated digits, etc.)  |

Whitelist match overrides everything. Weak pattern signals alone can never
push a number above LOW.

---

## Profiles

| Profile   | Block threshold | Description                                            |
|-----------|----------------:|--------------------------------------------------------|
| RELAXED   |              80 | Prefer fewer false positives; only strong evidence blocks. |
| BALANCED  |              60 | Default.                                               |
| STRICT    |              50 | Stronger blocking recommendations when evidence is solid. |

Switch with:

```
callshield config profile relaxed
callshield config profile balanced
callshield config profile strict
```

Profiles only tune thresholds and weight multipliers — they never grant
new capabilities.

---

## Database

SQLite, fully local. Default location: `~/.callshield/data/callshield.db`.
Tables:

- `schema_version` — current schema revision (used for safe migrations).
- `numbers` — blacklist/whitelist entries (number, list_type, reputation,
  risk_score, reason, first_seen, created_at, updated_at).
- `events` — analysis history (timestamp, number, risk_score, confidence,
  reputation, risk_level, verdict, action, reason).
- `reports` — user-submitted reports (number, reason, created_at).
- `settings` — key/value metadata used by the daemon.

All queries use parameterized statements — no string concatenation.
Database files are created with `0600` permissions where possible.

Migrations from Phase 1 databases are applied automatically and preserve
all user data.

---

## Configuration

Stored at `~/.callshield/data/config.json`.

| Key                  | Default  | Description                                         |
|----------------------|----------|-----------------------------------------------------|
| `protection_mode`    | BALANCED | Active profile                                      |
| `risk_threshold`     | 60       | Score at/above which BLOCK is recommended (profile-managed) |
| `high_risk_threshold`| 60       | Score at/above which verdict becomes HIGH_RISK      |
| `history_weight`     | 1.0      | Multiplier for history-based signals                |
| `report_weight`      | 1.0      | Multiplier for user-report signals                  |
| `pattern_weight`     | 0.5      | Multiplier for weak pattern signals                 |
| `logging_enabled`    | true     | Record scan events in the database                  |
| `color_enabled`      | AUTO     | AUTO / ON / OFF                                    |
| `default_country`    | IN       | ISO country code for numbers without a `+` prefix   |
| `database_path`      | …        | Path to SQLite file                                 |
| `pid_file`           | …        | PID file for the background engine                  |
| `log_file`           | …        | Text log file path                                  |

---

## Security

- **No network calls** in Phase 1 or Phase 2.
- **Parameterized SQL** everywhere.
- All CLI inputs are validated and normalized before touching the DB.
- Malformed numbers and malformed config files produce clean errors.
- No shell execution of user input; no `eval`, no `exec`.
- No hardcoded API keys or credentials.
- Database/PID files created with restricted permissions where possible.
- Numbers are masked by default in event listings; `--full` is required to
  see full numbers.
- No analytics, telemetry, or device identifiers.

---

## Termux Compatibility

- Pure Python 3 standard library — no native modules required.
- Installer detects Termux's `$PREFIX` and installs the `callshield`
  wrapper to `$PREFIX/bin` (already on PATH).
- Works without root, without Android Studio, without a display.
- PID-file based daemon works in Termux's Linux environment; stale PIDs
  are detected and cleaned automatically.

---

## Development

```bash
git clone <repo-url> Callshield
cd Callshield
python3 -m callshield --help
```

The package follows PEP 8, uses type hints on key interfaces, and keeps
CLI-specific code in `cli.py`. The core engine (`detector.py`,
`intelligence/`, `rules/`) has no CLI imports so it can be embedded
elsewhere.

---

## Testing

```bash
python3 -m unittest discover
```

The suite covers:

- Normalizer (spaces, `+`, invalid input, `00` prefixes, malformed input).
- Database (init, insert, update, delete, lookup, duplicates, coexistence,
  parameterization, migrations).
- Blacklist / whitelist (add, remove, lookup, duplicates, precedence,
  conflicts).
- Signals (blacklist, whitelist, history, reports, weak pattern signals).
- Scoring (clamping, whitelist override, combined signals).
- Confidence (strong/weak/conflicting evidence, history depth).
- Behavior (no history, one event, repeated events, repeated blocks,
  recent-window counting).
- Reports (create, duplicate, multiple reports, invalid input).
- Profiles (defaults, relaxed/balanced/strict thresholds, legacy
  "PERMISSIVE" alias).
- Detector (safe, unknown, blocked, whitelisted, conflicting, event
  logging).
- Configuration (defaults, persistence, invalid values, corrupt files,
  type coercion).
- CLI JSON output (`--json`) and quiet mode (`--quiet`).

---

## Roadmap

Future phases will add, in order:

1. **Phase 3** — On-device heuristic pattern detection (refined).
2. **Phase 4** — Optional, privacy-preserving opt-in crowd-sourced reports.
3. **Phase 5** — Contact-list integration and per-contact rules.
4. **Phase 6** — Status notifications and summaries.
5. **Phase 7** — Optional hardened daemon with privilege separation.
6. **Future** — Android call-screening integration via the privileged
   CallScreeningService API, calling straight into
   `detector.analyze_number()`.

Nothing beyond this repository is promised by Phase 2.

---

## Limitations

- **Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls.**
- **Phase 2 cannot intercept or block live phone calls.** It is an
  analysis and listing foundation. The `start` command launches a
  STANDBY engine for future integration work.
- The normalizer is intentionally conservative. It does not embed a full
  libphonenumber country database; it supports a small curated list of
  common country codes and leaves everything else in the form it was
  given.
- There is no network lookup, no ML, no cloud backend, and no account
  system — by design.
- Weak pattern signals (format anomalies) are weighted very low and will
  never, on their own, cause a BLOCK recommendation.

---

## Exit Codes

| Code | Meaning                    |
|-----:|----------------------------|
|    0 | Success                    |
|    1 | General error              |
|    2 | Invalid CLI usage          |
|    3 | Invalid phone number       |
|    4 | Database error             |
|    5 | Configuration error        |
|    6 | Daemon error               |

---

## License

MIT — see `LICENSE`.

---

**Remember:** CALLSHIELD Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls.
CALLSHIELD Phase 2 analyzes phone-number risk locally. It
does not yet intercept or automatically reject live phone calls. That
capability is reserved for a future phase that will require privileged
Android integration.
