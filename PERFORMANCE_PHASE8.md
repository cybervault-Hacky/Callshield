# CALLSHIELD Phase 8 Adaptive Intelligence Benchmark

Status: **VERIFIED FOR THE DOCUMENTED LOCAL WORKLOAD ONLY**

## Environment

- Date: 2026-08-11
- Platform: `Linux-6.1.158+-x86_64-with-glibc2.36`
- Python: `3.11.2`
- Clock: `time.perf_counter_ns`

## Workload

- 1,000 iterations per workload
- 100 bounded behavioral observations
- query limit: 100
- concurrency: 1
- local temporary SQLite database
- no Android, network, or physical call
- 20 unmeasured warm-up iterations

Reproduce:

```bash
python3 scripts/benchmark_phase8.py --iterations 1000 --observations 100
```

## Results

| Workload | p50 | p95 | p99 |
|---|---:|---:|---:|
| intelligence lookup | 0.579679 ms | 0.834626 ms | 1.091556 ms |
| behavioral analysis | 0.072811 ms | 0.098954 ms | 0.120621 ms |
| trend calculation | 0.045488 ms | 0.105911 ms | 0.131718 ms |
| full intelligence snapshot | 0.756128 ms | 0.821092 ms | 0.993023 ms |

Total benchmark wall time: `1.5210156959999495` seconds.

## Not verified

- Android or physical call latency
- cross-UID Android/Termux socket latency
- concurrent production database performance
- end-to-end screening and persistence latency
- performance on a Termux phone

No result outside the documented bounded local workload is claimed.
