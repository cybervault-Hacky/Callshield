# CALLSHIELD Phase 6 Performance Benchmark

Status: **VERIFIED FOR THE DOCUMENTED MICROBENCHMARK ONLY**

This is not an Android, SQLite, Unix IPC, or end-to-end call-screening benchmark.
It measures the in-memory Phase 5/6 `PolicyEngine.decide` path so the workload is
reproducible without claiming unavailable device performance.

## Environment

- Date: 2026-08-11
- Platform: `Linux-6.1.158+-x86_64-with-glibc2.36`
- Python: `3.11.2`
- Clock: `time.perf_counter_ns`

## Workload

- 5,000 policy decisions
- concurrency: 10 Python worker threads
- policy: BALANCED
- mode: ACTIVE, explicitly confirmed
- input: risk 95, confidence 95, no whitelist, emergency off
- 100 unmeasured warm-up decisions

Reproduce from the repository root:

```bash
python3 scripts/benchmark_phase6.py --events 5000 --concurrency 10
```

## Results

| Percentile | Latency |
|---|---:|
| p50 | 0.006790 ms |
| p95 | 0.021914 ms |
| p99 | 0.039164 ms |

Total measured wall time: `0.14853265799979454` seconds.

## Not verified

- Android service latency
- physical call-screening latency
- cross-UID Android/Termux socket latency
- end-to-end IPC + database latency
- performance on a Termux phone

No claim is made outside the measured policy-only workload.
