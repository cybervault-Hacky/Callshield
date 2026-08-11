"""Persistent CALLSHIELD service through Phase 4.

Phase 5 reuses the hardened daemon and Unix IPC. It can return BLOCK only for
an explicitly confirmed ACTIVE policy decision; every uncertainty and error
still fails open to ALLOW.
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
from typing import Any, Dict, Optional, Set

from ..adaptive import BehaviorStorage
from ..config import Config, load_config
from ..database import Database
from ..events import EventQueue, EventProcessor
from ..events.models import Event
from ..events.types import EVENT_TYPE_INCOMING_CALL, SOURCE_ANDROID
from ..policy import is_emergency_off, thresholds_for_config
from ..security import ReplayCache, ReplayStatus
from ..utils import iso_now, mask_number, safe_write_text
from .health import HealthMonitor
from .heartbeat import Heartbeat
from .process import _clear_pid, _clear_socket, _socket_path, _write_pid
from .recovery import recover_runtime, validate_startup
from .signals import SignalHandler

MAX_IPC_REQUEST = 16 * 1024
MAX_IPC_RESPONSE = 64 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_KEYS = 128
MAX_JSON_ARRAY = 256
MAX_IPC_WORKERS = 10
_ALLOWED_IPC_COMMANDS = {
    "status",
    "metrics",
    "health",
    "daemon_info",
    "event",
    "screening_status",
    "screening_config",
    "screening_feedback",
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
    """Real persistent daemon process for CALLSHIELD through Phase 4."""

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
        self._ipc_client_slots = threading.BoundedSemaphore(MAX_IPC_WORKERS)
        self._ipc_clients = set()  # type: Set[threading.Thread]
        self._replay_cache = ReplayCache(
            lifetime_seconds=int(self.cfg.replay_window_seconds),
            max_entries=int(self.cfg.replay_cache_size),
        )
        self._ipc_clients_lock = threading.Lock()
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
                "replay_window_seconds",
                "replay_cache_size",
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
            # Screening requests may arrive concurrently. Keep handling
            # bounded to ten daemon threads so resource guarantees remain intact.
            if not self._ipc_client_slots.acquire(blocking=False):
                self._send_ipc_response(
                    connection,
                    {"status": "error", "error": "IPC busy"},
                )
                connection.close()
                continue
            worker = threading.Thread(
                target=self._run_ipc_client,
                args=(connection,),
                name="callshield-ipc-client",
                daemon=True,
            )
            with self._ipc_clients_lock:
                self._ipc_clients.add(worker)
            worker.start()

    def _run_ipc_client(self, connection: socket.socket) -> None:
        try:
            self._handle_ipc_conn(connection)
        finally:
            with self._ipc_clients_lock:
                self._ipc_clients.discard(threading.current_thread())
            self._ipc_client_slots.release()

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
            value = json.loads(
                text,
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_json_constant,
            )
            _validate_json_shape(value)
            return value
        except (json.JSONDecodeError, RecursionError) as exc:
            message = exc.msg if isinstance(exc, json.JSONDecodeError) else "too deeply nested"
            raise ValueError(f"Invalid JSON: {message}") from exc

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
        is_screening = (
            "command" not in request
            and request.get("source") == SOURCE_ANDROID
        )
        if request.get("protocol") != "callshield/1":
            return self._reject_ipc_policy(request, "INVALID_PROTOCOL", is_screening)
        replay_status = self._replay_cache.check_and_store(
            request.get("request_id"), request.get("timestamp")
        )
        if replay_status != ReplayStatus.ACCEPTED:
            return self._reject_ipc_policy(request, replay_status.value, is_screening)

        if is_screening:
            return self._handle_screening_request(request)
        if not isinstance(command, str) or not command:
            return {"status": "error", "error": "Invalid request: missing command"}
        if command not in _ALLOWED_IPC_COMMANDS:
            return {"status": "error", "error": f"Unknown command: {command}"}
        return self._handle_ipc_command(command, request)

    def _reject_ipc_policy(
        self, request: Dict[str, Any], detail: str, is_screening: bool
    ) -> Dict[str, Any]:
        if not is_screening:
            return {
                "status": "error",
                "error": "POLICY_ERROR",
                "detail": detail,
                "request_id": request.get("request_id"),
            }
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not _is_uuid(request_id):
            request_id = str(uuid.uuid4())
        response = self._screening_fallback(request_id, "POLICY_ERROR", 0)
        response["policy_error"] = True
        response["policy_error_detail"] = detail
        self.health.inc_incoming_call()
        self.health.inc_received()
        self.health.record_screening(
            verdict="UNKNOWN",
            recommended_action="ALLOW",
            applied_action="ALLOW",
            reason="POLICY_ERROR",
            policy_error=True,
        )
        self.health.inc_failed(error=detail)
        return response

    def _snapshot(self) -> Dict[str, Any]:
        self._sync_runtime_metrics()
        snapshot = self.health.snapshot()
        persisted = self._database_screening_metrics()
        metric_keys = {
            "incoming_calls": "incoming_calls",
            "screened": "screened",
            "screening_timeouts": "timeouts",
            "bridge_errors": "bridge_errors",
            "policy_errors": "policy_errors",
            "screening_high_risk": "high_risk",
            "screening_allowed": "screening_allowed",
            "screening_unknown": "screening_unknown",
            "screening_block_recommended": "screening_block_recommended",
            "screening_blocked": "screening_blocked",
            "actually_rejected": "actually_rejected",
        }
        for key, persisted_key in metric_keys.items():
            snapshot[key] = max(
                int(snapshot.get(key, 0)), int(persisted.get(persisted_key, 0))
            )
        snapshot["screening_mode"] = self.cfg.screening_mode
        snapshot["screening_enabled"] = bool(self.cfg.screening_enabled)
        snapshot["screening_policy"] = self.cfg.screening_policy
        snapshot["emergency_off"] = is_emergency_off(self.cfg)
        return snapshot

    def _database_screening_metrics(self) -> Dict[str, int]:
        database = None
        try:
            database = Database(self.cfg.database_path, timeout=0.2)
            return database.screening_metrics()
        except Exception:
            return {}
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception:
                    pass

    def _screening_request_seen(self, request_id: str) -> Optional[bool]:
        database = None
        try:
            database = Database(self.cfg.database_path, timeout=0.1)
            return database.screening_event_exists(request_id)
        except Exception:
            return None
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception:
                    pass

    def _handle_ipc_command(
        self, command: str, request: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            if command == "ping":
                return {"status": "ok", "pong": True}
            if command == "status":
                snapshot = self._snapshot()
                snapshot["ipc"] = "ENABLED"
                snapshot["call_screening"] = "DRY_RUN"
                snapshot["android_verified"] = False
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
            if command == "screening_status":
                metrics = self._database_screening_metrics()
                thresholds = thresholds_for_config(self.cfg)
                emergency = is_emergency_off(self.cfg)
                auto_reject = (
                    self.cfg.screening_enabled
                    and self.cfg.screening_mode == "ACTIVE"
                    and self.cfg.active_mode_confirmed
                    and not emergency
                )
                return {
                    "status": "ok",
                    "data": {
                        "bridge": "CONNECTED",
                        "daemon": "RUNNING",
                        "android": "NOT VERIFIED",
                        "mode": self.cfg.screening_mode,
                        "policy": self.cfg.screening_policy,
                        "active_threshold": thresholds.active_block,
                        "confidence_threshold": thresholds.confidence,
                        "timeout_ms": int(self.cfg.screening_timeout_ms),
                        "live_screening": (
                            "IPC READY" if self.cfg.screening_enabled else "DISABLED"
                        ),
                        "auto_reject": "ENABLED" if auto_reject else "DISABLED",
                        "actually_rejected": int(metrics.get("actually_rejected", 0)),
                        "applied_blocks": int(metrics.get("screening_blocked", 0)),
                        "block_recommendations": int(
                            metrics.get("screening_block_recommended", 0)
                        ),
                        "emergency_off": emergency,
                        "screening_enabled": bool(self.cfg.screening_enabled),
                        "screened": int(metrics.get("screened", 0)),
                    },
                }
            if command == "screening_config":
                self._reload_config()
                return {
                    "status": "ok",
                    "screening_enabled": bool(self.cfg.screening_enabled),
                    "mode": self.cfg.screening_mode,
                    "policy": self.cfg.screening_policy,
                    "emergency_off": is_emergency_off(self.cfg),
                }
            if command == "screening_feedback":
                screening_request_id = request.get("screening_request_id")
                if (
                    request.get("source") != SOURCE_ANDROID
                    or request.get("result") != "REJECTED"
                    or not isinstance(screening_request_id, str)
                    or not _is_uuid(screening_request_id)
                ):
                    return {"status": "error", "error": "Invalid screening feedback"}
                database = Database(self.cfg.database_path, timeout=0.2)
                try:
                    confirmed = database.confirm_screening_rejection(
                        screening_request_id, iso_now()
                    )
                    if confirmed:
                        BehaviorStorage(database, self.cfg).confirm(
                            screening_request_id
                        )
                finally:
                    database.close()
                if confirmed:
                    self.health.confirm_actual_rejection()
                return {"status": "ok", "confirmed": confirmed}
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

    def _handle_screening_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process the exact callshield/1 Android request and always apply ALLOW."""

        started = time.monotonic()
        self.health.inc_incoming_call()
        self.health.inc_received()

        raw_request_id = request.get("request_id")
        request_id = (
            raw_request_id
            if isinstance(raw_request_id, str) and _is_uuid(raw_request_id)
            else str(uuid.uuid4())
        )
        number = request.get("number")
        stored_number = str(number) if isinstance(number, str) else ""

        unknown_fields = sorted(
            set(request)
            - {"protocol", "request_id", "timestamp", "number", "source"}
        )
        if unknown_fields:
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "INVALID_REQUEST", _elapsed_ms(started)
                ),
                stored_number,
                failed=True,
                bridge_error=True,
            )
        if request.get("protocol") != "callshield/1":
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "INVALID_PROTOCOL", _elapsed_ms(started)
                ),
                stored_number,
                failed=True,
                bridge_error=True,
            )
        if not isinstance(raw_request_id, str) or not _is_uuid(raw_request_id):
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "INVALID_REQUEST_ID", _elapsed_ms(started)
                ),
                stored_number,
                failed=True,
                bridge_error=True,
            )
        if request.get("source") != SOURCE_ANDROID:
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "INVALID_SOURCE", _elapsed_ms(started)
                ),
                stored_number,
                failed=True,
                bridge_error=True,
            )
        if not isinstance(number, str) or not number.strip() or len(number) > 128:
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "INVALID_NUMBER", _elapsed_ms(started)
                ),
                stored_number,
                failed=True,
            )
        persisted_replay = self._screening_request_seen(request_id)
        if persisted_replay is True:
            return self._reject_ipc_policy(
                request, "DUPLICATE_PERSISTED_REQUEST", True
            )
        if persisted_replay is None:
            return self._reject_ipc_policy(
                request, "DATABASE_REPLAY_CHECK_FAILED", True
            )
        if not self.cfg.screening_enabled:
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "SCREENING_DISABLED", _elapsed_ms(started)
                ),
                number,
            )

        event = Event(
            event_id=request_id,
            event_type=EVENT_TYPE_INCOMING_CALL,
            timestamp=iso_now(),
            source=SOURCE_ANDROID,
            number=number,
            payload={"protocol": "callshield/1"},
        )
        result_holder = {}  # type: Dict[str, Any]
        error_holder = {}  # type: Dict[str, BaseException]
        completed = threading.Event()

        def analyze() -> None:
            try:
                result_holder["result"] = self.processor.process(event)
            except BaseException as exc:
                error_holder["error"] = exc
            finally:
                completed.set()

        worker = threading.Thread(
            target=analyze,
            name="callshield-screening-analysis",
            daemon=True,
        )
        worker.start()
        # Reserve a small portion of the configured budget for response
        # serialization and best-effort audit persistence.
        timeout_seconds = max(
            0.05, (int(self.cfg.screening_timeout_ms) - 100) / 1000.0
        )
        if not completed.wait(timeout_seconds):
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "SCREENING_TIMEOUT", _elapsed_ms(started)
                ),
                number,
                failed=True,
            )
        if error_holder:
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "INTERNAL_ERROR", _elapsed_ms(started)
                ),
                number,
                failed=True,
                bridge_error=True,
            )

        processed = result_holder.get("result")
        if not isinstance(processed, dict):
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, "ANALYSIS_ERROR", _elapsed_ms(started)
                ),
                number,
                failed=True,
                bridge_error=True,
            )
        detection = processed.get("detection") or {}
        screening = processed.get("screening") or {}
        if processed.get("status") != "processed":
            reason = str(detection.get("reason") or "ANALYSIS_ERROR")
            return self._finalize_screening(
                self._screening_fallback(
                    request_id, reason, _elapsed_ms(started)
                ),
                number,
                failed=True,
                bridge_error=True,
            )

        policy = processed.get("policy") or screening
        reputation_profile = processed.get("reputation_profile") or {}
        intelligence = processed.get("intelligence") or {}
        recommendation = str(policy.get("recommended_action") or "ALLOW")
        if recommendation not in ("ALLOW", "BLOCK"):
            recommendation = "ALLOW"
        applied = str(policy.get("applied_action") or "ALLOW")
        mode = str(policy.get("mode") or "DRY_RUN")
        verdict = str(detection.get("verdict") or "UNKNOWN")
        if verdict not in ("SAFE", "UNKNOWN", "SUSPICIOUS", "HIGH_RISK", "MALICIOUS"):
            verdict = "UNKNOWN"
        reason = str(policy.get("reason") or "POLICY_ERROR")[:500]
        response = {
            "protocol": "callshield/1",
            "request_id": request_id,
            "risk_score": max(0, min(100, int(detection.get("risk_score", 0)))),
            "confidence": max(0, min(100, int(detection.get("confidence", 0)))),
            "verdict": verdict,
            "recommended_action": recommendation,
            "applied_action": applied,
            "mode": mode,
            "reason": reason,
            "latency_ms": _elapsed_ms(started),
            "policy_name": str(policy.get("policy_name") or "BALANCED"),
            "threshold": int(policy.get("threshold", 100)),
            "confidence_threshold": int(
                policy.get("confidence_threshold", 100)
            ),
            "emergency_off": bool(policy.get("emergency_off", False)),
            "policy_error": bool(policy.get("policy_error", False)),
            "reputation_score": int(reputation_profile.get("score", 0)),
            "reputation_confidence": int(
                reputation_profile.get("confidence", 0)
            ),
            "reputation_trend": str(
                reputation_profile.get("trend", "UNKNOWN")
            ),
            "reputation_reasons": list(
                reputation_profile.get("reasons", [])[:20]
            ),
            "intelligence_trend": str(
                intelligence.get("behavioral_trend", "INSUFFICIENT_DATA")
            ),
            "intelligence_patterns": [
                str(item.get("pattern_id"))
                for item in intelligence.get("patterns", [])[:20]
                if isinstance(item, dict) and item.get("pattern_id")
            ],
            "risk_delta": int(intelligence.get("risk_delta", 0)),
            "confidence_delta": int(intelligence.get("confidence_delta", 0)),
        }
        normalized_number = str(detection.get("number") or number)
        return self._finalize_screening(response, normalized_number)

    @staticmethod
    def _screening_fallback(
        request_id: str, reason: str, latency_ms: int
    ) -> Dict[str, Any]:
        return {
            "protocol": "callshield/1",
            "request_id": request_id,
            "risk_score": 0,
            "confidence": 0,
            "verdict": "UNKNOWN",
            "recommended_action": "ALLOW",
            "applied_action": "ALLOW",
            "mode": "DRY_RUN",
            "reason": str(reason)[:500],
            "latency_ms": max(0, int(latency_ms)),
            "policy_name": "BALANCED",
            "threshold": 100,
            "confidence_threshold": 100,
            "emergency_off": True,
            "policy_error": False,
        }

    def _finalize_screening(
        self,
        response: Dict[str, Any],
        number: str,
        *,
        failed: bool = False,
        bridge_error: bool = False,
    ) -> Dict[str, Any]:
        # Revalidate active application at the final response boundary. Any
        # mismatch or emergency state fails open even if an upstream object
        # accidentally requested BLOCK.
        applied = str(response.get("applied_action", "ALLOW"))
        mode = str(response.get("mode", "DRY_RUN"))
        recommendation = str(response.get("recommended_action", "ALLOW"))
        emergency = is_emergency_off(self.cfg)
        active_is_valid = (
            applied == "BLOCK"
            and recommendation == "BLOCK"
            and mode == "ACTIVE"
            and self.cfg.screening_enabled
            and self.cfg.screening_mode == "ACTIVE"
            and self.cfg.active_mode_confirmed
            and not emergency
        )
        if applied == "BLOCK" and not active_is_valid:
            response["applied_action"] = "ALLOW"
            response["reason"] = "SAFETY_FALLBACK"
            response["policy_error"] = True
        elif applied not in ("ALLOW", "BLOCK") or mode not in ("DRY_RUN", "ACTIVE"):
            response["applied_action"] = "ALLOW"
            response["mode"] = "DRY_RUN"
            response["reason"] = "INVALID_POLICY_DECISION"
            response["policy_error"] = True
        response["emergency_off"] = emergency
        persisted = self._persist_screening_result(number, response)
        if not persisted:
            bridge_error = True
        self.health.record_screening(
            verdict=str(response.get("verdict", "UNKNOWN")),
            recommended_action=str(response.get("recommended_action", "ALLOW")),
            applied_action=str(response.get("applied_action", "ALLOW")),
            reason=str(response.get("reason", "UNKNOWN")),
            bridge_error=bridge_error,
            policy_error=bool(response.get("policy_error", False)),
        )
        if failed:
            self.health.inc_failed(error=str(response.get("reason", "SCREENING_ERROR")))
        else:
            self.health.inc_processed(
                verdict=str(response.get("verdict", "UNKNOWN")),
                action=str(response.get("recommended_action", "ALLOW")),
            )
        try:
            self.logger.info(
                "screening request=%s number=%s verdict=%s recommended=%s applied=%s mode=%s policy=%s reason=%s latency=%sms",
                response.get("request_id"),
                mask_number(number),
                response.get("verdict"),
                response.get("recommended_action"),
                response.get("applied_action"),
                response.get("mode"),
                response.get("policy_name"),
                response.get("reason"),
                response.get("latency_ms"),
            )
        except Exception:
            pass
        return response

    def _persist_screening_result(
        self, number: str, response: Dict[str, Any]
    ) -> bool:
        database = None
        try:
            # Persistence must never extend an Android call indefinitely. A
            # contended database is treated as a bridge error and the ALLOW
            # response is still returned.
            database = Database(self.cfg.database_path, timeout=0.05)
            database.add_screening_event(
                timestamp=iso_now(),
                number=number,
                risk_score=int(response.get("risk_score", 0)),
                confidence=int(response.get("confidence", 0)),
                verdict=str(response.get("verdict", "UNKNOWN")),
                recommended_action=str(
                    response.get("recommended_action", "ALLOW")
                ),
                applied_action=str(response.get("applied_action", "ALLOW")),
                reason=str(response.get("reason", "UNKNOWN")),
                latency_ms=int(response.get("latency_ms", 0)),
                source=SOURCE_ANDROID,
                event_id=str(response.get("request_id", "")),
                mode=str(response.get("mode", "DRY_RUN")),
                policy_action=str(response.get("recommended_action", "ALLOW")),
                policy_name=str(response.get("policy_name", "BALANCED")),
                threshold=int(response.get("threshold", 100)),
                confidence_threshold=int(
                    response.get("confidence_threshold", 100)
                ),
                policy_reason=str(response.get("reason", "UNKNOWN")),
                emergency_off=bool(response.get("emergency_off", False)),
                reputation_score=(
                    int(response["reputation_score"])
                    if "reputation_score" in response
                    else None
                ),
                reputation_confidence=(
                    int(response["reputation_confidence"])
                    if "reputation_confidence" in response
                    else None
                ),
                reputation_trend=response.get("reputation_trend"),
                reputation_reasons=response.get("reputation_reasons", []),
            )
            return True
        except Exception as exc:
            try:
                self.logger.error(
                    "Unable to persist screening result for %s: %s",
                    mask_number(number),
                    exc,
                )
            except Exception:
                pass
            return False
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception:
                    pass

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

        ipc_deadline = time.monotonic() + float(self.cfg.shutdown_timeout)
        with self._ipc_clients_lock:
            ipc_clients = list(self._ipc_clients)
        for client in ipc_clients:
            if client is threading.current_thread():
                continue
            remaining = ipc_deadline - time.monotonic()
            if remaining <= 0:
                break
            client.join(timeout=remaining)

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


def _strict_json_object(pairs: Any) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    if len(pairs) > MAX_JSON_KEYS:
        raise ValueError("JSON object has too many keys")
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError("JSON object contains a duplicate or invalid key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _validate_json_shape(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    if isinstance(value, dict):
        if len(value) > MAX_JSON_KEYS:
            raise ValueError("JSON object has too many keys")
        for key, item in value.items():
            if len(key) > 128:
                raise ValueError("JSON key is too long")
            _validate_json_shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_JSON_ARRAY:
            raise ValueError("JSON array is too large")
        for item in value:
            _validate_json_shape(item, depth + 1)
    elif isinstance(value, str) and len(value.encode("utf-8")) > MAX_IPC_REQUEST:
        raise ValueError("JSON string is too large")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Unsupported JSON value")


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def run_foreground(cfg: Optional[Config] = None) -> int:
    """Entry point for ``python -m callshield _run-fg``."""

    service = DaemonService(cfg or load_config())
    return service.start()
