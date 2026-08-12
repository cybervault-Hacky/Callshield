# Phase 8.5 — Professional Terminal Interface

CALLSHIELD 0.8.0 gains an interactive, keyboard-driven terminal console. The
engine, daemon, database, screening bridge, reputation layer, adaptive
intelligence, policy engine, IPC and security architecture are unchanged. The
interface is a presentation layer: it renders values produced by the existing
code and delegates every mutation to the existing CLI handlers.

## 1. Files changed

### Added — `callshield/ui/` (39 modules, 11,425 lines)

| Layer | Modules | Purpose |
|---|---|---|
| shell | `__init__.py`, `app.py` | `AppContext`, `Application`, render loop, key handling, terminal ownership, non-interactive fallback |
| screens | `screens/` (18 modules) | one module per screen plus the `Screen`/`MenuScreen`/`ListScreen` framework and a lazy registry |
| components | `components/` (7 modules) | panels, tables, menus, chrome, progress, score meters |
| navigation | `navigation/` (3 modules) | key decoding, bounded screen stack, pager |
| theme | `theme/` (4 modules) | capability probing, palette, glyph tables |
| i18n | `i18n/` (2 modules) | nine translation dictionaries and lookup with English fallback |
| state | `state/` (3 modules) | `Backend` adapter and `PreferencesStore` |
| formatters | `formatters/` (1 module) | masking, status words, durations, widths, ANSI-aware truncation |

### Added — tests (7 files, 1,674 lines)

`tests/_ui.py`, `tests/test_ui_startup.py`, `tests/test_ui_navigation.py`,
`tests/test_ui_settings.py`, `tests/test_ui_i18n.py`, `tests/test_ui_screens.py`,
`tests/test_ui_errors.py`.

### Modified

| File | Change |
|---|---|
| `callshield/cli.py` | added `_ui_disabled()` and `_launch_ui()`; the bare-command branch of `main()` now calls `_launch_ui(ui, cfg)` instead of printing the banner directly. Nothing else changed; all handlers, the parser and `_COMMANDS` are untouched. |
| `.gitignore` | anchored the `state/` rule to `/state/` so it matches the runtime state directory at the repository root only, and no longer swallows `callshield/ui/state/`. |
| `README.md` | new "Terminal interface (Phase 8.5)" section, phase status, test count, verification limitations. |
| `CHANGELOG.md` | Phase 8.5 entry. |

## 2. TUI architecture

```text
callshield (no arguments)
   │
   ▼
cli.main() → _launch_ui()          non-tty / CALLSHIELD_NO_UI / import or
   │                               start failure → classic banner, EXIT_OK
   ▼
callshield.ui.run(cfg)
   │
   ├── theme.detect()      colour, Unicode, width, height, interactivity
   ├── PreferencesStore    ui_state.json  (interface preferences only)
   ├── startup.run_startup()   nine staged probes against the real backend
   └── Application.loop()
           │
           ├── Screen.body()   → components → formatters → lines
           └── Screen.handle() → Action(STAY|PUSH|POP|HOME|QUIT)
                                    │
                                    ▼
                         callshield.ui.state.backend.Backend
                                    │
        ┌───────────────────────────┼────────────────────────────┐
        ▼                           ▼                            ▼
  cli._COMMANDS[...]         cli._ipc_request()          existing engines
  (start, stop, block,       (AF_UNIX, local only)       detector, reputation,
   report, trust, screening,                             adaptive, policy,
   emergency-off, ...)                                   doctor, Database
```

Rules the layering enforces:

- **No business logic in the UI.** No detection, scoring, trend, pattern,
  policy or persistence logic exists in `callshield/ui/`.
- **One door.** Screens never import `Database`, the daemon or the engines;
  they only hold a `Backend` and receive a `Result(data, error, source)`.
  `source` distinguishes live IPC data from persisted fallbacks so the
  interface can label what it is showing instead of guessing.
- **Nothing raises.** Every backend call returns a `Result`; a missing daemon,
  a corrupt database or a bad number becomes a labelled message on screen.
- **Bounded queries.** Events, screening events and per-number history ≤ 1000
  rows; list entries ≤ 500; blocks and reports ≤ 200; profiles ≤ 200.
