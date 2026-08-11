# CALLSHIELD Phase 7 Reputation Lookup Benchmark

Status: **VERIFIED FOR THE DOCUMENTED LOCAL LOOKUP WORKLOAD ONLY**

## Environment

- Date: 2026-08-11
- Platform: `Linux-6.1.158+-x86_64-with-glibc2.36`
- Python: `3.11.2`
- Clock: `time.perf_counter_ns`

## Workload

- 1,000 sequential reputation calculations
- one SQLite database connection
- 100 indexed historical events for one canonical number
- bounded recent query limit: 100
- persistence disabled during timed lookups
- no network, Android, IPC, or policy application
- 20 unmeasured warm-up lookups

Reproduce:

```bash
python3 scripts/benchmark_phase7.py --lookups 1000 --history-events 100
```

## Results

| Percentile | Latency |
|---|---:|
| p50 | 0.229418 ms |
| p95 | 0.308114 ms |
| p99 | 0.437614 ms |

Total measured wall time: `0.24667476800004806` seconds.

## Not verified

- Android or physical call latency
- cross-UID Android/Termux socket latency
- end-to-end daemon screening latency
- performance on a Termux phone
- large multi-number production databases beyond configured retention

No result outside the documented local lookup workload is claimed.
