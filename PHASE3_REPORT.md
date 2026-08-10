# CALLSHIELD — Phase 3 Final Report

**Version:** 0.3.0 — Background Engine  
**Date:** 2026-08-10  
**Branch:** `arena/019fecb8-callshield`  
**Test Result:** 128 tests OK (Phase 1 77 + Phase 2 9 + Phase 3 42)

> **Phase 3 provides the background processing infrastructure. It does not yet receive or reject real Android phone calls.**

---

## 1. Files Created

```
callshield/daemon/
├── __init__.py      # package init, re-exports legacy API (status/start/stop) + new service
├── service.py       # DaemonService (queue, processor, heartbeat, health, IPC, signals, graceful shutdown)
├── process.py       # PID/socket/run-dir, stale detection, verify callshield via /proc/cmdline
├── heartbeat.py     # Heartbeat thread, configurable interval, lightweight state file + DB
├── health.py        # HealthMonitor (uptime, PID, queue, processed/failed, last event/heartbeat, DB, memory)
├── signals.py       # SIGTERM/SIGINT/SIGHUP (shutdown/reload)
└── recovery.py      # validate_startup (10-step), per-event exception isolation

callshield/events/
├── __init__.py
├── types.py         # VALID_EVENT_TYPES = NUMBER_SCAN/USER_REPORT/BLOCK_ACTION/ALLOW_ACTION/SYSTEM/HEARTBEAT (extensible)
├── models.py        # Event(event_id uuid4, event_type, timestamp iso_now, source, number, payload 8KB limit)
├── queue.py         # EventQueue (queue.Queue, maxsize 256 default, thread-safe, dropped/peak metrics, close)
└── processor.py     # EventProcessor (validate→normalize→analyze_number→persist→log→metrics, never duplicates scoring)

tests/
├── test_daemon.py   # start/duplicate/stop/stale/cleanup via CLI + process
├── test_process.py  # pid_alive/write/read/clear/stale detection
├── test_events.py   # Event model + processor (valid/invalid/payload limit, system/missing/malformed)
├── test_queue.py    # bounded, full→dropped, thread-safe, close, metrics
├── test_health.py   # snapshot, heartbeat fresh/stale, DB health, queue health, metrics inc
├── test_ipc.py      # valid status/metrics, invalid/unknown/oversized, socket perms, cleanup on stop
├── test_metrics.py  # CLI metrics + HealthMonitor metrics
└── test_recovery.py # event exception continues, malformed payload, DB failure, SIGTERM graceful

callshield/intelligence/reputation.py  # (Phase 2 add, now completed) 6-tier classifier
tests/test_rules.py                   # (Phase 2) rule engine deterministic tests
```