- **No second daemon.** Lifecycle actions call the same `start`/`stop` handlers
  a user would type, so pid-file ownership and the IPC handshake stay in one
  place.

## 3. Screens

| Screen | Contents |
|---|---|
| Dashboard | SYSTEM, THREAT OVERVIEW, INTELLIGENCE, QUICK ACTIONS; "Start daemon" surfaces when the daemon is offline |
| Scan Center | Basic Scan, Advanced Scan, Scan History, Compare Results |
| Advanced Scan | IDENTITY NORMALIZATION, REPUTATION, RISK SIGNALS, CONFIDENCE, BEHAVIOR, TREND, TRUST, POLICY, SCREENING, HISTORY |
| Live Monitor | real event and screening stream, non-blocking, "Waiting for events..." when empty, labelled when the daemon is down |
| Daemon Control | Status, Start, Stop, Restart, Health, Metrics |
| Screening Center | Status, Health, Metrics, Mode (DRY RUN / ACTIVE), Enable, Disable |
| Policy Center | Current, Test (simulation), RELAXED, BALANCED, STRICT, Emergency State |
| Reputation Center | Look Up, Recent Profiles, History, Trust/Untrust |
| Intelligence Center | Search, Behavior, Timeline, Trends, Patterns, Snapshots, Retention |
| Block Center | Blacklist, Whitelist, add/remove, Recent Decisions, Inspect |
| Report Center | Report a Number, Recent Reports, per-number reports |
| History | Events, Screening, per-number; bounded queries with PgUp/PgDn |
| Diagnostics | read-only `run_doctor(repair=False)` output |
| Settings | Language, Appearance, Animation, Refresh Rate, Default Scan Mode, Notifications, Data, Reset |
| About | version 0.8.0, Sarthak Bharambe, CyberVault, @cyber_vault123, Termux / Linux, MIT, local-first statement |

Keyboard: arrows move, Enter selects, `1`–`9` jump, Esc goes back (and exits at
the root), PgUp/PgDn page, `r` refreshes, `h` returns to the dashboard, `q` and
Ctrl+C quit. The user is never trapped in a mode.

## 4. Languages

English (default), Hindi, Hinglish (natural Roman Hindi), Spanish, French,
Japanese, Chinese, Portuguese, Russian — 321 keys each, held in translation
dictionaries in `callshield/ui/i18n/catalog.py`, not scattered through the code.
Missing keys fall back to English. Fifteen keys are intentionally identical in
every language (product and brand names, `PID`, and the ten advanced-scan
section identifiers). Technical command names are never translated. CJK and
Devanagari text is measured with `unicodedata.east_asian_width` so columns stay
aligned.

## 5. Tests added

| Module | Tests | Coverage |
|---|---:|---|
| `test_ui_startup.py` | 8 | nine named stages, real backend probing, duration bound, failure tolerance, frame content, no emoji, OFFLINE hint, animation disabled |
| `test_ui_navigation.py` | 23 | key decoding, bounded stack, pager, arrows/Enter/Esc/digits, quick actions, screen registry, Esc-at-root |
| `test_ui_settings.py` | 17 | defaults, round trip, coercion, corrupt/non-object/unknown-field recovery, every settings entry, persistence, reset prompt default N, reset scope, module isolation |
| `test_ui_i18n.py` | 18 | nine catalogues complete, no stray keys, no emoji, command names preserved, placeholders survive, language switching, fallback |
| `test_ui_screens.py` | 37 | dashboard sections and real values, scan flows, ten advanced sections, monitor, daemon, screening ACTIVE routing, policy simulation safety, blocks, reports, history paging and masking, diagnostics, About content, presentation rules |
| `test_ui_errors.py` | 55 | daemon down, database corrupt, UI state corrupt/hostile/oversized/unwritable, invalid input, Ctrl+C, Esc, resize, narrow/wide terminals, non-interactive fallback, no-colour and ASCII rendering, network/dangerous-API audit, safety rails |
| **Total** | **158** | |

## 6. Existing tests

```text
python -m unittest discover -s tests -t . -q
Ran 554 tests in 72s
OK
```

396 pre-existing tests before this phase, 554 after. No existing test file was
modified, weakened or removed; coverage was not reduced.

## 7. Security audit

