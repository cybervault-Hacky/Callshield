"""Persistent CALLSHIELD Phase 3 background service.

The service composes the bounded event queue, Phase 2 detector pipeline,
heartbeat, health monitor, safe signals/recovery, and owner-only Unix IPC.
It intentionally has no phone-call interception or active blocking behavior.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Config, load_config
from ..events import EventQueue, EventProcessor
from ..events.models import Event
from ..utils import iso_now, safe_write_text
from .health import HealthMonitor
from .heartbeat import Heartbeat
from .process import _clear_pid, _clear_socket, _socket_path, _write_pid
from .recovery import recover_runtime, validate_startup
from .signals import SignalHandler

MAX_IPC_REQUEST = 16 * 1024
MAX_IPC_RESPONSE = 64 * 1024
_ALLOWED_IPC_COMMANDS = {
    "status",
    "metrics",
    "health",
    "daemon_info",
    "event",
    "stop",
    "ping",
}


def _get_daemon_logger(cfg: Config) -> logging.Logger:
    """Create a private size-rotated daemon logger."""

    logger = logging.getLogger("callshield.daemon")
    logger.setLevel(logging.INFO)
    requested_path = str(Path(cfg.daemon_log_file).expanduser())
    configured_path = getattr(logger, "_callshield_path", None)
    if configured_path == requested_path and logger.handlers:
        return logger

    for existing in list(logger.handlers):
        try:
            existing.close()
        except Exception:
            pass
        logger.removeHandler(existing)
    try:
        log_path = Path(requested_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_path.parent.chmod(0o700)
        except OSError:
            pass
        handler = RotatingFileHandler(
            str(log_path),
            maxBytes=int(cfg.max_log_size),
            backupCount=int(cfg.max_log_files),
            encoding="utf-8",
        )
        try:
            log_path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    logger._callshield_path = requested_path  # type: ignore[attr-defined]
    return logger


class DaemonService:
    """Real persistent daemon process for CALLSHIELD Phase 3."""

    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.cfg = validate_startup(cfg or load_config())
        self.queue = EventQueue(maxsize=int(self.cfg.event_queue_size))
        self.health = HealthMonitor(self.cfg)
        self.heartbeat = Heartbeat(
            self.cfg,
            on_beat=lambda timestamp: self.health.set_heartbeat(timestamp),
        )
        self.logger = _get_daemon_logger(self.cfg)
        self.processor = EventProcessor(self.cfg, logger=self.logger)
        self._shutdown = threading.Event()
        self._ipc_stop = threading.Event()
        self._ipc_thread = None  # type: Optional[threading.Thread]
        self._processor_thread = None  # type: Optional[threading.Thread]
        self._ipc_socket = None  # type: Optional[socket.socket]
        self._signal_handler = None  # type: Optional[SignalHandler]
        self._cleanup_lock = threading.Lock()
        self._cleanup_complete = False
        self._pid_claimed = False

    def start(self) -> int:
        """Claim runtime state, start workers, and remain alive until shutdown."""

        recover_runtime(self.cfg)
        pid = _write_pid(self.cfg)
        self._pid_claimed = True
        self.health.pid = pid
        self.logger.info(
            "Daemon starting pid=%s queue=%s heartbeat=%ss",
            pid,
            self.cfg.event_queue_size,
            self.cfg.heartbeat_interval,
        )
        try:
            self._install_signals()
            self.health.check_db()
            self.heartbeat.start()
            if self.cfg.ipc_enabled:
                self._start_ipc()
            self._processor_thread = threading.Thread(
                target=self._processor_loop,
                name="callshield-processor",
                daemon=True,
            )
            self._processor_thread.start()
            self.health.set_state("RUNNING")

            while not self._shutdown.wait(timeout=1.0):
                try:
                    self.health.check_db()
                    self._sync_runtime_metrics()
                except Exception:
                    # Health collection must never terminate the daemon.
                    pass
        except BaseException:
            self.logger.exception("Daemon startup/runtime failure")
            raise
        finally:
            self._do_graceful_shutdown()
        return 0

    def _install_signals(self) -> None:
        self._signal_handler = SignalHandler(
            self.cfg,
            shutdown_cb=self.request_shutdown,
            reload_cb=self._reload_config,
        )
        self._signal_handler.install()

    def _reload_config(self) -> None:
        """Apply safe SIGHUP changes without moving live runtime endpoints."""

        try:
            new_cfg = load_config()
            immutable = (
                "pid_file",
                "socket_path",
                "run_dir",
                "database_path",
                "event_queue_size",
                "ipc_enabled",
                "daemon_log_file",
                "max_log_size",
                "max_log_files",
            )
            ignored = []
            for name in immutable:
                old_value = getattr(self.cfg, name)
                if getattr(new_cfg, name) != old_value:
                    ignored.append(name)
                    setattr(new_cfg, name, old_value)
            self.cfg = new_cfg
            self.processor.cfg = new_cfg
            self.processor.db_path = new_cfg.database_path
            self.health.update_config(new_cfg)
            self.heartbeat.cfg = new_cfg
            self.heartbeat.update_interval(float(new_cfg.heartbeat_interval))
            if self._signal_handler:
                self._signal_handler.cfg = new_cfg
            if ignored:
                self.logger.warning(
                    "SIGHUP ignored restart-required settings: %s",
                    ", ".join(ignored),
                )
            self.logger.info("Configuration reloaded safely via SIGHUP")
        except Exception as exc:
            self.logger.error("Configuration reload rejected: %s", exc)

    def _processor_loop(self) -> None:
        """Process all accepted events, including queued work during shutdown."""

        while True:
            event = None
            try:
                event = self.queue.dequeue(block=True, timeout=0.25)
                if event is None:
                    if self._shutdown.is_set() and self.queue.empty():
                        break
                    continue
                result = self.processor.process(event)
                if result.get("status") == "processed":
                    detection = result.get("detection") or {}
                    self.health.inc_processed(
                        verdict=detection.get("verdict"),
                        action=detection.get("recommended_action")
                        or detection.get("action"),
                    )
                else:
                    self.health.inc_failed(error=result.get("error"))
            except Exception as exc:
                event_id = getattr(event, "event_id", "unknown")
                try:
                    self.logger.exception(
                        "Processor exception for event %s: %s", event_id, exc
                    )
                except Exception:
                    pass
                self.health.inc_failed(error=str(exc))
            finally:
                if event is not None:
                    try:
                        self.queue.task_done()
                    except Exception:
                        pass
                try:
                    self._sync_runtime_metrics()
                except Exception:
                    pass

    def _sync_runtime_metrics(self) -> None:
        metrics = self.queue.metrics()
        self.health.update_queue(
            int(metrics.get("size", 0)), peak=int(metrics.get("peak", 0))
        )
        last_beat = self.heartbeat.last_beat
        if last_beat:
            self.health.set_heartbeat(last_beat)

    # ------------------------------------------------------------------ IPC

    def _start_ipc(self) -> None:
        endpoint = _socket_path(self.cfg)
        if endpoint.exists() or endpoint.is_symlink():
            # recover_runtime has already proved it stale and removed it. An
            # endpoint appearing now belongs to a competing startup.
            raise RuntimeError(f"Unix socket path became occupied: {endpoint}")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(endpoint))
            os.chmod(endpoint, 0o600)
            listener.listen(8)
            listener.settimeout(0.5)
        except Exception:
            listener.close()
            _clear_socket(self.cfg)
            raise
        self._ipc_socket = listener
        self._ipc_stop.clear()
        self._ipc_thread = threading.Thread(
            target=self._ipc_loop, name="callshield-ipc", daemon=True
        )
        self._ipc_thread.start()
        self.logger.info("IPC listening on owner-only Unix socket %s", endpoint)

    def _ipc_loop(self) -> None:
        listener = self._ipc_socket
        if listener is None:
            return
        while not self._ipc_stop.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            # Handle serially to keep local connection resource usage bounded.
            self._handle_ipc_conn(connection)

    def _handle_ipc_conn(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(float(self.cfg.ipc_timeout))
            try:
                request = self._read_ipc_request(connection)
                response = self._validate_and_dispatch(request)
            except socket.timeout:
                response = {"status": "error", "error": "Request timeout"}
            except (UnicodeError, ValueError) as exc:
                response = {"status": "error", "error": str(exc)}
            except Exception as exc:
                self.logger.error("IPC request failed safely: %s", exc)
                response = {"status": "error", "error": "Request handling failed"}
            self._send_ipc_response(connection, response)

    @staticmethod
    def _read_ipc_request(connection: socket.socket) -> Any:
        data = b""
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_IPC_REQUEST:
                raise ValueError(
                    f"Request too large (maximum {MAX_IPC_REQUEST} bytes)"
                )
            if b"\n" in data:
                first, remainder = data.split(b"\n", 1)
                if remainder.strip():
                    raise ValueError("Only one JSON request is allowed per connection")
                data = first
                break
        if not data:
            raise ValueError("Empty request")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("Request must be valid UTF-8") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc.msg}") from exc

    @staticmethod
    def _send_ipc_response(connection: socket.socket, response: Dict[str, Any]) -> None:
        try:
            encoded = (json.dumps(response, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            if len(encoded) > MAX_IPC_RESPONSE:
                encoded = b'{"status":"error","error":"Response too large"}\n'
            connection.sendall(encoded)
        except (OSError, TypeError, ValueError):
            pass

    def _validate_and_dispatch(self, request: Any) -> Dict[str, Any]:
        if not isinstance(request, dict):
            return {"status": "error", "error": "Request must be a JSON object"}
        command = request.get("command")
        if not isinstance(command, str) or not command:
            return {"status": "error", "error": "Invalid request: missing command"}
        if command not in _ALLOWED_IPC_COMMANDS:
            return {"status": "error", "error": f"Unknown command: {command}"}
        return self._handle_ipc_command(command, request)

    def _snapshot(self) -> Dict[str, Any]:
        self._sync_runtime_metrics()
        return self.health.snapshot()

    def _handle_ipc_command(
        self, command: str, request: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            if command == "ping":
                return {"status": "ok", "pong": True}
            if command == "status":
                snapshot = self._snapshot()
                snapshot["ipc"] = "ENABLED"
                snapshot["call_screening"] = "NOT CONNECTED"
                return {"status": "ok", "data": snapshot}
            if command == "metrics":
                return {"status": "ok", "data": self._snapshot()}
            if command == "health":
                snapshot = self._snapshot()
                return {
                    "status": "ok",
                    "data": snapshot,
                    "healthy": self.health.is_healthy(),
                }
            if command == "daemon_info":
                snapshot = self._snapshot()
                return {
                    "status": "ok",
                    "data": {
                        "pid": snapshot.get("pid"),
                        "uptime": snapshot.get("uptime_human"),
                        "state": snapshot.get("state"),
                        "queue": (
                            f"{snapshot.get('queue_size', 0)} / "
                            f"{snapshot.get('queue_max', self.queue.maxsize)}"
                        ),
                        "engine": (
                            "ONLINE"
                            if snapshot.get("db_status") == "ONLINE"
                            else "ERROR"
                        ),
                        "database": snapshot.get("db_status"),
                    },
                }
            if command == "event":
                return self._accept_event(request)
            if command == "stop":
                threading.Thread(
                    target=self._delayed_shutdown,
                    name="callshield-ipc-stop",
                    daemon=True,
                ).start()
                return {"status": "ok", "message": "Shutting down"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "error", "error": "Unhandled command"}

    def _accept_event(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raw = request.get("event", request.get("data"))
        if not isinstance(raw, dict):
            return {"status": "error", "error": "event must be a JSON object"}
        allowed_fields = {
            "event_id",
            "event_type",
            "timestamp",
            "source",
            "number",
            "payload",
        }
        unknown = sorted(set(raw) - allowed_fields)
        if unknown:
            return {
                "status": "error",
                "error": f"Unknown event field(s): {', '.join(unknown)}",
            }
        if "event_type" not in raw:
            return {"status": "error", "error": "event_type is required"}
        event_data = dict(raw)
        event_data.setdefault("event_id", str(uuid.uuid4()))
        event_data.setdefault("timestamp", iso_now())
        event_data.setdefault("source", "CLI")
        event_data.setdefault("payload", {})
        try:
            event = Event.from_dict(
                event_data, payload_limit=int(self.cfg.event_payload_limit)
            )
        except (TypeError, ValueError) as exc:
            return {"status": "error", "error": f"Invalid event: {exc}"}

        self.health.inc_received()
        accepted = self.queue.enqueue(event, block=False)
        if not accepted:
            self.health.inc_dropped()
            self._sync_runtime_metrics()
            reason = "Daemon is shutting down" if self.queue.is_closed() else "Queue full"
            return {
                "status": "error",
                "error": reason,
                "dropped": True,
            }
        self._sync_runtime_metrics()
        return {"status": "ok", "event_id": event.event_id}

    def _delayed_shutdown(self) -> None:
        time.sleep(0.1)
        self.request_shutdown()

    # -------------------------------------------------------------- shutdown

    def request_shutdown(self) -> None:
        """Stop accepting work and wake the main loop; safe to call repeatedly."""

        if self._shutdown.is_set():
            return
        try:
            self.logger.info("Shutdown requested")
        except Exception:
            pass
        self.queue.close()
        self._stop_ipc_accepting()
        self._shutdown.set()

    def _stop_ipc_accepting(self) -> None:
        self._ipc_stop.set()
        listener = self._ipc_socket
        self._ipc_socket = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

    def _do_graceful_shutdown(self) -> None:
        with self._cleanup_lock:
            if self._cleanup_complete:
                return
            self._cleanup_complete = True
        self.health.set_state("STOPPING")
        self.queue.close()
        self._stop_ipc_accepting()
        self._shutdown.set()

        if (
            self._ipc_thread
            and self._ipc_thread.is_alive()
            and self._ipc_thread is not threading.current_thread()
        ):
            self._ipc_thread.join(timeout=1.0)

        # The worker loop deliberately continues until every accepted queue
        # task has completed. Use a finite configured timeout for crash safety.
        drained = self.queue.wait_until_done(float(self.cfg.shutdown_timeout))
        if self._processor_thread and self._processor_thread.is_alive():
            self._processor_thread.join(timeout=0.5)
        if not drained:
            self.logger.error(
                "Shutdown timeout with %s queued event(s) still pending",
                self.queue.qsize(),
            )

        try:
            self.heartbeat.stop()
        except Exception:
            pass
        self._sync_runtime_metrics()
        self.health.set_state("STOPPED")
        self._persist_metrics()
        try:
            for handler in self.logger.handlers:
                handler.flush()
        except Exception:
            pass

        _clear_socket(self.cfg)
        if self._pid_claimed:
            _clear_pid(self.cfg, expected_pid=os.getpid())
        self.logger.info("Daemon stopped")

    def _persist_metrics(self) -> None:
        """Persist a bounded last-session snapshot for stopped-daemon metrics."""

        try:
            state_dir = Path(self.cfg.run_dir).expanduser().parent / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            try:
                state_dir.chmod(0o700)
            except OSError:
                pass
            snapshot = self.health.snapshot()
            snapshot["saved_at"] = iso_now()
            safe_write_text(
                state_dir / "daemon_metrics.json",
                json.dumps(snapshot, sort_keys=True) + "\n",
            )
        except Exception:
            pass


def run_foreground(cfg: Optional[Config] = None) -> int:
    """Entry point for ``python -m callshield _run-fg``."""

    service = DaemonService(cfg or load_config())
    return service.start()
