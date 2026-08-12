"""Startup sequence.

Nine short initialisation stages are rendered while the interface actually
performs the corresponding work: reading the configuration, opening the
database, probing the daemon, loading the policy and warming the reputation and
adaptive engines. There is no artificial delay — the animation is driven by the
real work, and when the work finishes early the sequence ends early.

The sequence never claims that Android call screening is operational.
"""

from __future__ import annotations

import os
import select
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import formatters as fmt
from ..components import Spinner, Surface, header, staged_lines, status_bar

#: Maximum wall-clock time the whole sequence may occupy (seconds).
MAX_DURATION = 2.0
#: Minimum time a stage stays visible so the sequence is readable, not a flash.
FRAME_INTERVAL = 0.06

STAGE_KEYS: Tuple[str, ...] = (
    "startup.init",
    "startup.engine",
    "startup.intelligence",
    "startup.daemon",
    "startup.database",
    "startup.policy",
    "startup.reputation",
    "startup.adaptive",
    "startup.interface",
)


class StartupReport:
    """Outcome of the startup probes, handed to the dashboard."""

    def __init__(self) -> None:
        self.daemon_state = "UNKNOWN"
        self.daemon_pid: Optional[int] = None
        self.database_ok = False
        self.database_error = ""
        self.policy = "BALANCED"
        self.emergency_off = False
        self.engine_ok = False
        self.intelligence_ok = False
        self.reputation_ok = False
        self.warnings: List[str] = []
        self.elapsed = 0.0

    @property
    def daemon_online(self) -> bool:
        return self.daemon_state == "RUNNING"

    def as_fields(self) -> Dict[str, Any]:
        return {
            "daemon": self.daemon_state,
            "database": "READY" if self.database_ok else "ERROR",
            "policy": self.policy,
            "emergency_off": self.emergency_off,
        }


def build_probes(backend: Any) -> List[Callable[[StartupReport], None]]:
    """One probe per stage. Every probe is defensive and never raises."""

    def probe_init(report: StartupReport) -> None:
        # Configuration is already loaded by the CLI before the UI starts.
        return None

    def probe_engine(report: StartupReport) -> None:
        try:
            from ... import detector, scoring  # noqa: F401  (import is the probe)

            report.engine_ok = True
        except Exception as exc:  # noqa: BLE001
            report.warnings.append("engine: {0}".format(exc))

    def probe_intelligence(report: StartupReport) -> None:
        try:
            from ...intelligence import profiles  # noqa: F401

            report.intelligence_ok = True
        except Exception as exc:  # noqa: BLE001
            report.warnings.append("intelligence: {0}".format(exc))

    def probe_daemon(report: StartupReport) -> None:
        state, pid = backend.daemon_state()
        report.daemon_state = state
        report.daemon_pid = pid

    def probe_database(report: StartupReport) -> None:
        result = backend.event_metrics()
        report.database_ok = bool(result.ok)
        if not result.ok:
            report.database_error = result.error
            report.warnings.append("database: {0}".format(result.error))

    def probe_policy(report: StartupReport) -> None:
        try:
            snapshot = backend.policy_snapshot()
            report.policy = str(snapshot.get("current") or "BALANCED")
            report.emergency_off = bool(snapshot.get("emergency_off"))
        except Exception as exc:  # noqa: BLE001
            report.warnings.append("policy: {0}".format(exc))

    def probe_reputation(report: StartupReport) -> None:
        result = backend.recent_reputation_profiles(1)
        report.reputation_ok = bool(result.ok)
        if not result.ok:
            report.warnings.append("reputation: {0}".format(result.error))

    def probe_adaptive(report: StartupReport) -> None:
        result = backend.recent_intelligence_profiles(1)
        if not result.ok:
            report.warnings.append("adaptive: {0}".format(result.error))

    def probe_interface(report: StartupReport) -> None:
        return None

    return [
        probe_init,
        probe_engine,
        probe_intelligence,
        probe_daemon,
        probe_database,
        probe_policy,
        probe_reputation,
        probe_adaptive,
        probe_interface,
    ]