| Check | Result |
|---|---|
| `eval` / `exec` / `compile` / `__import__` | none in `callshield/ui/` |
| `os.system`, `subprocess`, `shell=True` | none |
| `pickle` / `marshal` | none |
| `AF_INET` / `AF_INET6` | none |
| Arbitrary shell execution | none — commands are dispatched by looking up a function in `cli._COMMANDS` |
| Policy bypass | none — `PolicyEngine` is only ever called for simulation, wrapped so a simulated decision cannot be mistaken for an applied one |
| ACTIVE confirmation | preserved — `screening_mode_active()` hands the real terminal to the CLI handler that owns the prompt |
| `screening enable` from the UI | forces DRY_RUN with `active_mode_confirmed = false` |
| Emergency-off | reachable from the Policy Center at all times; never bypassed |
| Destructive actions | explicit `[y/N]` confirmation with a default of no |
| Direct config writes from the UI | none — `save_config`, `set_value`, `set_profile`, `enable_emergency_off`, `reset_emergency_off` appear nowhere in `callshield/ui/` |
| Plaintext numbers on screen | none — every rendered screen was asserted not to contain a raw number |
| Fabricated data | none — no call duration, caller identity, location, audio analysis, contact data, answered state, carrier or external reputation is displayed or inferred |
| Android claims | `Android: NOT VERIFIED` shown wherever screening state appears |
| Reset scope | only `ui_state.json`; config bytes, database size, blacklist and report counts asserted unchanged |
| Existing `test_security_audit.py` | passes over the new package |

## 8. Network audit

The interface introduces **zero** network communication.

- Static AST audit over all 39 UI modules: no import of `socket`, `ssl`,
  `requests`, `urllib`, `http`, `httpx`, `ftplib`, `telnetlib`, `smtplib`,
  `dns`, `xmlrpc`, `asyncio`, `websocket(s)` or `aiohttp`.
- No hardcoded URL, hostname, `0.0.0.0` or `127.0.0.1` anywhere in the package.
- Absolute imports are limited to the standard library: `contextlib`,
  `dataclasses`, `importlib`, `io`, `json`, `os`, `re`, `select`, `shutil`,
  `sys`, `termios`, `time`, `tty`, `typing`, `unicodedata`.
- The only transport is the daemon's pre-existing local `AF_UNIX` socket,
  reached through `cli._ipc_request`; no new IPC mechanism was added.
- `dependencies = []` in `pyproject.toml` is unchanged — no new dependency.

## 9. Termux verification

Verified on Linux with the Python standard library only, which is what a Termux
install provides:

| Scenario | Result |
|---|---|
| Pseudo-terminal, 80×24, default | exit 0, frames render, clean shutdown |
| `NO_COLOR=1` | exit 0, no ANSI escape sequences emitted |
| `CALLSHIELD_UI_ASCII=1`, `LANG=C` | exit 0, no box-drawing characters |
| `LANG=en_US.UTF-8` | exit 0, box-drawing characters present |
| 46×20 (narrow) | exit 0, no line exceeds the width |
| 160×50 (wide) | exit 0, no overflow |
| Ctrl+C at the root | exit 0, terminal restored, no traceback |
| Ctrl+C inside a sub-screen | exit 0, terminal restored |
| Esc chain to the root | exit 0, exits instead of trapping |
| Daemon running | backend reports `source="ipc"` with live metrics, health and screening status |
| Daemon stopped | backend reports `source="offline"` with persisted counters |
| Piped / non-tty | banner printed, exit 0 |
| All 17 existing subcommands | unchanged exit codes and output |

Not performed, and therefore not claimed:

```text
TERMUX DEVICE RUN = NOT VERIFIED
ANDROID BUILD     = NOT VERIFIED
PHYSICAL DEVICE   = NOT VERIFIED
```

`callshield doctor` returns exit 1 in this sandbox because of directory
permissions on `/tmp`; the identical result occurs on a pristine checkout, so it
is unrelated to this phase.

## 10. Phase boundary

Phase 9 has not started. No Phase 9 functionality, no new intelligence feature,
no cloud service, no Android application and no engine redesign is included.
CALLSHIELD remains a Termux/Linux command-line tool with an optional terminal
interface; the command line is always usable.
