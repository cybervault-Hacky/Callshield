#!/usr/bin/env python3
"""Reproducible Phase 6 PolicyEngine latency microbenchmark."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from callshield.config import Config
from callshield.policy import PolicyEngine


def percentile(values, percentile_value):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile_value * len(ordered)) - 1))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    if not (100 <= args.events <= 1_000_000):
        raise SystemExit("events must be between 100 and 1000000")
    if not (1 <= args.concurrency <= 64):
        raise SystemExit("concurrency must be between 1 and 64")

    cfg = Config(
        screening_enabled=True,
        screening_mode="ACTIVE",
        active_mode_confirmed=True,
    )
    engine = PolicyEngine(cfg)
    detection = {
        "risk_score": 95,
        "confidence": 95,
        "verdict": "MALICIOUS",
        "reputation": "UNKNOWN",
        "signals": [],
    }

    for _ in range(100):
        engine.decide(detection, emergency_off=False)

    def measure(_):
        started = time.perf_counter_ns()
        decision = engine.decide(detection, emergency_off=False)
        if decision.applied_action != "BLOCK":
            raise RuntimeError("benchmark policy decision changed")
        return (time.perf_counter_ns() - started) / 1_000_000.0

    wall_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        samples = list(executor.map(measure, range(args.events)))
    wall_seconds = time.perf_counter() - wall_started

    report = {
        "benchmark": "PolicyEngine.decide active high-risk in-memory microbenchmark",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "events": args.events,
        "concurrency": args.concurrency,
        "clock": "time.perf_counter_ns",
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
        "wall_seconds": wall_seconds,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
