# Banking Security Simulation System

A controlled, judge-ready red-team console that fires scripted attack scenarios
at the **Quantum RiskFabric** banking stack
([SachinDurairaj06/quantum-riskfabric](https://github.com/SachinDurairaj06/quantum-riskfabric))
and shows how its defenses — rate limiting, the fraud engine and the quantum-ML
challenger — actually respond.

> **No fabricated outcomes.** Every number on the dashboard — blocked requests,
> detection rate, engine decisions, bank responses — comes from a real defense
> decision or a real HTTP response. When the target is unreachable, that is
> reported as `UNREACHABLE` rather than being counted as a "block".

This project is the **attacker/visualisation side only**. It does not contain or
run the bank; it points at a RiskFabric instance you host (on loopback).

## What this system can do

| Capability | Detail |
| --- | --- |
| **DDoS / flood simulation** | HTTP, UDP and SYN profiles, multi-threaded, across a pool of simulated source IPs. Each request is evaluated by the real rate limiter; a sampled subset of allowed requests is sent to the RiskFabric channel to record its real `ALLOW`/`VERIFY`/`HOLD`. |
| **SQL-injection simulation** | Basic auth-bypass, DDL hijacking and UNION exfiltration payloads, interleaved with benign control traffic. Every payload is judged by the real SQL-injection detector; the reported detection rate is genuine. |
| **Stolen-session fraud test** | Submits a baseline legitimate transfer and an anomalous high-value transfer from the *same* account to a new payee, then shows the engine/ML's real decision and score for each — a direct account-takeover detection check. No credential theft is performed; it only sends transactions. |
| **Global attack map** | Animated origins → bank-server arcs. Each simulated source IP is pinned to a city; request arcs are green when they reach the server and red/shed at the perimeter when the origin is rate-limited — driven by real block state. |
| **Live defense feed** | Reads the RiskFabric console APIs so one tab shows engine decisions (ALLOW/VERIFY/HOLD, hold-rate vs cap, latency), the quantum shadow-vs-engine agreement, and the held transactions with their per-transaction quantum challenger score. |
| **Dataset-seeded fraud test** | Load a real account/transaction from the synthetic dataset into the fraud test, then send it (or a tampered high-value version) to the engine. |
| **Live metrics & charts** | Real throughput (req/s from request deltas), real blocked/allowed effectiveness, blocked-IP count, SQLi detection rate. |
| **Reliable execution** | Thread-safe counters, cooperative cancellation, one-run-per-kind concurrency cap, bounded joins, full reset. |
| **Safety controls** | Target allowlist (loopback only), per-run thread/duration limits, input validation, configurable target. |

## Project structure

```
simulation/
  attacks/
    ddos_simulation.py            # DDoS generator -> real rate limiter / target
    sql_injection_simulation.py   # SQLi payloads  -> real SQLi detector
  defenses/
    rate_limiter.py               # sliding-window rate limiter (+ reset)
    sql_injection_defense.py      # pattern-based SQLi detector (+ reset)
  test_simulation.py              # proves outcomes are real + cancel/reset
dashboard/
  app.py                          # Flask control plane + RiskFabric TargetClient
  templates/index.html            # dashboard UI (blue theme, animated attack map)
  static/vendor/chart.umd.js      # vendored Chart.js (offline-friendly)
  test_app.py                     # route validation / concurrency / scenario tests
docs/                             # attack-type notes and case studies
```

## Installation

```bash
pip install -r requirements.txt   # Flask + requests
```

## Running

1. Start your RiskFabric stack on loopback (see that repo's README), e.g. the
   bank channel on `:9000` or the perimeter on `:8000`.
2. Start this dashboard:
   ```bash
   python dashboard/app.py
   ```
3. Open <http://localhost:5001>.

If the target is not running, attacks still execute against the local rate
limiter / SQLi detector, and target responses are reported as `UNREACHABLE`.

### Configuration

| Setting | Env var | Default |
| --- | --- | --- |
| RiskFabric target URL | `RF_TARGET_URL` | `http://127.0.0.1:9000` |
| Channel (decision) path | `RF_PAY_PATH` | `/bank/pay` |
| Engine (score) path | `RF_ENGINE_PATH` | `/engine/pay` |
| Health path | `RF_HEALTH_PATH` | `/bank/health` |
| RiskFabric console URL | `RF_CONSOLE_URL` | `http://127.0.0.1:8500` |
| Synthetic dataset CSV | `RF_DATASET_CSV` | `data/HI-Small_Trans.csv` |
| Max threads per run | `SIM_MAX_THREADS` | `20` |
| Max run duration (s) | `SIM_MAX_DURATION` | `120` |

The target host is restricted to a loopback **allowlist** (`127.0.0.1`,
`localhost`, `::1`); runtime config changes to any other host are rejected. To
test the full edge-shedding chain, point `RF_TARGET_URL` at the perimeter
(`http://127.0.0.1:8000`); to read raw engine decisions, point it at the bank
(`:9000`).

The transaction schema sent to the target matches the RiskFabric contract:
`{txn_id, ts, from_acct, to_acct, amount, currency, format}`.

### Key endpoints

| Route | Purpose |
| --- | --- |
| `POST /start_ddos`, `POST /start_sql` | start a run (validated) |
| `POST /stop_ddos`, `POST /stop_sql`, `POST /stop_all` | cancel runs |
| `POST /run_scenario` | run the stolen-session fraud test |
| `POST /reset` | cancel runs, clear defenses, scenario, logs and counters |
| `POST /test_defense` | single-input probe of a defense |
| `GET /get_status` | live state, stats, attack-map data, scenario, logs |
| `GET /target_status` | RiskFabric connectivity |
| `GET /console_feed` | live engine decisions, shadow agreement and held transactions + quantum scores (read from the RiskFabric console) |
| `GET /dataset` | real accounts/transactions from the synthetic dataset for the fraud test |
| `GET/POST /config` | view / adjust target, console, dataset + verification |

## Testing

```bash
python -m pytest simulation/test_simulation.py dashboard/test_app.py -q
```

## Safety

All testing is confined to the authorized RiskFabric environment on loopback.
The tool adds no stealth, evasion or third-party targeting; the target
allowlist and execution limits are enforced in `dashboard/app.py`. The
"stolen-session" scenario is a fraud-detection test: it only submits
transactions and reports the engine's response.
