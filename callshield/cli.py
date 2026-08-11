"""CALLSHIELD command-line interface.

Commands are parsed with argparse (standard library) so we stay
dependency-free. The CLI is kept thin — all business logic lives in
dedicated modules so future phases (e.g. an Android call-screening
service) can reuse the engine directly.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .config import (
    Config,
    load_config,
    save_config,
    set_mode,
    set_profile,
    set_value,
)
from .database import Database
from .daemon import (
    DaemonError,
    run_foreground,
    start as daemon_start,
    status as daemon_status,
    stop as daemon_stop,
)
from .detector import AnalysisResult, analyze_number, open_database
from .intelligence import analyze_behavior, number_intelligence
from .intelligence.profiles import PROFILES, get_profile
from .logger import log_error, log_info
from .normalizer import normalize
from .utils import (
    EXIT_DAEMON,
    EXIT_DATABASE,
    EXIT_GENERAL,
    EXIT_INVALID_NUMBER,
    EXIT_OK,
    EXIT_USAGE,
    CallShieldError,
    InvalidNumberError,
    iso_now,
    mask_number,
    supports_color,
)


# --------------------------------------------------------------------- constants

_BANNER = "CALLSHIELD"
_TAGLINE = "Fraud Protection Engine"
_PHASE = "Phase 3 — Background Engine"
_PHASE_COMPAT = "Phase 1 — Foundation"


class _UI:
    """Very small helper for terminal styling."""

    def __init__(self, use_color: bool) -> None:
        self.use_color = use_color
        self.bold = "\033[1m" if use_color else ""
        self.dim = "\033[2m" if use_color else ""
        self.red = "\033[31m" if use_color else ""
        self.yellow = "\033[33m" if use_color else ""
        self.green = "\033[32m" if use_color else ""
        self.cyan = "\033[36m" if use_color else ""
        self.magenta = "\033[35m" if use_color else ""
        self.reset = "\033[0m" if use_color else ""

    def rule(self, width: int = 40, ch: str = "─") -> str:
        return ch * width


def _make_ui(args: argparse.Namespace, cfg: Config) -> _UI:
    if getattr(args, "no_color", False):
        return _UI(False)
    mode = (getattr(args, "color", None) or cfg.color_enabled or "AUTO").upper()
    if mode == "ON":
        return _UI(True)
    if mode == "OFF":
        return _UI(False)
    return _UI(supports_color(no_color=False))


def _header(ui: _UI, title: Optional[str] = None) -> None:
    print(f"{ui.bold}{_BANNER}{ui.reset}")
    print(ui.rule())
    if title:
        print(title)
        print(ui.rule())


def _print_error(ui: Optional[_UI], msg: str) -> None:
    if ui is None:
        print(f"Error: {msg}", file=sys.stderr)
    else:
        print(f"{ui.red}Error{ui.reset}: {msg}", file=sys.stderr)


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def _color_for_verdict(ui: _UI, verdict: str) -> str:
    if verdict in ("SAFE", "ALLOW"):
        return ui.green
    if verdict in ("SUSPICIOUS", "MEDIUM_RISK", "MONITOR", "CAUTION", "REVIEW"):
        return ui.yellow
    if verdict in ("HIGH_RISK", "MALICIOUS", "BLOCK"):
        return ui.red
    return ui.dim


def _level_from_score(score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "LOW"


def _ipc_request(
    cfg: Config,
    payload: Dict[str, Any],
    timeout: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Send one bounded JSON request over CALLSHIELD's local Unix socket."""

    import socket as _socket

    if not getattr(cfg, "ipc_enabled", True):
        return None
    endpoint = Path(getattr(cfg, "socket_path", Path(cfg.run_dir) / "callshield.sock"))
    if not endpoint.exists():
        return None
    timeout_value = float(timeout if timeout is not None else cfg.ipc_timeout)
    try:
        request = (
            json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        return {"status": "error", "error": "Request is not valid JSON"}
    if len(request) > 16 * 1024:
        return {"status": "error", "error": "Request too large"}

    client = None
    try:
        client = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        client.settimeout(timeout_value)
        client.connect(str(endpoint))
        client.sendall(request)
        response = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
            if len(response) > 64 * 1024:
                return {"status": "error", "error": "Response too large"}
            if b"\n" in response:
                break
        if not response:
            return None
        first, _, remainder = response.partition(b"\n")
        if remainder.strip():
            return {"status": "error", "error": "Invalid daemon response"}
        decoded = json.loads(first.decode("utf-8", errors="strict"))
        return decoded if isinstance(decoded, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    finally:
        if client is not None:
            try:
                client.close()
            except OSError:
                pass


def _format_uptime(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _saved_daemon_metrics(cfg: Config) -> Dict[str, Any]:
    """Load the bounded last-session snapshot, or an empty mapping."""

    path = Path(cfg.run_dir).expanduser().parent / "state" / "daemon_metrics.json"
    try:
        if not path.is_file() or path.stat().st_size > 128 * 1024:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _database_metrics(cfg: Config) -> Dict[str, int]:
    database = None
    try:
        database = open_database(cfg)
        return database.event_metrics(cfg.high_risk_threshold)
    except Exception:
        return {"total": 0, "high_risk": 0, "block_recommendations": 0}
    finally:
        if database is not None:
            try:
                database.close()
            except Exception:
                pass


def _safe_metric_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="callshield",
        description="CALLSHIELD — local fraud-number analysis and protection foundation.",
        epilog=textwrap.dedent(
            """\
            Exit codes: 0 ok, 1 general error, 2 usage, 3 invalid number,
            4 database error, 5 configuration error, 6 daemon error.

            Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls.
            Phase 2 analyzes phone-number risk locally. It does NOT yet
            intercept or reject live phone calls.
            Phase 3 provides the background processing infrastructure. It does not yet receive or reject real Android phone calls.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="store_true", help="Show version and exit.")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    p.add_argument(
        "--color",
        choices=["auto", "on", "off"],
        default=None,
        help="Control color output (default: auto).",
    )

    sub = p.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("version", help="Show version information.")
    s_status = sub.add_parser("status", help="Show engine status.")
    s_status.add_argument("--watch", action="store_true", help="Continuously display status (Ctrl+C to exit).")
    s_status.add_argument("--interval", type=int, default=None, help="Refresh interval for --watch (seconds).")

    s_scan = sub.add_parser("scan", help="Analyze a phone number.")
    s_scan.add_argument("number", help="Phone number to analyze.")
    s_scan.add_argument("--json", action="store_true", help="Emit JSON output.")
    s_scan.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the recommended action (or JSON with --json).",
    )
    s_scan.add_argument(
        "--no-log",
        action="store_true",
        help="Do not record this scan in the event log.",
    )

    s_block = sub.add_parser("block", help="Add a number to the blacklist.")
    s_block.add_argument("number")
    s_block.add_argument("--reason", default=None, help="Optional reason/note.")

    s_unblock = sub.add_parser("unblock", help="Remove a number from the blacklist.")
    s_unblock.add_argument("number")

    s_allow = sub.add_parser("allow", help="Add a number to the whitelist.")
    s_allow.add_argument("number")
    s_allow.add_argument("--reason", default=None)

    s_unallow = sub.add_parser("unallow", help="Remove a number from the whitelist.")
    s_unallow.add_argument("number")

    s_report = sub.add_parser(
        "report", help="File a local user report against a number."
    )
    s_report.add_argument("number")
    s_report.add_argument(
        "--reason",
        default=None,
        help="Optional description of why the number was reported.",
    )

    s_bl = sub.add_parser("blacklist", help="Blacklist management.")
    s_bl_sub = s_bl.add_subparsers(dest="bl_cmd")
    s_bl_sub.add_parser("list", help="List blacklisted numbers.")

    s_wl = sub.add_parser("whitelist", help="Whitelist management.")
    s_wl_sub = s_wl.add_subparsers(dest="wl_cmd")
    s_wl_sub.add_parser("list", help="List whitelisted numbers.")

    s_rep = sub.add_parser(
        "reputation", help="Show local reputation information for a number."
    )
    s_rep.add_argument("number")
    s_rep.add_argument("--json", action="store_true")

    s_hist = sub.add_parser("history", help="Show local event history for a number.")
    s_hist.add_argument("number")
    s_hist.add_argument("--limit", type=int, default=20)
    s_hist.add_argument("--full", action="store_true")

    s_sigs = sub.add_parser(
        "signals", help="Show signal breakdown for a number."
    )
    s_sigs.add_argument("number")

    s_logs = sub.add_parser("logs", help="Show recent analysis events.")
    s_logs.add_argument("--limit", type=int, default=20, help="Max entries (default 20).")
    s_logs.add_argument(
        "--full", action="store_true", help="Show full unmasked numbers."
    )

    s_cfg = sub.add_parser("config", help="View or edit configuration.")
    s_cfg_sub = s_cfg.add_subparsers(dest="cfg_cmd")
    s_cfg_sub.add_parser("show", help="Show current configuration.")
    s_set = s_cfg_sub.add_parser("set", help="Set a configuration value.")
    s_set.add_argument("key")
    s_set.add_argument("value")
    s_profile = s_cfg_sub.add_parser(
        "profile", help="Set protection profile (relaxed/balanced/strict)."
    )
    s_profile.add_argument(
        "mode", choices=[m.lower() for m in PROFILES]
    )
    # `config mode` kept for backward compatibility with Phase 1.
    s_mode = s_cfg_sub.add_parser("mode", help=argparse.SUPPRESS)
    s_mode.add_argument("mode", choices=[m.lower() for m in PROFILES] + ["permissive"])

    sub.add_parser("start", help="Start the background engine (STANDBY).")
    sub.add_parser("stop", help="Stop the background engine.")
    sub.add_parser("metrics", help="Show daemon metrics.")
    sub.add_parser("_run-fg", help=argparse.SUPPRESS)

    # Phase 3 daemon commands (with backward compat: start/stop/status map to daemon/*)
    s_daemon = sub.add_parser("daemon", help="Daemon management.")
    s_daemon_sub = s_daemon.add_subparsers(dest="daemon_cmd")
    s_daemon_sub.add_parser("start", help="Start daemon.")
    s_daemon_sub.add_parser("stop", help="Stop daemon.")
    s_daemon_sub.add_parser("restart", help="Restart daemon.")
    s_daemon_sub.add_parser("status", help="Show daemon status.")
    s_daemon_sub.add_parser("info", help="Show daemon info.")
    s_daemon_sub.add_parser("health", help="Show daemon health.")

    # Event pipeline testing (Phase 3)
    s_event = sub.add_parser("event", help="Event pipeline.")
    s_event_sub = s_event.add_subparsers(dest="event_cmd")
    s_evt_test = s_event_sub.add_parser("test", help="Send a TEST NUMBER_SCAN event through daemon.")
    s_evt_test.add_argument("number", help="Phone number for test event.")
    s_evt_test.add_argument("--reason", default=None, help="Optional reason payload.")

    return p


# --------------------------------------------------------------------- commands


def _cmd_version(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    if getattr(args, "json", False):
        _print_json({"name": "callshield", "version": __version__, "phase": _PHASE})
        return EXIT_OK
    print(f"{ui.bold}CALLSHIELD {__version__}{ui.reset}")
    print(_PHASE)
    return EXIT_OK


def _cmd_status(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    if getattr(args, "watch", False):
        configured = int(getattr(cfg, "status_refresh_interval", 2))
        interval = configured if getattr(args, "interval", None) is None else args.interval
        if not isinstance(interval, int) or not (1 <= interval <= 10):
            _print_error(ui, "Watch interval must be between 1 and 10 seconds.")
            return EXIT_USAGE
        try:
            import time as _time

            while True:
                if sys.stdout.isatty():
                    print("\033[2J\033[H", end="")
                _do_status_once(ui, cfg)
                print(
                    ui.dim
                    + f"\nRefreshing every {interval}s — Ctrl+C exits watch mode; daemon keeps running."
                    + ui.reset
                )
                _time.sleep(interval)
        except KeyboardInterrupt:
            print()
            return EXIT_OK
    return _do_status_once(ui, cfg)


def _do_status_once(ui: _UI, cfg: Config) -> int:
    _header(ui, "CALLSHIELD STATUS")
    state, pid = daemon_status(cfg)

    database = None
    try:
        database = open_database(cfg)
        database.get_setting("heartbeat")
        db_online = True
    except Exception:
        db_online = False
    finally:
        if database is not None:
            try:
                database.close()
            except Exception:
                pass

    ipc_data = None
    if state == "RUNNING":
        response = _ipc_request(cfg, {"command": "status"})
        if (
            response
            and response.get("status") == "ok"
            and isinstance(response.get("data"), dict)
        ):
            ipc_data = response["data"]

    state_color = {
        "RUNNING": ui.green,
        "STOPPED": ui.dim,
        "STALE": ui.yellow,
    }.get(state, "")
    print(f"Daemon:       {state_color}{state}{ui.reset}")
    if pid is not None:
        print(f"PID:          {pid}")

    if ipc_data is not None:
        uptime = ipc_data.get("uptime_human") or _format_uptime(
            int(ipc_data.get("uptime_seconds", 0))
        )
        engine_online = ipc_data.get("db_status") == "ONLINE"
        print(f"Uptime:       {uptime}")
        print(
            f"Engine:       {ui.green + 'ONLINE' + ui.reset if engine_online else ui.red + 'ERROR' + ui.reset}"
        )
        print(
            f"Database:     {ui.green + 'ONLINE' + ui.reset if db_online else ui.red + 'ERROR' + ui.reset}"
        )
        print(
            f"Queue:        {ipc_data.get('queue_size', 0)}/{ipc_data.get('queue_max', cfg.event_queue_size)}"
        )
        print()
        print("Events:")
        print(f"  Processed:  {ipc_data.get('processed', 0)}")
        print(f"  Failed:     {ipc_data.get('failed', 0)}")
        print()
        print("Last Heartbeat:")
        print(f"  {ipc_data.get('last_heartbeat_human') or 'unavailable'}")
        if ipc_data.get("heartbeat_stale"):
            print(f"  {ui.yellow}STALE{ui.reset}")
    else:
        persisted = _database_metrics(cfg)
        saved = _saved_daemon_metrics(cfg)
        engine = "OFFLINE" if state != "RUNNING" else "UNKNOWN (IPC unavailable)"
        last_uptime = saved.get("uptime_human")
        print(
            f"Uptime:       {'last session ' + str(last_uptime) if last_uptime else 'not running'}"
        )
        print(f"Engine:       {engine}")
        print(
            f"Database:     {ui.green + 'ONLINE' + ui.reset if db_online else ui.red + 'ERROR' + ui.reset}"
        )
        print(f"Queue:        0/{cfg.event_queue_size}")
        print()
        print("Events:")
        print(
            f"  Processed:  {max(_safe_metric_int(saved.get('processed')), persisted['total'])}"
        )
        print(f"  Failed:     {_safe_metric_int(saved.get('failed'))}")
        print()
        print("Last Heartbeat:")
        print(f"  {saved.get('last_heartbeat_human') or 'unavailable'}")
        print()
        if state == "RUNNING":
            print("IPC unavailable; PID-only fallback is in use.")
        elif state == "STALE":
            print("Stale CALLSHIELD runtime state will be recovered safely on start.")
        else:
            print("Use `callshield daemon start` to launch the background engine.")

    print()
    print(f"Call Screening: {ui.dim}NOT CONNECTED{ui.reset}")
    print(f"Profile:        {cfg.protection_mode}")
    print()
    print(f"Use `{ui.bold}callshield --help{ui.reset}` for commands.")
    return EXIT_OK

def _normalize_or_error(
    ui: Optional[_UI], number: str, cfg: Config, usage_hint: str
) -> Optional[object]:
    try:
        return normalize(number, default_country=cfg.default_country)
    except InvalidNumberError as exc:
        _print_error(ui, f"{exc.message}\nUse: {usage_hint}")
        return None


def _cmd_scan(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    as_json = getattr(args, "json", False)
    quiet = getattr(args, "quiet", False)
    record = cfg.logging_enabled and not getattr(args, "no_log", False)

    db = open_database(cfg)
    try:
        try:
            result: AnalysisResult = analyze_number(
                args.number, db=db, cfg=cfg, record_event=record
            )
        except InvalidNumberError as exc:
            _print_error(
                ui if not as_json else None,
                f"{exc.message}\nUse: callshield scan <number>",
            )
            return EXIT_INVALID_NUMBER
    finally:
        db.close()

    if as_json:
        _print_json(result.to_dict())
        return EXIT_OK

    if quiet:
        print(result.recommended_action)
        return EXIT_OK

    _header(ui, "CALLSHIELD ANALYSIS")
    print(f"Number       {result.normalized_number}")
    print(f"Reputation   {result.reputation}")
    print(f"Risk Score   {result.risk_score}/100")
    level_color = (
        ui.green
        if result.risk_level in ("LOW", "UNKNOWN")
        else ui.yellow
        if result.risk_level in ("MEDIUM",)
        else ui.red
    )
    print(f"Risk Level   {level_color}{result.risk_level}{ui.reset}")
    conf_color = (
        ui.green
        if result.confidence >= 70
        else ui.yellow
        if result.confidence >= 40
        else ui.dim
    )
    print(f"Confidence   {conf_color}{result.confidence}%{ui.reset}")
    verdict_color = _color_for_verdict(ui, result.verdict)
    print(f"Verdict      {verdict_color}{result.verdict}{ui.reset}")
    action_color = _color_for_verdict(ui, result.recommended_action)
    print(f"Action       {action_color}{result.recommended_action}{ui.reset}")

    if result.list_conflict:
        print(
            ui.yellow
            + "\nNote: number exists in BOTH blacklist and whitelist."
            + ui.reset
        )
        print(
            "Whitelist takes precedence (WHITELIST > BLACKLIST > REPUTATION)."
        )

    if result.signals:
        print()
        print("Signals")
        for s in result.signals:
            delta = s["score"]
            sign = f"+{delta}" if delta >= 0 else str(delta)
            reason = f" — {s['reason']}" if s.get("reason") else ""
            marker_color = ui.green if delta < 0 else ui.red if delta > 0 else ui.dim
            print(
                f"  {ui.bold}•{ui.reset} {marker_color}{sign.rjust(4)}{ui.reset}  {s['name']}{reason}"
            )

    print()
    print("Recommendation")
    if result.recommended_action == "BLOCK":
        print(f"  {ui.red}Block this number.{ui.reset}")
    elif result.recommended_action == "MONITOR":
        print(f"  {ui.yellow}Treat this number with caution; consider not answering.{ui.reset}")
    elif result.verdict == "SAFE":
        print(f"  {ui.green}This number is explicitly allowed.{ui.reset}")
    else:
        print(f"  {ui.dim}No strong fraud indicators found.{ui.reset}")
    print()
    print(f"Reason: {result.reason}")
    return EXIT_OK


def _add_to_list(
    ui: _UI, args: argparse.Namespace, cfg: Config, list_type: str
) -> int:
    n = _normalize_or_error(
        ui,
        args.number,
        cfg,
        usage_hint="callshield block|allow|unblock|unallow <number>",
    )
    if n is None:
        return EXIT_INVALID_NUMBER
    db = open_database(cfg)
    try:
        res = db.upsert_list_entry(
            n.normalized,
            list_type,
            reason=getattr(args, "reason", None),
            now_iso=iso_now(),
        )
        other = "whitelist" if list_type == "blacklist" else "blacklist"
        in_other = db.get_list_entry(n.normalized, other) is not None
    finally:
        db.close()

    label = "blacklist" if list_type == "blacklist" else "whitelist"
    status_label = "BLOCKED" if list_type == "blacklist" else "ALLOWED"

    _header(ui)
    if res == "exists":
        print(f"Number is already on the {label}.")
    else:
        print(f"Number added to {label}.")
    print()
    print(n.normalized)
    print(
        f"Status: {ui.red if list_type == 'blacklist' else ui.green}{status_label}{ui.reset}"
    )
    if in_other:
        print(
            ui.yellow
            + "Note: number is also on the "
            + other
            + ". By documented rule "
            + "(WHITELIST > BLACKLIST > REPUTATION), the whitelist takes precedence."
            + ui.reset
        )
    log_info(cfg, f"{list_type} add number={n.normalized} result={res}")
    return EXIT_OK


def _cmd_block(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    return _add_to_list(ui, args, cfg, "blacklist")


def _cmd_allow(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    return _add_to_list(ui, args, cfg, "whitelist")


def _remove_from_list(
    ui: _UI, args: argparse.Namespace, cfg: Config, list_type: str
) -> int:
    n = _normalize_or_error(
        ui,
        args.number,
        cfg,
        usage_hint="callshield unblock|unallow <number>",
    )
    if n is None:
        return EXIT_INVALID_NUMBER
    db = open_database(cfg)
    try:
        removed = db.remove_from_list(n.normalized, list_type)
    finally:
        db.close()
    _header(ui)
    label = "blacklist" if list_type == "blacklist" else "whitelist"
    if removed:
        print(f"Number removed from {label}.")
        print(n.normalized)
    else:
        print(f"Number was not on the {label}.")
        print(n.normalized)
    return EXIT_OK


def _cmd_unblock(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    return _remove_from_list(ui, args, cfg, "blacklist")


def _cmd_unallow(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    return _remove_from_list(ui, args, cfg, "whitelist")


def _cmd_report(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    n = _normalize_or_error(
        ui,
        args.number,
        cfg,
        usage_hint="callshield report <number> [--reason ...]",
    )
    if n is None:
        return EXIT_INVALID_NUMBER
    reason = (args.reason or "").strip()[:500] or None
    db = open_database(cfg)
    try:
        db.add_report(n.normalized, reason, iso_now())
        total = db.count_reports(n.normalized)
    finally:
        db.close()
    _header(ui, "USER REPORT")
    print(f"Number        {n.normalized}")
    print(f"Total reports {total}")
    if reason:
        print(f"Reason        {reason}")
    print(ui.dim + "\n(User reports are stored locally only.)" + ui.reset)
    log_info(cfg, f"report add number={n.normalized} total={total}")
    return EXIT_OK


def _cmd_blacklist(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    return _list_table(ui, cfg, "blacklist")


def _cmd_whitelist(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    return _list_table(ui, cfg, "whitelist")


def _list_table(ui: _UI, cfg: Config, list_type: str) -> int:
    db = open_database(cfg)
    try:
        rows = db.list_numbers(list_type=list_type)
    finally:
        db.close()
    _header(ui, f"{list_type.upper()}")
    if not rows:
        print(ui.dim + "(no entries)" + ui.reset)
        return EXIT_OK
    headers = ("NUMBER", "REPUTATION", "REASON", "ADDED")
    widths = [
        max(len(headers[0]), max((len(r["number"]) for r in rows), default=0)),
        max(len(headers[1]), 10),
        max(len(headers[2]), 20),
        max(len(headers[3]), 19),
    ]
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print(ui.rule(len(header_line)))
    for r in rows:
        reason = (r.get("reason") or "-")[: widths[2]]
        created = (r.get("created_at") or "-")[: widths[3]]
        print(
            f"{r['number'].ljust(widths[0])}  "
            f"{r['reputation'].ljust(widths[1])}  "
            f"{reason.ljust(widths[2])}  "
            f"{created.ljust(widths[3])}"
        )
    return EXIT_OK


def _cmd_reputation(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    n = _normalize_or_error(
        ui, args.number, cfg, usage_hint="callshield reputation <number>"
    )
    if n is None:
        return EXIT_INVALID_NUMBER
    as_json = getattr(args, "json", False)
    db = open_database(cfg)
    try:
        result = analyze_number(
            n.normalized, db=db, cfg=cfg, record_event=False
        )
        reports = db.count_reports(n.normalized)
        first_seen = db.get_first_seen(n.normalized)
        last_seen = db.get_last_seen(n.normalized)
        bl = db.get_list_entry(n.normalized, "blacklist")
        wl = db.get_list_entry(n.normalized, "whitelist")
    finally:
        db.close()

    if as_json:
        _print_json(
            {
                "number": result.normalized_number,
                "reputation": result.reputation,
                "risk_score": result.risk_score,
                "risk_level": result.risk_level,
                "confidence": result.confidence,
                "verdict": result.verdict,
                "recommended_action": result.recommended_action,
                "reports": reports,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "blacklisted": bl is not None,
                "whitelisted": wl is not None,
                "behavior": result.behavior,
                "signals": result.signals,
            }
        )
        return EXIT_OK

    _header(ui, "CALLSHIELD REPUTATION")
    print(f"Number          {result.normalized_number}")
    print(f"Reputation      {_color_for_verdict(ui, result.reputation)}{result.reputation}{ui.reset}")
    print(f"Risk Score      {result.risk_score}/100")
    print(f"Confidence      {result.confidence}%")
    print(f"Verdict         {result.verdict}")
    print(f"Action          {result.recommended_action}")
    print(f"Reports         {reports}")
    print(f"Suspicious evs  {result.behavior.get('suspicious_events', 0)}")
    print(f"Blocked evs     {result.behavior.get('blocked_events', 0)}")
    if first_seen:
        print(f"First seen      {first_seen}")
    if last_seen:
        print(f"Last seen       {last_seen}")
    if bl or wl:
        print()
        if wl:
            print(ui.green + "  • Present on whitelist" + ui.reset)
        if bl:
            print(ui.red + "  • Present on blacklist" + ui.reset)
    return EXIT_OK


def _cmd_history(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    n = _normalize_or_error(
        ui, args.number, cfg, usage_hint="callshield history <number>"
    )
    if n is None:
        return EXIT_INVALID_NUMBER
    db = open_database(cfg)
    try:
        events = db.get_events_for_number(n.normalized, limit=max(1, args.limit))
    finally:
        db.close()

    _header(ui, "CALLSHIELD HISTORY")
    print(f"Number       {n.normalized if args.full else mask_number(n.normalized)}")
    print(f"Events       {len(events)} shown")
    print()
    if not events:
        print(ui.dim + "(no events for this number)" + ui.reset)
        return EXIT_OK
    header = f"{'TIME':<19}  {'SCORE':>5}  {'CONF':>4}  {'VERDICT':<12}  ACTION"
    print(header)
    print(ui.rule(len(header)))
    for e in reversed(events):  # oldest first
        ts = (e["timestamp"] or "").replace("T", " ")[:19]
        score = e["risk_score"]
        conf = e.get("confidence") or 0
        print(
            f"{ts:<19}  {score:>5}  {conf:>3}%  {e['verdict']:<12}  {e['action']}"
        )
    return EXIT_OK


def _cmd_signals(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    n = _normalize_or_error(
        ui, args.number, cfg, usage_hint="callshield signals <number>"
    )
    if n is None:
        return EXIT_INVALID_NUMBER
    db = open_database(cfg)
    try:
        result = analyze_number(
            n.normalized, db=db, cfg=cfg, record_event=False
        )
    finally:
        db.close()

    _header(ui, "SIGNAL BREAKDOWN")
    print(f"Number        {result.normalized_number}")
    print(f"Final Score   {result.risk_score}/100")
    print()
    if not result.signals:
        print(ui.dim + "(no signals triggered)" + ui.reset)
    else:
        name_w = max(len(s["name"]) for s in result.signals)
        for s in result.signals:
            delta = s["score"]
            sign = f"+{delta}" if delta >= 0 else str(delta)
            c = ui.green if delta < 0 else ui.red if delta > 0 else ui.dim
            print(
                f"  {s['name'].ljust(name_w)}   {c}{sign.rjust(4)}{ui.reset}   {s['reason']}"
            )
    return EXIT_OK


def _cmd_logs(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    db = open_database(cfg)
    try:
        rows = db.recent_events(limit=args.limit)
    finally:
        db.close()
    _header(ui, "CALLSHIELD EVENTS")
    if not rows:
        print(
            ui.dim
            + "(no events logged yet — run `callshield scan <number>` first)"
            + ui.reset
        )
        return EXIT_OK
    header = f"{'TIME':<19} {'NUMBER':<18} {'SCORE':>5}  {'CONF':>4}  {'VERDICT':<12}  ACTION"
    print(header)
    print(ui.rule(len(header)))
    for r in rows:
        ts = (r["timestamp"] or "").replace("T", " ")[:19]
        num = r["number"] if args.full else mask_number(r["number"])
        verdict = r["verdict"]
        action = r["action"]
        score = r["risk_score"]
        conf = r.get("confidence") or 0
        print(
            f"{ts:<19} {num:<18} {score:>5}  {conf:>3}%  {verdict:<12}  {action}"
        )
    if not args.full:
        print(
            ui.dim
            + "\n(Numbers are masked by default; pass --full to show them.)"
            + ui.reset
        )
    return EXIT_OK


def _cmd_config(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    cmd = args.cfg_cmd
    if cmd in (None, "show"):
        _header(ui, "CALLSHIELD CONFIG")
        db_ok = False
        try:
            db = open_database(cfg)
            db.get_setting("heartbeat")
            db.close()
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        rows = [
            ("Profile", cfg.protection_mode),
            ("Risk Threshold", str(cfg.risk_threshold)),
            ("High-Risk Threshold", str(cfg.high_risk_threshold)),
            ("History Weight", str(cfg.history_weight)),
            ("Report Weight", str(cfg.report_weight)),
            ("Pattern Weight", str(cfg.pattern_weight)),
            ("Logging", "ON" if cfg.logging_enabled else "OFF"),
            ("Colors", cfg.color_enabled),
            ("Default Country", cfg.default_country or "(unset)"),
            ("Database", "SQLite" + ("" if db_ok else " (unreachable)")),
            ("Database Path", cfg.database_path),
            ("PID File", cfg.pid_file),
            ("Log File", cfg.log_file),
            ("Daemon", "ENABLED" if getattr(cfg, "daemon_enabled", True) else "DISABLED"),
            ("Heartbeat", f"{cfg.heartbeat_interval}s"),
            ("Queue Size", str(cfg.event_queue_size)),
            ("Shutdown Timeout", f"{cfg.shutdown_timeout}s"),
            ("Status Refresh", f"{cfg.status_refresh_interval}s"),
            ("IPC Timeout", f"{cfg.ipc_timeout:g}s"),
            ("Event Payload Limit", f"{cfg.event_payload_limit} bytes"),
            ("Log Size", f"{cfg.max_log_size // (1024*1024)}MB" if cfg.max_log_size >= 1024*1024 else f"{cfg.max_log_size // 1024}KB"),
            ("Log Files", str(cfg.max_log_files)),
            ("IPC", "ENABLED" if getattr(cfg, "ipc_enabled", True) else "DISABLED"),
            ("Run Dir", cfg.run_dir),
            ("Socket", cfg.socket_path),
            ("Daemon Log", cfg.daemon_log_file),
        ]
        label_w = max(len(k) for k, _ in rows)
        for k, v in rows:
            print(f"{k.ljust(label_w)}    {v}")
        print(
            ui.dim
            + "\nUse `callshield config set <key> <value>` or `callshield config profile <mode>`."
            + ui.reset
        )
        # Also show daemon config section per Phase 3 spec
        print()
        _header(ui, "CALLSHIELD DAEMON CONFIG")
        drows = [
            ("Daemon", "ENABLED" if getattr(cfg, "daemon_enabled", True) else "DISABLED"),
            ("Heartbeat", f"{cfg.heartbeat_interval}s"),
            ("Queue Size", str(cfg.event_queue_size)),
            ("Shutdown Timeout", f"{cfg.shutdown_timeout}s"),
            ("IPC Timeout", f"{cfg.ipc_timeout:g}s"),
            ("Event Payload Limit", f"{cfg.event_payload_limit} bytes"),
            ("Log Size", f"{cfg.max_log_size // (1024*1024)}MB" if cfg.max_log_size >= 1024*1024 else f"{cfg.max_log_size // 1024}KB"),
            ("Log Files", str(cfg.max_log_files)),
            ("IPC", "ENABLED" if getattr(cfg, "ipc_enabled", True) else "DISABLED"),
        ]
        lw = max(len(k) for k,_ in drows)
        for k,v in drows:
            print(f"{k.ljust(lw)}    {v}")
        return EXIT_OK

    if cmd in ("mode", "profile"):
        mode = args.mode.upper()
        if mode == "PERMISSIVE":
            mode = "RELAXED"
        try:
            cfg = set_profile(cfg, mode)
        except CallShieldError as exc:
            _print_error(ui, exc.message)
            return EXIT_CONFIG
        save_config(cfg)
        _header(ui)
        print(
            f"Profile set to {ui.bold}{cfg.protection_mode}{ui.reset} "
            f"(risk threshold {cfg.risk_threshold})."
        )
        return EXIT_OK

    if cmd == "set":
        try:
            cfg = set_value(cfg, args.key, args.value)
            save_config(cfg)
        except CallShieldError as exc:
            _print_error(ui, exc.message)
            return EXIT_CONFIG
        _header(ui)
        print(f"Updated {args.key} = {args.value}")
        return EXIT_OK

    _print_error(ui, "Unknown config subcommand.")
    return EXIT_USAGE


def _cmd_start(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    import time as _time

    if not cfg.daemon_enabled:
        _print_error(ui, "Daemon is disabled by configuration.")
        return EXIT_DAEMON
    state, pid = daemon_status(cfg)
    if state == "RUNNING":
        _header(ui)
        print("CALLSHIELD daemon is already running.")
        print(f"PID:       {pid}")
        return EXIT_OK
    if state == "STALE":
        from .daemon import _clear_pid
        from .daemon.process import _clear_socket

        _clear_pid(cfg, expected_pid=pid)
        _clear_socket(cfg)

    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "callshield", "_run-fg"],
            cwd=str(Path(__file__).resolve().parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=dict(os.environ),
        )
    except OSError as exc:
        _print_error(ui, f"Unable to start daemon: {exc}")
        return EXIT_DAEMON

    ready = False
    deadline = _time.monotonic() + 5.0
    running_pid = None
    while _time.monotonic() < deadline:
        current_state, running_pid = daemon_status(cfg)
        if current_state == "RUNNING":
            if not cfg.ipc_enabled:
                ready = True
                break
            ping = _ipc_request(cfg, {"command": "ping"}, timeout=0.25)
            if ping and ping.get("status") == "ok" and ping.get("pong") is True:
                ready = True
                break
        if process.poll() is not None:
            break
        _time.sleep(0.05)

    if not ready:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                pass
        _print_error(
            ui,
            f"Daemon failed startup validation; inspect {cfg.daemon_log_file}.",
        )
        return EXIT_DAEMON

    _header(ui)
    print("Protection daemon started.")
    print(f"PID:       {running_pid or process.pid}")
    print("Status:    RUNNING")
    print("Engine:    ONLINE")
    print(f"Queue:     0/{cfg.event_queue_size}")
    print(f"Profile:   {cfg.protection_mode}")
    print()
    print(f"Call Screening: {ui.dim}NOT CONNECTED{ui.reset}")
    print(
        ui.dim
        + "TEST events are local daemon events, not real phone calls. Live call interception and automatic rejection are not implemented."
        + ui.reset
    )
    return EXIT_OK

def _cmd_stop(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    import time as _time

    state, pid = daemon_status(cfg)
    _header(ui)
    if state == "STOPPED":
        from .daemon.process import _clear_socket

        _clear_socket(cfg)
        print("CALLSHIELD daemon is not running.")
        return EXIT_OK
    if state == "STALE":
        from .daemon import _clear_pid
        from .daemon.process import _clear_socket

        _clear_pid(cfg, expected_pid=pid)
        _clear_socket(cfg)
        print(f"Recovered stale daemon state{f' (PID {pid})' if pid else ''}.")
        return EXIT_OK

    response = _ipc_request(cfg, {"command": "stop"})
    if response and response.get("status") == "ok":
        deadline = _time.monotonic() + float(cfg.shutdown_timeout) + 2.0
        while _time.monotonic() < deadline:
            current, _ = daemon_status(cfg)
            if current == "STOPPED":
                print("Protection daemon stopped.")
                if pid:
                    print(f"PID:       {pid}")
                return EXIT_OK
            _time.sleep(0.1)

    try:
        stopped, stopped_pid = daemon_stop(cfg)
    except DaemonError as exc:
        _print_error(ui, exc.message)
        return EXIT_DAEMON
    if not stopped:
        _print_error(ui, "PID ownership could not be verified; no process was signalled.")
        return EXIT_DAEMON
    print("Protection daemon stopped.")
    if stopped_pid:
        print(f"PID:       {stopped_pid}")
    return EXIT_OK

def _cmd_run_fg(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    try:
        return run_foreground(cfg)
    except Exception as exc:  # noqa: BLE001
        log_error(cfg, f"engine crashed: {exc}")
        return EXIT_DAEMON


def _cmd_metrics(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    _header(ui, "CALLSHIELD METRICS")
    state, _ = daemon_status(cfg)
    response = (
        _ipc_request(cfg, {"command": "metrics"}) if state == "RUNNING" else None
    )
    if (
        response
        and response.get("status") == "ok"
        and isinstance(response.get("data"), dict)
    ):
        data = response["data"]
        print(
            f"Uptime               {data.get('uptime_human') or _format_uptime(int(data.get('uptime_seconds', 0)))}"
        )
        print(f"Events Received      {int(data.get('received', 0))}")
        print(f"Processed            {int(data.get('processed', 0))}")
        print(f"Failed               {int(data.get('failed', 0))}")
        print(f"Dropped              {int(data.get('dropped', 0))}")
        print(f"Queue Size           {int(data.get('queue_size', 0))}/{int(data.get('queue_max', cfg.event_queue_size))}")
        print(f"Queue Peak           {int(data.get('queue_peak', 0))}/{int(data.get('queue_max', cfg.event_queue_size))}")
        print(f"High-Risk Detections {int(data.get('high_risk_count', 0))}")
        print(
            f"Block Recommendations {int(data.get('blocked_recommendations', 0))}"
        )
        memory = data.get("memory_kb")
        print(f"Memory               {str(memory) + ' KiB' if memory is not None else 'unavailable'}")
    else:
        persisted = _database_metrics(cfg)
        saved = _saved_daemon_metrics(cfg)
        total = int(persisted.get("total", 0))
        print(
            f"Uptime               daemon not running (last {saved.get('uptime_human', 'unavailable')})"
        )
        print(f"Events Received      {max(total, _safe_metric_int(saved.get('received')))}")
        print(f"Processed            {max(total, _safe_metric_int(saved.get('processed')))}")
        print(f"Failed               {_safe_metric_int(saved.get('failed'))}")
        print(f"Dropped              {_safe_metric_int(saved.get('dropped'))}")
        print(f"Queue Size           0/{cfg.event_queue_size}")
        print(f"Queue Peak           {_safe_metric_int(saved.get('queue_peak'))}/{cfg.event_queue_size}")
        print(
            f"High-Risk Detections {max(int(persisted.get('high_risk', 0)), _safe_metric_int(saved.get('high_risk_count')))}"
        )
        print(
            "Block Recommendations "
            + str(
                max(
                    int(persisted.get("block_recommendations", 0)),
                    _safe_metric_int(saved.get("blocked_recommendations")),
                )
            )
        )
        memory = saved.get("memory_kb")
        print(f"Memory               {str(memory) + ' KiB (last session)' if memory is not None else 'unavailable'}")
        if state == "RUNNING":
            print("IPC                   unavailable (safe persisted fallback)")
    print(f"Call Screening:      {ui.dim}NOT CONNECTED{ui.reset}")
    return EXIT_OK

def _cmd_daemon(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    cmd = getattr(args, "daemon_cmd", None)
    if cmd in (None, "status"):
        return _do_status_once(ui, cfg)
    if cmd == "start":
        return _cmd_start(ui, args, cfg)
    if cmd == "stop":
        return _cmd_stop(ui, args, cfg)
    if cmd == "restart":
        stop_code = _cmd_stop(ui, args, cfg)
        if stop_code != EXIT_OK:
            return stop_code
        import time as _t

        _t.sleep(0.2)
        return _cmd_start(ui, args, cfg)
    if cmd == "info":
        return _cmd_daemon_info(ui, args, cfg)
    if cmd == "health":
        return _cmd_daemon_health(ui, args, cfg)
    _print_error(ui, "Unknown daemon subcommand")
    return EXIT_USAGE


def _cmd_daemon_info(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    _header(ui, "CALLSHIELD DAEMON INFO")
    state, pid = daemon_status(cfg)
    print(f"Daemon          {state}")
    if pid:
        print(f"PID             {pid}")
    # Try IPC
    resp = _ipc_request(cfg, {"command": "daemon_info"}) if state == "RUNNING" else None
    if resp and resp.get("status") == "ok":
        d = resp.get("data", {})
        for k, v in d.items():
            print(f"{k:<15} {v}")
    else:
        print(f"Engine          {'ONLINE' if state=='RUNNING' else 'OFFLINE'}")
        # Show config daemon details
        print(f"Daemon Enabled  {'ENABLED' if cfg.daemon_enabled else 'DISABLED'}")
        print(f"IPC             {'ENABLED' if cfg.ipc_enabled else 'DISABLED'}")
        print(f"Heartbeat       {cfg.heartbeat_interval}s")
        print(f"Queue Size      {cfg.event_queue_size}")
        print(f"Socket          {cfg.socket_path}")
        print(f"Run Dir         {cfg.run_dir}")
    print()
    print(f"Call Screening: {ui.dim}NOT CONNECTED{ui.reset}")
    return EXIT_OK


def _cmd_daemon_health(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    _header(ui, "CALLSHIELD HEALTH")
    state, pid = daemon_status(cfg)
    if state != "RUNNING":
        print(f"Daemon          {state}")
        if pid:
            print(f"PID             {pid}")
        print("Health          UNKNOWN (daemon not running)")
        return EXIT_OK
    resp = _ipc_request(cfg, {"command": "health"})
    if resp and resp.get("status") == "ok":
        data = resp.get("data", {})
        healthy = resp.get("healthy", False)
        print(f"Daemon          RUNNING")
        print(f"PID             {data.get('pid') or pid}")
        print(f"Uptime          {data.get('uptime_human')}")
        print(f"Health          {ui.green + 'HEALTHY' + ui.reset if healthy else ui.yellow + 'DEGRADED' + ui.reset}")
        print(f"Database        {data.get('db_status')}")
        print(f"Queue           {data.get('queue_size')} / {data.get('queue_max')}")
        print(f"Processed       {data.get('processed')}  Failed {data.get('failed')}")
        if data.get("last_heartbeat_human"):
            print(f"Last Heartbeat  {data.get('last_heartbeat_human')}")
        print(f"Memory          {data.get('memory_kb') or 'unknown'} kB")
        print(f"Call Screening: {ui.dim}NOT CONNECTED{ui.reset}")
    else:
        print(f"Daemon          RUNNING (IPC unavailable)")
        print(f"PID             {pid}")
        print("Health          UNKNOWN (IPC failed)")
    return EXIT_OK


def _cmd_event(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    cmd = getattr(args, "event_cmd", None)
    if cmd == "test":
        # Normalize number
        n = _normalize_or_error(ui, args.number, cfg, usage_hint="callshield event test <number>")
        if n is None:
            return EXIT_INVALID_NUMBER
        # Must have daemon running for real pipeline test
        state, pid = daemon_status(cfg)
        if state != "RUNNING":
            _print_error(ui, "Daemon is not running. Start it with `callshield start` first.")
            return EXIT_DAEMON
        # Send via IPC
        payload = {
            "event_type": "NUMBER_SCAN",
            "number": n.normalized,
            "source": "TEST",
            "payload": {"reason": args.reason} if args.reason else {},
        }
        # For spec, label clearly as TEST EVENT
        _header(ui, "TEST EVENT")
        print(f"Number        {n.normalized}")
        print(f"Sending NUMBER_SCAN via daemon event queue...")
        resp = _ipc_request(cfg, {"command": "event", "event": payload})
        if not resp:
            _print_error(ui, "Failed to communicate with daemon (IPC timeout).")
            return EXIT_DAEMON
        if resp.get("status") != "ok":
            _print_error(ui, f"Daemon rejected event: {resp.get('error')}")
            return EXIT_DAEMON
        print(f"Event ID      {resp.get('event_id')}")
        print(ui.dim + "Event accepted — processing via daemon pipeline (TEST EVENT, not a phone call)." + ui.reset)
        print(ui.dim + "Check `callshield history <number>` or `callshield metrics` for result." + ui.reset)
        return EXIT_OK
    _print_error(ui, "Unknown event subcommand. Use `callshield event test <number>`")
    return EXIT_USAGE


_COMMANDS = {
    "version": _cmd_version,
    "status": _cmd_status,
    "scan": _cmd_scan,
    "block": _cmd_block,
    "unblock": _cmd_unblock,
    "allow": _cmd_allow,
    "unallow": _cmd_unallow,
    "report": _cmd_report,
    "reputation": _cmd_reputation,
    "history": _cmd_history,
    "signals": _cmd_signals,
    "blacklist": _cmd_blacklist,
    "whitelist": _cmd_whitelist,
    "logs": _cmd_logs,
    "config": _cmd_config,
    "start": _cmd_start,
    "stop": _cmd_stop,
    "metrics": _cmd_metrics,
    "daemon": _cmd_daemon,
    "event": _cmd_event,
    "_run-fg": _cmd_run_fg,
}


def _print_banner_status(ui: _UI, cfg: Config) -> None:
    _header(ui)
    print(_TAGLINE)
    print()
    state, pid = daemon_status(cfg)
    db_ok = False
    db = None
    try:
        db = open_database(cfg)
        db.get_setting("heartbeat")
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    # Phase 1 spec expects Status READY when the database is online, not the daemon state.
    # Show READY for the banner, but keep daemon status visible via `callshield status`.
    banner_status = "READY" if db_ok else "ERROR"
    status_color = ui.green if banner_status == "READY" else ui.red
    # Also support STALE/RUNNING nuance in the banner if daemon is running
    if state == "RUNNING":
        banner_status = "READY"
        status_color = ui.green
    print(f"Status      {status_color}{banner_status}{ui.reset}")
    print(f"Engine      LOCAL")
    print(
        f"Database    {ui.green + 'ONLINE' + ui.reset if db_ok else ui.red + 'ERROR' + ui.reset}"
    )
    print(f"Protection  STANDBY")
    # Profile is useful but not part of the minimal Phase 1 banner; show it dimmed
    print(f"Profile     {cfg.protection_mode}")
    if pid and state == "RUNNING":
        print(f"PID         {pid}")
    print()
    print(f"Use `{ui.bold}callshield --help{ui.reset}` for commands.")
    # Required Phase 1 disclaimer must be present in help/banner context
    print(ui.dim + "Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls." + ui.reset)


# --------------------------------------------------------------------- entry


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = load_config()
    except CallShieldError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return EXIT_CONFIG

    # Global flags that need to be honored even if no UI is built yet.
    ui = _make_ui(args, cfg)

    if args.version and args.command is None:
        return _cmd_version(ui, args, cfg)

    if args.command is None:
        _print_banner_status(ui, cfg)
        return EXIT_OK

    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        return handler(ui, args, cfg)
    except InvalidNumberError as exc:
        _print_error(ui, exc.message)
        return EXIT_INVALID_NUMBER
    except CallShieldError as exc:
        _print_error(ui, exc.message)
        return exc.exit_code
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return EXIT_GENERAL
    except Exception as exc:  # noqa: BLE001
        try:
            log_error(cfg, f"unexpected error: {exc!r}")
        except Exception:  # noqa: BLE001
            pass
        _print_error(ui, f"Unexpected error: {exc}")
        return EXIT_GENERAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
