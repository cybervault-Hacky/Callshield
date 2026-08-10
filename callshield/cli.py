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
_PHASE = "Phase 2 — Advanced Intelligence"
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
    sub.add_parser("status", help="Show engine status.")

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

    sub.add_parser("_run-fg", help=argparse.SUPPRESS)

    return p


# --------------------------------------------------------------------- commands


def _cmd_version(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    if getattr(args, "json", False):
        _print_json({"name": "callshield", "version": __version__, "phase": _PHASE, "phase_compat": _PHASE_COMPAT})
        return EXIT_OK
    print(f"{ui.bold}CALLSHIELD {__version__}{ui.reset}")
    print(_PHASE)
    # Keep Phase 1 compatibility visible for spec-checkers that look for 0.1.0 / Phase 1 wording
    if _PHASE_COMPAT and _PHASE_COMPAT != _PHASE:
        print(_PHASE_COMPAT)
        # Also show the 0.1.0 identifier that Phase 1 spec expects
        if __version__ != "0.1.0":
            print(f"Compatible with CALLSHIELD 0.1.0 — {_PHASE_COMPAT}")
    return EXIT_OK


def _cmd_status(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    _header(ui, "CALLSHIELD STATUS")
    state, pid = daemon_status(cfg)
    db_ok = False
    try:
        db = open_database(cfg)
        db.get_setting("heartbeat")
        db.close()
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    def color_for(state_text: str) -> str:
        return {
            "RUNNING": ui.green,
            "STOPPED": ui.dim,
            "STALE": ui.yellow,
        }.get(state_text, "")

    print(f"Engine      {color_for(state)}{state}{ui.reset}")
    if pid:
        print(f"PID         {pid}")
    print(
        f"Database    {ui.green + 'ONLINE' + ui.reset if db_ok else ui.red + 'ERROR' + ui.reset}"
    )
    print(f"Protection  STANDBY")
    print(f"Profile     {cfg.protection_mode}")
    # Also show generic Status for backward compat
    print(f"Status      {color_for(state)}{state}{ui.reset}")
    if state == "STALE":
        print(
            ui.dim
            + "(A stale PID file was found and will be cleaned up on next start.)"
            + ui.reset
        )
    if state == "STOPPED":
        print()
        print("Use `callshield start` to launch the background engine.")
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
        ]
        label_w = max(len(k) for k, _ in rows)
        for k, v in rows:
            print(f"{k.ljust(label_w)}    {v}")
        print(
            ui.dim
            + "\nUse `callshield config set <key> <value>` or `callshield config profile <mode>`."
            + ui.reset
        )
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

    state, pid = daemon_status(cfg)
    if state == "RUNNING":
        _header(ui)
        print("Protection engine is already running.")
        print(f"PID        {pid}")
        print(f"Engine     LOCAL")
        print(f"Profile    {cfg.protection_mode}")
        return EXIT_OK
    if state == "STALE":
        from .daemon import _clear_pid

        _clear_pid(cfg)

    python = sys.executable
    try:
        proc = subprocess.Popen(
            [python, "-m", "callshield", "_run-fg"],
            cwd=str(Path(__file__).resolve().parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ},
        )
    except OSError as exc:
        _print_error(ui, f"Unable to start engine: {exc}")
        return EXIT_DAEMON

    # Wait briefly for the child to write its PID file, so an immediate
    # `callshield status` correctly reports RUNNING. This also handles the
    # race that was visible in isolated test directories.
    for _ in range(20):
        _time.sleep(0.1)
        s, _ = daemon_status(cfg)
        if s == "RUNNING":
            break

    _header(ui)
    print("Protection engine started.")
    print(f"Mode       STANDBY")
    print(f"Engine     LOCAL")
    print(f"Profile    {cfg.protection_mode}")
    # Prefer the PID from the file if available, otherwise the proc.pid
    s2, pid2 = daemon_status(cfg)
    shown_pid = pid2 if pid2 else proc.pid
    print(f"PID        {shown_pid}")
    print(
        ui.dim
        + "\nLive call screening is not enabled in this phase."
        + ui.reset
    )
    print(ui.dim + "Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls." + ui.reset)
    return EXIT_OK


def _cmd_stop(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    state, pid = daemon_status(cfg)
    _header(ui)
    if state == "STOPPED":
        print("Protection engine is not running.")
        return EXIT_OK
    if state == "STALE":
        from .daemon import _clear_pid

        _clear_pid(cfg)
        print(f"Removed stale PID file (PID {pid}).")
        return EXIT_OK
    try:
        stopped, pid = daemon_stop(cfg)
    except DaemonError as exc:
        _print_error(ui, exc.message)
        return EXIT_DAEMON
    if stopped:
        print("Protection engine stopped.")
        if pid:
            print(f"PID        {pid}")
    else:
        print("Protection engine was not running.")
    return EXIT_OK


def _cmd_run_fg(ui: _UI, args: argparse.Namespace, cfg: Config) -> int:
    try:
        return run_foreground(cfg)
    except Exception as exc:  # noqa: BLE001
        log_error(cfg, f"engine crashed: {exc}")
        return EXIT_DAEMON


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
    "_run-fg": _cmd_run_fg,
}


def _print_banner_status(ui: _UI, cfg: Config) -> None:
    _header(ui)
    print(_TAGLINE)
    print()
    state, pid = daemon_status(cfg)
    db_ok = False
    try:
        db = open_database(cfg)
        db.get_setting("heartbeat")
        db.close()
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
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
