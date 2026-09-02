# Documentation index

Start with the [README](../README.md) for results and architecture.

- **[DEMO-RUNBOOK.md](DEMO-RUNBOOK.md)** — How to run the demo, the 7-minute script, and the Q&A bank
- **[DATA-STATUS.md](DATA-STATUS.md)** — What is real, what is synthetic, what is a proxy — and how to say so
- **[FINDING-eye-detection.md](FINDING-eye-detection.md)** — Why Mocha detected no eyes, and why IR centre-fixing cannot beat motion extrapolation
- **[INSAT-ACCESS.md](INSAT-ACCESS.md)** — MOSDAC access, the L1B HDF5 reader, and how INSAT is wired into the pipeline
- **[WEATHERNEXT-2.md](WEATHERNEXT-2.md)** — The environment provider interface and what WeatherNext 2 would add

## Regenerating everything

```bash
make cases       # the three real-imagery storms
make figures     # every figure in artifacts/
make eval        # the results table
make test        # 68 tests
```

