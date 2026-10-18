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

## Cyber Range (Attack vs Defense)

A dedicated evidence-driven cyber range lives at **`/range`**. It runs bounded,
repeatable attack scenarios through a *simulated* defense chain
(edge/CDN/WAF -> application auth/authz/validation -> RiskFabric risk policy)
and records a single correlated event stream. Every metric is derived from
recorded events and an explicit per-attempt **ground-truth label** - no random
success rates.

* **Run IDs + seeds:** each run has a unique id; the same seed is replayable and
  lets the three defense modes be compared on identical inputs.
* **No double counting:** each attempt has exactly one final outcome, so an
  edge-blocked request is never also counted as an application block.
* **Compromise state:** `BLOCKED / CONTAINED / PARTIALLY_COMPROMISED /
  COMPROMISED / INCONCLUSIVE`, with the evidence behind it.
* **Three modes:** `baseline` (no RiskFabric), `classical` (RiskFabric classical
  scoring), `quantum` (RiskFabric + quantum challenger when the engine reports it
  ran). The risk step calls the **real RiskFabric engine** when reachable and a
  clearly-labelled local classical model otherwise. A result is only labelled
  quantum when the console confirms the challenger is live.
* **Scenarios:** credential impersonation (stolen session), password spraying,
  repeated failed auth, SQL injection, request flood, broken authorization,
  malformed input, suspicious transaction.

Range routes: `GET /range` (page), `GET /range/scenarios`, `POST /range/start`,
`POST /range/stop`, `GET /range/status`, `POST /range/compare`,
`GET /range/export?run_id=&fmt=csv|json`.

**Measured vs simulated:** the edge/app layers are *simulated* (modelled)
components; their decisions use real rule logic but are not a real CDN. The risk
decision is *measured* from the RiskFabric engine when connected, else from the
local classical model (labelled). The quantum-specific contribution is only
genuine on the VM with the quantum worker and `RF_QML_MODE=rerank`; offline,
`classical` and `quantum` modes are numerically identical and quantum is flagged
unavailable.

## Project structure

```
simulation/
  attacks/
    ddos_simulation.py            # DDoS generator -> real rate limiter / target
    sql_injection_simulation.py   # SQLi payloads  -> real SQLi detector
  defenses/
    rate_limiter.py               # sliding-window rate limiter (+ reset)
    sql_injection_defense.py      # pattern-based SQLi detector (+ reset)
  cyber_range.py                  # scenario engine: edge/app/riskfabric pipeline,
                                  #   ground truth, compromise state, 3-mode compare
  test_simulation.py              # proves outcomes are real + cancel/reset
  test_cyber_range.py             # run ids, no double-count, ground truth, modes
dashboard/
  app.py                          # Flask control plane + RiskFabric/console clients
  templates/index.html            # attack console (blue theme, animated attack map)
  templates/range.html            # cyber-range ops page (/range)
  static/vendor/chart.umd.js      # vendored Chart.js (offline-friendly)
  test_app.py                     # route validation / concurrency / range tests
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

**Fraud test with real accounts:** the engine holds any payer not in its
registry (rule R0), so the baseline must use a *known* account to show a real
ALLOW-vs-HOLD contrast. Point `RF_DATASET_CSV` at the registry file
`$RF_DATA/bank/accounts.csv` (built by `python -m vault build`, columns
`acct,segment`); the dropdown auto-detects that format and loads real known
payers. It also reads the IBM AML transaction format (`From Bank, Account, …`).
The bundled `data/HI-Small_Trans.csv` is a tiny sample for offline demos only.
If the baseline comes back held as "unknown account", the fraud panel shows a
hint telling you to switch to the registry file.

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
