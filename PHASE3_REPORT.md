# CALLSHIELD — Phase 3 Final Report

**Version:** 0.3.0 — Background Engine
**Date:** 2026-08-11
**Branch:** `arena/019ff0f4-callshield`
**Recovered source commit:** `7414a49c5cd9ead6bd6ce6ab34ac74f768983aad`
**Tests:** 163 passed

## Scope confirmation

Phase 3 is complete as a Termux-first, Python-only background engine.

- Android project: **NOT IMPLEMENTED — Phase 4**
- Live call interception: **NOT IMPLEMENTED**
- Automatic rejection: **DISABLED / NOT IMPLEMENTED**
- TCP/network listener: **NONE**
- Call screening status: **NOT CONNECTED**

`BLOCK_ACTION` and `ALLOW_ACTION` are advisory local events only. They do not
change phone state, reject calls, or mutate the user's blacklist/whitelist.

## Recovery audit

The starting `main` tree was the later Phase 4 commit `c2321c7`. Full history
was fetched and inspected before implementation. Its direct parent,
`7414a49`, was the existing clean Phase 3 implementation and a descendant of
the Phase 2 commit `6ea0cba`.

The Phase 3 candidate was verified before reuse:

- no `android/` tree
- no `policy/` tree
- no live incoming-call event
- no call-screening service
- no active rejection API
- no Phase 5/6 settings or hardening features

That exact Phase 3 tree was recovered instead of rebuilding the project. The
existing Phase 1/2 detector and `analyze_number()` API were retained. Recovery
work then tightened PID ownership, queue draining, IPC bounds, stale-runtime
handling, metrics fallback, and tests while remaining strictly inside Phase 3.

## Architecture

```text
Termux CLI
   │
   └── callshield daemon start
          │
          ▼
    DaemonService
       ├── EventQueue (bounded, default 256)
       ├── EventProcessor ──► existing analyze_number()
       ├── Heartbeat (default 30 seconds)
       ├── HealthMonitor
       ├── SignalHandler (SIGTERM/SIGINT/SIGHUP)
       ├── Recovery
       └── AF_UNIX JSON IPC
```

Created/reused packages:

```text
callshield/daemon/
├── __init__.py
├── service.py
├── process.py
├── heartbeat.py
├── health.py
├── signals.py
└── recovery.py

callshield/events/
├── __init__.py
├── models.py
├── queue.py
├── processor.py
└── types.py
```

## Daemon and process safety

- A real detached Python process runs `python -m callshield _run-fg`.
- PID creation is atomic and owner-only.
- `/proc/<pid>/cmdline` must match the exact CALLSHIELD foreground command;
  being an arbitrary Python process is not sufficient.
- PID start identity is checked again before a final termination signal to
  prevent PID-reuse races.
- Duplicate startup preserves the original PID and reports already running.
- Stale and malformed PID state is recovered without signalling the referenced
  unrelated process.
- Regular files, symlinks, unowned endpoints, and active Unix sockets are never
  removed as stale sockets.
- Startup failures and crashes clean the owned PID/socket state.

## Event system

Phase 3 defines exactly these local event types:

- `NUMBER_SCAN`
- `USER_REPORT`
- `BLOCK_ACTION`
- `ALLOW_ACTION`
- `SYSTEM`
- `HEARTBEAT`

Every event has a validated UUID, timezone-aware timestamp, type, bounded
source, optional number, and JSON-object payload. Payload size is measured as
UTF-8 JSON and bounded to 8 KiB by default. Invalid, oversized, non-JSON, or
mutated events are rejected without terminating the worker.

`NUMBER_SCAN` reuses the existing Phase 2 `analyze_number()` implementation.
There is no duplicate scoring or detection engine.

## Queue and graceful shutdown

`EventQueue` wraps the standard-library bounded queue with a default maximum of
256. It provides enqueue, dequeue, size, drain, close, dropped-event tracking,
peak tracking, and finite completion waits.

Shutdown order is:

1. stop accepting IPC and new events
2. close the queue to producers
3. process all accepted queued work within the configured timeout
4. stop heartbeat
5. persist bounded metrics and flush logs
6. remove the owned Unix socket and PID file
7. exit

A processor exception increments failure metrics and the next event continues.

## Heartbeat and health

Heartbeat is lightweight and defaults to 30 seconds. It writes owner-only local
state and a SQLite heartbeat, and updates the in-memory health monitor.

Health reports PID, daemon state, uptime, queue size/max/peak, received,
processed, failed, dropped, high-risk detections, block recommendations, last
event, last heartbeat, heartbeat age/staleness, database availability, and
memory where `/proc` or `resource` makes it available. Health failures are
contained and cannot crash the daemon.