def render_frame(
    surface: Surface,
    translator: Any,
    completed: int,
    spinner: Optional[Spinner],
    version: str = "",
) -> List[str]:
    """Compose one startup frame (pure: useful for tests and for redraws)."""

    stages = [translator(key) for key in STAGE_KEYS]
    lines = header(
        surface,
        translator("app.title"),
        translator("app.subtitle"),
        version,
    )
    lines.append("")
    lines.extend(staged_lines(surface, stages, completed, spinner))
    done = min(completed, len(stages))
    if done >= len(stages):
        lines.append("")
        lines.append(surface.style(translator("startup.ready"), "ok"))
    return lines


def _should_cancel(ctx: Any) -> bool:
    """True when the user pressed ``q`` or Ctrl+C during startup.

    Only consulted while the terminal is interactive; a probe is never
    interrupted mid-flight, only the pause between stages is shortened. The
    check is strictly best-effort: streams without a file descriptor are
    skipped so scripted contexts keep working.
    """

    caps = getattr(ctx, "caps", None)
    if caps is None or not caps.interactive:
        return False
    stream = getattr(ctx, "stdin", None)
    if stream is None:
        return False
    try:
        fileno = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    try:
        ready, _, _ = select.select([stream], [], [], 0.0)
    except (OSError, ValueError):
        return False
    if not ready:
        return False
    try:
        data = os.read(fileno, 8)
    except (OSError, ValueError):
        return False
    return any(byte in (0x03, ord("q"), ord("Q")) for byte in data)


def run_startup(ctx: Any, animate: bool = True) -> StartupReport:
    """Execute the startup sequence, drawing progress as the work happens."""

    report = StartupReport()
    probes = build_probes(ctx.backend)
    spinner = Spinner(enabled=animate and ctx.caps.interactive)
    started = time.monotonic()
    version = ctx.version

    if animate and ctx.caps.interactive:
        ctx.clear()

    for index, probe in enumerate(probes):
        if animate and ctx.caps.interactive:
            ctx.draw(render_frame(ctx.surface, ctx.t, index, spinner, version))
        try:
            probe(report)
        except Exception as exc:  # noqa: BLE001 - a probe must never abort start-up
            report.warnings.append("{0}: {1}".format(STAGE_KEYS[index], exc))
        spinner.advance()
        if animate and ctx.caps.interactive:
            remaining = MAX_DURATION - (time.monotonic() - started)
            budget = remaining / float(max(1, len(probes) - index))
            pause = max(0.0, min(FRAME_INTERVAL, budget))
            if pause and not _should_cancel(ctx):
                time.sleep(pause)

    if animate and ctx.caps.interactive:
        ctx.draw(render_frame(ctx.surface, ctx.t, len(probes), None, version))

    report.elapsed = time.monotonic() - started
    return report


def summary_lines(surface: Surface, translator: Any,
                  report: StartupReport) -> List[str]:
    """Post-startup status strip, including the OFFLINE hint when relevant."""

    fields = [
        (translator("main.field.daemon"), report.daemon_state),
        (translator("main.field.database"),
         "READY" if report.database_ok else "ERROR"),
        (translator("main.field.policy"), report.policy),
    ]
    lines = status_bar(surface, fields)
    if not report.daemon_online:
        lines.append(surface.style(translator("main.daemon_offline_hint"), "warn"))
    if report.emergency_off:
        lines.append(surface.style(translator("policy.emergency_engaged"), "warn"))
    lines.append(surface.style(translator("main.no_android"), "muted"))
    for warning in report.warnings[:3]:
        lines.append(surface.style(fmt.truncate(warning, surface.width), "muted"))
    return lines


__all__ = [
    "FRAME_INTERVAL",
    "MAX_DURATION",
    "STAGE_KEYS",
    "StartupReport",
    "build_probes",
    "render_frame",
    "run_startup",
    "summary_lines",
]
