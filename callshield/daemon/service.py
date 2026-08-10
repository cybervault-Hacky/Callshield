"""Main daemon service for CALLSHIELD Phase 3.

Orchestrates EventQueue, Processor, Heartbeat, Health, IPC, Signals,
graceful shutdown, crash recovery, resource control.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Config, load_config
from ..database import Database
from ..events import Event, EventQueue, EventProcessor
from ..events.types import VALID_EVENT_TYPES
from ..utils import safe_write_text
from .health import HealthMonitor
from .heartbeat import Heartbeat
from .process import _clear_pid, _clear_socket, _pid_path, _socket_path, _write_pid, _run_dir
from .recovery import validate_startup
from .signals import SignalHandler


# Daemon logger with rotation
def _get_daemon_logger(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("callshield.daemon")
    if getattr(logger, "_callshield_daemon_configured", False):
        return logger
    logger.setLevel(logging.INFO)
    logger.handlers = []
    try:
        log_path = Path(cfg.daemon_log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = _RotatingFileHandler(
            log_path,
            max_bytes=int(cfg.max_log_size),
            backup_count=int(cfg.max_log_files),
        )
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except Exception:
        # Fallback to stream
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(sh)
    logger.propagate = False
    logger._callshield_daemon_configured = True  # type: ignore
    return logger


class _RotatingFileHandler(logging.FileHandler):
    """Simple size-based rotating file handler."""

    def __init__(self, path: Path, max_bytes: int = 2*1024*1024, backup_count: int = 3, encoding: str = "utf-8"):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        super().__init__(str(self.path), encoding=encoding)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                self.do_rollover()
        except Exception:
            pass
        super().emit(record)

    def do_rollover(self) -> None:
        try:
            self.close()
            # Rotate: daemon.log.3 -> remove, 2->3, 1->2, .log->.1
            for i in range(self.backup_count, 0, -1):
                src = self.path.parent / f"{self.path.name}.{i}" if i > 1 else self.path
                # Actually logic: for i == backup_count down to 1, src is .i, dst is .(i+1) except base
                # Simpler: rotate from high to low
                pass
            # Implement correctly
            if self.backup_count > 0:
                # Remove oldest
                oldest = self.path.parent / f"{self.path.name}.{self.backup_count}"
                if oldest.exists():
                    oldest.unlink()
                # Shift
                for i in range(self.backup_count - 1, 0, -1):
                    src = self.path.parent / f"{self.path.name}.{i}"
                    dst = self.path.parent / f"{self.path.name}.{i+1}"
                    if src.exists():
                        src.rename(dst)
                # Base -> .1
                if self.path.exists():
                    self.path.rename(self.path.parent / f"{self.path.name}.1")
            self.stream = self._open()
        except Exception:
            try:
                self.stream = self._open()
            except Exception:
                pass


class DaemonService:
    """Persistent daemon service."""

    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.cfg = cfg or load_config()
        self.cfg = validate_startup(self.cfg)
        self.queue = EventQueue(maxsize=int(self.cfg.event_queue_size))
        self.health = HealthMonitor(self.cfg)
        self.heartbeat = Heartbeat(self.cfg)
        self.processor = EventProcessor(self.cfg, logger=_get_daemon_logger(self.cfg))
        self.logger = _get_daemon_logger(self.cfg)
        self._shutdown = threading.Event()
        self._ipc_thread: Optional[threading.Thread] = None
        self._processor_thread: Optional[threading.Thread] = None
        self._ipc_socket: Optional[socket.socket] = None
        self._ipc_stop = threading.Event()

    def start(self) -> int:
        # Startup validation already done
        pid = _write_pid(self.cfg)
        self.health.pid = pid
        self.health.set_state("RUNNING")
        self.logger.info(f"Daemon starting pid={pid} queue={self.cfg.event_queue_size} heartbeat={self.cfg.heartbeat_interval}s")

        # Start heartbeat
        self.heartbeat.start()
        self.health.set_heartbeat()

        # Install signal handlers
        def _do_shutdown():
            self.request_shutdown()

        def _do_reload():
            try:
                new_cfg = load_config()
                self.cfg = new_cfg
                self.logger.info("Configuration reloaded via SIGHUP")
            except Exception as exc:
                self.logger.error(f"Failed to reload config: {exc}")

        sig_handler = SignalHandler(self.cfg, shutdown_cb=_do_shutdown, reload_cb=_do_reload)
        sig_handler.install()

        # Start IPC
        if self.cfg.ipc_enabled:
            self._start_ipc()

        # Start processor thread
        self._processor_thread = threading.Thread(target=self._processor_loop, name="callshield-processor", daemon=True)
        self._processor_thread.start()

        # Main loop: just wait for shutdown, handle heartbeat via its own thread
        try:
            while not self._shutdown.is_set():
                # Check health periodically, update DB status
                try:
                    self.health.check_db()
                except Exception:
                    pass
                # Update queue metrics
                try:
                    self.health.update_queue(self.queue.qsize(), peak=self.queue.metrics().get("peak"))
                except Exception:
                    pass
                # Sleep with interruption
                self._shutdown.wait(timeout=1.0)
                # Resource control: avoid busy loop, sleep when idle is already handled via wait
        finally:
            self._do_graceful_shutdown()
        return 0

    def _processor_loop(self) -> None:
        """Worker that dequeues and processes events."""
        while not self._shutdown.is_set():
            try:
                event = self.queue.get(block=True, timeout=0.5)
                if event is None:
                    continue
                # Update health
                self.health.update_queue(self.queue.qsize())
                try:
                    result = self.processor.process(event)
                    # Update metrics based on result
                    if result.get("status") == "processed":
                        det = result.get("detection") or {}
                        verdict = det.get("verdict")
                        action = det.get("recommended_action") or det.get("action")
                        self.health.inc_processed(verdict=verdict, action=action)
                    else:
                        self.health.inc_failed(error=result.get("error"))
                except Exception as exc:
                    # Crash recovery: log, increment failed, continue
                    try:
                        self.logger.exception(f"Processor exception for event {getattr(event, 'event_id', 'unknown')}: {exc}")
                    except Exception:
                        pass
                    self.health.inc_failed(error=str(exc))
                finally:
                    # Mark queue task done if needed (queue.Queue doesn't require)
                    pass
            except Exception as exc:
                # Ensure daemon doesn't crash
                try:
                    self.logger.exception(f"Processor loop exception: {exc}")
                except Exception:
                    pass
                time.sleep(0.1)

    def _start_ipc(self) -> None:
        try:
            sp = _socket_path(self.cfg)
            # Clean stale
            if sp.exists():
                try:
                    sp.unlink()
                except OSError:
                    pass
            sp.parent.mkdir(parents=True, exist_ok=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            # Remove if exists
            try:
                # Allow reuse
                pass
            except Exception:
                pass
            sock.bind(str(sp))
            sock.listen(5)
            # Restrict permissions to user only
            try:
                os.chmod(sp, 0o700)
            except OSError:
                pass
            self._ipc_socket = sock

            def _ipc_loop():
                while not self._ipc_stop.is_set():
                    try:
                        sock.settimeout(1.0)
                        try:
                            conn, _ = sock.accept()
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                        # Handle connection in new thread to avoid blocking
                        t = threading.Thread(target=self._handle_ipc_conn, args=(conn,), daemon=True)
                        t.start()
                    except Exception as exc:
                        if not self._ipc_stop.is_set():
                            try:
                                self.logger.error(f"IPC accept failed: {exc}")
                            except Exception:
                                pass
                        time.sleep(0.1)
            self._ipc_thread = threading.Thread(target=_ipc_loop, name="callshield-ipc", daemon=True)
            self._ipc_thread.start()
            self.logger.info(f"IPC listening on {sp}")
        except Exception as exc:
            self.logger.error(f"Failed to start IPC socket: {exc}")
            # Fallback: continue without IPC, document via log
            self.logger.warning("IPC disabled due to socket failure; CLI will fallback to PID/DB polling")

    def _handle_ipc_conn(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5.0)
            data = b""
            # Limit request size to 16KB
            max_size = 16 * 1024
            while len(data) < max_size:
                try:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    # Check if we have complete JSON (simple: try parse)
                    if b"\n" in data or len(chunk) < 4096:
                        # Try to parse
                        try:
                            txt = data.decode(errors="ignore").strip()
                            if txt:
                                json.loads(txt)
                                break
                        except Exception:
                            # Not yet complete
                            if len(data) >= max_size:
                                break
                            continue
                    if len(data) >= max_size:
                        break
                except socket.timeout:
                    break
            if not data:
                conn.close()
                return
            txt = data.decode(errors="ignore").strip()
            if len(txt) > max_size:
                resp = {"status": "error", "error": "Request too large"}
                conn.sendall((json.dumps(resp) + "\n").encode())
                conn.close()
                return
            try:
                req = json.loads(txt)
            except Exception as exc:
                resp = {"status": "error", "error": f"Invalid JSON: {exc}"}
                conn.sendall((json.dumps(resp) + "\n").encode())
                conn.close()
                return
            # Validate
            if not isinstance(req, dict) or "command" not in req:
                resp = {"status": "error", "error": "Invalid request: missing command"}
                conn.sendall((json.dumps(resp) + "\n").encode())
                conn.close()
                return
            # Never exec/eval, only allow known commands
            cmd = req.get("command")
            allowed = {"status", "metrics", "health", "daemon_info", "event", "stop", "ping"}
            if cmd not in allowed:
                resp = {"status": "error", "error": f"Unknown command: {cmd}"}
                conn.sendall((json.dumps(resp) + "\n").encode())
                conn.close()
                return

            resp = self._handle_ipc_command(req)
            conn.sendall((json.dumps(resp) + "\n").encode())
            conn.close()
        except Exception as exc:
            try:
                self.logger.error(f"IPC handling failed: {exc}")
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _handle_ipc_command(self, req: Dict[str, Any]) -> Dict[str, Any]:
        cmd = req.get("command")
        try:
            if cmd == "ping":
                return {"status": "ok", "pong": True}
            elif cmd == "status":
                snap = self.health.snapshot()
                snap["ipc"] = "ENABLED"
                snap["call_screening"] = "NOT CONNECTED"
                return {"status": "ok", "data": snap}
            elif cmd == "metrics":
                snap = self.health.snapshot()
                # Add queue metrics
                qm = self.queue.metrics()
                snap.update({
                    "events_received": snap["received"],
                    "events_processed": snap["processed"],
                    "events_failed": snap["failed"],
                    "events_dropped": snap["dropped"],
                    "queue_peak": qm.get("peak"),
                })
                return {"status": "ok", "data": snap}
            elif cmd == "health":
                snap = self.health.snapshot()
                return {"status": "ok", "data": snap, "healthy": self.health.is_healthy()}
            elif cmd == "daemon_info":
                snap = self.health.snapshot()
                return {"status": "ok", "data": {
                    "pid": snap["pid"],
                    "uptime": snap["uptime_human"],
                    "state": snap["state"],
                    "queue": f"{snap['queue_size']} / {snap['queue_max']}",
                    "engine": "ONLINE" if snap["db_status"] == "ONLINE" else "ERROR",
                    "database": snap["db_status"],
                }}
            elif cmd == "event":
                # Expect event data
                payload = req.get("event") or req.get("data") or {}
                # Validate event type
                etype = payload.get("event_type") or "NUMBER_SCAN"
                number = payload.get("number")
                source = payload.get("source") or "CLI"
                # Create Event
                try:
                    from ..events.models import Event
                    ev = Event(
                        event_id=payload.get("event_id") or str(uuid.uuid4()),
                        event_type=etype,
                        timestamp=payload.get("timestamp") or __import__("callshield.utils", fromlist=["iso_now"]).iso_now(),
                        source=source,
                        number=number,
                        payload=payload.get("payload") or {},
                    )
                except Exception as exc:
                    return {"status": "error", "error": f"Invalid event: {exc}"}
                # Try enqueue
                ok = self.queue.put(ev, block=False)
                if not ok:
                    self.health.inc_dropped()
                    return {"status": "error", "error": "Queue full", "dropped": True}
                self.health.inc_received()
                # Also update queue metrics
                self.health.update_queue(self.queue.qsize(), peak=self.queue.metrics().get("peak"))
                return {"status": "ok", "event_id": ev.event_id}
            elif cmd == "stop":
                # Request graceful shutdown
                # Run in background to allow response
                def _delayed_shutdown():
                    time.sleep(0.2)
                    self.request_shutdown()
                threading.Thread(target=_delayed_shutdown, daemon=True).start()
                return {"status": "ok", "message": "Shutting down"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "error", "error": "Unhandled"}

    def request_shutdown(self) -> None:
        if not self._shutdown.is_set():
            self.logger.info("Shutdown requested")
            self._shutdown.set()

    def _do_graceful_shutdown(self) -> None:
        self.logger.info("Graceful shutdown started")
        self.health.set_state("STOPPING")
        # 1. Stop accepting new events
        self.queue.close()
        # 2. Finish current event - wait for queue to drain with timeout
        timeout = float(self.cfg.shutdown_timeout)
        start = time.time()
        while time.time() - start < timeout:
            if self.queue.empty():
                break
            time.sleep(0.1)
        # 3. Flush logs
        try:
            for h in self.logger.handlers:
                try:
                    h.flush()
                except Exception:
                    pass
        except Exception:
            pass
        # 4. Close DB - nothing to do (per-event connections)
        # 5. Stop heartbeat
        try:
            self.heartbeat.stop()
        except Exception:
            pass
        # 6. Stop IPC
        self._ipc_stop.set()
        if self._ipc_socket:
            try:
                self._ipc_socket.close()
            except Exception:
                pass
            try:
                # Wait for thread
                if self._ipc_thread and self._ipc_thread.is_alive():
                    self._ipc_thread.join(timeout=1.0)
            except Exception:
                pass
            try:
                sp = _socket_path(self.cfg)
                if sp.exists():
                    sp.unlink()
            except Exception:
                pass
        # 7. Remove PID file
        try:
            _clear_pid(self.cfg, expected_pid=os.getpid())
        except Exception:
            pass
        # Also clear socket if any
        try:
            _clear_socket(self.cfg)
        except Exception:
            pass
        self.health.set_state("STOPPED")
        self.logger.info("Daemon stopped")


def run_foreground(cfg: Optional[Config] = None) -> int:
    """Entry point for `python -m callshield _run-fg`."""
    if cfg is None:
        cfg = load_config()
    svc = DaemonService(cfg)
    return svc.start()
