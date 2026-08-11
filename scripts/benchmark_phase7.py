#!/usr/bin/env python3
"""Reproducible bounded Phase 7 reputation lookup microbenchmark."""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from callshield.config import Config
from callshield.database import Database
from callshield.reputation import ReputationEngine
from callshield.utils import iso_now


def percentile(values, value):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(value * len(ordered)) - 1))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookups", type=int, default=1000)
    parser.add_argument("--history-events", type=int, default=100)
    args = parser.parse_args()
    if not (100 <= args.lookups <= 100000):
        raise SystemExit("lookups must be between 100 and 100000")
    if not (1 <= args.history_events <= 500):
        raise SystemExit("history-events must be between 1 and 500")

    with tempfile.TemporaryDirectory(prefix="callshield-reputation-benchmark-") as tmp:
        path = Path(tmp) / "benchmark.db"
        cfg = Config(database_path=str(path), reputation_query_limit=100)
        database = Database(path)
        number = "+919876543210"
        for _ in range(args.history_events):
            database.add_event(
                timestamp=iso_now(),
                number=number,
                risk_score=70,
                confidence=75,
                reputation="HIGH_RISK",
                risk_level="HIGH",
                verdict="HIGH_RISK",
                action="BLOCK",
                reason="benchmark fixture",
            )
        engine = ReputationEngine(database, cfg)
        analysis = {"risk_score": 70, "confidence": 75, "signals": []}
        for _ in range(20):
            engine.calculate(number, analysis=analysis, persist=False)
        samples = []
        wall_start = time.perf_counter()
        for _ in range(args.lookups):
            started = time.perf_counter_ns()
            result = engine.calculate(number, analysis=analysis, persist=False)
            samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
            if not result.available:
                raise RuntimeError("reputation lookup failed")
        wall = time.perf_counter() - wall_start
        database.close()

    print(
        json.dumps(
            {
                "benchmark": "bounded local ReputationEngine.calculate lookup",
                "python": platform.python_version(),
                "platform": platform.platform(),
                "lookups": args.lookups,
                "history_events": args.history_events,
                "query_limit": 100,
                "concurrency": 1,
                "clock": "time.perf_counter_ns",
                "p50_ms": percentile(samples, 0.50),
                "p95_ms": percentile(samples, 0.95),
                "p99_ms": percentile(samples, 0.99),
                "wall_seconds": wall,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
