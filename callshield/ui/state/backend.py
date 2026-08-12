"""The single door between the interface and CALLSHIELD.

Every value the interface shows and every action it performs goes through this
module, which delegates to the *existing* CLI handlers, service APIs, engines
and databases. There is no detection, scoring, policy, screening or persistence
logic here, and there is no second daemon: lifecycle commands call the same
``callshield start`` / ``callshield stop`` handlers a user would type.

Design rules enforced by this module:

* No network communication of any kind. The only transport is the daemon's
  existing local Unix socket, reached through ``cli._ipc_request``.
* No shell. Commands are dispatched by looking up the CLI handler function.
* Nothing raises: every call returns a :class:`Result`, so a missing daemon, a
  locked database or a malformed number degrades into a message on screen.
* Every query is bounded, so a large database cannot stall the interface.
"""

from __future__ import annotations

import contextlib
import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ... import cli as _cli
from ...config import Config
from ...detector import analyze_number, open_database
from ...doctor import run_doctor
from ...normalizer import normalize as _normalize
from ...policy import (
    DEFAULT_POLICIES,
    PolicyEngine,
    is_emergency_off,
)
from ...utils import InvalidNumberError, mask_number

# Query ceilings. The interface never asks for an unbounded result set.
MAX_EVENTS = 1000
MAX_SCREENING_EVENTS = 1000
MAX_BLOCKS = 200
MAX_LIST_ENTRIES = 500
MAX_REPORTS = 200
MAX_PROFILES = 200
MAX_HISTORY = 1000

POLICY_NAMES = ("RELAXED", "BALANCED", "STRICT")


def _bounded(value: Any, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, maximum))


class Result:
    """Outcome of one backend call.

    ``ok`` is simply "no error"; ``source`` records where the data came from
    (``"ipc"``, ``"database"``, ``"offline"``, ``"cli"`` …) so screens can say
    whether they are showing live or persisted values instead of pretending.
    """

    __slots__ = ("data", "error", "source")

    def __init__(self, data: Any = None, error: str = "", source: str = "") -> None:
        self.data = data
        self.error = str(error or "")
        self.source = str(source or "")

    @property
    def ok(self) -> bool:
        return not self.error

    def get(self, key: str, default: Any = None) -> Any:
        """Read one key from a mapping payload."""

        if isinstance(self.data, dict):
            return self.data.get(key, default)
        return default

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.ok

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "ok" if self.ok else "error={0!r}".format(self.error)
        return "Result({0}, source={1!r})".format(state, self.source)