## Unix IPC

IPC uses only `AF_UNIX`/`SOCK_STREAM` at:

```text
~/.callshield/run/callshield.sock
```

The run directory is 0700 and the socket is 0600. Requests are strict UTF-8
JSON objects, limited to 16 KiB; responses are limited to 64 KiB. Reads have a
validated configurable timeout. One connection is handled at a time to bound
connection resources.

Supported operations:

- `ping`
- `status`
- `metrics`
- `health`
- `daemon_info`
- `event`
- `stop`

Malformed JSON, unknown commands, partial/time-out requests, oversized input,
and malformed events return an error while the daemon remains available.

## CLI

Implemented while preserving all Phase 1/2 commands:

```text
callshield daemon start
callshield daemon stop
callshield daemon restart
callshield daemon status
callshield daemon info
callshield daemon health
callshield status
callshield status --watch
callshield metrics
callshield event test <number>
```

Watch refresh defaults to two seconds. Ctrl+C exits only the watcher. Test event
output says `TEST EVENT` and explicitly says it is not a phone call.

Running and stopped metrics include uptime/last uptime, received, processed,
failed, dropped, queue size/peak, high-risk detections, block recommendations,
and memory where available. Stopped mode combines persisted SQLite analysis
counters with a bounded last-session snapshot and does not depend on an
uninitialized local variable.

## Configuration

Phase 3 settings only:

- `daemon_enabled`
- `pid_file`
- `socket_path`
- `run_dir`
- `heartbeat_interval`
- `event_queue_size`
- `shutdown_timeout`
- `status_refresh_interval`
- `ipc_enabled`
- `ipc_timeout`
- `event_payload_limit`
- daemon log path/size/count

All values have validated types and bounded ranges. SIGHUP safely reloads
mutable settings while retaining restart-required live paths and queue size.
No call-screening mode, call-screening decision configuration, or emergency-off setting exists.

## Installation and Termux

`scripts/install.sh` was run successfully in an isolated Termux-style prefix.
It created:

```text
~/.callshield/
├── data/
├── logs/
├── run/
└── state/
```

Directories were 0700; database, config, PID, heartbeat, logs, and socket were
owner-only. The installer requires no root and writes only to `$PREFIX/bin` or
`~/.local/bin`.

## Tests

Final Python suite:

```text
163 passed
```

Required suites are present:

- `tests/test_daemon.py`
- `tests/test_process.py`
- `tests/test_events.py`
- `tests/test_queue.py`
- `tests/test_health.py`
- `tests/test_ipc.py`
- `tests/test_metrics.py`
- `tests/test_recovery.py`

Coverage includes lifecycle, duplicate startup, restart, stale PID/socket,
unrelated-process protection, bounded/thread-safe queue, graceful drain,
invalid and oversized events, processor exception isolation, all IPC
operations, malformed/oversized/timed-out IPC, socket permissions, complete
running/stopped metrics, SIGHUP, watch-mode interruption, and graceful signals.

## Manual verification

An isolated installed `callshield` command was used for the complete sequence:

- daemon start: PASS
- status: RUNNING / ONLINE / queue 0/256 / NOT CONNECTED
- metrics before event: zero
- test event `+919876543210`: accepted and explicitly labeled TEST EVENT
- metrics after event: received 1, processed 1, queue peak 1
- status watch + SIGINT: watcher exit 0; daemon remained RUNNING
- daemon stop + stopped status/metrics fallback: PASS
- duplicate start: second start rejected; PID unchanged
- daemon restart + status: PASS
- daemon info/health: ONLINE and HEALTHY
- SIGHUP: configuration reloaded; PID unchanged
- PID/socket cleanup: PASS

`ss -ltnp` showed only unrelated sandbox listeners. CALLSHIELD had one socket
file descriptor whose inode appeared in `/proc/net/unix` and not in
`/proc/net/tcp` or `/proc/net/tcp6`. `ss -lxnp` showed only the configured
CALLSHIELD Unix socket.

## Security audit

Static checks found no implementation use of:

- `eval(`
- `exec(`
- `os.system(`
- `shell=True`
- `AF_INET`
- `Runtime.exec`
- `ProcessBuilder`

There is no TCP server, HTTP server, network listener, root requirement,
Android project, active call blocking, or automatic rejection.

## Known limitations

- Phase 3 does not receive real phone-call events.
- Phase 3 cannot intercept or reject calls.
- The daemon is user-started; no automatic boot integration is installed.
- Memory reporting depends on platform support.
- Internal watchdog health detection reports stale/degraded state but does not
  auto-restart a crashed process.
- Phase 4 is future work and is not included.
