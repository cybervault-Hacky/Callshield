#!/usr/bin/env python3
"""Reproducible bounded Phase 8 adaptive intelligence benchmark."""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from callshield.adaptive import BehaviorEngine, BehaviorObservation, BehaviorStorage
from callshield.adaptive.patterns import detect_patterns
from callshield.adaptive.trends import analyze_trend
from callshield.config import Config
from callshield.database import Database
from callshield.reputation import ReputationProfile, number_fingerprint
from callshield.utils import iso_now


def percentile(values, value):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(value * len(ordered)) - 1))
    return ordered[index]


def measure(iterations, function):
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return {
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--observations", type=int, default=100)
    args = parser.parse_args()
    if not (100 <= args.iterations <= 100000):
        raise SystemExit("iterations must be between 100 and 100000")
    if not (3 <= args.observations <= 500):
        raise SystemExit("observations must be between 3 and 500")

    with tempfile.TemporaryDirectory(prefix="callshield-intelligence-benchmark-") as tmp:
        cfg = Config(
            database_path=str(Path(tmp) / "benchmark.db"),
            intelligence_query_limit=100,
            intelligence_observation_limit=200,
        )
        database = Database(cfg.database_path)
        engine = BehaviorEngine(database, cfg)
        number = "+919876543210"
        for index in range(args.observations):
            engine.add_observation(
                number,
                BehaviorObservation(
                    event_id=f"00000000-0000-4000-8000-{index + 1:012d}",
                    timestamp=iso_now(),
                    event_type="BENCHMARK",
                    risk_score=30 + index % 50,
                    confidence=70,
                    recommended_action="ALLOW",
                    applied_action="ALLOW",
                    confirmed=False,
                    source="BENCHMARK",
                ),
            )
        fingerprint = number_fingerprint(number)
        storage = BehaviorStorage(database, cfg)
        timeline = storage.timeline(fingerprint)
        reputation = ReputationProfile(
            number_hash=fingerprint,
            number_masked="+919*****3210",
            risk_score=70,
            confidence=75,
            risk="HIGH",
            calls_seen=args.observations,
            calls_allowed=20,
            block_recommendations=15,
        )
        scores = [item.risk_score for item in timeline]
        confidences = [item.confidence for item in timeline]

        def trend_workload():
            return analyze_trend(
                scores,
                confidences,
                baseline_score=50,
                baseline_confidence=60,
                current_score=70,
                current_confidence=75,
            )

        trend = trend_workload()

        def behavior_workload():
            return detect_patterns(
                timeline,
                reputation=reputation,
                trend=trend,
                recent_reports=2,
                trusted=False,
                trust_expiry=None,
                now=datetime.now(timezone.utc),
            )

        workloads = {
            "intelligence_lookup": lambda: storage.timeline(fingerprint),
            "trend_calculation": trend_workload,
            "behavioral_analysis": behavior_workload,
            "full_intelligence_snapshot": lambda: engine.snapshot(
                number,
                reputation=reputation,
                detection={"recommended_action": "ALLOW"},
                persist=False,
            ),
        }
        for function in workloads.values():
            for _ in range(20):
                function()
        wall_started = time.perf_counter()
        results = {
            name: measure(args.iterations, function)
            for name, function in workloads.items()
        }
        wall = time.perf_counter() - wall_started
        database.close()

    print(
        json.dumps(
            {
                "benchmark": "bounded local Phase 8 adaptive intelligence",
                "python": platform.python_version(),
                "platform": platform.platform(),
                "iterations_per_workload": args.iterations,
                "observations": args.observations,
                "query_limit": 100,
                "concurrency": 1,
                "clock": "time.perf_counter_ns",
                "results": results,
                "wall_seconds": wall,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