def _error_text(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message[:200]


class Backend:
    """Read-only queries and delegated actions for the interface."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------- database
    @contextlib.contextmanager
    def _database(self):
        """Open the existing database briefly, then close it again."""

        database = open_database(self.cfg)
        try:
            yield database
        finally:
            try:
                database.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass

    def _query(self, function: Any, source: str = "database") -> Result:
        """Run ``function(database)`` and wrap the outcome."""

        try:
            with self._database() as database:
                return Result(function(database), source=source)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash
            return Result(error=_error_text(exc), source=source)

    # ------------------------------------------------------------------ cli
    def _run_cli(self, argv: Sequence[str]) -> Result:
        """Execute an existing CLI handler and capture its output.

        The command is dispatched through ``cli._COMMANDS`` — a dictionary of
        Python functions. No shell is involved and no string is interpreted.
        """

        try:
            parser = _cli.build_parser()
            args = parser.parse_args(list(argv))
        except SystemExit:
            return Result(error="Invalid command", source="cli")
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="cli")

        handler = _cli._COMMANDS.get(getattr(args, "command", None))
        if handler is None:
            return Result(error="Unknown command", source="cli")

        ui = _cli._make_ui(args, self.cfg)
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer), \
                    contextlib.redirect_stderr(buffer):
                code = handler(ui, args, self.cfg)
        except KeyboardInterrupt:
            return Result(error="Interrupted", source="cli")
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="cli")
        return Result(
            {"exit_code": int(code), "output": buffer.getvalue()},
            source="cli",
        )

    def run_cli_interactive(self, *argv: str) -> Result:
        """Run a CLI handler with the real terminal attached.

        Used for commands that own a safety prompt of their own — the ACTIVE
        protection confirmation in particular. The interface must never
        reimplement or bypass that prompt.
        """

        try:
            parser = _cli.build_parser()
            args = parser.parse_args(list(argv))
        except SystemExit:
            return Result(error="Invalid command", source="cli")
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="cli")

        handler = _cli._COMMANDS.get(getattr(args, "command", None))
        if handler is None:
            return Result(error="Unknown command", source="cli")
        ui = _cli._make_ui(args, self.cfg)
        try:
            code = handler(ui, args, self.cfg)
        except KeyboardInterrupt:
            return Result(error="Interrupted", source="cli")
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="cli")
        return Result({"exit_code": int(code), "output": ""}, source="cli")

    # --------------------------------------------------------------- daemon
    def daemon_state(self) -> Tuple[str, Optional[int]]:
        """``(RUNNING|STOPPED|STALE|UNKNOWN, pid)`` from the existing service."""

        try:
            state, pid = _cli.daemon_status(self.cfg)
            return str(state), pid
        except Exception:  # noqa: BLE001
            return "UNKNOWN", None

    def daemon_online(self) -> bool:
        state, _pid = self.daemon_state()
        return state == "RUNNING"

    def ipc(self, command: str, **payload: Any) -> Result:
        """One bounded request over the daemon's local Unix socket."""

        request: Dict[str, Any] = {"command": str(command)}
        request.update(payload)
        try:
            response = _cli._ipc_request(self.cfg, request)
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="ipc")
        if not response:
            return Result(error="Daemon IPC unavailable", source="ipc")
        if response.get("status") != "ok":
            return Result(
                error=str(response.get("error") or "Daemon returned an error")[:200],
                source="ipc",
            )
        data = response.get("data")
        if not isinstance(data, dict):
            data = {
                key: value for key, value in response.items()
                if key not in ("status", "data")
            }
        return Result(dict(data), source="ipc")

    def daemon_metrics(self) -> Result:
        """Live metrics when the daemon answers, persisted counters otherwise."""

        if self.daemon_online():
            live = self.ipc("metrics")
            if live.ok:
                return live

        merged: Dict[str, Any] = {}
        try:
            merged.update(_cli._saved_daemon_metrics(self.cfg))
        except Exception:  # noqa: BLE001
            pass
        events = self.event_metrics()
        if events.ok:
            data = events.data or {}
            merged.setdefault("received", data.get("total"))
            merged.setdefault("processed", data.get("total"))
            merged["high_risk_count"] = max(
                int(merged.get("high_risk_count") or 0),
                int(data.get("high_risk") or 0),
            )
            merged["blocked_recommendations"] = max(
                int(merged.get("blocked_recommendations") or 0),
                int(data.get("block_recommendations") or 0),
            )
        merged.setdefault("queue_size", 0)
        merged.setdefault("queue_max", getattr(self.cfg, "event_queue_size", 0))
        screening = self.screening_metrics()
        if screening.ok:
            for key in ("screened", "actually_rejected", "policy_errors",
                        "bridge_errors", "incoming_calls"):
                merged.setdefault(key, (screening.data or {}).get(key))
        return Result(merged, source="offline")

    def daemon_health(self) -> Result:
        if not self.daemon_online():
            return Result(error="Daemon is not running", source="offline")
        return self.ipc("health")

    def daemon_info(self) -> Result:
        if not self.daemon_online():
            return Result(error="Daemon is not running", source="offline")
        return self.ipc("daemon_info")

    def start_daemon(self) -> Result:
        """Start the existing daemon through the existing CLI handler."""

        return self._run_cli(["start"])

    def stop_daemon(self) -> Result:
        return self._run_cli(["stop"])

    # ------------------------------------------------------------ analysis
    def normalize(self, number: str) -> Result:
        try:
            parsed = _normalize(
                str(number), getattr(self.cfg, "default_country", None)
            )
        except InvalidNumberError as exc:
            return Result(error=_error_text(exc), source="engine")
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="engine")
        return Result(
            {
                "original": parsed.original,
                "normalized": parsed.normalized,
                "digits": parsed.digits,
                "country_code": parsed.country_code,
                "masked": mask_number(parsed.normalized),
            },
            source="engine",
        )

    def scan(self, number: str) -> Result:
        """Full analysis through the existing detection engine."""

        check = self.normalize(number)
        if not check.ok:
            return check
        target = (check.data or {}).get("normalized") or str(number)
        try:
            with self._database() as database:
                analysis = analyze_number(
                    target, db=database, cfg=self.cfg, record_event=True
                )
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="engine")
        return Result(analysis, source="engine")

    def reputation(self, number: str, persist: bool = False) -> Result:
        """Locally computed reputation profile. No external service exists."""

        from ...reputation import ReputationEngine

        try:
            with self._database() as database:
                analysis = analyze_number(
                    number, db=database, cfg=self.cfg, record_event=False
                )
                profile = ReputationEngine(database, self.cfg).calculate(
                    number, analysis=analysis, persist=bool(persist)
                )
                return Result(profile.to_public_dict(), source="engine")
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="engine")

    def reputation_history(self, number: str, limit: int = 100) -> Result:
        from ...reputation import ReputationStorage, number_fingerprint

        bounded = _bounded(limit, MAX_HISTORY, 100)

        def query(database: Any) -> Any:
            storage = ReputationStorage(database, self.cfg)
            return storage.history(number_fingerprint(str(number)), limit=bounded)

        return self._query(query)

    def recent_reputation_profiles(self, limit: int = 50) -> Result:
        from ...reputation import ReputationStorage

        bounded = _bounded(limit, MAX_PROFILES, 50)

        def query(database: Any) -> Any:
            return ReputationStorage(database, self.cfg).recent_profiles(
                limit=bounded
            )

        return self._query(query)

    def intelligence(self, number: str, include_history: bool = False) -> Result:
        """Phase 8 adaptive snapshot. The interface never recomputes it."""

        from ...adaptive import BehaviorEngine
        from ...reputation import ReputationEngine

        try:
            with self._database() as database:
                analysis = analyze_number(
                    number, db=database, cfg=self.cfg, record_event=False
                )
                profile = ReputationEngine(database, self.cfg).calculate(
                    number, analysis=analysis, persist=True
                )
                snapshot = BehaviorEngine(database, self.cfg).snapshot(
                    number,
                    reputation=profile,
                    detection=analysis,
                    persist=True,
                )
                return Result(
                    snapshot.to_public_dict(include_history=bool(include_history)),
                    source="engine",
                )
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="engine")

    def behavior_timeline(self, number: str, limit: int = 100) -> Result:
        from ...adaptive import BehaviorStorage
        from ...reputation import number_fingerprint

        bounded = _bounded(limit, MAX_HISTORY, 100)

        def query(database: Any) -> Any:
            storage = BehaviorStorage(database, self.cfg)
            observations = storage.timeline(
                number_fingerprint(str(number)), limit=bounded
            )
            return list(reversed(list(observations)))

        return self._query(query)

    def recent_intelligence_profiles(self, limit: int = 50) -> Result:
        from ...adaptive import BehaviorStorage

        bounded = _bounded(limit, MAX_PROFILES, 50)

        def query(database: Any) -> Any:
            return BehaviorStorage(database, self.cfg).recent_profiles(limit=bounded)

        return self._query(query)

    # -------------------------------------------------------------- events
    def recent_events(self, limit: int = 50) -> Result:
        bounded = _bounded(limit, MAX_EVENTS, 50)
        return self._query(lambda database: database.recent_events(bounded))

    def event_metrics(self) -> Result:
        threshold = int(getattr(self.cfg, "high_risk_threshold", 60) or 60)
        return self._query(lambda database: database.event_metrics(threshold))

    def number_history(self, number: str, limit: int = 50) -> Result:
        bounded = _bounded(limit, MAX_EVENTS, 50)
        return self._query(
            lambda database: database.get_events_for_number(str(number), bounded)
        )

    def number_history_count(self, number: str) -> Result:
        return self._query(
            lambda database: database.count_events_for_number(str(number))
        )

    # ----------------------------------------------------------- screening
    def screening_metrics(self) -> Result:
        return self._query(lambda database: database.screening_metrics())

    def recent_screening_events(self, limit: int = 50) -> Result:
        bounded = _bounded(limit, MAX_SCREENING_EVENTS, 50)
        return self._query(
            lambda database: database.recent_screening_events(bounded)
        )

    def recent_blocks(self, limit: int = 20) -> Result:
        bounded = _bounded(limit, MAX_BLOCKS, 20)
        return self._query(lambda database: database.recent_blocks(bounded))

    def inspect_block(self, decision_id: Any) -> Result:
        try:
            identifier = int(decision_id)
        except (TypeError, ValueError):
            return Result(error="Decision id must be a number", source="database")

        def query(database: Any) -> Any:
            record = database.inspect_block(identifier)
            if record is None:
                raise LookupError("No applied block with that id")
            return record

        return self._query(query)

    def screening_status(self) -> Result:
        """Configured screening state, plus the live daemon view when present."""

        snapshot = self.policy_snapshot()
        data: Dict[str, Any] = {
            "screening_enabled": snapshot.get("enabled"),
            "mode": snapshot.get("mode"),
            "policy": snapshot.get("current"),
            "emergency_off": snapshot.get("emergency_off"),
            "active_confirmed": snapshot.get("active_confirmed"),
            "android_verified": False,
        }
        live = self.ipc("screening_status") if self.daemon_online() else None
        if live is not None and live.ok:
            data.update(live.data or {})
            return Result(data, source="ipc")
        return Result(data, source="config")

    # ---------------------------------------------------------------- lists
    def list_numbers(self, list_type: str, limit: int = 200) -> Result:
        bounded = _bounded(limit, MAX_LIST_ENTRIES, 200)
        name = str(list_type or "").strip().lower()
        if name not in ("blacklist", "whitelist"):
            return Result(error="Unknown list", source="database")

        def query(database: Any) -> Any:
            rows = database.list_numbers(list_type=name)
            return list(rows)[:bounded]

        return self._query(query)

    def report_count(self, number: str) -> Result:
        return self._query(lambda database: database.count_reports(str(number)))

    def reports(self, number: str, limit: int = 50) -> Result:
        bounded = _bounded(limit, MAX_REPORTS, 50)
        if not number:
            return Result([], source="database")
        return self._query(
            lambda database: database.get_reports(str(number), limit=bounded)
        )

    # --------------------------------------------------------------- policy
    def policy_snapshot(self) -> Dict[str, Any]:
        """Current policy configuration. Reading it changes nothing."""

        cfg = self.cfg
        policies: Dict[str, Dict[str, Any]] = {}
        for name in POLICY_NAMES:
            defaults = DEFAULT_POLICIES[name]
            policies[name] = {
                "active_block": getattr(
                    cfg, name.lower() + "_active_block_threshold",
                    defaults.active_block,
                ),
                "confidence": getattr(
                    cfg, name.lower() + "_confidence_threshold",
                    defaults.confidence,
                ),
            }
        try:
            emergency = bool(is_emergency_off(cfg))
        except Exception:  # noqa: BLE001
            emergency = False
        return {
            "current": getattr(cfg, "screening_policy", "BALANCED"),
            "mode": getattr(cfg, "screening_mode", "DRY_RUN"),
            "enabled": bool(getattr(cfg, "screening_enabled", False)),
            "active_confirmed": bool(getattr(cfg, "active_mode_confirmed", False)),
            "emergency_off": emergency,
            "protection_mode": getattr(cfg, "protection_mode", "BALANCED"),
            "policies": policies,
        }

    def policy_simulate(
        self,
        risk: int,
        confidence: int,
        *,
        mode: Optional[str] = None,
        policy_name: Optional[str] = None,
        whitelisted: bool = False,
    ) -> Result:
        """Simulate one decision. Never writes configuration or state."""

        try:
            risk_value = max(0, min(100, int(risk)))
            confidence_value = max(0, min(100, int(confidence)))
        except (TypeError, ValueError):
            return Result(error="Risk and confidence must be numbers",
                          source="engine")

        selected_mode = str(
            mode if mode is not None
            else getattr(self.cfg, "screening_mode", "DRY_RUN")
        ).upper().replace("-", "_")
        selected_policy = str(
            policy_name if policy_name is not None
            else getattr(self.cfg, "screening_policy", "BALANCED")
        ).upper()

        detection = {
            "risk_score": risk_value,
            "confidence": confidence_value,
            "verdict": "HIGH_RISK" if risk_value >= 60 else "UNKNOWN",
            "reputation": "TRUSTED" if whitelisted else "UNKNOWN",
            "signals": [{"name": "whitelist_match"}] if whitelisted else [],
        }
        try:
            decision = PolicyEngine(self.cfg).decide(
                detection,
                mode=selected_mode,
                screening_enabled=bool(
                    getattr(self.cfg, "screening_enabled", False)
                ),
                active_confirmed=(selected_mode == "ACTIVE"),
                policy_name=selected_policy,
                emergency_off=None,
            )
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="engine")
        return Result(_SimulatedDecision(decision), source="engine")

    # --------------------------------------------------------------- actions
    def set_screening_policy(self, name: str) -> Result:
        policy = str(name or "").upper()
        if policy not in POLICY_NAMES:
            return Result(error="Policy must be RELAXED, BALANCED or STRICT",
                          source="cli")
        return self._run_cli(["screening", "policy", policy])

    def set_screening_enabled(self, enabled: bool) -> Result:
        """Enable (always DRY_RUN) or disable screening through the CLI."""

        return self._run_cli(["screening", "enable" if enabled else "disable"])

    def set_screening_mode(self, mode: str) -> Result:
        """Only the safe DRY_RUN transition is available without a terminal."""

        normalized = str(mode or "").lower().replace("_", "-")
        if normalized != "dry-run":
            return Result(
                error="ACTIVE mode requires the CLI confirmation prompt",
                source="cli",
            )
        return self._run_cli(["screening", "mode", "dry-run"])

    def screening_mode_active(self) -> Result:
        """Request ACTIVE mode. The CLI handler asks for confirmation itself."""

        return self.run_cli_interactive("screening", "mode", "active")

    def emergency_off(self) -> Result:
        return self._run_cli(["emergency-off"])

    def emergency_reset(self) -> Result:
        return self._run_cli(["emergency-reset"])

    def add_report(self, number: str, reason: str = "") -> Result:
        argv: List[str] = ["report", str(number)]
        text = str(reason or "").strip()
        if text:
            argv.extend(["--reason", text])
        return self._run_cli(argv)

    def list_action(self, action: str, number: str, reason: str = "") -> Result:
        name = str(action or "").strip().lower()
        if name not in ("block", "allow", "unblock", "unallow"):
            return Result(error="Unknown list action", source="cli")
        argv: List[str] = [name, str(number)]
        text = str(reason or "").strip()
        if text and name in ("block", "allow"):
            argv.extend(["--reason", text])
        return self._run_cli(argv)

    def set_trust(self, number: str, trusted: bool) -> Result:
        if trusted:
            return self._run_cli(["trust", str(number)])
        return self._run_cli(["untrust", str(number)])

    # ----------------------------------------------------------- diagnostics
    def doctor(self) -> Result:
        """Read-only diagnostics. The interface never requests repairs."""

        try:
            report = run_doctor(
                self.cfg, repair=False, ipc_request=_cli._ipc_request
            )
        except Exception as exc:  # noqa: BLE001
            return Result(error=_error_text(exc), source="doctor")
        return Result(report, source="doctor")


class _SimulatedDecision:
    """Read-only view of a :class:`PolicyDecision` for the simulator screen.

    Wrapping makes it structurally impossible for a simulated decision to be
    mistaken for an applied one: it carries a ``simulation`` flag and no code
    path can feed it back into the policy engine.
    """

    __slots__ = ("_decision",)

    simulation = True

    def __init__(self, decision: Any) -> None:
        self._decision = decision

    @property
    def action(self) -> Any:
        return getattr(self._decision, "applied_action", None)

    @property
    def policy(self) -> Any:
        return getattr(self._decision, "policy_name", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._decision, name)

    def to_dict(self) -> Dict[str, Any]:
        try:
            data = dict(self._decision.to_dict())
        except Exception:  # noqa: BLE001
            data = {}
        data["simulation"] = True
        return data

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "SimulatedDecision({0!r})".format(self._decision)


__all__ = ["Backend", "POLICY_NAMES", "Result"]