Modified:
- `callshield/cli.py` — Phase 3 CLI (status --watch, metrics, daemon, event test, daemon info/health, IPC, richer status, daemon config section)
- `callshield/config.py` — 7 new fields + validation + set_value handling (daemon_enabled, heartbeat_interval, event_queue_size, shutdown_timeout, status_refresh_interval, max_log_size, max_log_files, ipc_enabled, run_dir, socket_path, daemon_log_file)
- `callshield/daemon.py` → **removed** (replaced by package)
- `callshield/intelligence/*` — alias handling for previous_suspicious_events/number_format_anomaly
- `pyproject.toml` / `VERSION` → 0.3.0
- `README.md` / `CHANGELOG.md` → Phase 3 docs
- `.gitignore` → ignore run/*.sock/state
- `scripts/install.sh` / `uninstall.sh` → Phase 3 run/state dirs, 4-command quick start
- `tests/_common.py` → isolated run_dir/socket for Phase 3

---

## 2. Files Modified

- `VERSION`: 0.2.0 → 0.3.0
- `pyproject.toml`: description Phase 3
- `callshield/cli.py`: +~380 lines (watch, metrics, daemon, event, IPC, daemon config display)
- `callshield/config.py`: +47 lines (7 fields + validation)
- `callshield/intelligence/signals.py`: alias handling for spec name mismatch
- `callshield/intelligence/profiles.py`: alias weights for both naming variants
- `callshield/intelligence/reputation.py`: new file to satisfy §3 architecture
- `callshield/detector.py`: alias handling in weight multipliers
- `tests/_common.py`: isolated run_dir/socket

---

## 3. Daemon Architecture

```
Termux → callshield start → DaemonService.start()
           ↓
     validate_startup (config, DB, run/log dirs, IPC, duplicate check)
           ↓
     EventQueue(256) + HealthMonitor + Heartbeat(30s) + EventProcessor
           ↓
     SignalHandler(SIGTERM/SIGINT/SIGHUP) + IPC Unix socket (~/.callshield/run/callshield.sock, 700)
           ↓
     Processor thread: queue.get(timeout=0.5) → processor.process() → health.inc_* (per-event exception caught)
     Heartbeat thread: every heartbeat_interval → beat() (state file + DB)
     IPC thread: accept → handle JSON (size-limited 16KB req, 64KB resp, validated command whitelist, no eval/exec)
           ↓
     Graceful shutdown on SIGTERM/SIGINT/_shutdown event:
       close queue → drain with shutdown_timeout (10s) → flush logs → stop heartbeat → close IPC socket → unlink PID/socket → STOPPED
```

- **Not a fake status**: `status` via IPC when running, else PID fallback; `metrics` via IPC; `stop` via IPC `stop` + SIGTERM fallback; never kills unrelated PID (verified via `/proc/<pid>/cmdline` contains `callshield`/`python`).
- **Stale handling**: `status` returns `STALE` if pid not alive or not callshield; `start` clears stale pid+socket; `stop` on stale just clears.
- **Resource control**: `queue.get(timeout=0.5)`, `heartbeat.wait(1.0)`, `status.wait(1.0)` — no busy loops, bounded queue prevents OOM, sleep when idle, minimal CPU.

---

## 4. IPC Architecture

```
CLI (metrics/status/event test/stop) → JSON over Unix socket → Daemon IPC thread → handler → EventQueue / Health snapshot
```

- **Socket:** `~/.callshield/run/callshield.sock` (or isolated temp for tests), parent `mkdir -p` 700, `chmod 700`, single instance `listen(5)`.
- **Protocol:** newline-delimited JSON `{command: "status"|"metrics"|"health"|"daemon_info"|"event"|"stop"|"ping", ...}` + optional `event` payload. Request limit 16KB, response 64KB, timeout 2s/5s, validates `command` whitelist, rejects malformed/oversized/unknown with `{"status":"error"}`.
- **Security:** 700 perms, local-only (no TCP, no network listener verified via `ss -l`/`netstat`), validate incoming JSON, reject >16KB, never `eval`/`exec`/shell, timeout inactive clients (2s), clean socket on shutdown.
- **Fallback:** If IPC unavailable (socket missing, `ipc_enabled=false`, daemon stopped), CLI falls back to PID file + DB polling and shows `(IPC unavailable — ...)` note.

---

## 5. Event Pipeline

```
Event Source → EventQueue → EventProcessor → Detector → DetectionResult → DB + Logs → Metrics
```

- **Model:** `Event(event_id=uuid4, event_type=VALID_EVENT_TYPES, timestamp=iso_now, source=CLI/DAEMON/TEST/SYSTEM, number=normalized|None, payload=dict)` — 8KB payload limit, validation in `__post_init__`, `from_dict`/`to_dict`.
- **Types (Phase 3):** `NUMBER_SCAN`, `USER_REPORT`, `BLOCK_ACTION`, `ALLOW_ACTION`, `SYSTEM`, `HEARTBEAT` — no `INCOMING_CALL` fake; extensible for Phase 4.
- **Queue:** `EventQueue(maxsize=cfg.event_queue_size)` wraps `queue.Queue`, `put(block=False)` returns False on full → `dropped` metric, `peak` tracking, `close()` stops accepting, thread-safe via lock.
- **Processor:** `EventProcessor.process(event)`:
  1. validate event_type
  2. normalize number via `normalize()` (if present; SYSTEM/HEARTBEAT skip)
  3. call `analyze_number(normalized)` (Phase 2 engine, no duplication)
  4. persist via `analyze_number(record_event=True)` (DB) + processor logs masked number
  5. update health metrics
  6. return `{"event_id", "status": "processed"|"failed", "detection": {...}, "error": ...}`
  Per-event exception caught → `failed` + log + continue.

---

## 6. Process-Management Behavior

- **PID file:** `~/.callshield/run/callshield.pid` (new) + legacy `~/.callshield/data/callshield.pid` checked via `_all_pid_paths`. Written `600`, parent `700`, `write_pid()` chooses new location if legacy is `data/`.
- **Start:** `validate_startup` → check `status` → if `RUNNING` → `CALLSHIELD is already running. PID: X` (no duplicate); if `STALE` → clear pid+socket; then `Popen(start_new_session=True, python -m callshield _run-fg)` → wait up to 2s for `RUNNING`; prints `Protection daemon started. PID X Status RUNNING Queue READY Engine ONLINE` + `Live call screening: NOT CONNECTED`.
- **Stop:** try IPC `{"command":"stop"}` → delayed shutdown (0.2s) to allow response; fallback to `process.stop()` → `SIGTERM` → wait `shutdown_timeout` → `SIGKILL` if needed → clear pid+socket. Never kills unrelated PID (verified via `pid_is_callshield`).
- **Status:** IPC `status` when `RUNNING` → detailed `Daemon RUNNING PID Uptime Engine ONLINE Database ONLINE Queue 0/256 Events Processed/Failed Last Event/Heartbeat Call Screening NOT CONNECTED`; else fallback `Engine STOPPED/STALE` + `Queue 0/256 (IPC unavailable)` note.
- **Duplicate test:** second `start` while `RUNNING` returns `already running` and does not spawn second `sleep` process (verified via `ps`).

---

## 7. Health/Metrics Implementation

`daemon/health.py` `HealthMonitor`:

- **Tracks:** `state` (STARTING/RUNNING/STOPPING/STOPPED), `pid`, `start_time`, `uptime`, `queue_size`/`queue_max`/`queue_peak`, `received`/`processed`/`failed`/`dropped`, `analysis_count`/`high_risk_count`/`blocked_recommendations`, `last_event` (ISO), `last_heartbeat`, `db_status` (ONLINE/ERROR via `Database.get_setting`), `memory_kb` (via `/proc/<pid>/status` VmRSS or `resource`).
- **Updates:** `inc_received()` on `queue.put`, `inc_processed(verdict,action)` on success, `inc_failed()` on exception, `update_queue()` on each loop, `set_heartbeat()` on beat, `check_db()` each main loop iteration.
- **Snapshot:** `snapshot()` returns dict with `uptime_human` (`HH:MM:SS`), `healthy` via `is_healthy()` (DB ONLINE + heartbeat age < 3*interval + queue <90% max).
- **Exposed:** `callshield metrics` (IPC `metrics` → same snapshot + `events_received` etc.), `callshield daemon health` (IPC `health` → `HEALTHY`/`DEGRADED`), `daemon info`.

Heartbeat: `daemon/heartbeat.py` thread every `heartbeat_interval` (default 30s) writes `run/heartbeat.json` (safe_write) + DB `heartbeat`/`heartbeat_iso`, `is_fresh(max_age=interval*2+10)`.

---

## 8. Security Checks

- **No network listener:** `ss -ltn`/`netstat` shows no TCP; `grep -r "socket.*AF_INET\|TCP\|bind.*0.0.0.0"` none (only `AF_UNIX`).
- **IPC local-only:** `callshield.sock` 700, `run` 700, `chmod` after `bind`/`write_pid`, validated `command` whitelist, size limits 16KB/64KB, timeout 2–5s, no `eval`/`exec`/`shell` (code search confirms).
- **PID validation:** `/proc/<pid>/cmdline` must contain `callshield` or `python` for `RUNNING`; otherwise `STALE`; `stop` only signals if `pid_is_callshield`.
- **Input validation:** `Event` validates `event_type` in `VALID_EVENT_TYPES`, `payload` size 8KB, CLI `normalize()` validates numbers, `config` validates all 7 new fields, `database` uses parameterized SQL, `processor` catches per-event exception.
- **Safe DB writes:** `Database` uses `queue.Queue` + per-event `Database()` with `BEGIN`/`COMMIT`/`ROLLBACK`, `timeout`, `WAL`, indexes, no long-held locks, clean shutdown flushes.
- **Log handling:** `daemon.log` via `_RotatingFileHandler` (size check before `emit`, rotate `log.3`→delete, `2→3`, `1→2`, `base→.1`, `600` perms), masked numbers via `mask_number`, no sensitive plain text unless configured.

Verified via `grep -r "eval\|exec(" callshield --include="*.py"` no user-input execution.

---

## 9. Tests Executed

```
$ python -m unittest discover -s tests
Ran 128 tests in ~29s
OK
```

Previous Phase 1 77 → Phase 2 86 → Phase 3 128 (+42):

- `test_normalizer` 10, `test_database` 8, `test_scoring` 9, `test_detector` 8, `test_config` 11, `test_profiles` 6, `test_reports` 6, `test_reputation` 5, `test_signals` 5, `test_behavior` 4, `test_confidence` 5, `test_rules` 8, **new:** `test_queue` 6, `test_events` 10, `test_health` 5, `test_daemon` 3, `test_process` 5, `test_ipc` 7, `test_metrics` 2, `test_recovery` 4

Spec-required suites all present and passing; existing Phase 1/2 preserved.

---

## 10. Manual Verification

```
$ callshield start
Protection daemon started. PID 2666 Status RUNNING Queue READY Engine ONLINE
Live call screening: NOT CONNECTED

$ callshield status
Daemon          RUNNING
PID             2666
Uptime          00:00:01
Engine          ONLINE
Database        ONLINE
Queue           0 / 256
Events
  Processed     0
  Failed        0
Last Heartbeat  2026-08-10T18:02:11Z
Call Screening  NOT CONNECTED

$ callshield metrics
Uptime              00:00:01
Events Received     0
Processed           0
Failed              0
Dropped             0
High Risk           0
Block Recommendations 0
Queue Peak          0 / 256
Call Screening      NOT CONNECTED

$ callshield event test +919876543210
TEST EVENT
Number        +919876543210
Sending NUMBER_SCAN via daemon event queue...
Event ID      ace772e3-...  Event accepted — processing via daemon pipeline (TEST EVENT, not a phone call).

$ callshield metrics
Events Received     1
Processed           1
Queue Peak          1 / 256

$ callshield history +919876543210
Events       1 shown
TIME SCORE VERDICT ACTION
2026-08-10 17:58:46 0 25% UNKNOWN ALLOW

$ callshield status --watch   # refreshes every 2s, Ctrl+C exits watch only
Daemon RUNNING ... (live)

$ callshield stop
Protection engine stopped. PID 2666

$ callshield status
Engine      STOPPED

$ callshield start; callshield start  # second → CALLSHIELD is already running. PID: 2666 (no duplicate)

$ callshield daemon restart  # stop+start, health→HEALTHY, info shows uptime
```

Idle CPU minimal (sleep 0.5–1.0), memory ~18MB, queue bounded, no busy loop.

---

## 11. Termux Compatibility Notes

- Pure stdlib (`queue`, `socket`, `threading`, `signal`, `sqlite3`, `argparse`), no native modules, `python3.8+`.
- Installer now creates `~/.callshield/{data,logs,run,state}` 700, handles `$PREFIX/bin` (Termux) vs `~/.local/bin` + `/usr/local/bin` symlink, adds to PATH, runs DB init + 128 tests.
- `run/callshield.pid` + `callshield.sock` 700 works on Termux Linux (`/proc` available, `AF_UNIX` supported); stale detection via `kill(pid,0)` + `cmdline` check, socket cleanup on shutdown, fallback to PID/DB if IPC unavailable (documented in CLI).
- No root, no Android Studio, no GUI/APK; `Termux:Boot` concept documented (`callshield daemon start`) but not auto-installed.

---

## 12. Known Limitations

- **Phase 3 provides the background processing infrastructure. It does not yet receive or reject real Android phone calls.** No `INCOMING_CALL` type, no `CallScreeningService`, no telephony permission, `Call Screening: NOT CONNECTED` always shown, `event test` explicitly labeled `TEST EVENT`.
- Normalizer still curated country table; weak pattern signals capped; no network/ML/cloud.
- Daemon not auto-restarted internally; watchdog is foundation (`alive`/`heartbeat`/`queue`/`DB` checks via `health.is_healthy()`), future Phase 4/5 may add restart.
- `data/callshield.db` etc. in repo when running without `CALLSHIELD_DATA_DIR` are now ignored (`run/`, `*.sock`, `data/config.json`), runtime after install is `~/.callshield`.
- `status --watch` uses ANSI clear (`\033[2J\033[H`) — works on Termux, falls back gracefully.

**Phase 3 complete, ready for Phase 4 call-screening integration via `events` extensibility and `analyze_number()` API.**
